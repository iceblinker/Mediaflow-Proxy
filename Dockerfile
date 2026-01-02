# Stage 1: Builder
FROM python:3.13.5-slim as builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Configure poetry to create venv in project
RUN poetry config virtualenvs.in-project true

# Ensure lock file is up to date
RUN poetry lock

# Install dependencies
RUN poetry install --no-interaction --no-ansi --only main --no-root

# Stage 2: Runtime
FROM python:3.13.5-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8888 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 mediaflow

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY --chown=mediaflow:mediaflow . /app

# Switch to non-root user
USER mediaflow

EXPOSE 8888

# Run application
# Note: FORWARDED_ALLOW_IPS default is set to * for ease of use behind proxies, 
# can be overridden by env var.
CMD gunicorn mediaflow_proxy.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --timeout 120 --max-requests 500 --max-requests-jitter 200 --access-logfile - --error-logfile - --log-level info --forwarded-allow-ips '*'
