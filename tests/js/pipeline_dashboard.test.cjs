const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const repo = path.resolve(__dirname, "../..");
const html = `<!doctype html><nav><button class="tab" data-mode="dashboard"></button>
<button class="tab" data-mode="pipeline"></button></nav>
<section id="pipeline-panel"></section>`;
const dom = new JSDOM(html, { runScripts: "outside-only", url: "http://localhost/" });
const { window } = dom;
Object.defineProperty(window.document, "hidden", { value: false });
const summaryRequests = [];
const runRequests = [];
const reportRequests = [];
const intervalCallbacks = [];
const selected = { id: "repo-1" };
let intervalDelay = null;
let reportAvailable = true;
let runItems = [];
let resolveReportRequest = null;
window.setInterval = (callback, delay) => {
  intervalCallbacks.push(callback);
  intervalDelay = delay;
  return intervalCallbacks.length;
};
window.clearInterval = () => {};
window.state = { mode: "dashboard" };
window.selectedRepo = () => ({ ...selected, status: "ready" });
window.api = async (url) => {
  if (url.endsWith("/status")) return { repository: "octo/demo", github_token_configured: true };
  if (url.endsWith("/runs")) { runRequests.push(url); return runItems; }
  const reportMatch = url.match(/\/runs\/(\d+)\/reports$/);
  if (reportMatch) {
    reportRequests.push(Number(reportMatch[1]));
    return new Promise((resolve, reject) => {
      resolveReportRequest = () => {
        if (Number(reportMatch[1]) === 14) reject(new Error("report unavailable"));
        else resolve({
          findings: Number(reportMatch[1]) === 16
            ? [{ severity: "high", rule_id: "test.rule", title: "Finding for run 16", path: "app.py", line: 1 }]
            : [],
          explanation: null,
        });
      };
    });
  }
  if (url.endsWith("/summary")) {
    summaryRequests.push(url);
    return {
      branches: [],
      latest_with_reports: reportAvailable ? {
        run_id: 88,
        run_number: 8,
        branch: "main",
        run_label: "Run #8 on main",
        conclusion: "success",
        quality_score: 90,
        security: 90,
        coverage: 85,
        test_pass_percent: 100,
        parts: { security: 90, coverage: 85, tests: 100 },
        tests: { tests: 2, passed: 2, failed: 0 },
        findings_by_severity: { critical: 0, high: 0, medium: 1, low: 0 },
        missing: [],
      } : null,
      report_errors: reportAvailable ? [{ run_id: 87, message: "Actions read access denied" }] : [],
      last_10_scores: reportAvailable ? [
        { run_id: 87, score: 80, created_at: "2026-01-01T00:00:00Z" },
        { run_id: 88, score: 90, created_at: "2026-01-02T00:00:00Z" },
      ] : [],
    };
  }
  if (url.endsWith("/sync")) return {};
  throw new Error(`Unexpected API request: ${url}`);
};
window.el = (tag, className, text) => {
  const node = window.document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};
window.updatePanels = () => {};
window.eval(fs.readFileSync(path.join(repo, "frontend/pipeline.js"), "utf8"));
window.updatePanels();

