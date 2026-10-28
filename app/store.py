"""SQLite registry of repositories and their indexing status."""
import sqlite3
from datetime import datetime, timezone

from app.config import get_settings

ACTIVE_STATUSES = ("queued", "cloning", "indexing")

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT DEFAULT '',
    commit_sha TEXT DEFAULT '',
    files INTEGER DEFAULT 0,
    chunks INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
)
"""


def _connect():
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.data_dir / "registry.db")
    connection.row_factory = sqlite3.Row
    connection.execute(SCHEMA)
    return connection


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_repo(repo_id, url, owner, name, status="queued"):
    with _connect() as db:
        db.execute(
            "INSERT INTO repos (id, url, owner, name, status, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET url = excluded.url, status = excluded.status, "
            "error = '', updated_at = excluded.updated_at",
            (repo_id, url, owner, name, status, _now()),
        )


def update_repo(repo_id, **fields):
    allowed = {"status", "error", "commit_sha", "files", "chunks"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    updates["updated_at"] = _now()
    assignments = ", ".join(f"{column} = ?" for column in updates)
    with _connect() as db:
        db.execute(f"UPDATE repos SET {assignments} WHERE id = ?", (*updates.values(), repo_id))


def get_repo(repo_id):
    with _connect() as db:
        row = db.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return dict(row) if row else None


def list_repos():
    with _connect() as db:
        rows = db.execute("SELECT * FROM repos ORDER BY updated_at DESC").fetchall()
    return [dict(row) for row in rows]
