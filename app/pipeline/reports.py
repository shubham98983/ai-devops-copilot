"""Small, defensive parsers for CI security and test reports."""
import json
import xml.etree.ElementTree as ET

from defusedxml import ElementTree as SafeET

MAX_FINDINGS = 200
SEVERITIES = {"critical", "high", "medium", "low"}


def _severity(value):
    value = str(value or "low").lower()
    value = {"error": "high", "warning": "medium", "info": "low"}.get(value, value)
    return value if value in SEVERITIES else "low"


def parse_semgrep(data):
    data = json.loads(data) if isinstance(data, (str, bytes)) else data
    findings = []
    for item in (data or {}).get("results", []) or []:
        extra = item.get("extra") or {}
        findings.append({"tool": "semgrep", "rule_id": str(item.get("check_id") or ""), "severity": _severity(extra.get("severity")),
                         "title": str(extra.get("message") or item.get("check_id") or ""), "path": str(item.get("path") or ""),
                         "line": (item.get("start") or {}).get("line"), "package": "", "installed": "", "fixed": ""})
        if len(findings) >= MAX_FINDINGS: break
    return findings


def parse_trivy(data):
    data = json.loads(data) if isinstance(data, (str, bytes)) else data
    findings = []
    for result in (data or {}).get("Results", []) or []:
        for section, key in (("Vulnerabilities", "VulnerabilityID"), ("Secrets", "RuleID")):
            for item in result.get(section, []) or []:
                findings.append({"tool": "trivy", "rule_id": str(item.get(key) or ""), "severity": _severity(item.get("Severity")),
                                 "title": str(item.get("Title") or item.get("Description") or item.get(key) or ""),
                                 "path": str(result.get("Target") or ""), "line": None,
                                 "package": str(item.get("PkgName") or item.get("Category") or ""),
                                 "installed": str(item.get("InstalledVersion") or ""), "fixed": str(item.get("FixedVersion") or "")})
                if len(findings) >= MAX_FINDINGS: return findings
    return findings


def parse_junit(data):
    root = SafeET.fromstring(data)
    suites = [root] if root.tag.endswith("testsuite") else list(root.findall(".//testsuite"))
    def count(name):
        explicit = root.attrib.get(name)
        return int(explicit) if explicit is not None else sum(int(s.attrib.get(name, 0)) for s in suites)
    time = root.attrib.get("time")
    if time is None: time = sum(float(s.attrib.get("time", 0)) for s in suites)
    return {"tests": count("tests"), "failures": count("failures"), "errors": count("errors"), "skipped": count("skipped"), "time": float(time)}


def parse_coverage(data):
    root = SafeET.fromstring(data)
    return float(root.attrib.get("line-rate", 0)) * 100
