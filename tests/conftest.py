"""Configurazione dei test: database isolato in una directory temporanea."""
from __future__ import annotations

import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="gesart-test-")
os.environ["GESART_DATA_DIR"] = _TMP
os.environ["GESART_DB_PATH"] = os.path.join(_TMP, "test.sqlite3")
os.environ["GESART_IMPORTS_DIR"] = os.path.join(_TMP, "imports")
os.environ["GESART_ADMIN_USER"] = "admin"
os.environ["GESART_ADMIN_PASSWORD"] = "admin"
os.environ["GESART_OPERATOR_USER"] = "operatore"
os.environ["GESART_OPERATOR_PASSWORD"] = "operatore"
os.environ["GESART_STAGING_TTL_HOURS"] = "1"

import pytest  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def db_pulito():
    """Svuota le tabelle operative e restituisce la connessione."""
    from app import db

    db.init_db()
    for tabella in (
        "log_importazioni",
        "listini",
        "articoli",
        "marche",
        "campi_personalizzati",
        "viste",
        "sessioni",
        "utenti",
    ):
        db.execute(f"DELETE FROM {tabella}")
    db.execute("DELETE FROM sqlite_sequence")
    return db


@pytest.fixture()
def client(db_pulito):
    """Client HTTP con l'applicazione avviata su un database pulito."""
    from fastapi.testclient import TestClient

    from app.security import ensure_utenti_iniziali
    from app.web.main import app

    ensure_utenti_iniziali()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def login(client):
    """Client autenticato come admin."""

    def _login(username="admin", password="admin"):
        risposta = client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )
        assert risposta.status_code in (303, 401), risposta.text
        return risposta

    return _login
