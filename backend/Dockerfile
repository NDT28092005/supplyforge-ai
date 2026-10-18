# SupplyForge AI — Backend & Celery Worker Container Image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    libmariadb-dev-compat \
    libmariadb-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# This Dockerfile is built from the repository root so the runtime image also
# contains the shared `src` package used by Django services.
# Install Python dependencies
COPY backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY backend/ /app/
COPY src/ /app/src/

# Do not run the application as root inside the container.
RUN addgroup --system supplyforge && \
    adduser --system --ingroup supplyforge supplyforge && \
    chown -R supplyforge:supplyforge /app
USER supplyforge

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=15s \
    CMD curl -f http://localhost:8080/health/live || exit 1

# Migrations are executed once by the release job, not by every web replica.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080", "--workers", "3", "--graceful-timeout", "30", "--timeout", "120", "--keep-alive", "5", "--max-requests", "1000", "--max-requests-jitter", "50", "--access-logfile", "-", "--error-logfile", "-"]
