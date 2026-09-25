FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client mariadb-client && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini ./
RUN pip install --no-cache-dir .
RUN useradd --system --create-home --uid 10001 backupforge && mkdir -p /var/lib/backupforge && chown -R backupforge:backupforge /app /var/lib/backupforge
USER backupforge
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
