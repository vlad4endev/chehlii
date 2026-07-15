# casetop — команды локальной разработки (нативный запуск, без Docker).
# Требуется: Homebrew PostgreSQL 17 и Redis (brew services start postgresql@17 redis).

PG_BIN := /opt/homebrew/opt/postgresql@17/bin
VENV   := backend/.venv
PY     := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

.PHONY: help install db migrate seed run test lint fmt services reset-db

help:
	@echo "install   — venv + зависимости backend"
	@echo "services  — запустить postgres@17 и redis (brew)"
	@echo "db        — создать роль и базу casetop"
	@echo "migrate   — применить миграции (alembic upgrade head)"
	@echo "seed      — посеять демо-данные (админ, каталог, тексты бота)"
	@echo "run       — запустить backend (uvicorn, http://localhost:8000)"
	@echo "test      — pytest"
	@echo "lint      — ruff check + format --check"
	@echo "fmt       — ruff format"
	@echo "reset-db  — пересоздать базу с нуля (ОСТОРОЖНО: удаляет данные)"

install:
	cd backend && /opt/homebrew/bin/python3.12 -m venv .venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r backend/requirements.txt -r backend/requirements-dev.txt
	@echo "OK: зависимости установлены"

services:
	brew services start postgresql@17
	brew services start redis

db:
	$(PG_BIN)/psql -d postgres -tc "SELECT 1 FROM pg_roles WHERE rolname='casetop'" | grep -q 1 || \
		$(PG_BIN)/psql -d postgres -c "CREATE ROLE casetop LOGIN PASSWORD 'casetop';"
	$(PG_BIN)/psql -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='casetop'" | grep -q 1 || \
		$(PG_BIN)/createdb -O casetop casetop
	@echo "OK: роль и база casetop готовы"

migrate:
	cd backend && .venv/bin/alembic upgrade head

seed:
	cd backend && .venv/bin/python -m app.seed

run:
	cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

test:
	cd backend && .venv/bin/python -m pytest -q

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .

fmt:
	cd backend && .venv/bin/ruff format .

reset-db:
	$(PG_BIN)/dropdb --if-exists casetop
	$(PG_BIN)/createdb -O casetop casetop
	$(MAKE) migrate seed
