import logging
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.pipeline import routes, score, store, sync


def test_score_with_no_report_components_returns_no_score():
    result = score.score()
    assert result["has_reports"] is False
    assert result["quality_score"] is None
    assert result["missing"] == ["security", "coverage", "tests"]


def test_score_uses_and_reweights_only_available_components():
    result = score.score(findings=[], has_security=True, coverage_percent=50, tests=None)
    assert result["has_reports"] is True
    assert result["quality_score"] == 81
    assert result["parts"] == {"security": 100, "coverage": 50, "tests": None}
    assert result["missing"] == ["tests"]


def test_summary_uses_reported_runs_and_excludes_unscored_runs_from_trend(monkeypatch):
    runs = [
        {
            "run_id": 30,
            "run_number": 30,
            "name": "CI",
            "branch": "main",
            "status": "completed",
            "conclusion": "success",
            "created_at": "3",
        },
        {
            "run_id": 20,
            "run_number": 20,
            "name": "CI",
            "branch": "main",
            "status": "completed",
            "conclusion": "success",
            "created_at": "2",
        },
        {
            "run_id": 10,
            "run_number": 10,
            "name": "CI",
            "branch": "main",
            "status": "completed",
            "conclusion": "failure",
            "created_at": "1",
        },
    ]
    reports = {
        30: {
            "reports": {
                "findings": [],
                "tests": None,
                "coverage_percent": None,
                "available": {"security": False, "tests": False, "coverage": False},
            },
            "error_message": "Actions read access denied",
        },
        20: {
            "reports": {
                "findings": [{"severity": "high"}],
                "tests": {"tests": 2, "failures": 0, "errors": 0, "skipped": 0},
                "coverage_percent": 75,
                "available": {"security": True, "tests": True, "coverage": True},
            },
            "error_message": "",
        },
        10: None,
    }
    monkeypatch.setattr(routes, "require_repo", lambda _: {"owner": "octo", "name": "demo"})
    monkeypatch.setattr(store, "list_runs", lambda *args, **kwargs: runs)
    monkeypatch.setattr(store, "get_report", lambda _, run_id: reports[run_id])

    result = routes.pipeline_summary("octo__demo")

    assert result["latest_with_reports"]["run_id"] == 20
    assert result["latest_with_reports"]["run_label"] == "Run #20 on main"
    assert [item["run_id"] for item in result["last_10_scores"]] == [20]
    assert result["branches"][0]["quality_score"] is None
    assert result["branches"][0]["has_reports"] is False
    assert "Actions read access denied" in result["report_errors"][0]["message"]


def test_sync_logs_and_stores_each_run_report_error_without_stopping(monkeypatch, caplog):
    fake_runs = [
        {"run_id": 2, "status": "completed", "branch": "main"},
        {"run_id": 1, "status": "completed", "branch": "main"},
    ]
    failed = []

    class Client:
        def list_runs(self, *args, **kwargs):
            return fake_runs

        def list_jobs(self, *args, **kwargs):
            return []

        def list_artifacts(self, *args, **kwargs):
            return []

    monkeypatch.setattr(sync.registry, "get_repo", lambda _: {"owner": "octo", "name": "demo"})
    monkeypatch.setattr(sync.store, "get_run", lambda *_: None)
    monkeypatch.setattr(sync.store, "get_report", lambda *_: None)
    monkeypatch.setattr(sync.store, "upsert_run", lambda *args: None)

    def fetch_reports(_repo_id, _repo, run_id, _client):
        if run_id == 2:
            raise RuntimeError("Actions read access denied")
        return {"findings": [], "tests": None, "coverage_percent": None}

    monkeypatch.setattr(sync, "fetch_reports", fetch_reports)
    monkeypatch.setattr(
        sync.store, "save_report_error", lambda repo_id, run_id, error: failed.append((run_id, error))
    )
    with caplog.at_level(logging.WARNING):
        result = sync.sync_repo("octo__demo", client=Client())

    assert result["runs"] == 2
    assert failed == [(2, "Actions read access denied")]
    assert "run 2" in caplog.text and "Actions read access denied" in caplog.text


def test_save_report_error_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    store.save_report_error("repo", 8, "token lacks Actions read access")
    assert store.get_report("repo", 8)["error_message"] == "token lacks Actions read access"


def test_existing_report_table_is_migrated_for_error_messages(monkeypatch, tmp_path):
    import sqlite3

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    connection = sqlite3.connect(tmp_path / "registry.db")
    connection.execute(
        "CREATE TABLE run_reports (repo_id TEXT, run_id INTEGER, reports_json TEXT, "
        "explanation_json TEXT, PRIMARY KEY(repo_id, run_id))"
    )
    connection.close()

    store.save_report_error("repo", 9, "missing Actions permission")

    assert store.get_report("repo", 9)["error_message"] == "missing Actions permission"


def test_svg_namespace_dom_check_is_included():
    test_file = Path(__file__).parent / "js" / "pipeline_dashboard.test.cjs"
    node = os.environ.get("NODE_BIN") or shutil.which("node") or "/tmp/jsd/bin/node"
    if not Path(node).exists():
        pytest.skip("Node.js is not installed")
    environment = dict(os.environ)
    jsdom_modules = Path("/tmp/jsd/node_modules")
    if jsdom_modules.exists():
        environment["NODE_PATH"] = str(jsdom_modules)
    available = subprocess.run(
        [node, "-e", "require.resolve('jsdom')"],
        env=environment,
        check=False,
        capture_output=True,
    )
    if available.returncode:
        pytest.skip("jsdom is not installed")
    subprocess.run([node, str(test_file)], check=True, env=environment)
