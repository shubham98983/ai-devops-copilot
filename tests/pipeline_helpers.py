"""Shared fakes and builders for the pipeline tests."""
import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app import store as registry
from app.ingestion.chunker import build_overview_document, chunk_files
from app.ingestion.loader import load_repo_files
from app.pipeline import store as pstore
from app.pipeline.github_client import normalize_job, normalize_run
from app.rag.vectorstore import rebuild_index

FIXTURES = Path(__file__).parent / "fixtures"
LOG = (FIXTURES / "pytest_failure_job.log").read_text()
REPO_ID = "octo__demo"

GOOD_ANSWER = json.dumps(
    {
        "summary": "test_is_low_stock_at_threshold fails because is_low_stock uses < instead of <=.",
        "root_cause": "is_low_stock compares quantity < reorder_level, so equal values are not low stock.",
        "category": "test_failure",
        "failing_step": "Test (pytest + coverage)",
        "files": [{"path": "app/inventory.py", "line": 2, "reason": "wrong comparison operator"}],
        "suggested_fix": "Change < to <= in is_low_stock.",
        "confidence": "high",
    }
)


def raw_runs():
    return json.loads((FIXTURES / "github_runs.json").read_text())["workflow_runs"]


def raw_jobs():
    return json.loads((FIXTURES / "github_jobs.json").read_text())["jobs"]


class FakeGitHub:
    """Stands in for GitHubClient. Counts calls so tests can check caching."""

    def __init__(self, runs=None, log=LOG):
        self.runs = [normalize_run(r) for r in (runs or raw_runs())]
        self.jobs = [normalize_job(j) for j in raw_jobs()]
        self.log = log
        self.job_calls = []
        self.log_calls = []

    def list_runs(self, owner, name, per_page=15, branch=None):
        return self.runs[:per_page]

    def list_jobs(self, owner, name, run_id):
        self.job_calls.append(run_id)
        return self.jobs

    def job_logs(self, owner, name, job_id):
        self.log_calls.append(job_id)
        return self.log


class SpyModel(FakeListChatModel):
    """Fake chat model that records the prompt it was given and how often it was called."""

    prompts: list = []

    def _call(self, messages, *args, **kwargs):
        self.prompts.append(" ".join(str(m.content) for m in messages))
        return super()._call(messages, *args, **kwargs)


def make_llm(answer=GOOD_ANSWER):
    model = SpyModel(responses=[answer])
    model.prompts = []
    return model


def register_repo(commit="84eae5e377823db28bf2deec7eca874d3815d64f"):
    registry.upsert_repo(REPO_ID, "https://github.com/octo/demo", "octo", "demo", status="ready")
    registry.update_repo(REPO_ID, status="ready", commit_sha=commit)


def index_repo(root):
    """Index a directory into the vector store and BM25 files under REPO_ID."""
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_inventory_service.py").write_text(
        "from app import inventory\n\n\ndef test_is_low_stock_at_threshold():\n"
        "    assert inventory.is_low_stock(make(10, reorder_level=10)) is True\n"
    )
    files = load_repo_files(root)
    documents = chunk_files(files, chunk_size=400, chunk_overlap=50)
    documents.append(build_overview_document(files, "octo/demo"))
    rebuild_index(REPO_ID, documents)


def store_runs(fake):
    for run in fake.runs:
        pstore.upsert_run(REPO_ID, run, fake.jobs if run["run_id"] == 2002 else None)
