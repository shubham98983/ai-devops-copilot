"""Optional background polling so the dashboard stays current without clicking Sync."""
import os
import threading

from app import store as registry
from app.pipeline.github_client import get_token
from app.pipeline.sync import sync_repo
from app.utils import get_logger

log = get_logger(__name__)

_thread = None
_stop = threading.Event()
_lock = threading.Lock()


def poll_seconds():
    try:
        return int(os.environ.get("PIPELINE_POLL_SECONDS", "60"))
    except ValueError:
        return 60


def is_running():
    return _thread is not None and _thread.is_alive()


def _loop(interval):
    while not _stop.wait(interval):
        for repo in registry.list_repos():
            if repo["status"] != "ready":
                continue
            try:
                sync_repo(repo["id"])
            except Exception as error:  # noqa: BLE001 - keep polling whatever happens
                log.warning("Pipeline sync failed for %s: %s", repo["id"], error)


def ensure_poller():
    """Start the polling thread once, if a token is configured and polling is enabled."""
    global _thread
    interval = poll_seconds()
    if not get_token() or interval <= 0:
        return False
    with _lock:
        if is_running():
            return True
        _stop.clear()
        _thread = threading.Thread(target=_loop, args=(interval,), daemon=True, name="pipeline-poller")
        _thread.start()
    return True


def stop_poller():
    _stop.set()
