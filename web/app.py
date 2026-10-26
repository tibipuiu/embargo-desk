"""Web app: a shared board of embargoed story picks for the ZME Science team.

Run locally:   uvicorn web.app:app --reload
In Docker:     see Dockerfile / docker-compose.yml
"""

import threading
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from eureka.config import load_config
from eureka.pipeline import Pipeline, editorial_profile, is_running, run_tracked
from eureka.scheduler import start_scheduler
from eureka.store import STATUSES, Store

HERE = Path(__file__).parent
EASTERN = ZoneInfo("America/New_York")

cfg = load_config()
if not cfg.secret_key:
    raise SystemExit("Set SECRET_KEY in .env (any long random string) before starting the web app.")
store = Store(cfg.db_path)
store.fail_stale_runs()

# First start: create the admin account from ADMIN_USERNAME / ADMIN_PASSWORD.
if cfg.admin_username and cfg.admin_password and not store.users():
    store.create_user(cfg.admin_username, cfg.admin_username, cfg.admin_password, is_admin=True)

@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_scheduler(cfg, store)
    yield


app = FastAPI(title="Embargo Desk", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=cfg.secret_key,
    session_cookie="embargo_desk",
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=cfg.secure_cookies,
)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@app.middleware("http")
async def same_origin_posts(request: Request, call_next):
    # Session cookies are SameSite=Lax; also refuse cross-site form posts outright.
    if request.method == "POST":
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host"):
            return PlainTextResponse("Cross-site request refused", status_code=403)
    return await call_next(request)


# --- helpers ---------------------------------------------------------------

def current_user(request: Request):
    uid = request.session.get("uid")
    user = store.user(uid) if uid else None
    if not user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


def require_admin(request: Request):
    user = current_user(request)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admins only")
    return user


def render(request: Request, name: str, **ctx) -> HTMLResponse:
    ctx.setdefault("user", None)
    ctx["running"] = is_running()
    ctx["flash"] = request.session.pop("flash", None)
    return templates.TemplateResponse(request, name, ctx)


def back(url: str, flash: str | None = None, request: Request | None = None) -> RedirectResponse:
    if flash and request is not None:
        request.session["flash"] = flash
    return RedirectResponse(url, status_code=303)


def embargo_label(iso: str | None) -> dict | None:
    if not iso:
        return None
    lifts = datetime.fromisoformat(iso).replace(tzinfo=EASTERN)
    delta = lifts - datetime.now(EASTERN)
    hours = delta.total_seconds() / 3600
    if hours <= 0:
        rel = "lifted"
    elif hours < 24:
        rel = f"in {int(hours)}h" if hours >= 1 else "within the hour"
    else:
        rel = f"in {int(hours // 24)}d {int(hours % 24)}h"
    return {"when": lifts.strftime("%a %d %b, %H:%M ET"), "rel": rel, "lifted": hours <= 0, "soon": 0 < hours < 24}


def ago(iso: str | None) -> str:
    if not iso:
        return ""
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    return f"{int(secs // 86400)} d ago"


templates.env.filters["embargo"] = embargo_label
templates.env.filters["ago"] = ago


# --- auth ------------------------------------------------------------------

_failed: dict[str, list[float]] = defaultdict(list)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else "?"
    recent = [t for t in _failed[ip] if time.time() - t < 900]
    _failed[ip] = recent
    if len(recent) >= 10:
        return render(request, "login.html", error="Too many attempts. Try again in 15 minutes.")
    user = store.authenticate(username, password)
    if not user:
        recent.append(time.time())
        return render(request, "login.html", error="Wrong username or password.")
    request.session.clear()
    request.session["uid"] = user["id"]
    return back("/")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return back("/login")


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"


# --- board -----------------------------------------------------------------

VERDICT_RANK = {"strong pick": 0, "maybe": 1, "skip": 2}


@app.get("/", response_class=HTMLResponse)
def board(request: Request, days: int = 3, verdict: str = "picks", status: str = "", sort: str = "score"):
    user = current_user(request)
    items = store.board(days=days, reviewed=True, status=status or None)
    if verdict == "picks":
        items = [i for i in items if i["review"]["verdict"] != "skip"]
    elif verdict in VERDICT_RANK:
        items = [i for i in items if i["review"]["verdict"] == verdict]
    if sort == "embargo":
        items.sort(key=lambda i: i["embargo_until"] or "9999")
    else:
        items.sort(key=lambda i: (VERDICT_RANK.get(i["review"]["verdict"], 3), -(i["score"] or 0)))
    passed_count = len(store.board(days=days, reviewed=False))
    last_run = (store.runs(1) or [None])[0]
    return render(
        request, "board.html", user=user, items=items, days=days, verdict=verdict, status=status,
        sort=sort, statuses=STATUSES, passed_count=passed_count, last_run=last_run,
    )


