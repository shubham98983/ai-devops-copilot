from pathlib import Path

from app.pipeline.logs import (
    clean_log,
    extract_error_section,
    extract_references,
    failed_tests,
    truncate_middle,
)

LOG = (Path(__file__).parent / "fixtures" / "pytest_failure_job.log").read_text()


def test_clean_log_removes_timestamps_and_marks_steps_and_errors():
    lines = clean_log(LOG)
    assert not any(line.startswith("2026-") for line in lines)
    assert any(line.startswith("### STEP: Run pytest") for line in lines)
    assert "ERROR: Process completed with exit code 1." in lines
    assert any(line.startswith("ANNOTATION (error): config.py:3") for line in lines)


def test_pytest_failure_section_is_chosen_over_earlier_lint_error():
    """The lint step also logs an error first; the real failure is the pytest step."""
    section = extract_error_section(LOG)
    assert section["kind"] == "pytest"
    assert section["step"].startswith("Run pytest")
    assert "test_is_low_stock_at_threshold" in section["text"]
    assert "AssertionError" in section["text"]
    assert "F401" not in section["text"]


def test_coverage_table_is_dropped_but_summary_kept():
    text = extract_error_section(LOG)["text"]
    assert "Stmts" not in text and "app/db.py" not in text
    assert "short test summary info" in text
    assert "1 failed, 46 passed" in text


def test_failed_tests_are_listed():
    section = extract_error_section(LOG)
    assert [t["id"] for t in section["failed_tests"]] == [
        "tests/test_inventory_service.py::test_is_low_stock_at_threshold"
    ]


def test_references_are_repo_relative_and_include_the_test_file_and_line():
    refs = extract_error_section(LOG)["references"]
    assert {"path": "tests/test_inventory_service.py", "line": 26} in refs
    assert all(not ref["path"].startswith("/") for ref in refs)


def test_workspace_prefix_and_site_packages_are_handled():
    text = (
        'File "/home/runner/work/demo/demo/app/service.py", line 12, in run\n'
        'File "/opt/hostedtoolcache/Python/3.12/site-packages/flask/app.py", line 5, in x\n'
    )
    assert extract_references(text) == [{"path": "app/service.py", "line": 12}]


def test_generic_failure_uses_the_last_erroring_step():
    log = "\n".join(
        [
            "2026-10-05T10:00:00.0000000Z ##[group]Run npm ci",
            "2026-10-05T10:00:01.0000000Z installing",
            "2026-10-05T10:00:02.0000000Z ##[endgroup]",
            "2026-10-05T10:00:03.0000000Z ##[group]Run docker build .",
            "2026-10-05T10:00:04.0000000Z Step 5/8 : RUN pip install -r requirements.txt",
            "2026-10-05T10:00:05.0000000Z ERROR: No matching distribution found for nonexistent==9.9",
            "2026-10-05T10:00:06.0000000Z ##[error]Process completed with exit code 1.",
            "2026-10-05T10:00:07.0000000Z ##[endgroup]",
        ]
    )
    section = extract_error_section(log)
    assert section["kind"] == "generic"
    assert section["step"] == "Run docker build ."
    assert "No matching distribution" in section["text"]


def test_unknown_failure_falls_back_to_the_tail():
    section = extract_error_section("line one\nline two\nline three")
    assert section["kind"] == "tail"
    assert "line three" in section["text"]


def test_long_logs_are_truncated_in_the_middle():
    text = "A" * 5000 + "B" * 5000
    shortened = truncate_middle(text, 1000)
    assert len(shortened) < 1100
    assert shortened.startswith("A") and shortened.endswith("B") and "truncated" in shortened


def test_failed_tests_ignore_non_test_error_lines():
    assert failed_tests(["ERROR: something broke", "FAILED tests/test_a.py::test_x - boom"]) == [
        {"id": "tests/test_a.py::test_x", "message": "boom"}
    ]
