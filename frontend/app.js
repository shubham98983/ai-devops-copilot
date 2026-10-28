"use strict";

const state = { repos: [], selectedId: null, mode: "chat", history: [], pollTimer: null };
const $ = (id) => document.getElementById(id);

const SUGGESTIONS = [
  "Give me an overview of this repo",
  "How does authentication work?",
  "What happens when a sale is created?",
  "Which endpoints require admin access?",
  "Where is stock reduced and recorded?",
];

/* ---------- API helpers ---------- */
async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let body = null;
  try { body = await response.json(); } catch (_) { /* no body */ }
  if (!response.ok) {
    const detail = body && body.detail;
    const message = typeof detail === "string" ? detail : "Request failed (" + response.status + ")";
    throw new Error(message);
  }
  return body;
}

/* ---------- Safe DOM rendering (no innerHTML with dynamic data) ---------- */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[[^\]\s]+:\d+-\d+\])/g;

function renderInline(parent, text) {
  text.split(INLINE).forEach((part) => {
    if (!part) return;
    if (part.startsWith("`") && part.endsWith("`")) {
      parent.appendChild(el("code", null, part.slice(1, -1)));
    } else if (part.startsWith("**") && part.endsWith("**")) {
      parent.appendChild(el("strong", null, part.slice(2, -2)));
    } else if (/^\[[^\]\s]+:\d+-\d+\]$/.test(part)) {
      const cite = el("span", "cite", part);
      cite.addEventListener("click", () => flashSource(part.slice(1, -1), parent));
      parent.appendChild(cite);
    } else {
      parent.appendChild(document.createTextNode(part));
    }
  });
}

