"""SQLite storage for matched events, device snapshots, and power-cycle test results."""
import csv
import sqlite3
from contextlib import contextmanager
from typing import Iterable, List, Optional, Sequence

from .paths import get_db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS matched_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id INTEGER,
    time_created TEXT,
    provider TEXT,
    level INTEGER,
    event_id INTEGER,
    computer TEXT,
    message TEXT,
    xml TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS device_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,              -- 'baseline' or 'check'
    batch_id TEXT NOT NULL,          -- groups one snapshot "pass"
    device_id TEXT,
    name TEXT,
    pnp_class TEXT,
    status TEXT,
    error_code INTEGER,
    present INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS power_cycle_test (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_type TEXT NOT NULL,        -- reboot / sleep / hibernate
    cycle_index INTEGER NOT NULL,
    start_time TEXT,
    end_time TEXT,
    result TEXT,                     -- pass / fail / running
    reason TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(get_db_path())
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA)


def insert_event(record_id: int, time_created: str, provider: str, level: int,
                  event_id: int, computer: str, message: str, xml: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO matched_events (record_id, time_created, provider, level, "
            "event_id, computer, message, xml) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (record_id, time_created, provider, level, event_id, computer, message, xml),
        )


def query_events(limit: int = 500, level: Optional[int] = None,
                  provider: Optional[str] = None, event_id: Optional[int] = None) -> List[sqlite3.Row]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        clauses = []
        params: List = []
        if level is not None:
            clauses.append("level = ?")
            params.append(level)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        if event_id is not None:
            clauses.append("event_id = ?")
            params.append(event_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        cur = conn.execute(
            f"SELECT * FROM matched_events {where} ORDER BY id DESC LIMIT ?", params
        )
        return cur.fetchall()


def export_events_csv(path: str) -> None:
    rows = query_events(limit=1_000_000)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["record_id", "time_created", "provider", "level", "event_id", "computer", "message"])
        for r in rows:
            writer.writerow([r["record_id"], r["time_created"], r["provider"], r["level"],
                              r["event_id"], r["computer"], r["message"]])


def insert_device_snapshot(kind: str, batch_id: str, devices: Iterable[dict]) -> None:
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO device_snapshots (kind, batch_id, device_id, name, pnp_class, "
            "status, error_code, present) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (kind, batch_id, d["device_id"], d["name"], d["pnp_class"],
                 d["status"], d["error_code"], 1 if d["present"] else 0)
                for d in devices
            ],
        )


def get_latest_snapshot(kind: str) -> List[sqlite3.Row]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM device_snapshots WHERE kind = ? AND batch_id = ("
            "  SELECT batch_id FROM device_snapshots WHERE kind = ? ORDER BY id DESC LIMIT 1"
            ")",
            (kind, kind),
        )
        return cur.fetchall()


def insert_power_cycle_result(cycle_type: str, cycle_index: int, start_time: str,
                               end_time: Optional[str], result: str, reason: str = "") -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO power_cycle_test (cycle_type, cycle_index, start_time, end_time, "
            "result, reason) VALUES (?, ?, ?, ?, ?, ?)",
            (cycle_type, cycle_index, start_time, end_time, result, reason),
        )
        return cur.lastrowid


def update_power_cycle_result(row_id: int, end_time: str, result: str, reason: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE power_cycle_test SET end_time = ?, result = ?, reason = ? WHERE id = ?",
            (end_time, result, reason, row_id),
        )


def query_power_cycle_results(limit: int = 500) -> List[sqlite3.Row]:
    with _connect() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM power_cycle_test ORDER BY id DESC LIMIT ?", (limit,)
        )
        return cur.fetchall()


def export_power_cycle_csv(path: str) -> None:
    rows = query_power_cycle_results(limit=1_000_000)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["cycle_type", "cycle_index", "start_time", "end_time", "result", "reason"])
        for r in rows:
            writer.writerow([r["cycle_type"], r["cycle_index"], r["start_time"],
                              r["end_time"], r["result"], r["reason"]])
