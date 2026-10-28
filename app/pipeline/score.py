"""Pure pipeline quality score calculations."""

def score(findings, coverage_percent, tests, failures, errors=0, skipped=0):
    counts = {level: sum(1 for finding in findings if finding.get("severity") == level) for level in ("critical", "high", "medium", "low")}
    security = max(0, 100 - (counts["critical"] * 10 + counts["high"] * 5 + counts["medium"] * 2))
    coverage = max(0.0, min(100.0, float(coverage_percent or 0)))
    total = max(0, int(tests or 0))
    passed = max(0, total - int(failures or 0) - int(errors or 0) - int(skipped or 0))
    test_pass = 0.0 if total == 0 else 100.0 * passed / total
    quality = round(0.5 * security + 0.3 * coverage + 0.2 * test_pass)
    return {"quality_score": quality, "security": security, "coverage": round(coverage, 2), "test_pass_percent": round(test_pass, 2), "findings": counts}
