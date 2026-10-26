"""Embargo Desk fetcher.

Runs on a colleague's computer: opens EurekAlert! in a browser window (logged
in with their own reporter account), collects new embargoed releases, and
uploads them to Embargo Desk, which scores them and puts the picks on the board.

    python collect.py              fetch and upload
    python collect.py --discover   save the listing and one release to debug/ (for troubleshooting)

Settings (server address and personal upload key) are in fetcher.json, which
comes with the download from the Fetch page.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import asdict
from pathlib import Path

from eureka.browser import EurekaSession, open_session
from eureka.collect import fetch_releases, gather_listing
from eureka.config import BASE_URL, load_config
from eureka.parse import looks_logged_in, parse_listing, parse_release

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "fetcher.json"
LOGIN_WAIT_MINUTES = 15


class Server:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def call(self, method: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
        req = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                     "User-Agent": "EmbargoDeskFetcher/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise SystemExit("Embargo Desk didn't accept this fetcher's key. Download the fetcher again "
                                 "from the Fetch page (each download replaces the previous key).")
            raise SystemExit(f"Embargo Desk returned an error ({e.code}). Try again in a few minutes.")
        except urllib.error.URLError as e:
            raise SystemExit(f"Couldn't reach Embargo Desk at {self.url}: {e.reason}")

    def known(self, ids: list[str]) -> set[str]:
        return set(self.call("POST", "/api/known", {"ids": ids})["known"])


def say(msg: str, log: list[str] | None = None) -> None:
    print(msg, flush=True)
    if log is not None:
        log.append(msg)


def ensure_logged_in(s: EurekaSession) -> bool:
    if s.is_logged_in():
        return True
    say("\nPlease log in to EurekAlert! in the browser window that just opened,")
    say("with your own reporter account. The fetcher continues by itself once you're in.")
    s.page.goto(BASE_URL + "/login")
    deadline = time.time() + LOGIN_WAIT_MINUTES * 60
    while time.time() < deadline:
        time.sleep(2)
        url = s.page.url
        if "eurekalert.org" in url and "/login" not in url:
            try:
                s.page.wait_for_load_state("domcontentloaded", timeout=15_000)
                if looks_logged_in(s.page.content()):
                    say("Logged in. Thanks! This browser remembers it for next time.\n")
                    return True
            except Exception:
                pass
    return False


def discover(cfg) -> None:
    cfg.debug_dir.mkdir(parents=True, exist_ok=True)
    with open_session(cfg, headless=False) as s:
        if not ensure_logged_in(s):
            raise SystemExit("Not logged in to EurekAlert!.")
        for i, url in enumerate(cfg.listing_urls):
            html = s.get(url)
            (cfg.debug_dir / f"listing{i}.html").write_text(html, encoding="utf-8")
            items = parse_listing(html)
            say(f"{url}: {len(items)} releases found")
            if items:
                rhtml = s.get(items[0].url)
                (cfg.debug_dir / f"release_{items[0].release_id}.html").write_text(rhtml, encoding="utf-8")
                rel = parse_release(rhtml, items[0].url)
                say(f"  first: {rel.title[:80]!r} | embargo: {rel.embargo_text or 'not found'} | {len(rel.body)} characters")
    say(f"\nSaved to {cfg.debug_dir}. Send that folder to whoever looks after Embargo Desk.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Embargo Desk fetcher")
    parser.add_argument("--discover", action="store_true", help="save pages to debug/ for troubleshooting")
    args = parser.parse_args()

    if not SETTINGS.exists():
        raise SystemExit("fetcher.json is missing. Download the fetcher from the Fetch page in Embargo Desk.")
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    cfg = load_config()
    if args.discover:
        discover(cfg)
        return 0

    server = Server(settings["server"], settings["key"])
    who = server.call("GET", "/api/ping")["user"]
    log: list[str] = []
    say(f"Embargo Desk fetcher, signed in to {server.url} as {who}.", log)
    say("Opening EurekAlert! (keep the browser window open until this finishes)...", log)

    with open_session(cfg, headless=False) as s:
        if not ensure_logged_in(s):
            raise SystemExit("Didn't see a EurekAlert! login within 15 minutes. Run the fetcher again when ready.")
        items = gather_listing(s, cfg, server.known, lambda m: say(m, log))
        if not items:
            say("\nNo new embargoed releases since the last fetch. Nothing to upload.", log)
            return 0
        say(f"Reading {len(items)} new releases...", log)
        releases = fetch_releases(s, items, lambda m: say(m, log))

    say(f"Uploading {len(releases)} releases to Embargo Desk...", log)
    result = server.call("POST", "/api/upload", {"releases": [asdict(r) for r in releases], "log": log}, timeout=300)
    say(f"\nDone: {result['new']} new releases uploaded. Embargo Desk is scoring them now;")
    say(f"the picks appear on the board in a few minutes. Progress: {result['url']}")
    webbrowser.open(result["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
