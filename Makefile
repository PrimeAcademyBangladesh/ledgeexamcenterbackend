.PHONY: up build start down restart logs logs-api logs-worker logs-beat shell migrate makemigrations \
        superuser setup-admin collectstatic check dbshell psql \
        test test-qualification test-pytest coverage lint bash clean resetdb rebuild

# ─────────────────────────────────────────────────────────
# Environment selector
# ─────────────────────────────────────────────────────────
# Auto-detected from the current directory name:
#   /var/www/leadedge/backend/dev        → ENV=dev
#   /var/www/leadedge/backend/production → ENV=production
#   anywhere else (e.g. local laptop)    → ENV=dev (fallback)
#
# Override anytime by passing it explicitly:
#   make ENV=production rebuild
# ─────────────────────────────────────────────────────────

DETECTED_ENV := $(notdir $(CURDIR))
ENV ?= $(if $(filter $(DETECTED_ENV),dev production),$(DETECTED_ENV),dev)

COMPOSE_FILE := docker-compose.$(ENV).yml
COMPOSE := docker compose -f $(COMPOSE_FILE)

# Print the resolved env on every run so you always see which stack you're hitting
$(info ▶ ENV=$(ENV)  COMPOSE_FILE=$(COMPOSE_FILE))

# ─────────────────────────────────────────────────────────
# Containers
# ─────────────────────────────────────────────────────────

up:
	$(COMPOSE) up -d

build:
	$(COMPOSE) build

start:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

rebuild:
	$(COMPOSE) down --remove-orphans && $(COMPOSE) up -d --build

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f api

logs-worker:
	$(COMPOSE) logs -f celery_worker

logs-beat:
	$(COMPOSE) logs -f celery_beat

test:
	$(COMPOSE) exec -T api python manage.py test


# ─────────────────────────────────────────────────────────
# Django Commands
# ─────────────────────────────────────────────────────────

shell:
	$(COMPOSE) exec api python manage.py shell

migrate:
	$(COMPOSE) exec -T api python manage.py migrate

makemigrations:
	$(COMPOSE) exec -T api python manage.py makemigrations

superuser:
	$(COMPOSE) exec api python manage.py createsuperuser

setup-admin:
	$(COMPOSE) exec -T api python manage.py create_superadmin

collectstatic:
	$(COMPOSE) exec -T api python manage.py collectstatic --noinput

check:
	$(COMPOSE) exec -T api python manage.py check

# ─────────────────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────────────────

dbshell:
	$(COMPOSE) exec api python manage.py dbshell

psql:
	$(COMPOSE) exec postgres psql -U $$POSTGRES_USER -d $$POSTGRES_DB

resetdb:
	@echo "⚠️  WARNING: This will DELETE ALL DATA in ENV=$(ENV)"
	@read -p "Type 'YES' to continue: " confirm && [ "$$confirm" = "YES" ] || exit 1
	$(COMPOSE) exec postgres psql -U $$POSTGRES_USER -c "DROP DATABASE IF EXISTS $$POSTGRES_DB;"
	$(COMPOSE) exec postgres psql -U $$POSTGRES_USER -c "CREATE DATABASE $$POSTGRES_DB;"

# ─────────────────────────────────────────────────────────
# Dev Tools (DO NOT USE IN PROD)
# ─────────────────────────────────────────────────────────

test-pytest:
	$(COMPOSE) exec api pytest

coverage:
	$(COMPOSE) exec api pytest --cov

lint:
	$(COMPOSE) exec api pylint .

bash:
	$(COMPOSE) exec api bash

# ─────────────────────────────────────────────────────────
# Cleanup (VERY DANGEROUS)
# ─────────────────────────────────────────────────────────

clean:
	@echo "⚠️  WARNING: This will REMOVE ALL CONTAINERS + VOLUMES in ENV=$(ENV)"
	@read -p "Type 'DELETE' to continue: " confirm && [ "$$confirm" = "DELETE" ] || exit 1
	$(COMPOSE) down -v
