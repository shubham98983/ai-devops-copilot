import threading

from app.pipeline import poller
from tests.pipeline_helpers import register_repo


def test_poller_stays_off_without_a_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert poller.ensure_poller() is False and not poller.is_running()


def test_poller_stays_off_when_disabled(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_POLL_SECONDS", "0")
    assert poller.ensure_poller() is False


def test_poller_syncs_ready_repositories_in_the_background(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_POLL_SECONDS", "1")
    register_repo()
    synced = threading.Event()
    seen = []
    monkeypatch.setattr(poller, "sync_repo", lambda repo_id: (seen.append(repo_id), synced.set()))
    try:
        assert poller.ensure_poller() is True
        assert poller.ensure_poller() is True  # second call must not start another thread
        assert synced.wait(5)
        assert seen[0] == "octo__demo"
    finally:
        poller.stop_poller()
        poller._thread.join(3)
    assert not poller.is_running()


def test_poller_survives_a_failing_sync(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("PIPELINE_POLL_SECONDS", "1")
    register_repo()
    calls = []

    def flaky(repo_id):
        calls.append(repo_id)
        raise RuntimeError("network down")

    monkeypatch.setattr(poller, "sync_repo", flaky)
    try:
        poller.ensure_poller()
        for _ in range(60):
            if len(calls) >= 2:
                break
            threading.Event().wait(0.1)
            if len(calls) == 1:
                threading.Event().wait(1.2)
        assert len(calls) >= 2 and poller.is_running()
    finally:
        poller.stop_poller()
        poller._thread.join(3)
