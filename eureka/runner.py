"""Scores uploaded releases in a separate, low-priority process.

Each upload from a colleague's computer creates a run; the web app hands it to
`agent.py score --run-id N`. A separate process keeps the website responsive,
and if scoring dies the site stays up and the run is marked failed. Uploads
that arrive while a run is scoring wait in a queue.
"""

import shutil
import subprocess
import sys
import threading
from typing import Callable

from .config import ROOT, Config
from .store import Store


def default_command(run_id: int) -> list[str]:
    cmd = [sys.executable, str(ROOT / "agent.py"), "score", "--run-id", str(run_id)]
    if sys.platform.startswith("linux") and shutil.which("nice"):
        cmd = ["nice", "-n", "15", *cmd]
    return cmd


class RunManager:
    def __init__(self, cfg: Config, store: Store, command: Callable[[int], list[str]] = default_command):
        self.cfg = cfg
        self.store = store
        self.command = command
        self._proc: subprocess.Popen | None = None
        self._run_id: int | None = None
        self._queue: list[int] = []
        self._lock = threading.Lock()

    def _advance(self) -> None:
        """Reap a finished child (recording a crash), then start the next queued run."""
        if self._proc is not None and self._proc.poll() is not None:
            code = self._proc.returncode
            if code != 0:
                reason = "killed (likely out of memory)" if code in (-9, 137) else f"exited with code {code}"
                self.store.fail_run(self._run_id, f"Scoring process {reason}")
            self._proc = self._run_id = None
        if self._proc is None and self._queue:
            self._run_id = self._queue.pop(0)
            self._proc = subprocess.Popen(self.command(self._run_id), cwd=ROOT)

    def score(self, run_id: int) -> None:
        """Queue a run for scoring; it starts right away if nothing else is scoring."""
        with self._lock:
            self._queue.append(run_id)
            self._advance()

    def is_running(self) -> bool:
        with self._lock:
            self._advance()
            return self._proc is not None

    def check(self) -> None:
        with self._lock:
            self._advance()
