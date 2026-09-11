FROM python:3.14-slim

LABEL org.opencontainers.image.title="ReconcileFlow AI" \
      org.opencontainers.image.version="0.4.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system reconcileflow && useradd --system --gid reconcileflow reconcileflow

COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY docker/entrypoint.sh ./docker/entrypoint.sh

RUN pip install --no-cache-dir . \
    && sed -i 's/\r$//' ./docker/entrypoint.sh \
    && chmod +x ./docker/entrypoint.sh \
    && mkdir -p /app/var/uploads \
    && chown -R reconcileflow:reconcileflow /app

USER reconcileflow

EXPOSE 8000

ENTRYPOINT ["./docker/entrypoint.sh"]
