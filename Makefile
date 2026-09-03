.PHONY: setup precommit-install precommit-run lint format typecheck test test-fast test-unit test-integration test-slow test-mysql migration-check ci backend scheduler dashboard docker-up docker-logs security

setup:
	python -m pip install --upgrade pip
	python -m pip install -r requirements/dev.txt

precommit-install:
	pre-commit install

precommit-run:
	pre-commit run --all-files

lint:
	ruff check backend dashboard scripts tests

format:
	ruff format backend dashboard scripts tests

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

ci: lint typecheck test

backend:
	uvicorn backend.app.main:app --reload

scheduler:
	python -m backend.app.scheduler.worker

docker-up:
	docker compose up -d --build

docker-logs:
	docker compose logs --tail=100 backend scheduler frontend

security:
	pip-audit -r requirements/backend.txt
	bandit -q -r backend scripts -x tests,venv
	semgrep scan --config p/security-audit --config p/python --error --metrics=off --exclude venv --exclude tests backend scripts
