#!/usr/bin/env bash
# Esegue la suite di test con un database temporaneo.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    echo "Creo l'ambiente virtuale in .venv ..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements-dev.txt
fi

exec .venv/bin/python -m pytest tests/ "$@"
