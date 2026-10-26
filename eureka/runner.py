"""Starts pipeline runs in a separate, low-priority process.

Running the scan inside the web server made the whole site freeze while
Chromium and the parser were busy. A child process (`agent.py run`) keeps the
web app responsive, and if the scan dies (e.g. killed for using too much
memory) the site stays up and the run is marked as failed.
"""

import shutil
import subprocess
import sys
import threading
from typing import Callable

from .config import ROOT, Config
from .store import Store


def default_command(trigger: str) -> list[str]:
    cmd = [sys.executable, str(ROOT / "agent.py"), "run", "--trigger", trigger]
    if sys.platform.startswith("linux") and shutil.which("nice"):
        cmd = ["nice", "-n", "15", *cmd]
    return cmd


class RunManager:
    def __init__(self, cfg: Config, store: Store, command: Callable[[str], list[str]] = default_command):
        self.cfg = cfg
        self.store = store
        self.command = command
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _reap(self) -> None:
        """Forget a finished child; if it died without recording its result, record it."""
        if self._proc is None or self._proc.poll() is None:
            return
        code = self._proc.returncode
        if code != 0:
            reason = "killed (likely out of memory)" if code in (-9, 137) else f"exited with code {code}"
            self.store.fail_running_runs(f"Run process {reason}")
        self._proc = None

    def is_running(self) -> bool:
        with self._lock:
            self._reap()
            if self._proc is not None:
                return True
        # A run started from the command line also counts.
        return self.store.active_run() is not None

    def start(self, trigger: str) -> bool:
        """Start a run unless one is already going. Returns False if one was."""
        with self._lock:
            self._reap()
            if self._proc is not None or self.store.active_run() is not None:
                return False
            self._proc = subprocess.Popen(self.command(trigger), cwd=ROOT)
            return True

    def check(self) -> None:
        """Called periodically so a crashed run gets marked even if nobody opens the site."""
        with self._lock:
            self._reap()
