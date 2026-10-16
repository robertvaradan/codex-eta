"""Small, draggable Windows companion for the current Codex turn."""

from __future__ import annotations

import msvcrt
import os
from pathlib import Path
import tkinter as tk

from eta_core import EtaStore


def clock_text(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def main() -> None:
    data_dir = Path(os.environ["PLUGIN_DATA"])
    data_dir.mkdir(parents=True, exist_ok=True)
    lock = open(data_dir / "eta-window.lock", "a+b")
    if os.fstat(lock.fileno()).st_size == 0:
        lock.write(b"0")
        lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return

    store = EtaStore(data_dir / "eta.sqlite3")
    root = tk.Tk()
    root.title("ETA for Codex")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg="#20252d")
    width, height = 238, 70
    root.geometry(f"{width}x{height}+{root.winfo_screenwidth()-width-24}+58")

    frame = tk.Frame(root, bg="#20252d", highlightbackground="#46515e", highlightthickness=1)
    frame.pack(fill="both", expand=True)
    top = tk.Frame(frame, bg="#20252d")
    top.pack(fill="x", padx=12, pady=(7, 0))
    tk.Label(top, text="ETA", fg="#dce9fb", bg="#20252d", font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Button(top, text="×", command=root.destroy, borderwidth=0, bg="#20252d",
              activebackground="#384453", fg="#9eacbd", activeforeground="#ffffff",
              font=("Segoe UI", 10), cursor="hand2").pack(side="right")
    headline = tk.Label(frame, text="Ready for next turn", fg="#ffffff", bg="#20252d",
                        font=("Segoe UI", 13, "bold"), anchor="w")
    headline.pack(fill="x", padx=12)
    detail = tk.Label(frame, text="Drag to place beside Codex", fg="#9eacbd", bg="#20252d",
                      font=("Segoe UI", 8), anchor="w")
    detail.pack(fill="x", padx=12)

    drag = {"x": 0, "y": 0}

    def begin(event):
        drag["x"] = event.x_root - root.winfo_x()
        drag["y"] = event.y_root - root.winfo_y()

    def move(event):
        root.geometry(f"+{event.x_root-drag['x']}+{event.y_root-drag['y']}")

    for widget in (frame, top, headline, detail):
        widget.bind("<ButtonPress-1>", begin)
        widget.bind("<B1-Motion>", move)

    def refresh():
        try:
            turn = store.current()
            if turn:
                if turn["status"] == "waiting":
                    headline.configure(text="Waiting for agent ETA")
                elif turn["status"] == "overdue":
                    headline.configure(text="Awaiting revised ETA")
                else:
                    headline.configure(text=f"~ {clock_text(turn['remaining'])} left")
                source = "agent ETA" if turn["samples"] == 0 else f"agent × {turn['factor']:.2f}"
                detail.configure(text=f"{clock_text(turn['elapsed'])} elapsed  ·  {source}")
            else:
                headline.configure(text="Ready for next turn")
                detail.configure(text="Drag to place beside Codex")
        except Exception as exc:
            headline.configure(text="ETA unavailable")
            detail.configure(text=str(exc)[:42])
        root.after(1000, refresh)

    refresh()
    try:
        root.mainloop()
    finally:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        lock.close()


if __name__ == "__main__":
    main()
