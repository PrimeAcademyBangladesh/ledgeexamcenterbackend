FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies
RUN apt-get update \
    && apt-get install -y \
        gcc \
        libpq-dev \
        libmagic1 \
        libmagic-dev \
        netcat-openbsd \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN addgroup --system app && adduser --system --ingroup app app

# Install Python dependencies
COPY requirements*.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install -r requirements-prod.txt

# Copy project
COPY --chown=app:app . .

# Copy entrypoint
COPY --chown=app:app docker/django/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create static/media dirs with correct ownership
RUN mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app/staticfiles /app/media

# Switch user
USER app

# Healthcheck
HEALTHCHECK CMD curl --fail http://localhost:8000/ || exit 1

ENTRYPOINT ["/entrypoint.sh"]

CMD ["gunicorn", "examinationleadedge.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120"]