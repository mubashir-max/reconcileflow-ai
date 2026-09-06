#!/bin/sh
set -eu

alembic upgrade head
exec uvicorn reconcileflow.api.app:app --host 0.0.0.0 --port 8000
