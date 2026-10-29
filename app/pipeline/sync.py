"""Pull workflow runs, job summaries, and reports from GitHub."""

from app import store as registry
from app.pipeline import reports as report_parser
from app.pipeline import store
from app.pipeline.github_client import GitHubClient
from app.utils import get_logger

MAX_JOB_FETCHES = 10  # per sync, keeps us well inside GitHub's rate limit
log = get_logger(__name__)


def fetch_reports(repo_id, repo, run_id, client):
    artifacts = client.list_artifacts(repo["owner"], repo["name"], run_id)
    parsed = {
        "findings": [],
        "tests": None,
        "coverage_percent": None,
        "available": {"security": False, "tests": False, "coverage": False},
    }
    errors = []
    expected_members = {
        "security-reports": {"semgrep-report.json", "trivy-report.json"},
        "test-reports": {"pytest-report.xml", "coverage.xml"},
    }

    for artifact in artifacts:
        if artifact.get("expired"):
            continue
        artifact_name = artifact.get("name")
        if artifact_name not in expected_members:
            continue
        try:
            blob = client.download_artifact(repo["owner"], repo["name"], artifact["id"])
            files = client.read_artifact_members(blob, expected_members[artifact_name])
        except Exception as error:  # noqa: BLE001 - keep other artifacts and runs available
            errors.append(str(error)[:500] or error.__class__.__name__)
            continue

        try:
            if artifact_name == "security-reports":
                for filename in ("semgrep-report.json", "trivy-report.json"):
                    if filename not in files:
                        continue
                    parser = (
                        report_parser.parse_semgrep
                        if filename.startswith("semgrep")
                        else report_parser.parse_trivy
                    )
                    parsed["findings"].extend(parser(files[filename]))
                    parsed["available"]["security"] = True
            else:
                if "pytest-report.xml" in files:
                    parsed["tests"] = report_parser.parse_junit(files["pytest-report.xml"])
                    parsed["available"]["tests"] = True
                if "coverage.xml" in files:
                    parsed["coverage_percent"] = report_parser.parse_coverage(files["coverage.xml"])
                    parsed["available"]["coverage"] = True
        except Exception as error:  # noqa: BLE001 - continue with remaining report artifacts
            errors.append(str(error)[:500] or error.__class__.__name__)

    parsed["findings"] = parsed["findings"][: report_parser.MAX_FINDINGS]
    store.save_report(repo_id, run_id, parsed)
    if errors:
        reason = "; ".join(errors)
        store.save_report_error(repo_id, run_id, reason)
        log.warning("Could not fetch all reports for run %s: %s", run_id, reason)
    return parsed


def sync_repo(repo_id, client=None, per_page=15):
    repo = registry.get_repo(repo_id)
    if repo is None:
        raise LookupError("Repository not found. Index it first.")
    client = client or GitHubClient()

    runs = client.list_runs(repo["owner"], repo["name"], per_page=per_page)
    new_runs = 0
    jobs_fetched = 0
    for run in runs:
        existing = store.get_run(repo_id, run["run_id"])
        needs_jobs = existing is None or not existing["jobs"] or existing["status"] != "completed"
        jobs = None
        if needs_jobs and jobs_fetched < MAX_JOB_FETCHES:
            jobs = client.list_jobs(repo["owner"], repo["name"], run["run_id"])
            jobs_fetched += 1
        if existing is None:
            new_runs += 1
        store.upsert_run(repo_id, run, jobs)

    completed = [run for run in runs if run.get("status") == "completed"][:5]
    if hasattr(client, "list_artifacts"):
        for run in completed:
            try:
                fetch_reports(repo_id, repo, run["run_id"], client)
            except Exception as error:  # noqa: BLE001 - report failure must not block run sync
                reason = str(error)[:500] or error.__class__.__name__
                store.save_report_error(repo_id, run["run_id"], reason)
                log.warning("Could not fetch reports for run %s: %s", run["run_id"], reason)
    return {"runs": len(runs), "new": new_runs, "jobs_fetched": jobs_fetched}
