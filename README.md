# Evidra — Research Evidence & Contradiction Engine

Evidra turns a plain-English research question into **structured, comparable evidence**.
Ask something like *"does sleep improve memory consolidation?"* and it retrieves
live literature, extracts PICO study design + atomic claims with an LLM, then
clusters claims, surfaces contradictions, and maps research gaps — all in one flow.

## What it does

- **Live literature search** (`POST /api/v1/search`) — queries Google Scholar via
  SerpApi (primary) with a Semantic Scholar fallback, dedupes across providers,
  and backfills missing abstracts.
- **Single-call LLM extraction** — one request per paper returns both the PICO
  design (`population`, `intervention`, `control`, …) and atomic claims with
  effect direction (`increases` / `decreases` / `no_effect` / `conditional`) and
  confidence scores. Works with any OpenAI-compatible API (OpenAI, Groq, Gemini
  gateway, …). Missing fields fall back to `"Not reported"` instead of blanks.
- **Methodology-aware comparison** (`POST /api/v1/compare`) — clusters claims
  into topics, pairs opposing findings, diffs PICO designs, and explains
  divergences as cautious, evidence-grounded hypotheses.
- **Research-gap detection** — deterministic, hallucination-free scan of the
  retrieved corpus (under-reported dimensions, population coverage, sample
  scale, settings balance).
- **Free-tier safe** — serial request pacing (default 12 s ≈ 5 RPM), burst caps,
  and quota-aware retries that honor the provider's retry hint and fail fast on
  daily lockouts. Extraction never 500s: failures degrade to structured defaults.
- **Frontend** — Next.js results page with study cards, contradiction explorer,
  and an interactive evidence graph (question → topic clusters → studies, with
  dashed-red contradiction edges).

## Repo layout

```
Evidra/
├── backend/               # FastAPI API (Python 3.11+, uv)
│   ├── app/
│   │   ├── api/v1/        # routes_search, routes_compare, routes_studies
│   │   ├── services/      # search_s2, search_serp, extraction, comparison, gap_analysis
│   │   ├── prompts/       # versioned LLM prompt contracts (*.json)
│   │   ├── models/        # Study, Claim, ComparisonMatrix schemas
│   │   ├── db/            # Motor (async MongoDB) client
│   │   └── core/          # pydantic-settings config
│   └── pyproject.toml
├── frontend/              # Next.js 16 + React 19 + Tailwind + XYFlow
├── docker-compose.yml     # api + mongo:7
└── .env.example           # env template (copy to backend/.env for local dev)
```

## Quickstart

**Local dev** (two terminals):

```powershell
# Backend — from backend/
copy .env.example .env   # then fill in keys
uv sync
uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000 (docs at /docs)

# Frontend — from frontend/
npm install
npm run dev              # http://localhost:3000
```

MongoDB must be reachable at `MONGO_URL` (default `mongodb://localhost:27017`).

**Docker:**

```powershell
copy .env.example .env   # fill in keys at repo root
docker compose up --build
```

## Configuration (`backend/.env`)

| Key | Default | Purpose |
| --- | --- | --- |
| `OPENAI_BASE_URL` / `OPENAI_API_KEY` / `OPENAI_MODEL` | `https://api.openai.com/v1` / — / `gpt-4o-mini` | Any OpenAI-compatible LLM endpoint |
| `LLM_MIN_INTERVAL_SECONDS` | `12.0` | Min gap between LLM calls (≈5 RPM; `4.0` ≈ 15 RPM, `0` = off) |
| `LLM_MAX_RETRIES` / `LLM_MAX_RETRY_DELAY_SECONDS` | `2` / `75.0` | Transient 429/503 retries; larger server hints fail fast |
| `SERPAPI_API_KEY` / `S2_API_KEY` | empty | Scholar providers (S2 also backfills abstracts) |
| `MONGO_URL` / `MONGO_DB` | `mongodb://localhost:27017` / `evidra` | Persistence (best-effort; search works without it) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Frontend → backend wiring |

## API

| Method & path | Body | Returns |
| --- | --- | --- |
| `POST /api/v1/search` | `{ "query": string, "max_results": 1–50 }` | `{ query, results: Study[], claims: Claim[] }` |
| `POST /api/v1/compare` | `{ "study_ids": [...], "claims"?: [...] }` | `{ clusters, contradictions, summary, gaps }` |
| `GET /api/v1/studies/{study_id}` | — | stub study detail |
| `GET /health` | — | `{ status, env, mongo_connected }` |

Each paper costs **1 LLM call**; keep `max_results` small (3–5) on free tiers
(e.g. Gemini free tier ≈ 5 req/min, 20 req/day per model).

## Notes

- Restart the backend after editing anything under `backend/app/prompts/` —
  prompts are cached in-process and JSON edits don't trigger `--reload`.
- Empty extractions from failed runs persist in Mongo; stale all-empty studies
  can be reaped by deleting `studies` docs whose `design` fields are all empty.
