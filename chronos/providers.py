"""Detect Provider (Source) names that actually appear in the System log."""
import win32evtlog as evt

CHANNEL = "System"


def detect_providers(scan_limit: int = 5000) -> list:
    """Scan the most recent `scan_limit` System log records and return the
    distinct Provider names found, sorted alphabetically."""
    query = evt.EvtQuery(CHANNEL, evt.EvtQueryReverseDirection)
    ctx = evt.EvtCreateRenderContext(evt.EvtRenderContextSystem)
    names = set()
    remaining = scan_limit
    while remaining > 0:
        batch = evt.EvtNext(query, min(200, remaining))
        if not batch:
            break
        for event_handle in batch:
            result = evt.EvtRender(event_handle, evt.EvtRenderEventValues, Context=ctx)
            name = result[evt.EvtSystemProviderName][0]
            if name:
                names.add(name)
        remaining -= len(batch)
    return sorted(names)
