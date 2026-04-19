#!/bin/sh
set -eu

cd /app/backend

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"
