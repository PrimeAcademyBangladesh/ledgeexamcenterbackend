#!/bin/sh

set -e

echo "Waiting for PostgreSQL..."
until nc -z postgres 5432; do
  echo "Postgres not ready..."
  sleep 1
done
echo "PostgreSQL ready"

echo "Waiting for Redis..."
until nc -z redis 6379; do
  echo "Redis not ready..."
  sleep 1
done
echo "Redis ready"

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "Running migrations..."
  python manage.py migrate --noinput

  echo "Setting up admin..."
  python manage.py create_superadmin
fi

if [ "$1" = "gunicorn" ]; then
  # Ignore externally injected Gunicorn control-socket args that target /app.
  unset GUNICORN_CMD_ARGS
  echo "Collecting static..."
  python manage.py collectstatic --noinput
fi

if [ "$#" -eq 0 ]; then
  set -- gunicorn examinationleadedge.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
fi

echo "Starting service: $1"
exec "$@"
