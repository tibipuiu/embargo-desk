"""Logged-in EurekAlert! session backed by a persistent Chromium profile.

You log in once with `python agent.py login` (a real browser window opens and
you type your AAAS credentials yourself). The cookies are kept in
.browser-profile/ so the daily run can reuse them. If the session
expires and EUREKA_EMAIL / EUREKA_PASSWORD are set in .env, the agent tries to
log back in automatically through the AAAS (Auth0) login form.
"""

import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import BrowserContext, TimeoutError as PlaywrightTimeout, sync_playwright

from .config import BASE_URL, Config
from .parse import looks_logged_in


class EurekaSession:
    def __init__(self, ctx: BrowserContext, cfg: Config):
        self.ctx = ctx
        self.cfg = cfg
        self.page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def get(self, url: str) -> str:
        self.page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=10_000)
        except PlaywrightTimeout:
            pass
        time.sleep(self.cfg.request_delay)
        return self.page.content()

    def is_logged_in(self) -> bool:
        return looks_logged_in(self.get(BASE_URL + "/"))

    def auto_login(self) -> bool:
        if not (self.cfg.email and self.cfg.password):
            return False
        page = self.page
        page.goto(BASE_URL + "/login", wait_until="domcontentloaded", timeout=60_000)
        try:
            # AAAS uses Auth0's identifier-first flow: email, then password.
            page.fill("input[name=username], input[type=email]", self.cfg.email, timeout=20_000)
            page.locator("button[type=submit]").first.click()
            page.fill("input[name=password], input[type=password]", self.cfg.password, timeout=20_000)
            page.locator("button[type=submit]").first.click()
            page.wait_for_url("**eurekalert.org/**", timeout=45_000)
        except PlaywrightTimeout:
            return False
        return self.is_logged_in()


VIRTUAL_DISPLAY = ":99"


@contextmanager
def virtual_display(needed: bool) -> Iterator[None]:
    """On a Linux server with no screen, run Xvfb so a non-headless Chromium has one to draw on.

    Started only for the length of a browser session, so the web app never depends on it.
    """
    if not needed or os.environ.get("DISPLAY") or not sys.platform.startswith("linux") or not shutil.which("Xvfb"):
        yield
        return
    # A lock file left by a previous crash would stop Xvfb from starting.
    Path(f"/tmp/.X{VIRTUAL_DISPLAY[1:]}-lock").unlink(missing_ok=True)
    proc = subprocess.Popen(
        ["Xvfb", VIRTUAL_DISPLAY, "-screen", "0", "1280x900x24", "-nolisten", "tcp"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    time.sleep(1.5)
    if proc.poll() is not None:
        raise RuntimeError(f"Xvfb failed to start: {proc.stderr.read().decode(errors='replace')[-500:]}")
    os.environ["DISPLAY"] = VIRTUAL_DISPLAY
    try:
        yield
    finally:
        os.environ.pop("DISPLAY", None)
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@contextmanager
def open_session(cfg: Config, headless: bool | None = None) -> Iterator[EurekaSession]:
    if headless is None:
        headless = cfg.headless
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    with virtual_display(needed=not headless), sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(cfg.profile_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            # Docker gives containers only 64 MB of /dev/shm, which makes Chromium
            # crash; this flag has it use /tmp instead.
            args=["--disable-dev-shm-usage"],
        )
        try:
            yield EurekaSession(ctx, cfg)
        finally:
            ctx.close()
