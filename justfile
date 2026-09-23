# Application commands load their own configuration; quality gates must not
# inject an operator's .env (especially DATABASE_URL) into the test process.
set dotenv-load := false

default:
  @just --list

setup:
  python -m pip install --upgrade pip
  python -m pip install -r requirements/dev.txt

precommit-install:
  pre-commit install

precommit-run:
  pre-commit run --all-files

lint:
  make lint

lint-staged:
  make lint-staged

format:
  ruff format backend shared scripts tests

format-check:
  make format-check

dependency-check:
  make dependency-check

typecheck:
  mypy --config-file mypy.ini
  pyright

test:
  pytest -q

test-fast:
  pytest -q -m "not slow and not mysql"

test-unit:
  pytest -q -m unit

test-integration:
  pytest -q -m "integration and not mysql"

test-slow:
  pytest -q -m slow

test-mysql:
  pytest -q -m mysql

migration-check:
  test "$(alembic heads | grep -c '(head)' || true)" -eq 1
  alembic check

frontend-check:
  make frontend-check

backend-check:
  make backend-check

ci:
  make ci

backend:
  uvicorn backend.app.main:app --reload

scheduler:
  python -m backend.app.scheduler.worker

docker-up:
  docker compose up -d --build

docker-logs:
  docker compose logs --tail=100 backend scheduler frontend

security:
  make security

security-dependencies:
  make security-dependencies

security-bandit:
  make security-bandit

security-semgrep:
  make security-semgrep
