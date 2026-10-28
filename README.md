# AI DevOps Copilot

Paste a GitHub repository URL, let the copilot index it, then ask questions about the code.
Answers are grounded in the repository and cite file paths and line ranges.

This is the first milestone: the **RAG Q&A bot**. CI/CD automation, test generation,
security explanation and the pipeline dashboard are added in later milestones.

## How it works

```
GitHub URL -> clone -> filter files -> code-aware chunks (LangChain splitters)
           -> bge-small embeddings -> ChromaDB  (+ BM25 keyword index)
Question   -> hybrid retrieval (vector + BM25 + exact identifier boost, merged with RRF)
           -> secret redaction -> prompt -> cloud LLM (LangChain) -> answer with citations
```

| Part | Choice |
|---|---|
| Framework | LangChain (splitters, documents, Chroma, embeddings, prompt + chat model chain) |
| Embeddings | `BAAI/bge-small-en-v1.5` via sentence-transformers, CPU |
| Vector DB | ChromaDB, one collection per repository |
| Keyword search | BM25 with identifier-aware tokenizer (`is_low_stock` also matches `low`, `stock`) |
| LLM | Gemini, Groq, Anthropic or OpenRouter through one `get_llm()` factory |
| Backend | FastAPI |
| Frontend | Plain HTML, CSS and JavaScript served by FastAPI |

### Safety choices
- Only `https://github.com/owner/repo` URLs are accepted (no local paths, no other hosts).
- Secret-looking values are replaced with `[REDACTED]` before code is sent to the cloud LLM.
- Repository text is treated as untrusted data in the prompt (prompt-injection guard).
- Limits: 500 files, 200 KB per file; `node_modules`, lockfiles, binaries and build output are skipped.

## Setup (Ubuntu VM)

```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip
python3 -m venv .venv && source .venv/bin/activate

# CPU-only PyTorch first (avoids a multi-GB CUDA download), then the rest
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

cp .env.example .env     # set LLM_PROVIDER and the matching API key
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The first index downloads the embedding model (about 130 MB).

With VirtualBox NAT, add a port-forwarding rule host `8000` -> guest `8000` to open it from your host browser.

### Free API keys
- Gemini: https://aistudio.google.com/apikey  (`LLM_PROVIDER=gemini`, `GOOGLE_API_KEY`)
- Groq: https://console.groq.com/keys  (`LLM_PROVIDER=groq`, `GROQ_API_KEY`)
- OpenRouter: https://openrouter.ai/keys (`LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`)

To switch providers, set `LLM_PROVIDER` and the matching key in `.env`, then restart the server.
For OpenRouter's free-model router, use `LLM_PROVIDER=openrouter` and `LLM_MODEL=openrouter/free`.
It chooses an eligible free model for each request, so the specific model can vary.

If a request fails with a model-not-found error, set `LLM_MODEL` to a current model name from the provider's docs.

### Docker

```bash
docker compose up --build
```

## API

| Method | Path | Description |
|---|---|---|
| POST | `/api/repos` | `{"url": "https://github.com/owner/repo"}` starts indexing (202) |
| GET | `/api/repos` | List repositories and their status |
| GET | `/api/repos/{id}` | Status: queued, cloning, indexing, ready, failed |
| POST | `/api/repos/{id}/chat` | `{"question": "...", "history": []}` returns answer and sources |
| GET | `/api/repos/{id}/search?q=&language=&kind=` | Retrieval only, no LLM |
| GET | `/health` | Service and configuration info |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The tests use fake embeddings and a fake LLM, so they run offline.

## Project layout

```
app/
  ingestion/   cloner (URL validation, git), loader (file filtering), chunker (line metadata)
  rag/         embeddings, vectorstore (Chroma), retriever (hybrid), chain (prompt + LLM), redact
  llm/         provider factory
  indexer.py   background indexing job      store.py   SQLite repo registry
  main.py      FastAPI routes + static frontend
frontend/      index.html, style.css, app.js
tests/         pytest suite
```
