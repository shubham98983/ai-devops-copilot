"""Pull workflow runs and job summaries from GitHub into the local database."""
from app import store as registry
from app.pipeline import store
from app.pipeline.github_client import GitHubClient
from app.pipeline import reports as report_parser

MAX_JOB_FETCHES = 10  # per sync, keeps us well inside GitHub's rate limit


def fetch_reports(repo_id, repo, run_id, client):
    artifacts = client.list_artifacts(repo["owner"], repo["name"], run_id)
    parsed = {"findings": [], "tests": None, "coverage_percent": None}
    for artifact in artifacts:
        if artifact.get("expired"):
            continue
        artifact_name = artifact.get("name")
        if artifact_name not in ("security-reports", "test-reports"):
            continue
        files = client.read_artifact_members(
            client.download_artifact(repo["owner"], repo["name"], artifact["id"]),
            {"security-reports": {"semgrep-report.json", "trivy-report.json"},
             "test-reports": {"pytest-report.xml", "coverage.xml"}}[artifact_name],
        )
        if artifact_name == "security-reports":
            if "semgrep-report.json" in files: parsed["findings"].extend(report_parser.parse_semgrep(files["semgrep-report.json"]))
            if "trivy-report.json" in files: parsed["findings"].extend(report_parser.parse_trivy(files["trivy-report.json"]))
        else:
            if "pytest-report.xml" in files: parsed["tests"] = report_parser.parse_junit(files["pytest-report.xml"])
            if "coverage.xml" in files: parsed["coverage_percent"] = report_parser.parse_coverage(files["coverage.xml"])
    parsed["findings"] = parsed["findings"][:report_parser.MAX_FINDINGS]
    store.save_report(repo_id, run_id, parsed)
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
        needs_jobs = (
            existing is None or not existing["jobs"] or existing["status"] != "completed"
        )
        jobs = None
        if needs_jobs and jobs_fetched < MAX_JOB_FETCHES:
            jobs = client.list_jobs(repo["owner"], repo["name"], run["run_id"])
            jobs_fetched += 1
        if existing is None:
            new_runs += 1
        store.upsert_run(repo_id, run, jobs)
    completed = [r for r in runs if r.get("status") == "completed"][:5]
    if hasattr(client, "list_artifacts"):
        for run in completed:
            if store.get_report(repo_id, run["run_id"]) is not None:
                continue
            try:
                fetch_reports(repo_id, repo, run["run_id"], client)
            except Exception:
                # A missing/expired artifact does not make the main Actions sync fail.
                continue
    return {"runs": len(runs), "new": new_runs, "jobs_fetched": jobs_fetched}
