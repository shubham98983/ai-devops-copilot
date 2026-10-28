"""Turn a raw GitHub Actions job log into a short, useful failure excerpt."""
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
ANNOTATION = re.compile(r"^::(?P<level>error|warning)\s+(?P<props>.*?)::(?P<message>.*)$")
STEP_MARK = "### STEP: "

FAILURES_HEADER = re.compile(r"^={3,} (?:FAILURES|ERRORS) ={3,}$")
SUMMARY_LINE = re.compile(r"^={3,} .*\b(?:passed|failed|errors?|no tests ran)\b.* ={3,}$")
COVERAGE_HEADER = re.compile(r"^-+ coverage:")
SHORT_SUMMARY = re.compile(r"^={3,} short test summary info ={3,}$")
FAILED_TEST = re.compile(r"^(?:FAILED|ERROR) (?P<id>\S+?)(?: - (?P<message>.*))?$")

PATH_LINE = re.compile(r"(?P<path>[\w./-]+\.py):(?P<line>\d+)")
TRACEBACK_FILE = re.compile(r'File "(?P<path>[^"]+\.py)", line (?P<line>\d+)')
TEST_ID = re.compile(r"(?P<path>[\w./-]+\.py)::(?P<name>\w+)")
WORKSPACE = re.compile(r"^/home/runner/work/[^/]+/[^/]+/")


def clean_log(text):
    """Strip timestamps and ANSI colours, and mark steps, errors and annotations clearly."""
    lines = []
    for raw in text.splitlines():
        line = ANSI.sub("", TIMESTAMP.sub("", raw)).rstrip()
        if line.startswith("##[group]"):
            lines.append(f"{STEP_MARK}{line[len('##[group]'):]}")
        elif line.startswith("##[endgroup]"):
            continue
        elif line.startswith("##[error]"):
            lines.append(f"ERROR: {line[len('##[error]'):]}")
        elif line.startswith("##[warning]"):
            lines.append(f"WARNING: {line[len('##[warning]'):]}")
        else:
            annotation = ANNOTATION.match(line)
            if annotation:
                lines.append(f"ANNOTATION ({annotation['level']}): {annotation['message']}")
            else:
                lines.append(line)
    return lines


def split_steps(lines):
    """Group cleaned lines into [(step title, [lines])]."""
    steps = [("(setup)", [])]
    for line in lines:
        if line.startswith(STEP_MARK):
            steps.append((line[len(STEP_MARK):], []))
        else:
            steps[-1][1].append(line)
    return steps


def truncate_middle(text, max_chars):
    if len(text) <= max_chars:
        return text
    head = int(max_chars * 0.65)
    tail = max_chars - head
    return f"{text[:head]}\n... [log truncated] ...\n{text[-tail:]}"


def _pytest_section(step_lines):
    start = next((i for i, line in enumerate(step_lines) if FAILURES_HEADER.match(line)), None)
    if start is None:
        return None
    end = len(step_lines) - 1
    for i in range(len(step_lines) - 1, start, -1):
        if SUMMARY_LINE.match(step_lines[i]):
            end = i
            break
    section = step_lines[start : end + 1]
    # drop the coverage table that pytest-cov prints between the failures and the summary
    cleaned, skipping = [], False
    for line in section:
        if COVERAGE_HEADER.match(line):
            skipping = True
        elif SHORT_SUMMARY.match(line):
            skipping = False
        if not skipping:
            cleaned.append(line)
    return cleaned


def failed_tests(lines):
    results = []
    for line in lines:
        match = FAILED_TEST.match(line)
        if match and "::" in match["id"]:
            results.append({"id": match["id"], "message": (match["message"] or "").strip()})
    return results


def extract_references(text, limit=8):
    """File and line references found in a log excerpt, as repo-relative paths."""
    found = []

    def add(path, line):
        path = WORKSPACE.sub("", path)
        if path.startswith("/") or "site-packages" in path or path.startswith(("..", "~")):
            return
        entry = {"path": path, "line": int(line) if line else None}
        if all(entry["path"] != f["path"] or entry["line"] != f["line"] for f in found):
            found.append(entry)

    for pattern in (TRACEBACK_FILE, PATH_LINE):
        for match in pattern.finditer(text):
            add(match["path"], match["line"])
    for match in TEST_ID.finditer(text):
        add(match["path"], None)
    return found[:limit]


def extract_error_section(raw_log, max_chars=6000):
    """Return {'kind', 'step', 'text', 'failed_tests', 'references'} for one job log."""
    lines = clean_log(raw_log)
    steps = split_steps(lines)

    for title, step_lines in steps:
        section = _pytest_section(step_lines)
        if section:
            text = "\n".join(section)
            return _result("pytest", title, text, lines, max_chars)

    error_steps = [
        (title, body) for title, body in steps if any(line.startswith("ERROR:") for line in body)
    ]
    if error_steps:
        title, body = error_steps[-1]  # the step that ended the job is normally the last to error
        first_error = next(i for i, line in enumerate(body) if line.startswith("ERROR:"))
        excerpt = body[max(0, first_error - 60) : first_error + 10]
        return _result("generic", title, "\n".join(excerpt), lines, max_chars)

    return _result("tail", "(unknown)", "\n".join(lines[-80:]), lines, max_chars)


def _result(kind, step, text, all_lines, max_chars):
    text = truncate_middle(text, max_chars)
    return {
        "kind": kind,
        "step": step,
        "text": text,
        "failed_tests": failed_tests(all_lines),
        "references": extract_references(text),
    }
