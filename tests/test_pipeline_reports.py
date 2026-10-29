import json
from pathlib import Path

from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.pipeline import reports, security_explain
from app.pipeline.score import score

FIXTURES = Path(__file__).parent / "fixtures"


def test_parsers_normalize_security_and_test_reports():
    semgrep = reports.parse_semgrep((FIXTURES / "semgrep-report.json").read_bytes())
    trivy = reports.parse_trivy((FIXTURES / "trivy-report.json").read_bytes())
    junit = reports.parse_junit((FIXTURES / "pytest-report.xml").read_bytes())
    coverage = reports.parse_coverage((FIXTURES / "coverage.xml").read_bytes())
    assert (semgrep[0]["tool"], semgrep[0]["severity"], semgrep[0]["line"]) == ("semgrep", "high", 12)
    assert [(x["rule_id"], x["severity"]) for x in trivy] == [
        ("CVE-2099-0001", "high"),
        ("generic-api-key", "critical"),
    ]
    assert junit == {"tests": 4, "failures": 1, "errors": 0, "skipped": 1, "time": 0.42}
    assert coverage == 87.5


def test_score_has_documented_weights_and_penalties():
    result = score([{"severity": "critical"}, {"severity": "high"}, {"severity": "medium"}], 80, 10, 1, 0, 1)
    assert result["security"] == 83
    assert result["test_pass_percent"] == 80
    assert result["quality_score"] == 82
    assert result["findings"]["critical"] == 1


def test_parsers_cap_findings():
    payload = {"results": [{"check_id": str(i), "extra": {"severity": "LOW"}} for i in range(250)]}
    assert len(reports.parse_semgrep(json.dumps(payload))) == 200


def test_security_explanation_uses_fake_llm_and_caches(monkeypatch):
    repo = {"owner": "octo", "name": "demo"}
    run = {"run_id": 41}
    findings = [{"rule_id": "RULE-1", "path": "app/demo.py", "line": 4, "severity": "high"}]
    report = {"reports": {"findings": findings}, "explanation": None}
    monkeypatch.setattr(security_explain.registry, "get_repo", lambda _: repo)
    monkeypatch.setattr(security_explain.store, "get_run", lambda *_: run)
    monkeypatch.setattr(security_explain.store, "get_report", lambda *_: report)
    saved = []
    monkeypatch.setattr(security_explain.store, "save_explanation", lambda *args: saved.append(args))
    response = json.dumps(
        {
            "summary": "One issue",
            "top_actions": ["Fix it", "Review it", "Retest"],
            "findings": [
                {
                    "rule_id": "RULE-1",
                    "path": "app/demo.py",
                    "line": 4,
                    "explanation": "Unsafe call",
                    "impact": "Input execution",
                    "fix": "Validate input",
                    "priority": 5,
                }
            ],
        }
    )
    result = security_explain.explain_run("repo", 41, llm=FakeListChatModel(responses=[response]))
    assert result["findings"][0]["priority"] == 5
    assert result["top_actions"] == ["Fix it", "Review it", "Retest"]
    assert saved and saved[0][2] == result
