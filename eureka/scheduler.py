"""Tiny in-process daily scheduler: runs the pipeline at each RUN_TIMES entry (server local time)."""

import threading
import time
from datetime import datetime

from .config import Config
from .pipeline import run_tracked
from .store import Store


def start_scheduler(cfg: Config, store: Store) -> threading.Thread:
    def loop() -> None:
        fired: set[str] = set()
        while True:
            now = datetime.now()
            for hhmm in cfg.run_times:
                key = f"{now:%Y-%m-%d} {hhmm}"
                if now.strftime("%H:%M") >= hhmm and key not in fired:
                    fired.add(key)
                    # Don't fire for times that already passed before the server started.
                    if (now - now.replace(hour=int(hhmm[:2]), minute=int(hhmm[3:]), second=0)).total_seconds() < 600:
                        run_tracked(cfg, store, "schedule")
            time.sleep(30)

    thread = threading.Thread(target=loop, name="scheduler", daemon=True)
    thread.start()
    return thread
