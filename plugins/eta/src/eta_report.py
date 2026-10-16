"""Explicit command the active Codex agent uses to report its remaining time."""

import argparse
import json
from pathlib import Path
import sys

from eta_core import CATEGORIES, EtaStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--remaining-seconds", required=True, type=float)
    parser.add_argument("--category", required=True, choices=sorted(CATEGORIES))
    args = parser.parse_args()
    result = EtaStore(args.data_dir / "eta.sqlite3").set_estimate(
        args.session_id, args.turn_id, args.remaining_seconds, args.category)
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ETA report failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
