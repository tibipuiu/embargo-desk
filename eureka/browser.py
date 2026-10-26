"""Logged-in EurekAlert! session backed by a persistent Chromium profile.

You log in once with `python agent.py login` (a real browser window opens and
you type your AAAS credentials yourself). The cookies are kept in
.browser-profile/ so the daily run can reuse them. If the session
expires and EUREKA_EMAIL / EUREKA_PASSWORD are set in .env, the agent tries to
log back in automatically through the AAAS (Auth0) login form.
"""

import time
from contextlib import contextmanager
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


@contextmanager
def open_session(cfg: Config, headless: bool | None = None) -> Iterator[EurekaSession]:
    if headless is None:
        headless = cfg.headless
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
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
