#!/bin/sh
set -eu

if [ "${RECONCILEFLOW_RUN_MIGRATIONS:-true}" = "true" ]; then
    alembic upgrade head
fi

if [ "$#" -eq 0 ]; then
    set -- uvicorn reconcileflow.api.app:app --host 0.0.0.0 --port 8000
fi

exec "$@"
