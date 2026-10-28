"""SQLite storage for workflow runs and their AI analysis."""
import json
import sqlite3

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    repo_id TEXT NOT NULL,
    run_id INTEGER NOT NULL,
    run_number INTEGER,
    name TEXT,
    event TEXT,
    branch TEXT,
    head_sha TEXT,
    message TEXT,
    status TEXT,
    conclusion TEXT,
    html_url TEXT,
    created_at TEXT,
    updated_at TEXT,
    jobs_json TEXT DEFAULT '[]',
    analysis_json TEXT DEFAULT '',
    PRIMARY KEY (repo_id, run_id)
)
"""

RUN_FIELDS = (
    "run_number", "name", "event", "branch", "head_sha", "message",
    "status", "conclusion", "html_url", "created_at", "updated_at",
)


def _connect():
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.data_dir / "registry.db")
    connection.row_factory = sqlite3.Row
    connection.execute(SCHEMA)
    return connection


def _to_dict(row):
    if row is None:
        return None
    data = dict(row)
    data["jobs"] = json.loads(data.pop("jobs_json") or "[]")
    raw_analysis = data.pop("analysis_json") or ""
    data["analysis"] = json.loads(raw_analysis) if raw_analysis else None
    return data


def upsert_run(repo_id, run, jobs=None):
    """Insert or update a run. Existing analysis is kept; jobs are only replaced when given."""
    columns = ", ".join(RUN_FIELDS)
    placeholders = ", ".join("?" for _ in RUN_FIELDS)
    updates = ", ".join(f"{field} = excluded.{field}" for field in RUN_FIELDS)
    values = [run.get(field) for field in RUN_FIELDS]
    with _connect() as db:
        db.execute(
            f"INSERT INTO runs (repo_id, run_id, {columns}) VALUES (?, ?, {placeholders}) "
            f"ON CONFLICT(repo_id, run_id) DO UPDATE SET {updates}",
            (repo_id, run["run_id"], *values),
        )
        if jobs is not None:
            db.execute(
                "UPDATE runs SET jobs_json = ? WHERE repo_id = ? AND run_id = ?",
                (json.dumps(jobs), repo_id, run["run_id"]),
            )


def get_run(repo_id, run_id):
    with _connect() as db:
        row = db.execute(
            "SELECT * FROM runs WHERE repo_id = ? AND run_id = ?", (repo_id, run_id)
        ).fetchone()
    return _to_dict(row)


def list_runs(repo_id, limit=30):
    with _connect() as db:
        rows = db.execute(
            "SELECT * FROM runs WHERE repo_id = ? ORDER BY created_at DESC, run_id DESC LIMIT ?",
            (repo_id, limit),
        ).fetchall()
    return [_to_dict(row) for row in rows]


def save_analysis(repo_id, run_id, analysis):
    with _connect() as db:
        db.execute(
            "UPDATE runs SET analysis_json = ? WHERE repo_id = ? AND run_id = ?",
            (json.dumps(analysis), repo_id, run_id),
        )
