"""Local turn history and a survival-based remaining-time estimate."""

from __future__ import annotations

import math
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import statistics
import time

PRIORS = {
    "quick": 75.0,
    "research": 300.0,
    "code": 420.0,
    "large": 900.0,
}
SPREAD = 0.65


def require_event(event: object) -> dict:
    if not isinstance(event, dict):
        raise ValueError("Hook input must be a JSON object")
    kind = event.get("hook_event_name")
    if kind not in {"UserPromptSubmit", "Stop", "Interrupt"}:
        raise ValueError(f"Unexpected hook event: {kind!r}")
    for key in ("session_id", "turn_id", "model"):
        if not isinstance(event.get(key), str) or not event[key]:
            raise ValueError(f"Missing required hook field: {key}")
    if kind == "UserPromptSubmit" and not isinstance(event.get("prompt"), str):
        raise ValueError("UserPromptSubmit requires a prompt string")
    return event


def category(prompt: str) -> str:
    words = prompt.lower()
    if len(prompt) > 1000 or any(term in words for term in ("whole project", "entire app", "end to end", "deploy", "publish", "release")):
        return "large"
    if any(term in words for term in ("implement", "fix", "bug", "code", "test", "refactor", "plugin", "build")):
        return "code"
    if any(term in words for term in ("research", "compare", "analyze", "investigate", "review", "search")):
        return "research"
    return "quick"


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
                (event["session_id"], event["turn_id"], event["model"], category(event["prompt"]), now))

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
            samples = db.execute("""SELECT ended_at-started_at AS duration FROM turns
                WHERE outcome='completed' AND model=? AND category=?
                AND ended_at > started_at ORDER BY ended_at DESC LIMIT 100""",
                (row["model"], row["category"])).fetchall()
        elapsed = max(0.0, now - row["started_at"])
        durations = [r["duration"] for r in samples]
        return {
            "model": row["model"],
            "category": row["category"],
            "elapsed": elapsed,
            "remaining": remaining_seconds(elapsed, durations, PRIORS[row["category"]]),
            "samples": len(durations),
        }


def remaining_seconds(elapsed: float, durations: list[float], prior: float) -> float:
    """Conditional median remaining time for a lognormal duration model.

    The category prior is six virtual observations. Completed matching turns
    gradually replace it; the survival condition makes the estimate move as
    a long turn continues past its initial prediction.
    """
    logs = [math.log(d) for d in durations if d > 0]
    weight = len(logs) / (len(logs) + 6)
    mu = (1 - weight) * math.log(prior) + weight * (statistics.mean(logs) if logs else math.log(prior))
    sigma = max(0.35, statistics.stdev(logs) if len(logs) > 1 else SPREAD)
    normal = statistics.NormalDist()
    if elapsed <= 0:
        return math.exp(mu)
    z = (math.log(max(elapsed, 0.01)) - mu) / sigma
    survival = max(1e-12, 1 - normal.cdf(z))
    target_cdf = min(1 - 1e-12, 1 - survival / 2)
    conditional_median = math.exp(mu + sigma * normal.inv_cdf(target_cdf))
    return max(0.0, conditional_median - elapsed)
