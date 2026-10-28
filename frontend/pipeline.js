"use strict";

/* Pipeline tab: GitHub Actions runs, job status and AI failure analysis.
   Reuses helpers from app.js (state, api, el, renderRichText, selectedRepo, updatePanels). */
(function () {
  const panel = document.getElementById("pipeline-panel");
  if (!panel) return;

  const view = {
    repoId: null, runs: [], status: null, summary: null, reports: {}, selectedReportRun: null, explaining: {}, error: "", syncing: false,
    open: {}, analyzing: {}, errors: {}, timer: null, loaded: false,
  };

  /* ---------- helpers ---------- */
  const base = (id) => "/api/repos/" + encodeURIComponent(id) + "/pipeline";
  const safeUrl = (url) => (/^https:\/\/github\.com\//.test(url || "") ? url : "");

  function ago(iso) {
    const then = Date.parse(iso);
    if (!then) return "";
    const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (seconds < 60) return "just now";
    if (seconds < 3600) return Math.round(seconds / 60) + " min ago";
    if (seconds < 86400) return Math.round(seconds / 3600) + " h ago";
    return Math.round(seconds / 86400) + " d ago";
  }

  function outcome(item) {
    if (item.status && item.status !== "completed") return { icon: "●", cls: "running", label: item.status.replace("_", " ") };
    switch (item.conclusion) {
      case "success": return { icon: "✓", cls: "ok", label: "passed" };
      case "failure": case "timed_out": return { icon: "✕", cls: "bad", label: "failed" };
      default: return { icon: "○", cls: "idle", label: item.conclusion || "unknown" };
    }
  }

  function link(text, url) {
    const safe = safeUrl(url);
    if (!safe) return null;
    const a = el("a", "ext", text);
    a.href = safe; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }

  /* ---------- data ---------- */
  async function loadRuns(repoId) {
    view.runs = await api(base(repoId) + "/runs");
    if (state.mode === "dashboard") view.summary = await api(base(repoId) + "/summary");
    view.loaded = true;
  }

  async function loadReport(runId) {
    view.errors["report-" + runId] = "";
    try { view.reports[runId] = await api(base(view.repoId) + "/runs/" + runId + "/reports", { method: "POST" }); }
    catch (err) { view.errors["report-" + runId] = err.message; }
    render();
  }

  async function explainSecurity(runId) {
    view.explaining[runId] = true; render();
    try { view.reports[runId].explanation = await api(base(view.repoId) + "/runs/" + runId + "/security/explain", { method: "POST" }, 180000); }
    catch (err) { view.errors["explain-" + runId] = err.message; }
    view.explaining[runId] = false; render();
  }

  async function sync(repoId) {
    view.syncing = true; view.error = ""; render();
    try {
      await api(base(repoId) + "/sync", { method: "POST" });
    } catch (err) {
      view.error = err.message;
    }
    try { await loadRuns(repoId); } catch (err) { view.error = view.error || err.message; }
    view.syncing = false; render();
  }

  async function analyze(runId, force) {
    const repoId = view.repoId;
    view.analyzing[runId] = true; view.errors[runId] = ""; view.open[runId] = true; render();
    try {
      await api(base(repoId) + "/runs/" + runId + "/analyze" + (force ? "?force=true" : ""), { method: "POST" }, 180000);
      await loadRuns(repoId);
    } catch (err) {
      view.errors[runId] = err.message;
    }
    view.analyzing[runId] = false; render();
  }

  async function activate(repoId) {
    if (view.repoId !== repoId) {
      Object.assign(view, { repoId, runs: [], status: null, summary: null, reports: {}, selectedReportRun: null, explaining: {}, error: "", open: {}, analyzing: {}, errors: {}, loaded: false });
      render();
      try { view.status = await api(base(repoId) + "/status"); } catch (err) { view.error = err.message; }
      try { await loadRuns(repoId); } catch (err) { view.error = view.error || err.message; }
      render();
      sync(repoId);
    }
    startTimer();
  }

  function startTimer() {
    if (view.timer) return;
    view.timer = setInterval(async () => {
      if (!view.repoId || state.mode !== "pipeline" || document.hidden) return;
      try { await loadRuns(view.repoId); render(); } catch (_) { /* keep the last good data */ }
    }, 15000);
  }

  function stopTimer() {
    if (view.timer) { clearInterval(view.timer); view.timer = null; }
  }

  /* ---------- rendering ---------- */
  function chip(text, cls) { return el("span", "chip " + (cls || ""), text); }

  function renderToolbar() {
    const bar = el("div", "pl-toolbar");
    const title = el("div");
    title.appendChild(el("h2", "pl-title", "CI/CD pipeline"));
    title.appendChild(el("div", "muted", view.status ? view.status.repository : ""));
    bar.appendChild(title);

    const right = el("div", "pl-actions");
    if (view.status) {
      right.appendChild(chip(view.status.github_token_configured ? "GitHub token set" : "No GitHub token",
        view.status.github_token_configured ? "exact" : "warn"));
    }
    const button = el("button", "primary", view.syncing ? "Syncing…" : "Sync from GitHub");
    button.disabled = view.syncing;
    button.addEventListener("click", () => sync(view.repoId));
    right.appendChild(button);
    bar.appendChild(right);
    return bar;
  }

  function renderAnalysis(run, analysis) {
    const card = el("div", "analysis");
    card.appendChild(el("h3", "analysis-title", analysis.summary || "Analysis"));

    const chips = el("div", "analysis-chips");
    chips.appendChild(chip(analysis.category.replace("_", " "), "cat"));
    chips.appendChild(chip("confidence: " + analysis.confidence, "conf-" + analysis.confidence));
    if (analysis.failing_step) chips.appendChild(chip("step: " + analysis.failing_step));
    card.appendChild(chips);

    if (analysis.root_cause) {
      card.appendChild(el("h4", null, "Root cause"));
      const box = el("div", "analysis-text");
      renderRichText(box, analysis.root_cause);
      card.appendChild(box);
    }
    if (analysis.files && analysis.files.length) {
      card.appendChild(el("h4", null, "Files to look at"));
      const list = el("ul", "analysis-files");
      analysis.files.forEach((f) => {
        const item = el("li");
        item.appendChild(el("code", null, f.path + (f.line ? ":" + f.line : "")));
        if (f.reason) item.appendChild(document.createTextNode(" - " + f.reason));
        list.appendChild(item);
      });
      card.appendChild(list);
    }
    if (analysis.suggested_fix) {
      card.appendChild(el("h4", null, "Suggested fix"));
      const box = el("div", "analysis-text");
      renderRichText(box, analysis.suggested_fix);
      card.appendChild(box);
    }

    const meta = el("div", "analysis-meta");
    const used = (analysis.context_files || []).length;
    meta.appendChild(document.createTextNode(
      used ? "Based on the job log and " + used + " code chunk" + (used === 1 ? "" : "s") + " from the repository index."
           : "Based on the job log only (no repository code was available)."));
    if (analysis.context_may_be_stale) {
      meta.appendChild(el("div", "warn-text",
        "The index was built from a different commit than this run, so the code shown to the AI may differ."));
    }
    if (analysis.parse_error) {
      meta.appendChild(el("div", "warn-text", "The model did not return structured output; showing its raw reply."));
    }
    card.appendChild(meta);

    if (used) {
      const details = el("details", "sources");
      details.appendChild(el("summary", null, "Code context used"));
      const ul = el("ul", "analysis-files");
      analysis.context_files.forEach((label) => ul.appendChild(el("li", null, label)));
      details.appendChild(ul);
      card.appendChild(details);
    }
    const again = el("button", "link-button", "Re-analyze");
    again.addEventListener("click", () => analyze(run.run_id, true));
    card.appendChild(again);
    return card;
  }

  function renderRun(run) {
    const result = outcome(run);
    const card = el("article", "run " + result.cls);

    const head = el("div", "run-head");
    head.appendChild(el("span", "run-icon " + result.cls, result.icon));
    const main = el("div", "run-main");
    const line = el("div", "run-title");
    line.appendChild(el("strong", null, run.name + " #" + (run.run_number || run.run_id)));
    line.appendChild(chip(run.branch || "-", "branch"));
    line.appendChild(el("code", "sha", (run.head_sha || "").slice(0, 7)));
    line.appendChild(chip(result.label, "state-" + result.cls));
    main.appendChild(line);
    main.appendChild(el("div", "run-msg", run.message));
    head.appendChild(main);

    const side = el("div", "run-side");
    side.appendChild(el("span", "muted", ago(run.created_at)));
    const gh = link("GitHub ↗", run.html_url);
    if (gh) side.appendChild(gh);
    head.appendChild(side);
    card.appendChild(head);

    if (run.jobs && run.jobs.length) {
      const jobs = el("div", "run-jobs");
      run.jobs.forEach((job) => {
        const r = outcome(job);
        const c = chip(r.icon + " " + job.name, "job-" + r.cls);
        c.title = job.failed_steps && job.failed_steps.length ? "Failed: " + job.failed_steps.join(", ") : r.label;
        jobs.appendChild(c);
      });
      card.appendChild(jobs);
    }

    if (run.conclusion === "failure" || run.conclusion === "timed_out") {
      const actions = el("div", "run-actions");
      if (view.analyzing[run.run_id]) {
        actions.appendChild(el("span", "muted", "Reading the log and the related code…"));
      } else if (run.analyzed) {
        const toggle = el("button", null, view.open[run.run_id] ? "Hide analysis" : "Show AI analysis");
        toggle.addEventListener("click", () => { view.open[run.run_id] = !view.open[run.run_id]; render(); });
        actions.appendChild(toggle);
        if (!view.open[run.run_id]) actions.appendChild(el("span", "muted", run.analysis_summary));
      } else {
        const go = el("button", "primary", "Analyze failure with AI");
        go.addEventListener("click", () => analyze(run.run_id, false));
        actions.appendChild(go);
      }
      card.appendChild(actions);
      if (view.errors[run.run_id]) card.appendChild(el("p", "error", view.errors[run.run_id]));
      if (run.analyzed && view.open[run.run_id]) {
        // the list endpoint omits the full analysis, so fetch it on demand
        const holder = el("div", "analysis-holder");
        card.appendChild(holder);
        fetchAnalysis(run, holder);
      }
    }
    return card;
  }

  const analysisCache = {};
  async function fetchAnalysis(run, holder) {
    const key = view.repoId + ":" + run.run_id + ":" + run.analysis_summary;
    try {
      if (!analysisCache[key]) {
        analysisCache[key] = (await api(base(view.repoId) + "/runs/" + run.run_id)).analysis;
      }
      holder.replaceChildren(renderAnalysis(run, analysisCache[key]));
    } catch (err) {
      holder.replaceChildren(el("p", "error", err.message));
    }
  }

  function render() {
    panel.replaceChildren(renderToolbar());
    if (state.mode === "dashboard") renderDashboard();
    if (view.status && !view.status.github_token_configured) {
      panel.appendChild(el("p", "banner",
        "No GITHUB_TOKEN is set. You can list public runs (60 requests per hour), but downloading logs " +
        "and AI failure analysis need a token. Add GITHUB_TOKEN to .env and restart the server."));
    }
    if (view.error) panel.appendChild(el("p", "error", view.error));

    const list = el("div", "runs");
    if (!view.runs.length) {
      list.appendChild(el("p", "muted", view.loaded && !view.syncing
        ? "No workflow runs found yet. Push a commit to the repository, then click Sync."
        : "Loading runs…"));
    }
    view.runs.forEach((run) => list.appendChild(renderRun(run)));
    if (state.mode === "pipeline") {
      panel.appendChild(el("h3", null, "Security findings"));
      const selector = el("select"); selector.setAttribute("aria-label", "Run security report");
      view.runs.forEach((run) => { const option = el("option", null, run.name + " #" + (run.run_number || run.run_id)); option.value = run.run_id; if (String(run.run_id) === String(view.selectedReportRun)) option.selected = true; selector.appendChild(option); });
      selector.addEventListener("change", () => { view.selectedReportRun = Number(selector.value); render(); });
      panel.appendChild(selector);
      const reportButton = el("button", "primary", "Load security findings"); reportButton.addEventListener("click", () => { view.selectedReportRun = Number(selector.value); loadReport(view.selectedReportRun); }); panel.appendChild(reportButton);
      const selected = view.selectedReportRun || Number(selector.value);
      const current = view.reports[selected];
      if (current) panel.appendChild(renderSecurity(current, selected));
      if (view.errors["report-" + selected]) panel.appendChild(el("p", "error", view.errors["report-" + selected]));
      if (view.errors["explain-" + selected]) panel.appendChild(el("p", "error", view.errors["explain-" + selected]));
    }
    panel.appendChild(list);
  }

  function renderDashboard() {
    const summary = view.summary;
    const cards = el("div", "dashboard-grid");
    const latest = summary && summary.branches && summary.branches[0];
    const addCard = (title, value, extra) => { const card = el("article", "dashboard-card"); card.appendChild(el("h3", null, title)); card.appendChild(el("strong", null, value)); if (extra) card.appendChild(el("p", "muted", extra)); cards.appendChild(card); };
    addCard("CI status", latest ? latest.conclusion || latest.status : "No run", latest ? latest.branch : "");
    const tests = latest && latest.tests;
    addCard("Tests", tests ? (tests.tests - tests.failures - tests.errors - tests.skipped) + " passed / " + (tests.failures + tests.errors) + " failed" : "No report");
    addCard("Coverage", latest ? latest.coverage_percent + "%" : "No report");
    addCard("Quality score", latest ? String(latest.quality_score) : "—", latest ? "Security " + latest.security + " · coverage " + latest.coverage + " · tests " + latest.test_pass_percent + "%" : "");
    if (latest && latest.findings_by_severity) addCard("Security", "Critical " + latest.findings_by_severity.critical + " · High " + latest.findings_by_severity.high + " · Medium " + latest.findings_by_severity.medium + " · Low " + latest.findings_by_severity.low);
    panel.appendChild(cards);
    if (latest && latest.ai_top_actions && latest.ai_top_actions.length) { panel.appendChild(el("h3", null, "AI top actions")); const actions = el("ol"); latest.ai_top_actions.forEach((action) => actions.appendChild(el("li", null, action))); panel.appendChild(actions); }
    const scores = summary ? summary.last_10_scores : [];
    const trend = el("svg", "score-trend"); trend.setAttribute("viewBox", "0 0 500 110"); trend.setAttribute("role", "img"); trend.setAttribute("aria-label", "Quality score trend for recent runs");
    if (scores.length) { const points = scores.map((item, i) => (scores.length === 1 ? 250 : i * 480 / (scores.length - 1) + 10) + "," + (100 - item.score)).join(" "); const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline"); line.setAttribute("points", points); line.setAttribute("fill", "none"); line.setAttribute("stroke", "currentColor"); line.setAttribute("stroke-width", "3"); trend.appendChild(line); }
    panel.appendChild(trend);
  }

  function renderSecurity(report, runId) {
    const section = el("div", "security-list");
    (report.findings || []).forEach((finding) => { const row = el("article", "security-finding"); row.appendChild(el("strong", null, finding.severity.toUpperCase() + " · " + finding.rule_id)); row.appendChild(el("p", null, finding.title)); row.appendChild(el("code", null, finding.path + (finding.line ? ":" + finding.line : ""))); if (finding.package) row.appendChild(el("p", "muted", finding.package + " " + finding.installed + (finding.fixed ? " → " + finding.fixed : ""))); section.appendChild(row); });
    const button = el("button", "primary", view.explaining[runId] ? "Explaining…" : "Explain with AI"); button.disabled = Boolean(view.explaining[runId]); button.addEventListener("click", () => explainSecurity(runId)); section.appendChild(button);
    const explanation = report.explanation;
    if (explanation) { section.appendChild(el("h3", null, explanation.summary)); const actions = el("ol"); (explanation.top_actions || []).forEach((action) => actions.appendChild(el("li", null, action))); section.appendChild(actions); (explanation.findings || []).forEach((item) => { const card = el("article", "security-finding"); card.appendChild(el("strong", null, item.rule_id + " · priority " + item.priority)); card.appendChild(el("p", null, item.explanation)); card.appendChild(el("p", null, "Impact: " + item.impact)); card.appendChild(el("p", null, "Fix: " + item.fix)); section.appendChild(card); }); }
    return section;
  }

  /* ---------- hook into the existing tab logic ---------- */
  const baseUpdatePanels = updatePanels;
  updatePanels = function () {
    baseUpdatePanels();
    const repo = selectedRepo();
    const show = Boolean(repo && repo.status === "ready") && (state.mode === "pipeline" || state.mode === "dashboard");
    panel.hidden = !show;
    if (show) activate(repo.id); else stopTimer();
  };
})();
