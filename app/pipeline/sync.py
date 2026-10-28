"""Pull workflow runs and job summaries from GitHub into the local database."""
from app import store as registry
from app.pipeline import store
from app.pipeline.github_client import GitHubClient

MAX_JOB_FETCHES = 10  # per sync, keeps us well inside GitHub's rate limit


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
    return {"runs": len(runs), "new": new_runs, "jobs_fetched": jobs_fetched}
