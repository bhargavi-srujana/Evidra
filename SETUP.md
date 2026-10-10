# Evidra — Setup Instructions

Step-by-step setup for running Evidra locally (Windows, macOS, or Linux).
Evidra has two apps: a **FastAPI backend** (`backend/`) and a **Next.js frontend**
(`frontend/`), plus MongoDB (Atlas or local Docker).

## 1. Prerequisites

| Tool | Version | Check | Install |
| --- | --- | --- | --- |
| Node.js | 20+ | `node --version` | https://nodejs.org |
| Python | 3.11+ | `python --version` | https://python.org |
| uv | latest | `uv --version` | https://docs.astral.sh/uv/ |
| MongoDB | Atlas **or** Docker | — | https://cloud.mongodb.com or https://docker.com |

> MongoDB is **optional for trying search** (the API degrades gracefully
> without it), but required for cached results, the compare pipeline's
> stored claims, and `npm run db:seed`.

## 2. Clone and configure environment

```powershell
git clone <repo-url> Evidra
cd Evidra

# Backend env (LLM keys, Scholar keys, Mongo)
copy backend\.env.example backend\.env   # Windows
# cp backend/.env.example backend/.env   # macOS / Linux
```

Edit `backend/.env` — minimum for a working demo:

```ini
# MongoDB Atlas (preferred): paste your cluster URI, or use MONGO_URL for local
MONGODB_URI=mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/
MONGO_DB=evidra

# Any OpenAI-compatible LLM endpoint (OpenAI, Groq, Gemini gateway, …)
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# Literature providers (at least one recommended; S2 also backfills abstracts)
SERPAPI_API_KEY=
S2_API_KEY=
```

> Never commit `backend/.env` — it is git-ignored. Only `*.example` templates
> belong in version control.

```powershell
# Frontend env
copy frontend\.env.example frontend\.env.local   # Windows
# cp frontend/.env.example frontend/.env.local   # macOS / Linux
```

`frontend/.env.local` needs exactly one line (already in the template):

```ini
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

The `/api/v1` prefix is mandatory — without it every request 404s.

## 3. Start the backend

```powershell
cd backend
uv sync                 # installs dependencies into .venv (first run only)
uv run uvicorn app.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health (reports `mongo_connected` and LLM key status)

Restart the backend after editing anything under `backend/app/prompts/`
(prompts are cached in-process).

## 4. Seed the database (recommended)

Seeding loads 24 sample papers + claims across the four homepage test
questions, so results are instant with zero LLM quota burn:

```powershell
# From frontend/ (one command, Windows/macOS/Linux):
cd frontend
npm run db:seed

# …or directly from backend/:
cd backend
uv run python scripts/seed.py
```

Expected output ends with `Seeding completed successfully` plus
`24 studies, 24 claims, 4 cache entries, 4 comparisons`. Re-running is safe
(previous seed rows are removed first; your other data is untouched).

## 5. Start the frontend

```powershell
cd frontend
npm install   # first run only
npm run dev
```

- App: http://localhost:3000

## 6. Verify it works

1. Open http://localhost:3000, click **"Do explanations improve trust in AI decisions?"** — 6 papers, claims, contradiction clusters, and gaps should render instantly (seeded).
2. Try a new question (e.g. *"Does sleep improve memory consolidation?"*) — first run hits live Scholar + LLM extraction (takes ~1–2 min on free tiers), repeats are instant.
3. Check http://127.0.0.1:8000/health → `"status": "ok"`, `"mongo_connected": true`.

## 7. Docker alternative (backend + Mongo together)

```powershell
copy .env.example .env   # fill in keys at repo root
docker compose up --build
```

- API: http://127.0.0.1:8000 · Mongo: 127.0.0.1:27017 (loopback only)
- Change `MONGO_USER`/`MONGO_PASSWORD` before first boot; changing them later
  requires `docker compose down -v`.
- The frontend still runs separately (`npm run dev`) and points at the
  composed API via `NEXT_PUBLIC_API_URL`.

## 8. Useful commands

| Where | Command | Purpose |
| --- | --- | --- |
| `backend/` | `uv run pytest` | Backend test suite (66 tests) |
| `backend/` | `uv run ruff check app tests scripts` | Lint |
| `backend/` | `uv run python scripts/seed.py` | Seed MongoDB directly |
| `frontend/` | `npm run dev` / `build` / `start` | Dev / production build / serve |
| `frontend/` | `npm run typecheck` / `npm run lint` | Type + lint checks |
| `frontend/` | `npm run db:seed` | Seed MongoDB via npm |

## 9. Troubleshooting

| Symptom | Fix |
| --- | --- |
| `mongo_connected: false` | Check `MONGODB_URI`/`MONGO_URL`; for Atlas, allowlist your IP (Network Access → Add IP). |
| LLM 401 / hollow "Not reported" cards | Re-paste the key in `backend/.env` (Groq keys start with `gsk_`), restart backend; `/health` flags malformed keys. |
| Results 502 "providers unavailable" | Set `SERPAPI_API_KEY` and/or `S2_API_KEY`; free tiers rate-limit — wait and retry. |
| Frontend API errors / 404s | `NEXT_PUBLIC_API_URL` must end in `/api/v1`; backend must be running on port 8000. |
| Only 4 (or fewer) papers on a new question | Provider variability — seeded demo questions always serve 6. |
| Port already in use | Backend: `uvicorn` on another terminal; frontend: `npm run dev -- -p 3001`. |
