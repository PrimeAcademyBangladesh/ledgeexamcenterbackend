.PHONY: start down restart build logs logs-all ps shell db-shell migrate makemigrations superadmin collectstatic prune

# ── Docker ───────────────────────────────────────────────────

start:
	docker compose up -d --build

down:
	docker compose down

restart:
	docker compose down && docker compose up -d --build

build:
	docker compose build --no-cache

prune:
	docker compose down -v --remove-orphans

ps:
	docker compose ps

# ── Logs ─────────────────────────────────────────────────────

logs:
	docker compose logs -f web

logs-all:
	docker compose logs -f

logs-worker:
	docker compose logs -f celery_worker

# ── Django ───────────────────────────────────────────────────

migrate:
	docker compose exec web python manage.py migrate --noinput

makemigrations:
	docker compose exec web python manage.py makemigrations

superadmin:
	docker compose exec web python manage.py create_superadmin

collectstatic:
	docker compose exec web python manage.py collectstatic --noinput

# ── Shells ───────────────────────────────────────────────────

shell:
	docker compose exec web python manage.py shell

bash:
	docker compose exec web /bin/sh

db-shell:
	docker compose exec db psql -U $$POSTGRES_USER -d $$POSTGRES_DB

# ── Nuclear reset (server-side) ───────────────────────────────

reset-db:
	docker compose down
	sudo rm -rf /var/data/examcenterleadedge/postgres
	sudo rm -rf /var/data/examcenterleadedge/media
	sudo rm -rf /var/data/examcenterleadedge/staticfiles
	make start
