# ARIA task runner. Run `make` or `make help` for the list.
# PYTHON prefers the local miniconda interpreter if present, else python3 (CI/Railway).
PYTHON ?= $(shell [ -x /Users/sucheetboppana/miniconda-arm64/bin/python3 ] && echo /Users/sucheetboppana/miniconda-arm64/bin/python3 || echo python3)
ROOT := $(CURDIR)

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: install-backend install-frontend ## Install all dependencies

install-backend: ## Install Python dependencies
	cd backend && $(PYTHON) -m pip install -r requirements.txt

install-frontend: ## Install frontend dependencies
	cd frontend && npm ci

dev-python: ## Run the Python FastAPI service (:8000)
	cd backend && PYTHONPATH=$(ROOT)/backend $(PYTHON) -m uvicorn app.main:app --port 8000

dev-go: ## Run the Go server (:8080)
	cd backend && go run cmd/server/main.go

dev-frontend: ## Run the Next.js frontend (:3000)
	cd frontend && npm run dev

test: test-backend test-go test-frontend ## Run all test suites

test-backend: ## Python tests (pytest)
	PYTHONPATH=$(ROOT)/backend $(PYTHON) -m pytest backend/tests/ -v

test-go: ## Go tests (with the race detector)
	cd backend && go test -race ./...

test-frontend: ## Frontend tests (vitest)
	cd frontend && npm test

lint: lint-backend lint-go lint-frontend ## Lint everything

lint-backend: ## Python lint + type-check (ruff + mypy)
	cd backend && ruff check . && mypy app tests

lint-go: ## Go format check + vet
	cd backend && test -z "$$(gofmt -l .)" && go vet ./...

lint-frontend: ## Frontend lint + type-check (eslint + tsc)
	cd frontend && npm run lint && npm run type-check

build: ## Build the Go server and the frontend bundle
	cd backend && go build ./...
	cd frontend && npm run build

proto: ## Regenerate protobuf stubs (Go + Python)
	cd proto && buf generate

check: lint test build ## Run everything CI runs (lint + test + build)

clean: ## Remove build artifacts
	rm -f backend/server
	rm -rf frontend/.next

.PHONY: help install install-backend install-frontend dev-python dev-go dev-frontend \
	test test-backend test-go test-frontend lint lint-backend lint-go lint-frontend \
	build proto check clean
