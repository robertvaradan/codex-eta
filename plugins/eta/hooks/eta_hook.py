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
        if not pythonw.is_file():
            raise FileNotFoundError(f"ETA requires the Windows Python GUI runtime: {pythonw}")
        command[0] = str(pythonw)
    env = os.environ.copy()
    env["PLUGIN_DATA"] = str(data_dir)
    with open(data_dir / "eta-window.log", "a", encoding="utf-8") as log:
        subprocess.Popen(
            command,
            cwd=str(window.parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=flags,
            start_new_session=sys.platform != "win32",
        )


def agent_context(event: dict, data_dir: Path) -> str:
    report = Path(__file__).resolve().parents[1] / "src" / "eta_report.py"

    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"

    command = (
        f"python {literal(report)} --data-dir {literal(data_dir)} "
        f"--session-id {literal(event['session_id'])} --turn-id {literal(event['turn_id'])} "
        "--remaining-seconds SECONDS --category CATEGORY"
    )
    return (
        "ETA desktop timer is enabled by the user. The primary agent determines the ETA. "
        "After reading the request and forming an initial plan, use the command below to report "
        "your best estimate of wall-clock seconds remaining until your final response for this turn. "
        "Include inspection, implementation, tool waits, verification, and final reporting you expect "
        "to perform. Revise it at meaningful phase changes, after unexpected work, and when reminded. "
        "Replace SECONDS with a positive number and CATEGORY with quick, research, code, or large, "
        "chosen from your understanding of the task. Each report is remaining time from now, not "
        "total duration. Report your own raw estimate; ETA applies local historical calibration once. "
        "Do not delay the task to make estimates match, and do not run a loop or start a separate "
        "agent just to update ETA. No report is needed if you are immediately giving a final answer. "
        "Delegated subagents must not report or revise the primary agent's ETA. "
        "The window explicitly waits if you have not supplied an estimate. "
        f"Use your shell execution tool to run this PowerShell command:\n{command}"
    )


def main() -> None:
    data_dir = Path(os.environ["PLUGIN_DATA"])
    event = require_event(json.load(sys.stdin))
    store = EtaStore(data_dir / "eta.sqlite3")
    kind = event["hook_event_name"]
    if kind == "UserPromptSubmit":
        store.start(event)
        launch_window(data_dir)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": kind,
            "additionalContext": agent_context(event, data_dir),
        }}))
    elif kind == "PostToolUse":
        if store.reminder_due(event["session_id"], event["turn_id"]):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": kind,
                "additionalContext": "ETA check-in: revise your remaining time based on what you now know.\n"
                    + agent_context(event, data_dir),
            }}))
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