function renderRichText(container, text) {
  text.split(/```[a-zA-Z0-9_+-]*\n?/).forEach((block, index) => {
    if (index % 2 === 1) {
      const pre = el("pre");
      pre.appendChild(el("code", null, block.replace(/\n$/, "")));
      container.appendChild(pre);
      return;
    }
    block.split(/\n{2,}/).forEach((paragraph) => {
      if (!paragraph.trim()) return;
      const p = el("p");
      paragraph.split("\n").forEach((line, i) => {
        if (i > 0) p.appendChild(document.createElement("br"));
        renderInline(p, line);
      });
      container.appendChild(p);
    });
  });
}

function flashSource(label, from) {
  const bubble = from.closest(".msg");
  const target = bubble && bubble.querySelector('[data-label="' + CSS.escape(label) + '"]');
  if (!target) return;
  const details = bubble.querySelector("details.sources");
  if (details) details.open = true;
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.add("flash");
  setTimeout(() => target.classList.remove("flash"), 1500);
}

function renderSource(source) {
  const box = el("div", "source");
  box.dataset.label = source.label;
  const head = el("div", "source-head");
  head.appendChild(el("strong", null, source.label));
  (source.found_by || []).forEach((name) => head.appendChild(el("span", "chip" + (name === "exact" ? " exact" : ""), name)));
  box.appendChild(head);
  box.appendChild(el("pre", "snippet", source.snippet));
  return box;
}

/* ---------- Repositories ---------- */
function selectedRepo() { return state.repos.find((r) => r.id === state.selectedId) || null; }

function renderRepos() {
  const list = $("repo-list");
  list.replaceChildren();
  $("repo-empty").hidden = state.repos.length > 0;
  state.repos.forEach((repo) => {
    const item = el("li", "repo-item" + (repo.id === state.selectedId ? " selected" : ""));
    item.appendChild(el("span", "repo-name", repo.owner + "/" + repo.name));
    item.appendChild(el("span", "badge " + repo.status, repo.status));
    item.addEventListener("click", () => selectRepo(repo.id));
    list.appendChild(item);
  });

  const repo = selectedRepo();
  $("repo-details").hidden = !repo;
  if (repo) {
    const meta = $("repo-meta");
    meta.replaceChildren();
    [["Status", repo.status], ["Files", repo.files], ["Chunks", repo.chunks],
     ["Commit", (repo.commit_sha || "").slice(0, 8) || "-"], ["Updated", repo.updated_at]].forEach(([k, v]) => {
      meta.appendChild(el("dt", null, k));
      meta.appendChild(el("dd", null, String(v)));
    });
    if (repo.error) {
      meta.appendChild(el("dt", null, "Error"));
      meta.appendChild(el("dd", null, repo.error));
    }
  }
  updatePanels();
}

function updatePanels() {
  const repo = selectedRepo();
  const ready = repo && repo.status === "ready";
  $("empty-state").hidden = Boolean(ready);
  $("chat-panel").hidden = !(ready && state.mode === "chat");
  $("search-panel").hidden = !(ready && state.mode === "search");
  if (repo && !ready) {
    const title = $("empty-state").querySelector("h1");
    title.textContent = repo.status === "failed" ? "Indexing failed" : "Indexing " + repo.owner + "/" + repo.name + "…";
  }
}

async function refreshRepos() {
  state.repos = await api("/api/repos");
  if (!state.selectedId && state.repos.length) state.selectedId = state.repos[0].id;
  renderRepos();
  const busy = state.repos.some((r) => ["queued", "cloning", "indexing"].includes(r.status));
  if (busy && !state.pollTimer) state.pollTimer = setInterval(refreshRepos, 2000);
  if (!busy && state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
}

function selectRepo(id) {
  if (state.selectedId !== id) { state.history = []; $("messages").replaceChildren(); $("search-results").replaceChildren(); }
  state.selectedId = id;
  renderRepos();
}

$("repo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("repo-error");
  error.hidden = true;
  $("repo-submit").disabled = true;
  try {
    const repo = await api("/api/repos", { method: "POST", body: JSON.stringify({ url: $("repo-url").value.trim() }) });
    state.selectedId = repo.id;
    $("repo-url").value = "";
    await refreshRepos();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  } finally {
    $("repo-submit").disabled = false;
  }
});

/* ---------- Chat ---------- */
function addMessage(role, text) {
  const bubble = el("div", "msg " + role);
  if (role === "user") bubble.textContent = text; else renderRichText(bubble, text);
  $("messages").appendChild(bubble);
  $("messages").scrollTop = $("messages").scrollHeight;
  return bubble;
}

async function ask(question) {
  const repo = selectedRepo();
  if (!repo || repo.status !== "ready" || !question.trim()) return;
  addMessage("user", question);
  const pending = addMessage("bot", "Searching the code and thinking…");
  pending.classList.add("pending");
  $("chat-submit").disabled = true;
  try {
    const result = await api("/api/repos/" + encodeURIComponent(repo.id) + "/chat", {
      method: "POST",
      body: JSON.stringify({ question, history: state.history.slice(-6) }),
    });
    pending.replaceChildren();
    pending.classList.remove("pending");
    renderRichText(pending, result.answer);
    if (result.sources.length) {
      const details = el("details", "sources");
      details.appendChild(el("summary", null, "Sources (" + result.sources.length + ")"));
      result.sources.forEach((s) => details.appendChild(renderSource(s)));
      pending.appendChild(details);
    }
    state.history.push({ role: "user", content: question }, { role: "assistant", content: result.answer });
  } catch (err) {
    pending.classList.remove("pending");
    pending.textContent = "Error: " + err.message;
  } finally {
    $("chat-submit").disabled = false;
    $("messages").scrollTop = $("messages").scrollHeight;
  }
}

$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("chat-input");
  const question = input.value;
  input.value = "";
  ask(question);
});

SUGGESTIONS.forEach((text) => {
  const button = el("button", null, text);
  button.type = "button";
  button.addEventListener("click", () => ask(text));
  $("suggestions").appendChild(button);
});

/* ---------- Semantic search ---------- */
$("search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const repo = selectedRepo();
  const query = $("search-input").value.trim();
  if (!repo || query.length < 2) return;
  const params = new URLSearchParams({ q: query, k: "8" });
  if ($("search-language").value) params.set("language", $("search-language").value);
  const results = $("search-results");
  results.replaceChildren(el("p", "muted", "Searching…"));
  try {
    const hits = await api("/api/repos/" + encodeURIComponent(repo.id) + "/search?" + params);
    results.replaceChildren();
    if (!hits.length) results.appendChild(el("p", "muted", "No matches."));
    hits.forEach((hit) => {
      const card = el("div", "result");
      const head = el("div", "source-head");
      head.appendChild(el("strong", null, hit.label));
      if (hit.symbols) head.appendChild(el("span", "chip", hit.symbols));
      hit.found_by.forEach((name) => head.appendChild(el("span", "chip" + (name === "exact" ? " exact" : ""), name)));
      card.appendChild(head);
      card.appendChild(el("pre", "snippet", hit.snippet));
      results.appendChild(card);
    });
  } catch (err) {
    results.replaceChildren(el("p", "error", err.message));
  }
});

/* ---------- Tabs and health ---------- */
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    state.mode = tab.dataset.mode;
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    updatePanels();
  });
});

async function init() {
  try {
    const health = await api("/health");
    const pill = $("health");
    if (health.llm_key_configured) {
      pill.textContent = "LLM: " + health.llm_provider + " · " + health.embedding_model;
      pill.classList.add("ok");
    } else {
      pill.textContent = "API key missing for " + health.llm_provider + " (check .env)";
      pill.classList.add("bad");
    }
  } catch (_) {
    $("health").textContent = "backend offline";
    $("health").classList.add("bad");
  }
  try { await refreshRepos(); } catch (_) { /* backend offline */ }
}
init();
