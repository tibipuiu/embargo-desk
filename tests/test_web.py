import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from eureka.parse import Release

REVIEW = {
    "fit_score": 8, "verdict": "strong pick", "topic": "Archaeology",
    "headline_idea": "Neolithic farmers bred drought-proof wheat 7,000 years ago",
    "hook": "Climate adaptation is older than we thought.", "key_finding": "Seeds show selection for drought tolerance.",
    "why_it_fits": "Ancient + climate angle.", "caveats": ["Single site"], "study_type": "fieldwork",
    "visual_potential": "high",
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ADMIN_USERNAME", "editor")
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse-battery")
    monkeypatch.setenv("SECURE_COOKIES", "false")
    for mod in [m for m in sys.modules if m.startswith(("web", "eureka.config"))]:
        del sys.modules[mod]
    import eureka.config
    importlib.reload(eureka.config)
    app_module = importlib.import_module("web.app")

    store = app_module.store
    rel = Release(release_id="1150001", url="https://www.eurekalert.org/news-releases/1150001",
                  title="Ancient seed vault reveals drought-tolerant wheat", institution="Example University",
                  journal="Science", embargo_text="Embargoed until 28-Oct-2099 11:00 ET", body="Para one.\nPara two.")
    store.add(rel)
    store.save_triage("1150001", {"release_id": "1150001", "keep": True, "reason": "Great story"})
    store.save_review("1150001", REVIEW, 8)
    rel2 = Release(release_id="1150002", url="https://www.eurekalert.org/news-releases/1150002",
                   title="University announces new dean", embargo_text="Embargoed")
    store.add(rel2)
    store.save_triage("1150002", {"release_id": "1150002", "keep": False, "reason": "Institutional news"})
    store.create_user("ana", "Ana Writer", "another-long-pass")
    c = TestClient(app_module.app)
    c.scored = []  # run ids handed to the scorer, instead of starting real processes
    monkeypatch.setattr(app_module.runner, "score", c.scored.append)
    return c, store


def login(c, user="editor", pw="correct-horse-battery"):
    return c.post("/login", data={"username": user, "password": pw}, follow_redirects=False)


def test_requires_login(client):
    c, _ = client
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_bad_password(client):
    c, _ = client
    r = login(c, pw="nope")
    assert "Wrong username or password" in r.text


def test_board_claim_and_notes(client):
    c, store = client
    assert login(c).status_code == 303
    board = c.get("/")
    assert "Neolithic farmers bred drought-proof wheat" in board.text
    assert "Embargo in" in board.text
    assert "1 <a href=\"/passed" in board.text

    c.post("/release/1150001/status", data={"status": "claimed", "assignee": "me"})
    item = store.item("1150001")
    assert item["status"] == "claimed" and item["assignee_name"] == "editor"

    c.post("/release/1150001/notes", data={"body": "Call the lead author <b>today</b>"})
    page = c.get("/release/1150001")
    assert "Call the lead author &lt;b&gt;today&lt;/b&gt;" in page.text  # escaped
    assert "Para two." in page.text

    passed = c.get("/passed")
    assert "Institutional news" in passed.text


def test_cross_site_post_refused(client):
    c, store = client
    login(c)
    r = c.post("/release/1150001/status", data={"status": "passed"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert store.item("1150001")["status"] == "new"


def test_settings_admin_only(client):
    c, store = client
    login(c, "ana", "another-long-pass")
    assert c.get("/settings").status_code == 403
    c.post("/logout")
    login(c)
    assert c.get("/settings").status_code == 200
    c.post("/settings/users", data={"display_name": "Bo", "username": "bo", "password": "long-enough-pw"})
    assert store.user_by_name("bo") is not None
    c.post("/settings/profile", data={"profile": "Only space stories."})
    assert store.get_setting("editorial_profile") == "Only space stories."


def get_key(c):
    """Download the fetcher like a user would and read the key out of it."""
    import io, json, zipfile
    r = c.post("/fetch/download")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    settings = json.loads(zf.read("Embargo Desk Fetcher/fetcher.json"))
    return settings, names, zf


def test_fetcher_download_contains_everything(client):
    c, store = client
    login(c, "ana", "another-long-pass")
    settings, names, zf = get_key(c)
    for f in ["collect.py", "eureka/browser.py", "eureka/collect.py", "requirements.txt",
              "1 - Set up (Windows).bat", "2 - Fetch embargoes (Mac).command", "README.txt"]:
        assert f"Embargo Desk Fetcher/{f}" in names
    assert settings["user"] == "Ana Writer" and settings["key"].startswith("edk_")
    mac = zf.getinfo("Embargo Desk Fetcher/1 - Set up (Mac).command")
    assert (mac.external_attr >> 16) & 0o111  # executable on macOS
    assert b"\r\n" in zf.read("Embargo Desk Fetcher/1 - Set up (Windows).bat")  # Windows line endings
    assert store.user_by_api_key(settings["key"])["username"] == "ana"


def test_upload_flow(client):
    c, store = client
    login(c, "ana", "another-long-pass")
    key = get_key(c)[0]["key"]
    c.post("/logout")
    auth = {"Authorization": f"Bearer {key}"}

    assert c.get("/api/ping", headers=auth).json() == {"user": "Ana Writer"}
    assert c.get("/api/ping", headers={"Authorization": "Bearer edk_wrong"}).status_code == 401
    assert c.post("/api/known", json={"ids": ["1150001", "1159999"]}, headers=auth).json() == {"known": ["1150001"]}

    new = {"release_id": "1159999", "url": "https://www.eurekalert.org/news-releases/1159999",
           "title": "Bees count to five", "embargo_text": "Embargoed until 30-Oct-2099 10:00 ET",
           "body": "x" * 100_000, "unexpected": "ignored"}
    bad = {"release_id": "../etc", "url": "https://evil.example", "title": "nope"}
    old = {"release_id": "1150001", "url": "https://www.eurekalert.org/news-releases/1150001", "title": "dup"}
    r = c.post("/api/upload", json={"releases": [new, bad, old], "log": ["Listing page 1: 3 releases, 1 new"]},
               headers=auth).json()
    assert r["new"] == 1
    run = store.run(r["run_id"])
    assert run["trigger"] == "fetch: Ana Writer" and run["status"] == "running"
    assert "Listing page 1" in run["log"]
    assert c.scored == [r["run_id"]]
    saved = store.get("1159999")
    assert saved.title == "Bees count to five" and len(saved.body) == 60_000

    # Nothing new: the run finishes straight away, no scoring.
    r2 = c.post("/api/upload", json={"releases": [old]}, headers=auth).json()
    assert r2["new"] == 0 and store.run(r2["run_id"])["status"] == "ok"
    assert c.scored == [r["run_id"]]


def test_revoke_key(client):
    c, store = client
    login(c)
    key = get_key(c)[0]["key"]
    c.post("/fetch/revoke")
    assert c.get("/api/ping", headers={"Authorization": f"Bearer {key}"}).status_code == 401
