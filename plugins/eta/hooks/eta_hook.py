"""Codex lifecycle hook entrypoint. Receives one documented JSON event on stdin."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from eta_core import EtaStore, require_event  # noqa: E402


def launch_window(data_dir: Path) -> None:
    window = Path(__file__).resolve().parents[1] / "src" / "eta_window.py"
    command = [sys.executable, str(window)]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.exists():
            command[0] = str(pythonw)
    env = os.environ.copy()
    env["PLUGIN_DATA"] = str(data_dir)
    subprocess.Popen(
        command,
        cwd=str(window.parent),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=sys.platform != "win32",
    )


def main() -> None:
    data_dir = Path(os.environ["PLUGIN_DATA"])
    event = require_event(json.load(sys.stdin))
    store = EtaStore(data_dir / "eta.sqlite3")
    kind = event["hook_event_name"]
    if kind == "UserPromptSubmit":
        store.start(event)
        launch_window(data_dir)
    elif kind == "Stop":
        store.finish(event, "completed")
        print("{}")
    elif kind == "Interrupt":
        store.finish(event, "interrupted")
    else:
        raise ValueError(f"Unsupported hook event: {kind}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ETA hook failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

