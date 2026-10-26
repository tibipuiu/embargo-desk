"""EurekAlert! embargo scout for ZME Science - command line.

Commands:
  python agent.py login               open a browser window and log in to EurekAlert! yourself
  python agent.py discover            save logged-in page snapshots to data/debug/ and list embargo links
  python agent.py run                 fetch new embargoed releases, pick story candidates, write a digest
  python agent.py run --dry-run       fetch and parse only, no Claude calls
  python agent.py run --all           consider every new release, not just embargoed ones
  python agent.py create-user NAME    add a web app account (prompts for a password)

The web app (web/app.py) runs the same pipeline on a schedule.
"""

import argparse
import getpass
import sys

from eureka.browser import open_session
from eureka.config import BASE_URL, Config, load_config
from eureka.parse import embargo_links, parse_listing, parse_release
from eureka.pipeline import run_tracked
from eureka.store import Store


def cmd_login(cfg: Config) -> int:
    with open_session(cfg, headless=False) as s:
        s.page.goto(BASE_URL + "/login")
        input("\nLog in to EurekAlert! in the browser window that just opened, then press Enter here... ")
        if s.is_logged_in():
            print(f"Logged in. The session is saved in {cfg.profile_dir}.")
            return 0
        print("Could not confirm the login (no logout link found). Try `python agent.py discover` to check.")
        return 1


def cmd_discover(cfg: Config) -> int:
    cfg.debug_dir.mkdir(parents=True, exist_ok=True)
    with open_session(cfg) as s:
        print(f"Logged in: {s.is_logged_in()}")
        pages = {f"listing{i}": u for i, u in enumerate(cfg.listing_urls)}
        pages["home"] = BASE_URL + "/"
        for name, url in pages.items():
            html = s.get(url)
            (cfg.debug_dir / f"{name}.html").write_text(html, encoding="utf-8")
            items = parse_listing(html)
            flagged = sum(1 for i in items if i.embargo_text)
            print(f"\n{name}: {url}\n  {len(items)} releases parsed, {flagged} with an embargo time on the listing")
            for label, link in embargo_links(html):
                print(f"  embargo link: {label!r} -> {link}")
            if items:
                first = items[0]
                rhtml = s.get(first.url)
                (cfg.debug_dir / f"{name}_release_{first.release_id}.html").write_text(rhtml, encoding="utf-8")
                rel = parse_release(rhtml, first.url)
                print(f"  sample release: {rel.title[:80]!r}\n  embargo: {rel.embargo_text or 'not detected'}"
                      f" | journal: {rel.journal or '?'} | body: {len(rel.body)} chars")
    print(f"\nSnapshots saved to {cfg.debug_dir}")
    return 0


def cmd_run(cfg: Config, dry_run: bool, include_all: bool) -> int:
    store = Store(cfg.db_path)
    run_id = run_tracked(cfg, store, "cli", dry_run=dry_run, include_all=include_all)
    run = store.run(run_id)
    print(f"\n{run['status'].upper()}: {run['summary']}")
    return 0 if run["status"] == "ok" else 1


def cmd_create_user(cfg: Config, username: str, display_name: str, admin: bool) -> int:
    store = Store(cfg.db_path)
    if store.user_by_name(username):
        print(f"User {username!r} already exists.")
        return 1
    password = getpass.getpass(f"Password for {username}: ")
    if len(password) < 10:
        print("Use at least 10 characters.")
        return 1
    store.create_user(username, display_name or username, password, is_admin=admin)
    print(f"Created {'admin ' if admin else ''}user {username!r}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login")
    sub.add_parser("discover")
    run = sub.add_parser("run")
    run.add_argument("--dry-run", action="store_true", help="fetch and parse only; no Claude calls")
    run.add_argument("--all", action="store_true", help="include releases not marked as embargoed")
    user = sub.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--name", default="", help="display name, e.g. 'Jane Doe'")
    user.add_argument("--admin", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    if args.command == "login":
        return cmd_login(cfg)
    if args.command == "discover":
        return cmd_discover(cfg)
    if args.command == "create-user":
        return cmd_create_user(cfg, args.username, args.name, args.admin)
    return cmd_run(cfg, args.dry_run, args.all)


if __name__ == "__main__":
    sys.exit(main())
