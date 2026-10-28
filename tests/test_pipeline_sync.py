import pytest

from app.pipeline import store, sync
from tests.pipeline_helpers import REPO_ID, FakeGitHub, raw_runs, register_repo


def test_first_sync_stores_all_runs_and_fetches_their_jobs():
    register_repo()
    fake = FakeGitHub()
    result = sync.sync_repo(REPO_ID, client=fake)
    assert result == {"runs": 3, "new": 3, "jobs_fetched": 3}
    runs = store.list_runs(REPO_ID)
    assert [r["run_id"] for r in runs] == [3001, 2002, 1001]  # newest first
    failed = store.get_run(REPO_ID, 2002)
    assert failed["conclusion"] == "failure"
    assert failed["jobs"][0]["failed_steps"] == ["Lint (Ruff)", "Test (pytest + coverage)"]


def test_second_sync_only_refreshes_runs_that_were_not_finished():
    register_repo()
    sync.sync_repo(REPO_ID, client=FakeGitHub())
    fake = FakeGitHub()
    result = sync.sync_repo(REPO_ID, client=fake)
    assert result["new"] == 0
    assert fake.job_calls == [1001]  # the only run still in progress


def test_run_that_finishes_is_updated_on_the_next_sync():
    register_repo()
    sync.sync_repo(REPO_ID, client=FakeGitHub())
    finished = raw_runs()
    finished[2]["status"], finished[2]["conclusion"] = "completed", "failure"
    sync.sync_repo(REPO_ID, client=FakeGitHub(runs=finished))
    run = store.get_run(REPO_ID, 1001)
    assert (run["status"], run["conclusion"]) == ("completed", "failure")


def test_sync_never_overwrites_an_existing_analysis():
    register_repo()
    sync.sync_repo(REPO_ID, client=FakeGitHub())
    store.save_analysis(REPO_ID, 2002, {"summary": "kept"})
    sync.sync_repo(REPO_ID, client=FakeGitHub())
    assert store.get_run(REPO_ID, 2002)["analysis"] == {"summary": "kept"}


def test_job_fetches_are_capped_per_sync():
    register_repo()
    many = []
    for i in range(14):
        run = dict(raw_runs()[0], id=9000 + i, created_at=f"2026-10-07T10:{i:02d}:00Z")
        many.append(run)
    fake = FakeGitHub(runs=many)
    result = sync.sync_repo(REPO_ID, client=fake, per_page=14)
    assert result["jobs_fetched"] == sync.MAX_JOB_FETCHES
    assert result["new"] == 14


def test_unknown_repository():
    with pytest.raises(LookupError):
        sync.sync_repo("nope__nope", client=FakeGitHub())
