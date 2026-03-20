.PHONY: up down build logs ps shell-ingestion shell-feature shell-regime shell-api test lint migrate

# ── Docker Compose ──────────────────────────────────────────────────────────
up:
	docker compose up -d

up-infra:
	docker compose up -d timescaledb redis kafka zookeeper mlflow

up-services:
	docker compose up -d ingestion feature regime alert api

down:
	docker compose down

down-volumes:
	docker compose down -v

build:
	docker compose build

build-no-cache:
	docker compose build --no-cache

logs:
	docker compose logs -f

logs-%:
	docker compose logs -f $*

ps:
	docker compose ps

# ── Shell access ────────────────────────────────────────────────────────────
shell-%:
	docker compose exec $* /bin/bash

# ── Testing ─────────────────────────────────────────────────────────────────
test:
	docker compose run --rm ingestion pytest tests/ -v
	docker compose run --rm feature pytest tests/ -v
	docker compose run --rm regime pytest tests/ -v
	docker compose run --rm api pytest tests/ -v

test-%:
	docker compose run --rm $* pytest tests/ -v

# ── Linting ─────────────────────────────────────────────────────────────────
lint:
	docker compose run --rm ingestion ruff check src/ && mypy src/
	docker compose run --rm feature ruff check src/ && mypy src/
	docker compose run --rm regime ruff check src/ && mypy src/
	docker compose run --rm api ruff check src/ && mypy src/

# ── DB Migrations ───────────────────────────────────────────────────────────
migrate:
	docker compose exec timescaledb psql -U quantpulse -d quantpulse -f /docker-entrypoint-initdb.d/001_schema.sql

# ── Setup ───────────────────────────────────────────────────────────────────
setup:
	cp .env.example .env
	@echo "Edit .env with your API keys then run: make up-infra && make up-services"

# ── Frontend ────────────────────────────────────────────────────────────────
frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build
