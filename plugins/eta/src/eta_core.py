"""Agent-supplied remaining times and local calibration against actual durations."""

from __future__ import annotations

import math
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

CATEGORIES = {"quick", "research", "code", "large"}


def require_event(event: object) -> dict:
    if not isinstance(event, dict):
        raise ValueError("Hook input must be a JSON object")
    kind = event.get("hook_event_name")
    if kind not in {"UserPromptSubmit", "Stop", "Interrupt", "PostToolUse"}:
        raise ValueError(f"Unexpected hook event: {kind!r}")
    for key in ("session_id", "turn_id", "model"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise ValueError(f"Missing required hook field: {key}")
    if kind == "UserPromptSubmit" and not isinstance(event.get("prompt"), str):
        raise ValueError("UserPromptSubmit requires a prompt string")
    return event


class EtaStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS turns (
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                model TEXT NOT NULL,
                category TEXT NOT NULL,
                started_at REAL NOT NULL,
                ended_at REAL,
                outcome TEXT,
                PRIMARY KEY (session_id, turn_id)
            )""")
            # Keep v0.1 duration history, but only paired agent estimates can
            # contribute to calibration. No invented estimates for old rows.
            db.execute("""CREATE TABLE IF NOT EXISTS estimates (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                issued_at REAL NOT NULL,
                remaining_seconds REAL NOT NULL,
                category TEXT NOT NULL,
                factor REAL NOT NULL,
                sample_count INTEGER NOT NULL
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS estimates_turn
                ON estimates(session_id, turn_id, id)""")
            db.execute("""CREATE TABLE IF NOT EXISTS reminders (
                session_id TEXT NOT NULL,
                turn_id TEXT NOT NULL,
                last_reminded_at REAL NOT NULL,
                PRIMARY KEY (session_id, turn_id)
            )""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def start(self, event: dict, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("""INSERT INTO turns
                (session_id, turn_id, model, category, started_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, turn_id) DO NOTHING""",
                (event["session_id"], event["turn_id"], event["model"], "unclassified", now))

    def set_estimate(self, session_id: str, turn_id: str, seconds: float,
                     category: str, now: float | None = None) -> dict:
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Remaining seconds must be a positive finite number")
        if category not in CATEGORIES:
            raise ValueError(f"Category must be one of {sorted(CATEGORIES)}")
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            turn = db.execute("""SELECT * FROM turns
                WHERE session_id=? AND turn_id=? AND ended_at IS NULL""",
                (session_id, turn_id)).fetchone()
            if turn is None:
                raise ValueError("No active ETA turn matched the estimate")
            if now < turn["started_at"]:
                raise ValueError("Estimate timestamp precedes turn start")
            rows = db.execute("""SELECT t.ended_at-e.issued_at AS actual,
                       e.remaining_seconds AS predicted
                FROM turns t JOIN estimates e
                  ON e.session_id=t.session_id AND e.turn_id=t.turn_id
                WHERE t.outcome='completed' AND t.model=? AND e.category=?
                  AND t.ended_at>e.issued_at
                  AND e.id=(SELECT MIN(first.id) FROM estimates first
                    WHERE first.session_id=t.session_id AND first.turn_id=t.turn_id)
                ORDER BY t.ended_at DESC LIMIT 100""",
                (turn["model"], category)).fetchall()
            factor = calibration_factor([(r["actual"], r["predicted"]) for r in rows])
            db.execute("""INSERT INTO estimates
                (session_id,turn_id,issued_at,remaining_seconds,category,factor,sample_count)
                VALUES (?,?,?,?,?,?,?)""",
                (session_id, turn_id, now, seconds, category, factor, len(rows)))
            db.execute("UPDATE turns SET category=? WHERE session_id=? AND turn_id=?",
                       (category, session_id, turn_id))
        return {"agent_seconds": seconds, "display_seconds": seconds * factor,
                "calibration_factor": factor, "samples": len(rows)}

    def finish(self, event: dict, outcome: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self.connect() as db:
            updated = db.execute("""UPDATE turns SET ended_at=?, outcome=?
                WHERE session_id=? AND turn_id=? AND ended_at IS NULL""",
                (now, outcome, event["session_id"], event["turn_id"])).rowcount
            if not updated:
                raise ValueError("No active ETA turn matched the completion hook")

    def current(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        with self.connect() as db:
            row = db.execute("""SELECT * FROM turns WHERE ended_at IS NULL
                ORDER BY started_at DESC LIMIT 1""").fetchone()
            if row is None:
                return None
            estimate = db.execute("""SELECT * FROM estimates
                WHERE session_id=? AND turn_id=? ORDER BY id DESC LIMIT 1""",
                (row["session_id"], row["turn_id"])).fetchone()
        elapsed = max(0.0, now - row["started_at"])
        remaining = None if estimate is None else max(
            0.0, estimate["remaining_seconds"] * estimate["factor"] - (now - estimate["issued_at"]))
        return {
            "model": row["model"],
            "category": row["category"],
            "elapsed": elapsed,
            "remaining": remaining,
            "status": "waiting" if estimate is None else "overdue" if remaining == 0 else "estimated",
            "samples": 0 if estimate is None else estimate["sample_count"],
            "factor": 1.0 if estimate is None else estimate["factor"],
        }

    def reminder_due(self, session_id: str, turn_id: str,
                     now: float | None = None) -> bool:
        """At tool boundaries, remind at most once per minute to revise the ETA."""
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            turn = db.execute("""SELECT started_at FROM turns
                WHERE session_id=? AND turn_id=? AND ended_at IS NULL""",
                (session_id, turn_id)).fetchone()
            if turn is None:
                raise ValueError("No active ETA turn matched the tool hook")
            estimate = db.execute("""SELECT issued_at, remaining_seconds, factor FROM estimates
                WHERE session_id=? AND turn_id=? ORDER BY id DESC LIMIT 1""",
                (session_id, turn_id)).fetchone()
            reminder = db.execute("""SELECT last_reminded_at FROM reminders
                WHERE session_id=? AND turn_id=?""", (session_id, turn_id)).fetchone()
            last_update = turn["started_at"] if estimate is None else estimate["issued_at"]
            last_reminder = turn["started_at"] if reminder is None else reminder["last_reminded_at"]
            expired = estimate is not None and now >= (
                estimate["issued_at"] + estimate["remaining_seconds"] * estimate["factor"])
            due = now - last_reminder >= 60 and (expired or now - last_update >= 60)
            if due:
                db.execute("""INSERT INTO reminders VALUES (?,?,?)
                    ON CONFLICT(session_id,turn_id)
                    DO UPDATE SET last_reminded_at=excluded.last_reminded_at""",
                    (session_id, turn_id, now))
            return due


def calibration_factor(pairs: list[tuple[float, float]]) -> float:
    """Shrink the geometric actual/agent ratio toward 1 with four prior pairs.

    One initial estimate per completed turn gets one vote. Bound the correction
    to 0.25..4 so a single long wait cannot dominate an agent's later estimates.
    With no paired history, the agent's estimate is displayed unchanged.
    """
    log_ratio = sum(math.log(actual) - math.log(predicted) for actual, predicted in pairs)
    correction = log_ratio / (len(pairs) + 4)
    return math.exp(max(math.log(0.25), min(math.log(4.0), correction)))
