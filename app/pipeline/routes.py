"""HTTP API for the pipeline monitor and failure analyzer."""

from fastapi import APIRouter, HTTPException

from app import store as registry
from app.pipeline import analyzer, poller, score, store, sync
from app.pipeline.github_client import GitHubClient, GitHubError, get_token
from app.pipeline.security_explain import explain_run
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


@router.post("/runs/{run_id}/reports")
def get_reports(repo_id: str, run_id: int):
    repo = require_repo(repo_id)
    run = store.get_run(repo_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found. Sync the pipeline first.")
    existing = store.get_report(repo_id, run_id)
    if existing:
        return existing["reports"]
    try:
        return sync.fetch_reports(repo_id, repo, run_id, get_client())
    except GitHubError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not parse the run reports.") from error


@router.post("/runs/{run_id}/security/explain")
def explain_security(repo_id: str, run_id: int, force: bool = False):
    require_repo(repo_id)
    try:
        return explain_run(repo_id, run_id, client=get_client(), force=force)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        log.exception("Security explanation failed for run %s", run_id)
        try:
            from app.llm.provider import LLMConfigError, describe_llm_error
        except ImportError:
            raise HTTPException(status_code=502, detail="The language model request failed.") from error
        if isinstance(error, LLMConfigError):
            raise HTTPException(status_code=503, detail=str(error)) from error
        code, message = describe_llm_error(error)
        raise HTTPException(status_code=code, detail=message) from error


@router.get("/summary")
def pipeline_summary(repo_id: str):
    require_repo(repo_id)
    runs = store.list_runs(repo_id, limit=100)
    branches = {}
    scored = []
    for run in runs:
        report = store.get_report(repo_id, run["run_id"])
        data = (report or {}).get("reports", {})
        findings = data.get("findings", [])
        tests = data.get("tests") or {}
        coverage = data.get("coverage_percent") or 0
        tests = {
            **tests,
            "passed": max(
                0,
                int(tests.get("tests", 0))
                - int(tests.get("failures", 0))
                - int(tests.get("errors", 0))
                - int(tests.get("skipped", 0)),
            ),
            "failed": int(tests.get("failures", 0)) + int(tests.get("errors", 0)),
        }
        breakdown = score.score(
            findings,
            coverage,
            tests.get("tests", 0),
            tests.get("failures", 0),
            tests.get("errors", 0),
            tests.get("skipped", 0),
        )
        item = {
            "run_id": run["run_id"],
            "branch": run["branch"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "tests": tests,
            "coverage_percent": coverage,
            "findings_by_severity": breakdown["findings"],
            **breakdown,
        }
        item["ai_top_actions"] = ((report or {}).get("explanation") or {}).get("top_actions", [])
        if run["branch"] not in branches:
            branches[run["branch"]] = item
        if len(scored) < 10:
            scored.append(
                {
                    "run_id": run["run_id"],
                    "score": breakdown["quality_score"],
                    "created_at": run["created_at"],
                }
            )
    return {"branches": list(branches.values()), "last_10_scores": list(reversed(scored))}
