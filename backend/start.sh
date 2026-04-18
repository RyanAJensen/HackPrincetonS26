#!/bin/bash
set -e
cd "$(dirname "$0")"
source .env 2>/dev/null || true
venv/Scripts/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