setTimeout(async () => {
  try {
    const svg = window.document.querySelector("svg.score-trend");
    const namespace = "http://www.w3.org/2000/svg";
    assert.ok(svg, "dashboard trend SVG should render");
    assert.equal(svg.namespaceURI, namespace);
    for (const child of svg.querySelectorAll("*")) {
      assert.equal(child.namespaceURI, namespace, `${child.localName} should use SVG namespace`);
    }
    assert.ok([...svg.querySelectorAll("text")].some((element) => element.textContent === "0"));
    assert.ok([...svg.querySelectorAll("text")].some((element) => element.textContent === "100"));
    const points = svg.querySelectorAll("circle");
    assert.equal(points.length, 2);
    assert.ok([...points].every((point) => point.querySelector("title")?.textContent));
    assert.match(window.document.getElementById("pipeline-panel").textContent, /Run #8 on main/);
    assert.match(
      window.document.getElementById("pipeline-panel").textContent,
      /Reports unavailable: Actions read access denied \(run 87\)/,
    );
    assert.equal(summaryRequests.length, 1);
    assert.equal(intervalCallbacks.length, 1);
    assert.equal(intervalDelay, 15000);
    await intervalCallbacks[0]();
    assert.equal(summaryRequests.length, 2, "dashboard timer should refresh the summary");
    window.state.mode = "pipeline";
    window.updatePanels();
    assert.match(window.document.getElementById("pipeline-panel").textContent, /CI\/CD pipeline/);
    assert.doesNotMatch(window.document.getElementById("pipeline-panel").textContent, /Quality score/);
    runItems = [
      { run_id: 16, run_number: 16, name: "CI", status: "completed", conclusion: "success" },
      { run_id: 15, run_number: 15, name: "CI", status: "completed", conclusion: "success" },
      { run_id: 14, run_number: 3, name: "Team approval gate", status: "completed", conclusion: "success" },
    ];
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.ok(runRequests.length >= 2, "switching from Dashboard to Pipeline should load the runs");
    const selector = window.document.querySelector('select[aria-label="Run security report"]');
    assert.ok(selector);
    assert.equal(selector.options.length, 2, "approval gate events should not be offered as CI report runs");
    selector.value = "15";
    selector.dispatchEvent(new window.Event("change", { bubbles: true }));
    assert.equal(window.document.querySelector('select[aria-label="Run security report"]'), selector,
      "changing the run should not replace the native selector");
    const loadButton = [...window.document.querySelectorAll("button")]
      .find((button) => button.textContent === "Load security findings");
    loadButton.click();
    assert.equal(
      [...window.document.querySelectorAll("button")].find((button) => button.textContent.includes("Loading findings"))?.disabled,
      true,
      "report button should show a disabled loading state while fetching",
    );
    resolveReportRequest();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(reportRequests, [15], "selected run should be used to load its report");
    assert.match(window.document.getElementById("pipeline-panel").textContent, /No security findings for this run/);
    assert.equal(
      window.document.querySelector('select[aria-label="Run security report"]').value,
      "15",
      "rerendering after report load should keep the selected run",
    );
    const secondSelector = window.document.querySelector('select[aria-label="Run security report"]');
    secondSelector.value = "16";
    secondSelector.dispatchEvent(new window.Event("change", { bubbles: true }));
    [...window.document.querySelectorAll("button")]
      .find((button) => button.textContent === "Load security findings")
      .click();
    resolveReportRequest();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(reportRequests, [15, 16]);
    assert.match(window.document.getElementById("pipeline-panel").textContent, /Finding for run 16/);
    const thirdSelector = window.document.querySelector('select[aria-label="Run security report"]');
    thirdSelector.value = "14";
    thirdSelector.dispatchEvent(new window.Event("change", { bubbles: true }));
    [...window.document.querySelectorAll("button")]
      .find((button) => button.textContent === "Load security findings")
      .click();
    resolveReportRequest();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.deepEqual(reportRequests, [15, 16, 14]);
    assert.match(window.document.getElementById("pipeline-panel").textContent, /report unavailable/);
    window.state.mode = "dashboard";
    window.updatePanels();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(summaryRequests.length, 3, "switching back to Dashboard should fetch a fresh summary");
    reportAvailable = false;
    window.state.mode = "pipeline";
    window.updatePanels();
    window.state.mode = "dashboard";
    window.updatePanels();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(summaryRequests.length, 4);
    assert.match(window.document.getElementById("pipeline-panel").textContent, /No data/);
    selected.id = "repo-2";
    window.updatePanels();
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(summaryRequests.length, 5, "changing repositories should fetch the new summary");
    window.close();
    process.stdout.write("jsdom dashboard SVG and refresh tests passed\n");
  } catch (error) {
    window.close();
    throw error;
  }
}, 30);
