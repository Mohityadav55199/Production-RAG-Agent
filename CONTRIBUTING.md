# Contributing

Thanks for taking a look. This is a full-stack project (Next.js frontend, FastAPI backend), and these notes get you from
a fresh clone to a passing test run.

## Prerequisites

- Python 3.12 and Node.js 24
- Docker (for the local stack and for the database the API tests need)
- Optional: `make`. On Windows, install it with `choco install make` or use Git Bash; every `make` target below is just
  a short alias for the plain command shown next to it.

## Setup

```bash
git clone https://github.com/Mohityadav55199/Production-RAG-Agent.git
cd Production-RAG-Agent

cp backend/.env.example backend/.env     # then fill in your keys (see README, "Configure Backend Environment")
make install                              # or: see the two commands below
```

Without `make`:

```bash
cd backend && python -m venv .venv && source .venv/bin/activate   # Windows: .\.venv\Scripts\Activate.ps1
pip install -c requirements.lock -r requirements-dev.txt
cd .. && npm ci
```

## Everyday commands

| Task | `make` | Plain command |
|---|---|---|
| Run the whole stack | `make up` | `docker compose up --build` |
| Run the API | `make dev-backend` | `cd backend && uvicorn app.main:app --reload --port 8000` |
| Run the frontend | `make dev-frontend` | `npm run dev` |
| Lint | `make lint` | `cd backend && ruff check .` and `npm run lint` |
| Type check | `make typecheck` | `npm run typecheck` |
| Backend tests | `make test` | `cd backend && pytest -q` |
| Backend tests incl. API tests | `make test-db` | see below |
| Everything CI checks | `make check` | all of the above |

### Running the API tests

The API tests need a PostgreSQL database whose **name contains `test`**, because the suite wipes the schema when it
starts. Never point it at a real database.

```bash
docker run -d --name ragtest -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=ragtest -p 5433:5432 postgres:16
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://postgres:pw@localhost:5433/ragtest pytest -q
```

Without `TEST_DATABASE_URL` those tests are skipped and the rest still run. The resume PDF tests also skip when
`pdflatex` is not installed; CI installs it, so they do run there.

## Workflow

1. Create a branch from `main` (`feat/...`, `fix/...`).
2. Make the change and add or update tests next to the code it covers (`backend/tests/`).
3. Run `make check`, then `npm run build` if you touched the frontend.
4. Open a pull request. CI must be green: ruff, pytest against Postgres, frontend typecheck/lint/build, Docker build.

Commit messages follow the Conventional Commits style used in the history: `feat(scope): ...`, `fix(scope): ...`,
`docs: ...`, `ci: ...`.

## Conventions

- **Backend:** async everywhere (SQLAlchemy 2.0 async, httpx), Pydantic v2 schemas in `app/schemas/`, business logic in
  `app/services/`, thin routers in `app/api/`. Schema changes need an Alembic migration (`alembic revision --autogenerate`).
- **Frontend:** App Router pages in `app/`, reusable pieces in `components/`, API calls in `lib/api/`. This repo uses a
  newer Next.js than most tutorials; check `node_modules/next/dist/docs/` before relying on older conventions.
- **No secrets in git.** `.env` files are ignored; add new settings to `backend/.env.example` with a safe placeholder.
- **Keep the Render free tier cheap.** Do not add keep-warm pings, cron jobs, or background polling of the backend.

## Reporting security problems

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
