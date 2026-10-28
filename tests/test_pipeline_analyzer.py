import pytest

from app.pipeline import analyzer, store
from tests.pipeline_helpers import (
    GOOD_ANSWER,
    LOG,
    REPO_ID,
    FakeGitHub,
    index_repo,
    make_llm,
    register_repo,
    store_runs,
)


@pytest.fixture
def ready(sample_repo):
    register_repo()
    index_repo(sample_repo)
    fake = FakeGitHub()
    store_runs(fake)
    return fake


def test_analysis_combines_log_failure_and_related_code(ready):
    llm = make_llm()
    analysis = analyzer.analyze_run(REPO_ID, 2002, client=ready, llm=llm)

    assert analysis["category"] == "test_failure" and analysis["confidence"] == "high"
    assert analysis["files"][0]["path"] == "app/inventory.py"
    assert analysis["failed_jobs"] == ["Lint and test"]
    assert analysis["failed_tests"] == ["tests/test_inventory_service.py::test_is_low_stock_at_threshold"]
    assert any(label.startswith("app/inventory.py") for label in analysis["context_files"])

    prompt = llm.prompts[0]
    assert "AssertionError" in prompt and "is_low_stock" in prompt
    assert "quantity < product.reorder_level" in prompt  # the buggy code was retrieved from the index
    assert "F401" not in prompt  # unrelated lint noise was kept out
    assert "2026-10-05T14" not in prompt  # timestamps stripped


def test_result_is_saved_and_reused_without_calling_the_model_again(ready):
    llm = make_llm()
    first = analyzer.analyze_run(REPO_ID, 2002, client=ready, llm=llm)
    second = analyzer.analyze_run(REPO_ID, 2002, client=ready, llm=llm)
    assert second == first and len(llm.prompts) == 1
    assert store.get_run(REPO_ID, 2002)["analysis"]["summary"] == first["summary"]
    analyzer.analyze_run(REPO_ID, 2002, client=ready, llm=llm, force=True)
    assert len(llm.prompts) == 2


def test_secrets_in_logs_are_redacted_before_reaching_the_model(sample_repo):
    register_repo()
    index_repo(sample_repo)
    leaky = LOG.replace(
        "E       AssertionError: assert False is True",
        'E       AssertionError: assert False is True\nE       api_key = "sk_live_abcdef123456"',
    )
    fake = FakeGitHub(log=leaky)
    store_runs(fake)
    llm = make_llm()
    analyzer.analyze_run(REPO_ID, 2002, client=fake, llm=llm)
    assert "sk_live_abcdef123456" not in llm.prompts[0]
    assert "[REDACTED]" in llm.prompts[0]


def test_index_from_a_different_commit_is_flagged_as_possibly_stale(sample_repo):
    register_repo(commit="0000000000000000000000000000000000000000")
    index_repo(sample_repo)
    fake = FakeGitHub()
    store_runs(fake)
    analysis = analyzer.analyze_run(REPO_ID, 2002, client=fake, llm=make_llm())
    assert analysis["context_may_be_stale"] is True


def test_works_without_an_index_but_says_so(tmp_path):
    register_repo()
    fake = FakeGitHub()
    store_runs(fake)
    llm = make_llm()
    analysis = analyzer.analyze_run(REPO_ID, 2002, client=fake, llm=llm)
    assert analysis["context_files"] == []
    assert "no code context" in llm.prompts[0]


def test_successful_run_cannot_be_analyzed(ready):
    with pytest.raises(ValueError, match="did not fail"):
        analyzer.analyze_run(REPO_ID, 3001, client=ready, llm=make_llm())


def test_unknown_run(ready):
    with pytest.raises(LookupError):
        analyzer.analyze_run(REPO_ID, 424242, client=ready, llm=make_llm())


def test_json_in_code_fences_is_accepted():
    parsed = analyzer.parse_analysis(f"Here you go:\n```json\n{GOOD_ANSWER}\n```")
    assert parsed["category"] == "test_failure" and parsed["parse_error"] is False


def test_unstructured_reply_falls_back_without_crashing():
    parsed = analyzer.parse_analysis("I think the test is flaky, sorry.")
    assert parsed["parse_error"] is True and parsed["confidence"] == "low"
    assert "flaky" in parsed["root_cause"]


def test_unexpected_values_are_normalised():
    parsed = analyzer.parse_analysis(
        '{"summary": "s", "category": "weird", "confidence": "certain", '
        '"files": ["a.py", {"path": "b.py", "line": 3, "reason": "x"}, {"nope": 1}], '
        '"suggested_fix": ["step one", "step two"]}'
    )
    assert parsed["category"] == "unknown" and parsed["confidence"] == "low"
    assert [f["path"] for f in parsed["files"]] == ["a.py", "b.py"]
    assert "step one" in parsed["suggested_fix"]
