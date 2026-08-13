.DEFAULT_GOAL := run

COVERAGE_THRESHOLD := 95

.PHONY: test test-backend test-frontend build up run down logs clean

# Runs both test suites with a hard coverage gate. Either failing (tests red,
# or coverage under $(COVERAGE_THRESHOLD)%) stops the chain before anything gets built.
test: test-backend test-frontend

test-backend:
	@echo "==> backend: pytest (coverage must be >= $(COVERAGE_THRESHOLD)%)"
	cd backend && uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=$(COVERAGE_THRESHOLD)

test-frontend:
	@echo "==> frontend: vitest (coverage must be >= $(COVERAGE_THRESHOLD)%)"
	cd frontend && npx vitest run --coverage \
		--coverage.thresholds.statements=$(COVERAGE_THRESHOLD) \
		--coverage.thresholds.branches=$(COVERAGE_THRESHOLD) \
		--coverage.thresholds.functions=$(COVERAGE_THRESHOLD) \
		--coverage.thresholds.lines=$(COVERAGE_THRESHOLD)

# Only builds once tests + coverage pass.
build: test
	docker compose build

# test -> build -> start db + migrate + backend + frontend.
# Frontend  -> http://localhost:5173
# Backend   -> http://localhost:8000
up: build
	docker compose up

run: up

down:
	docker compose down

logs:
	docker compose logs -f

# Stops everything AND deletes the Postgres data volume - use deliberately.
clean:
	docker compose down -v
