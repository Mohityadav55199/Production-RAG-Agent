.PHONY: help install lint typecheck test test-db check dev-backend dev-frontend up down

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

typecheck: ## Type check the frontend
	npm run typecheck

test: ## Backend tests (API tests are skipped unless TEST_DATABASE_URL is set)
	cd backend && $(PYTHON) -m pytest -q

test-db: ## Backend tests including the API tests (starts a throwaway Postgres in Docker)
	-docker run -d --name ragtest -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=ragtest -p 5433:5432 postgres:16
	cd backend && TEST_DATABASE_URL=$(TEST_DB_URL) $(PYTHON) -m pytest -q

check: lint typecheck test ## Everything CI checks, except the production build and audits

dev-backend: ## Run the API with auto-reload on :8000
	cd backend && $(PYTHON) -m uvicorn app.main:app --reload --port 8000

dev-frontend: ## Run the Next.js app on :3000
	npm run dev

up: ## Start the full stack with Docker Compose
	docker compose up --build

down: ## Stop the Docker Compose stack
	docker compose down
