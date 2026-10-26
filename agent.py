"""Embargo Desk server commands.

  python agent.py create-user NAME [--name "Full Name"] [--admin]   add a web app account
  python agent.py score --run-id N                                  score pending releases (the web app runs this)

Fetching from EurekAlert! happens on colleagues' computers: see collect.py and
the Fetch page in the web app.
"""

import argparse
import getpass
import sys

from eureka.config import load_config
from eureka.pipeline import score_run
from eureka.store import Store


def cmd_create_user(username: str, display_name: str, admin: bool) -> int:
    store = Store(load_config().db_path)
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


def cmd_score(run_id: int) -> int:
    cfg = load_config()
    store = Store(cfg.db_path)
    score_run(cfg, store, run_id)
    return 0 if store.run(run_id)["status"] == "ok" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("create-user")
    user.add_argument("username")
    user.add_argument("--name", default="", help="display name, e.g. 'Jane Doe'")
    user.add_argument("--admin", action="store_true")
    score = sub.add_parser("score")
    score.add_argument("--run-id", type=int, required=True)
    args = parser.parse_args()

    if args.command == "create-user":
        return cmd_create_user(args.username, args.name, args.admin)
    return cmd_score(args.run_id)


if __name__ == "__main__":
    sys.exit(main())