@app.get("/passed", response_class=HTMLResponse)
def passed(request: Request, days: int = 3):
    user = current_user(request)
    items = store.board(days=days, reviewed=False)
    return render(request, "passed.html", user=user, items=items, days=days)


# --- release detail --------------------------------------------------------

@app.get("/release/{release_id}", response_class=HTMLResponse)
def release_detail(request: Request, release_id: str):
    user = current_user(request)
    item = store.item(release_id)
    if not item:
        raise HTTPException(404)
    return render(
        request, "release.html", user=user, item=item, notes=store.notes(release_id),
        statuses=STATUSES, users=store.users(),
    )


@app.post("/release/{release_id}/status")
def release_status(request: Request, release_id: str, status: str = Form(...), assignee: str = Form(""),
                   next: str = Form("")):
    user = current_user(request)
    if status not in STATUSES:
        raise HTTPException(400)
    if assignee == "me":
        assignee_id = user["id"]
    else:
        assignee_id = int(assignee) if assignee.isdigit() else None
    if status == "new":
        assignee_id = None
    store.set_status(release_id, status, assignee_id)
    return back(next or f"/release/{release_id}")


@app.post("/release/{release_id}/notes")
def release_note(request: Request, release_id: str, body: str = Form(...)):
    user = current_user(request)
    if body.strip():
        store.add_note(release_id, user["id"], body.strip()[:5000])
    return back(f"/release/{release_id}#notes")


_reviewing: set[str] = set()


@app.post("/release/{release_id}/review")
def release_review(request: Request, release_id: str):
    current_user(request)
    if release_id not in _reviewing:
        _reviewing.add(release_id)

        def work():
            try:
                Pipeline(cfg, store).review_one(release_id)
            except Exception as e:
                print(f"review of {release_id} failed: {e}", flush=True)
            finally:
                _reviewing.discard(release_id)

        threading.Thread(target=work, daemon=True).start()
    return back(f"/release/{release_id}", "Full review started. Refresh in a minute.", request)


# --- runs ------------------------------------------------------------------

@app.get("/runs", response_class=HTMLResponse)
def runs(request: Request):
    user = current_user(request)
    return render(request, "runs.html", user=user, runs=store.runs(), run_times=cfg.run_times)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: int):
    user = current_user(request)
    run = store.run(run_id)
    if not run:
        raise HTTPException(404)
    return render(request, "run.html", user=user, run=run)


@app.post("/runs")
def run_now(request: Request):
    user = current_user(request)
    if is_running():
        return back("/runs", "A run is already in progress.", request)
    threading.Thread(target=run_tracked, args=(cfg, store, f"manual: {user['display_name']}"), daemon=True).start()
    time.sleep(0.5)
    return back("/runs", "Run started.", request)


# --- settings & team -------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    user = require_admin(request)
    return render(request, "settings.html", user=user, profile=editorial_profile(cfg, store), users=store.users(), cfg=cfg)


@app.post("/settings/profile")
def save_profile(request: Request, profile: str = Form(...)):
    require_admin(request)
    store.set_setting("editorial_profile", profile.replace("\r\n", "\n"))
    return back("/settings", "Editorial profile saved. It applies from the next run.", request)


@app.post("/settings/users")
def add_user(request: Request, username: str = Form(...), display_name: str = Form(...),
             password: str = Form(...), is_admin: str = Form("")):
    require_admin(request)
    if store.user_by_name(username):
        return back("/settings", f"Username {username!r} is taken.", request)
    if len(password) < 10:
        return back("/settings", "Passwords need at least 10 characters.", request)
    store.create_user(username, display_name, password, is_admin=bool(is_admin))
    return back("/settings", f"Added {display_name}. Send them the address, username and password.", request)


@app.post("/settings/users/{user_id}/password")
def reset_password(request: Request, user_id: int, password: str = Form(...)):
    require_admin(request)
    if len(password) < 10:
        return back("/settings", "Passwords need at least 10 characters.", request)
    store.set_password(user_id, password)
    return back("/settings", "Password reset.", request)


@app.post("/settings/users/{user_id}/delete")
def delete_user(request: Request, user_id: int):
    admin = require_admin(request)
    if user_id == admin["id"]:
        return back("/settings", "You can't remove your own account.", request)
    store.delete_user(user_id)
    return back("/settings", "Account removed.", request)


@app.get("/account", response_class=HTMLResponse)
def account(request: Request):
    return render(request, "account.html", user=current_user(request))


@app.post("/account/password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...)):
    user = current_user(request)
    if not store.authenticate(user["username"], current):
        return back("/account", "Current password is wrong.", request)
    if len(new) < 10:
        return back("/account", "Use at least 10 characters.", request)
    store.set_password(user["id"], new)
    return back("/account", "Password changed.", request)
