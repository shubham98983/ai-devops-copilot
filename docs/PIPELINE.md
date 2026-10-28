# Pipeline monitor and AI failure analyzer

Shows the GitHub Actions runs of an indexed repository and explains why a run failed,
using the job log and the related code from the RAG index.

## Setup

1. Create a GitHub token the copilot can use to read Actions data.
   - Preferred: GitHub > Settings > Developer settings > Personal access tokens > Fine-grained tokens.
     Select only the demo repository and give it read access to **Actions** and **Contents**.
   - Quick alternative for a demo: `gh auth token` (broader access, so keep it private).
2. Put it in `.env` (never commit that file):
   ```
   GITHUB_TOKEN=<your token>
   PIPELINE_POLL_SECONDS=60
   ```
3. `pip install httpx`, restart `uvicorn`, open the **Pipeline** tab for an indexed repository.

Without a token you can still list public runs (GitHub allows 60 anonymous requests per hour),
but job logs cannot be downloaded, so the analyzer is unavailable.

## How it works

```
GitHub API --poll--> runs + job summaries --> SQLite (registry.db, table "runs")
Failed run -> download the failed job logs
           -> clean (timestamps, ANSI) and cut to the failing section
              (pytest FAILURES block first; otherwise the last step that errored)
           -> files and lines named in the log + code mentioned by name in the errors
           -> look them up in the RAG index (log references, then hybrid search)
           -> redact secrets -> LLM returns JSON -> validated -> stored and shown
```

- The VM is behind NAT, so GitHub cannot send webhooks. The backend polls instead, in the background
  every `PIPELINE_POLL_SECONDS` and whenever you press **Sync**.
- Job details are fetched only for new or unfinished runs, and at most 10 per sync, to stay inside rate limits.
- Results are cached; **Re-analyze** forces a new answer.
- The analysis records the commit the index was built from. If it differs from the failing run's commit,
  the UI warns that the code shown to the AI may be out of date. Re-index to refresh it.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/repos/{id}/pipeline/status` | Token configured, polling state |
| POST | `/api/repos/{id}/pipeline/sync` | Pull runs and jobs from GitHub now |
| GET | `/api/repos/{id}/pipeline/runs` | Stored runs, newest first |
| GET | `/api/repos/{id}/pipeline/runs/{run_id}` | One run with its full analysis |
| POST | `/api/repos/{id}/pipeline/runs/{run_id}/analyze?force=` | Analyse a failed run |

## Safety choices

- Logs and code are treated as untrusted input in the prompt (prompt-injection guard).
- Secret-looking values are removed before anything is sent to the cloud LLM.
- The token is read from the environment, never returned by the API, and not forwarded when GitHub
  redirects a log download to another host.
- Links from GitHub are only rendered when they start with `https://github.com/`.
- Model output is rendered as text, never as HTML.
