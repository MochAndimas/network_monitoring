.PHONY: setup precommit-install precommit-run lint lint-staged format format-check dependency-check typecheck test test-fast test-unit test-integration test-slow test-mysql migration-check ci backend-check backend scheduler frontend-check docker-up docker-logs security security-dependencies security-bandit security-semgrep

setup:
	python -m pip install --upgrade pip
	python -m pip install -r requirements/dev.txt

precommit-install:
	pre-commit install

precommit-run:
	pre-commit run --all-files

lint:
	ruff check backend shared scripts tests

lint-staged:
	ruff check --select B,I,UP,SIM backend/app/services/auth backend/app/repositories/alert_repository.py backend/app/repositories/incident_repository.py

format:
	ruff format backend shared scripts tests

format-check:
	ruff format --check backend shared scripts tests

dependency-check:
	python -m pip check

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
	test "$$(alembic heads | grep -c '(head)' || true)" -eq 1
	alembic check

frontend-check:
	cd frontend && pnpm lint && pnpm typecheck && pnpm test && pnpm build

backend-check: dependency-check lint lint-staged format-check typecheck test

ci: backend-check frontend-check

backend:
	uvicorn backend.app.main:app --reload

scheduler:
	python -m backend.app.scheduler.worker

docker-up:
	docker compose up -d --build

docker-logs:
	docker compose logs --tail=100 backend scheduler frontend

security: security-dependencies security-bandit security-semgrep

security-dependencies:
	pip-audit -r requirements/backend.txt

security-bandit:
	bandit -q -r backend scripts -x tests,venv

security-semgrep:
	semgrep scan --config p/security-audit --config p/python --error --metrics=off --exclude venv --exclude tests backend shared scripts
