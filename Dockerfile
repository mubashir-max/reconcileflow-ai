FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system reconcileflow && useradd --system --gid reconcileflow reconcileflow

COPY pyproject.toml README.md alembic.ini ./
COPY backend ./backend
COPY docker/entrypoint.sh ./docker/entrypoint.sh

RUN pip install --no-cache-dir . \
    && chmod +x ./docker/entrypoint.sh \
    && mkdir -p /app/var/uploads \
    && chown -R reconcileflow:reconcileflow /app

USER reconcileflow

EXPOSE 8000

ENTRYPOINT ["./docker/entrypoint.sh"]
