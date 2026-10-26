"""SQLite store shared by the pipeline and the web app.

Every method opens its own short-lived connection, so the store is safe to use
from the web server's threads and from the background pipeline thread at once.
"""

import hashlib
import hmac
import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .parse import Release

STATUSES = ["new", "claimed", "writing", "published", "passed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS releases (
    release_id    TEXT PRIMARY KEY,
    data          TEXT NOT NULL,
    embargoed     INTEGER NOT NULL,
    embargo_until TEXT,
    fetched_at    TEXT NOT NULL,
    run_id        INTEGER,
    triage        TEXT,
    review        TEXT,
    score         INTEGER,
    reviewed_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'new',
    assignee_id   INTEGER REFERENCES users(id),
    updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS releases_fetched ON releases(fetched_at);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin      INTEGER NOT NULL DEFAULT 0,
    api_key_hash  TEXT,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    release_id TEXT NOT NULL REFERENCES releases(release_id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    body       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,
    trigger     TEXT NOT NULL,
    summary     TEXT,
    log         TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _key_hash(key: str) -> str:
    # Upload keys are long random strings, so a plain SHA-256 is enough.
    return hashlib.sha256(key.encode()).hexdigest()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # Databases created before upload keys existed.
            columns = {r["name"] for r in db.execute("PRAGMA table_info(users)")}
            if "api_key_hash" not in columns:
                db.execute("ALTER TABLE users ADD COLUMN api_key_hash TEXT")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        finally:
            db.close()

    # --- releases -----------------------------------------------------------

    def known_ids(self, release_ids: list[str]) -> set[str]:
        if not release_ids:
            return set()
        marks = ",".join("?" * len(release_ids))
        with self._conn() as db:
            rows = db.execute(f"SELECT release_id FROM releases WHERE release_id IN ({marks})", release_ids)
            return {r["release_id"] for r in rows}

    def untriaged_count(self, embargoed_only: bool) -> int:
        sql = "SELECT COUNT(*) FROM releases WHERE triage IS NULL" + (" AND embargoed=1" if embargoed_only else "")
        with self._conn() as db:
            return db.execute(sql).fetchone()[0]

    def has(self, release_id: str) -> bool:
        with self._conn() as db:
            return db.execute("SELECT 1 FROM releases WHERE release_id=?", (release_id,)).fetchone() is not None

    def add(self, release: Release, run_id: int | None = None) -> None:
        until = release.embargo_until
        with self._conn() as db:
            db.execute(
                "INSERT OR IGNORE INTO releases (release_id, data, embargoed, embargo_until, fetched_at, run_id)"
                " VALUES (?,?,?,?,?,?)",
                (release.release_id, json.dumps(release.to_dict()), int(release.is_embargoed),
                 until.isoformat() if until else None, now_iso(), run_id),
            )

    def get(self, release_id: str) -> Release:
        with self._conn() as db:
            row = db.execute("SELECT data FROM releases WHERE release_id=?", (release_id,)).fetchone()
        return Release(**json.loads(row["data"]))

    def untriaged(self, embargoed_only: bool) -> list[Release]:
        sql = "SELECT data FROM releases WHERE triage IS NULL"
        if embargoed_only:
            sql += " AND embargoed=1"
        with self._conn() as db:
            return [Release(**json.loads(r["data"])) for r in db.execute(sql)]

    def save_triage(self, release_id: str, triage: dict) -> None:
        with self._conn() as db:
            db.execute("UPDATE releases SET triage=? WHERE release_id=?", (json.dumps(triage), release_id))

    def save_review(self, release_id: str, review: dict, score: int) -> None:
        with self._conn() as db:
            db.execute(
                "UPDATE releases SET review=?, score=?, reviewed_at=? WHERE release_id=?",
                (json.dumps(review), score, now_iso(), release_id),
            )

    def results_for(self, release_ids: list[str]) -> list[dict]:
        marks = ",".join("?" * len(release_ids))
        return self._query_items(f"triage IS NOT NULL AND r.release_id IN ({marks})", release_ids)

    def board(self, days: int, reviewed: bool, status: str | None = None) -> list[dict]:
        """Items fetched in the last `days` days, either reviewed picks or triage rejects."""
        where = ["r.fetched_at >= datetime('now', ?)", "r.triage IS NOT NULL"]
        params: list = [f"-{days} days"]
        where.append("r.review IS NOT NULL" if reviewed else "r.review IS NULL")
        if status:
            where.append("r.status=?")
            params.append(status)
        return self._query_items(" AND ".join(where), params)

    def item(self, release_id: str) -> dict | None:
        items = self._query_items("r.release_id=?", [release_id])
        return items[0] if items else None

    def _query_items(self, where: str, params: list) -> list[dict]:
        sql = f"""
            SELECT r.*, u.display_name AS assignee_name,
                   (SELECT COUNT(*) FROM notes n WHERE n.release_id = r.release_id) AS note_count
            FROM releases r LEFT JOIN users u ON u.id = r.assignee_id
            WHERE {where}
            ORDER BY r.score IS NULL, r.score DESC, r.fetched_at DESC
        """
        with self._conn() as db:
            rows = db.execute(sql, params).fetchall()
        return [{
            "release": Release(**json.loads(r["data"])),
            "triage": json.loads(r["triage"]) if r["triage"] else None,
            "review": json.loads(r["review"]) if r["review"] else None,
            "score": r["score"],
            "status": r["status"],
            "assignee_id": r["assignee_id"],
            "assignee_name": r["assignee_name"],
            "embargo_until": r["embargo_until"],
            "fetched_at": r["fetched_at"],
            "note_count": r["note_count"],
        } for r in rows]

    def set_status(self, release_id: str, status: str, assignee_id: int | None) -> None:
        if status not in STATUSES:
            raise ValueError(status)
        with self._conn() as db:
            db.execute(
                "UPDATE releases SET status=?, assignee_id=?, updated_at=? WHERE release_id=?",
                (status, assignee_id, now_iso(), release_id),
            )

    # --- notes --------------------------------------------------------------

    def add_note(self, release_id: str, user_id: int, body: str) -> None:
        with self._conn() as db:
            db.execute(
                "INSERT INTO notes (release_id, user_id, body, created_at) VALUES (?,?,?,?)",
                (release_id, user_id, body, now_iso()),
            )

    def notes(self, release_id: str) -> list[sqlite3.Row]:
        with self._conn() as db:
            return db.execute(
                "SELECT n.*, u.display_name FROM notes n JOIN users u ON u.id = n.user_id"
                " WHERE release_id=? ORDER BY n.created_at",
                (release_id,),
            ).fetchall()

    # --- users --------------------------------------------------------------

    def create_user(self, username: str, display_name: str, password: str, is_admin: bool = False) -> None:
        with self._conn() as db:
            db.execute(
                "INSERT INTO users (username, display_name, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
                (username.strip().lower(), display_name.strip(), hash_password(password), int(is_admin), now_iso()),
            )

    def set_password(self, user_id: int, password: str) -> None:
        with self._conn() as db:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), user_id))

    def delete_user(self, user_id: int) -> None:
        with self._conn() as db:
            db.execute("UPDATE releases SET assignee_id=NULL WHERE assignee_id=?", (user_id,))
            db.execute("DELETE FROM notes WHERE user_id=?", (user_id,))
            db.execute("DELETE FROM users WHERE id=?", (user_id,))

    def new_api_key(self, user_id: int) -> str:
        """Create (or replace) the user's upload key. Only its hash is stored."""
        key = "edk_" + secrets.token_urlsafe(32)
        with self._conn() as db:
            db.execute("UPDATE users SET api_key_hash=? WHERE id=?", (_key_hash(key), user_id))
        return key

    def user_by_api_key(self, key: str) -> sqlite3.Row | None:
        if not key.startswith("edk_"):
            return None
        with self._conn() as db:
            return db.execute("SELECT * FROM users WHERE api_key_hash=?", (_key_hash(key),)).fetchone()

    def authenticate(self, username: str, password: str) -> sqlite3.Row | None:
        user = self.user_by_name(username)
        return user if user and verify_password(password, user["password_hash"]) else None

    def user_by_name(self, username: str) -> sqlite3.Row | None:
        with self._conn() as db:
            return db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()

    def user(self, user_id: int) -> sqlite3.Row | None:
        with self._conn() as db:
            return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def users(self) -> list[sqlite3.Row]:
        with self._conn() as db:
            return db.execute("SELECT * FROM users ORDER BY display_name").fetchall()

    # --- runs ---------------------------------------------------------------

    def start_run(self, trigger: str, summary: str | None = None) -> int:
        with self._conn() as db:
            cur = db.execute(
                "INSERT INTO runs (started_at, status, trigger, summary) VALUES (?, 'running', ?, ?)",
                (now_iso(), trigger, summary),
            )
            return cur.lastrowid

    def append_run_log(self, run_id: int, line: str) -> None:
        with self._conn() as db:
            db.execute("UPDATE runs SET log = log || ? WHERE id=?", (line + "\n", run_id))

    def finish_run(self, run_id: int, status: str, summary: str) -> None:
        with self._conn() as db:
            db.execute(
                "UPDATE runs SET status=?, summary=?, finished_at=? WHERE id=?",
                (status, summary, now_iso(), run_id),
            )

    def fail_stale_runs(self) -> None:
        """Runs left 'running' by a previous process (e.g. a container restart)."""
        with self._conn() as db:
            db.execute("UPDATE runs SET status='error', summary='Interrupted (server restarted)' WHERE status='running'")

    def fail_run(self, run_id: int, reason: str) -> None:
        """Mark a run failed, unless it already recorded its own result."""
        with self._conn() as db:
            db.execute(
                "UPDATE runs SET status='error', summary=COALESCE(summary || ' · ', '') || ?, finished_at=?"
                " WHERE id=? AND status='running'",
                (reason, now_iso(), run_id),
            )

    def runs(self, limit: int = 30) -> list[sqlite3.Row]:
        with self._conn() as db:
            return db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def run(self, run_id: int) -> sqlite3.Row | None:
        with self._conn() as db:
            return db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()

    # --- settings -----------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        with self._conn() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._conn() as db:
            db.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
