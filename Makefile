.PHONY: up build start down restart logs shell migrate makemigrations \
        superuser setup-admin collectstatic check dbshell psql \
        test test-qualification test-pytest coverage lint bash clean resetdb rebuild

# ─────────────────────────────────────────────────────────
# Containers
# ─────────────────────────────────────────────────────────

up:
	docker compose up -d

build:
	docker compose build

start:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose restart

rebuild:
	docker compose down && docker compose up -d --build

logs:
	docker compose logs -f

test:
	docker compose exec -T api python manage.py test


# ─────────────────────────────────────────────────────────
# Django Commands
# ─────────────────────────────────────────────────────────

shell:
	docker compose exec api python manage.py shell

migrate:
	docker compose exec -T api python manage.py migrate

makemigrations:
	docker compose exec -T api python manage.py makemigrations

superuser:
	docker compose exec api python manage.py createsuperuser

setup-admin:
	docker compose exec -T api python manage.py create_superadmin

collectstatic:
	docker compose exec -T api python manage.py collectstatic --noinput

check:
	docker compose exec -T api python manage.py check

# ─────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────

dbshell:
	docker compose exec api python manage.py dbshell

psql:
	docker compose exec postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB

resetdb:
	@echo "⚠️  WARNING: This will DELETE ALL DATA"
	@read -p "Type 'YES' to continue: " confirm && [ "$$confirm" = "YES" ] || exit 1
	docker compose exec postgres psql -U $$POSTGRES_USER -c "DROP DATABASE IF EXISTS $$POSTGRES_DB;"
	docker compose exec postgres psql -U $$POSTGRES_USER -c "CREATE DATABASE $$POSTGRES_DB;"

# ─────────────────────────────────────────────────────────
# Dev Tools (DO NOT USE IN PROD)
# ─────────────────────────────────────────────────────────

test-pytest:
	docker compose exec api pytest

coverage:
	docker compose exec api pytest --cov

lint:
	docker compose exec api pylint .

bash:
	docker compose exec api bash

# ─────────────────────────────────────────────────────────
# Cleanup (VERY DANGEROUS)
# ─────────────────────────────────────────────────────────

clean:
	@echo "⚠️  WARNING: This will REMOVE ALL CONTAINERS + VOLUMES"
	@read -p "Type 'DELETE' to continue: " confirm && [ "$$confirm" = "DELETE" ] || exit 1
	docker compose down -v
