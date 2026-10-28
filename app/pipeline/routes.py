"""HTTP API for the pipeline monitor and failure analyzer."""
from fastapi import APIRouter, HTTPException

from app import store as registry
from app.pipeline import analyzer, poller, store, sync
from app.pipeline.github_client import GitHubClient, GitHubError, get_token
from app.utils import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/repos/{repo_id}/pipeline", tags=["pipeline"])


def get_client():
    return GitHubClient()


def require_repo(repo_id):
    repo = registry.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found. Index it first.")
    return repo


def run_summary(run):
    analysis = run.get("analysis")
    data = {key: value for key, value in run.items() if key not in ("analysis",)}
    data["analyzed"] = analysis is not None
    data["analysis_summary"] = analysis["summary"] if analysis else ""
    return data


@router.get("/status")
def pipeline_status(repo_id: str):
    repo = require_repo(repo_id)
    poller.ensure_poller()
    return {
        "repository": f"{repo['owner']}/{repo['name']}",
        "github_token_configured": bool(get_token()),
        "poll_seconds": poller.poll_seconds() if get_token() else 0,
        "poller_running": poller.is_running(),
    }


@router.post("/sync")
def sync_pipeline(repo_id: str):
    require_repo(repo_id)
    poller.ensure_poller()
    try:
        return sync.sync_repo(repo_id, client=get_client())
    except GitHubError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@router.get("/runs")
def list_runs(repo_id: str):
    require_repo(repo_id)
    return [run_summary(run) for run in store.list_runs(repo_id)]


@router.get("/runs/{run_id}")
def get_run(repo_id: str, run_id: int):
    require_repo(repo_id)
    run = store.get_run(repo_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found. Sync the pipeline first.")
    return run


@router.post("/runs/{run_id}/analyze")
def analyze(repo_id: str, run_id: int, force: bool = False):
    require_repo(repo_id)
    try:
        return analyzer.analyze_run(repo_id, run_id, client=get_client(), force=force)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except GitHubError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - LLM and provider failures
        log.exception("Failure analysis crashed for run %s", run_id)
        try:
            from app.llm.provider import LLMConfigError, describe_llm_error
        except ImportError:  # a customised provider module without these helpers
            raise HTTPException(status_code=502, detail="The language model request failed.") from error
        if isinstance(error, LLMConfigError):
            raise HTTPException(status_code=503, detail=str(error)) from error
        status_code, message = describe_llm_error(error)
        raise HTTPException(status_code=status_code, detail=message) from error
