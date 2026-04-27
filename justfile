set dotenv-load := true

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
  ruff check backend dashboard scripts tests

format:
  ruff format backend dashboard scripts tests

typecheck:
  mypy --config-file mypy.ini
  pyright

test:
  pytest -q

ci:
  just lint
  just typecheck
  just test

backend:
  uvicorn backend.app.main:app --reload

scheduler:
  python -m backend.app.scheduler.worker

dashboard:
  streamlit run dashboard/Overview.py

docker-up:
  docker compose up -d --build

docker-logs:
  docker compose logs --tail=100 backend scheduler dashboard

security:
  pip-audit -r requirements/backend.txt
  pip-audit -r requirements/dashboard.txt
  bandit -q -r backend scripts -x tests,venv
  semgrep scan --config p/security-audit --config p/python --error --metrics=off --exclude venv --exclude tests backend scripts dashboard
