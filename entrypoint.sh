#!/bin/sh
mkdir -p /app/media /app/staticfiles
python manage.py migrate --noinput
python manage.py create_superadmin
python manage.py collectstatic --noinput
exec "$@"
