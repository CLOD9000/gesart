#!/usr/bin/env bash
# Avvio locale di Gesart (senza Docker per l'app, ma con PostgreSQL).
#
#   scripts/dev.sh            -> server su http://localhost:9080 con reload
#   scripts/dev.sh 8080       -> su un'altra porta
#
# Il database puo' essere quello del compose, esposto in locale con:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
#
set -euo pipefail

cd "$(dirname "$0")/.."

PORT="${1:-9080}"

if [ ! -d .venv ]; then
    echo "Creo l'ambiente virtuale in .venv ..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements-dev.txt
fi

mkdir -p data imports

export GESART_DATA_DIR="${GESART_DATA_DIR:-$PWD/data}"
export GESART_IMPORTS_DIR="${GESART_IMPORTS_DIR:-$PWD/imports}"
export GESART_DB_HOST="${GESART_DB_HOST:-localhost}"
export GESART_DB_PORT="${GESART_DB_PORT:-5432}"
export GESART_DB_NAME="${GESART_DB_NAME:-gesart}"
export GESART_DB_USER="${GESART_DB_USER:-gesart}"
export GESART_DB_PASSWORD="${GESART_DB_PASSWORD:-gesart}"

echo "Gesart su http://localhost:${PORT}  (Ctrl+C per fermare)"
exec .venv/bin/python -m uvicorn app.web.main:app --host 127.0.0.1 --port "$PORT" --reload
