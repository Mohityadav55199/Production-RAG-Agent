.PHONY: help install lint typecheck types test test-web test-db check eval judge guardrails gen-api seed-demo loadtest dev-backend dev-frontend up down

PYTHON ?= python
TEST_DB_URL ?= postgresql+asyncpg://postgres:pw@localhost:5433/ragtest

help: ## Show this list
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install backend (pinned) and frontend dependencies
	cd backend && $(PYTHON) -m pip install -c requirements.lock -r requirements-dev.txt
	npm ci

lint: ## Lint backend (ruff) and frontend (eslint)
	cd backend && $(PYTHON) -m ruff check .
	npm run lint

typecheck: ## Type check the frontend (TypeScript)
	npm run typecheck

types: ## Type check the backend (mypy)
	cd backend && $(PYTHON) -m mypy app

test: ## Backend tests (API tests are skipped unless TEST_DATABASE_URL is set)
	cd backend && $(PYTHON) -m pytest -q

test-web: ## Frontend tests (Vitest)
	npm test

test-db: ## Backend tests including the API tests (starts a throwaway Postgres in Docker)
	-docker run -d --name ragtest -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=ragtest -p 5433:5432 postgres:16
	cd backend && TEST_DATABASE_URL=$(TEST_DB_URL) $(PYTHON) -m pytest -q

check: lint typecheck types test test-web ## Everything CI checks, except the production build, the Docker build and audits

eval: ## Retrieval benchmark for every pipeline stage (live; needs API keys, costs a few embeddings)
	cd backend && PYTHON=$(PYTHON) bash eval/run_comparison.sh && $(PYTHON) eval/summarize_results.py --write

judge: ## Answer-quality check, 20 questions (live; two model calls each)
	cd backend && $(PYTHON) eval/judge.py --limit 20

guardrails: ## Prompt-injection and invented-fact cases (live; one model call each)
	cd backend && $(PYTHON) eval/guardrails.py

gen-api: ## Regenerate lib/api-client/schema.d.ts from the backend (activate the backend virtualenv first)
	npm run gen:api

seed-demo: ## Create a demo account with the sample documents (needs DEMO_PASSWORD; BASE_URL defaults to local)
	cd backend && $(PYTHON) scripts/seed_demo.py --base-url $(or $(BASE_URL),http://localhost:8000)

loadtest: ## Load test a LOCAL backend with Locust (refuses remote hosts)
	cd backend && locust -f loadtest/locustfile.py --host http://localhost:8000

dev-backend: ## Run the API with auto-reload on :8000
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Next.js app on :3000
	npm run dev

up: ## Start the full stack with Docker Compose
	docker compose up --build

down: ## Stop the Docker Compose stack
	docker compose down
