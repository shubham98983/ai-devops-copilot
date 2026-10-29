"""Pure pipeline quality score calculations with explicit component availability."""

WEIGHTS = {"security": 0.5, "coverage": 0.3, "tests": 0.2}
SEVERITIES = ("critical", "high", "medium", "low")


def score(
    findings=None,
    coverage_percent=None,
    tests=None,
    failures=0,
    errors=0,
    skipped=0,
    *,
    has_security=None,
):
    """Score only report components that exist, renormalizing their configured weights."""
    if has_security is None:
        has_security = findings is not None
    findings = findings or []
    counts = {
        level: sum(1 for finding in findings if finding.get("severity") == level) for level in SEVERITIES
    }

    security = None
    if has_security:
        security = max(
            0,
            100 - counts["critical"] * 10 - counts["high"] * 5 - counts["medium"] * 2,
        )

    coverage = None
    if coverage_percent is not None:
        coverage = max(0.0, min(100.0, float(coverage_percent)))

    test_pass = None
    if tests is not None:
        total = max(0, int(tests.get("tests", 0)))
        passed = max(
            0,
            total
            - int(tests.get("failures", failures) or 0)
            - int(tests.get("errors", errors) or 0)
            - int(tests.get("skipped", skipped) or 0),
        )
        test_pass = 0.0 if total == 0 else 100.0 * passed / total

    parts = {"security": security, "coverage": coverage, "tests": test_pass}
    available = {name: value is not None for name, value in parts.items()}
    missing = [name for name in WEIGHTS if not available[name]]
    weight_total = sum(WEIGHTS[name] for name in WEIGHTS if available[name])
    quality = None
    if weight_total:
        quality = round(
            sum(WEIGHTS[name] * parts[name] for name in WEIGHTS if available[name]) / weight_total
        )

    return {
        "has_reports": bool(weight_total),
        "quality_score": quality,
        "security": security,
        "coverage": round(coverage, 2) if coverage is not None else None,
        "test_pass_percent": round(test_pass, 2) if test_pass is not None else None,
        "parts": parts,
        "missing": missing,
        "findings": counts,
    }
