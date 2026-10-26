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
    monkeypatch.setenv("RUN_TIMES", "")
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
    return TestClient(app_module.app), store


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
