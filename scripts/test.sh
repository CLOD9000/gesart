#!/usr/bin/env bash
# Esegue la suite di test.
#
#   scripts/test.sh             -> in locale (serve PostgreSQL raggiungibile)
#   scripts/test.sh --docker    -> dentro Docker, sul database del compose
#
# Per i test in locale servono le variabili di connessione, ad esempio:
#   docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db
#   export GESART_TEST_DATABASE_URL=postgresql://gesart:<password>@localhost:5432/gesart_test
#
set -euo pipefail

cd "$(dirname "$0")/.."

if [ "${1:-}" = "--docker" ]; then
    shift
    exec docker compose --env-file stack.env --profile test run --rm test "$@"
fi

if [ ! -d .venv ]; then
    echo "Creo l'ambiente virtuale in .venv ..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements-dev.txt
fi

exec .venv/bin/python -m pytest tests/ "$@"
