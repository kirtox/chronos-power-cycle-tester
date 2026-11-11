"""Real-time System log tracking via EvtSubscribe, with bookmark-based resume."""
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Callable, List, Optional

import win32evtlog as evt

from .config import FilterConfig
from .paths import get_bookmark_path

logger = logging.getLogger(__name__)

CHANNEL = "System"

LEVEL_NAMES = {1: "Critical", 2: "Error", 3: "Warning", 4: "Information", 5: "Verbose"}


def _xpath_escape(value: str) -> str:
    """Best-effort escaping for a value used inside a single-quoted XPath literal."""
    return value.replace("'", "&apos;")


def build_query(filter_config: FilterConfig) -> str:
    """Build an XPath query combining Level/Provider/EventID with AND across fields,
    OR within each field. An empty field means "no restriction" on that field."""
    clauses: List[str] = []

    if filter_config.levels:
        levels = " or ".join(f"Level={lvl}" for lvl in filter_config.levels)
        clauses.append(f"({levels})")

    if filter_config.providers:
        provs = " or ".join(
            f"Provider[@Name='{_xpath_escape(p)}']" for p in filter_config.providers
        )
        clauses.append(f"({provs})")

    if filter_config.event_ids:
        eids = " or ".join(f"EventID={eid}" for eid in filter_config.event_ids)
        clauses.append(f"({eids})")

    if not clauses:
        return "*"
    return "*[System[" + " and ".join(clauses) + "]]"


class EventWatcher:
    """Wraps a push-based EvtSubscribe subscription on the System channel."""

    def __init__(self, filter_config: FilterConfig, on_match: Callable[[dict], None]):
        self._filter_config = filter_config
        self._on_match = on_match
        self._subscription = None
        self._render_ctx = evt.EvtCreateRenderContext(evt.EvtRenderContextSystem)
        self._lock = threading.Lock()

    def _load_bookmark(self):
        path = get_bookmark_path()
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                xml = f.read()
            return evt.EvtCreateBookmark(xml)
        except Exception:
            logger.exception("Failed to load bookmark, starting fresh")
            return None

    def _save_bookmark(self, event_handle) -> None:
        bookmark = evt.EvtCreateBookmark(None)
        evt.EvtUpdateBookmark(bookmark, event_handle)
        xml = evt.EvtRender(bookmark, evt.EvtRenderBookmark)
        tmp_path = get_bookmark_path() + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(xml)
        os.replace(tmp_path, get_bookmark_path())

    def _render_event(self, event_handle) -> dict:
        result = evt.EvtRender(event_handle, evt.EvtRenderEventValues, Context=self._render_ctx)
        time_created = result[evt.EvtSystemTimeCreated][0]
        if isinstance(time_created, datetime):
            time_created_str = time_created.astimezone(timezone.utc).isoformat()
        else:
            time_created_str = str(time_created)

        provider = result[evt.EvtSystemProviderName][0] or ""
        message = ""
        try:
            metadata = evt.EvtOpenPublisherMetadata(provider)
            message = evt.EvtFormatMessage(metadata, event_handle, evt.EvtFormatMessageEvent)
        except Exception:
            pass

        return {
            "record_id": result[evt.EvtSystemEventRecordId][0],
            "time_created": time_created_str,
            "provider": provider,
            "level": result[evt.EvtSystemLevel][0],
            "event_id": result[evt.EvtSystemEventID][0],
            "computer": result[evt.EvtSystemComputer][0] or "",
            "message": message,
            "xml": evt.EvtRender(event_handle, evt.EvtRenderEventXml),
        }

    def _callback(self, reason, context, event_handle):
        if reason != evt.EvtSubscribeActionDeliver:
            logger.warning("EvtSubscribe error action received")
            return 0
        with self._lock:
            try:
                data = self._render_event(event_handle)
                self._save_bookmark(event_handle)
            except Exception:
                logger.exception("Failed to process delivered event")
                return 0
        try:
            self._on_match(data)
        except Exception:
            logger.exception("on_match handler raised")
        return 0

    def start(self) -> None:
        query = build_query(self._filter_config)
        bookmark = self._load_bookmark()
        if bookmark is not None:
            self._subscription = evt.EvtSubscribe(
                CHANNEL,
                evt.EvtSubscribeStartAfterBookmark,
                Query=query,
                Callback=self._callback,
                Bookmark=bookmark,
            )
        else:
            self._subscription = evt.EvtSubscribe(
                CHANNEL,
                evt.EvtSubscribeToFutureEvents,
                Query=query,
                Callback=self._callback,
            )
        logger.info("EventWatcher started with query: %s", query)

    def update_filter(self, filter_config: FilterConfig) -> None:
        """Rebuild the subscription with a new filter, keeping the current bookmark position."""
        self._filter_config = filter_config
        self._subscription = None  # release old handle
        self.start()

    def stop(self) -> None:
        self._subscription = None
