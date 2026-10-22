"""Configurazione dei test: database PostgreSQL di test isolato.

La suite usa un database dedicato (`gesart_test` per default) e svuota le
tabelle all'inizio di ogni test. Se PostgreSQL non e' raggiungibile i test che
richiedono il database vengono saltati: restano eseguibili i test di parsing.

Variabili:
- `GESART_TEST_DATABASE_URL`: URL completo del database di test
  (default: `postgresql://<utente>:<password>@<host>:<porta>/gesart_test`)
- in alternativa `GESART_DB_HOST`, `GESART_DB_PORT`, `GESART_DB_USER`,
  `GESART_DB_PASSWORD` (o i corrispondenti `POSTGRES_*`).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from urllib.parse import quote

_TMP = tempfile.mkdtemp(prefix="gesart-test-")
os.environ["GESART_DATA_DIR"] = _TMP
os.environ["GESART_IMPORTS_DIR"] = os.path.join(_TMP, "imports")
os.environ["GESART_ADMIN_USER"] = "admin"
os.environ["GESART_ADMIN_PASSWORD"] = "admin"
os.environ["GESART_OPERATOR_USER"] = "operatore"
os.environ["GESART_OPERATOR_PASSWORD"] = "operatore"
os.environ["GESART_STAGING_TTL_HOURS"] = "1"
# Nei test non serve il ruolo di sola lettura.
os.environ["GESART_DB_READONLY_ROLE"] = ""


def _url_database_test() -> str:
    if os.environ.get("GESART_TEST_DATABASE_URL"):
        return os.environ["GESART_TEST_DATABASE_URL"]
    utente = os.environ.get("GESART_DB_USER") or os.environ.get("POSTGRES_USER", "gesart")
    password = os.environ.get("GESART_DB_PASSWORD") or os.environ.get("POSTGRES_PASSWORD", "gesart")
    host = os.environ.get("GESART_DB_HOST", "localhost")
    porta = os.environ.get("GESART_DB_PORT", "5432")
    nome = os.environ.get("GESART_TEST_DB_NAME", "gesart_test")
    return (
        f"postgresql://{quote(utente, safe='')}:{quote(password, safe='')}"
        f"@{host}:{porta}/{quote(nome, safe='')}"
    )


_TEST_DATABASE_URL = _url_database_test()
os.environ["GESART_DATABASE_URL"] = _TEST_DATABASE_URL

import pytest  # noqa: E402


def _apri_database(url: str):
    import psycopg

    return psycopg.connect(url, connect_timeout=3, autocommit=True)


def _assicura_database_test() -> bool:
    """Verifica il database di test, creandolo se manca. False se non c'e' DB."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    try:
        with _apri_database(_TEST_DATABASE_URL):
            return True
    except psycopg.OperationalError:
        pass
    except Exception:
        return False

    # Il database non esiste (o non e' raggiungibile): proviamo a crearlo.
    try:
        info = conninfo_to_dict(_TEST_DATABASE_URL)
        nome = info.get("dbname", "gesart_test")
        info["dbname"] = "postgres"
        with _apri_database(make_conninfo(**info)) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nome)))
    except Exception:
        return False

    try:
        with _apri_database(_TEST_DATABASE_URL):
            return True
    except Exception:
        return False


_DATABASE_DISPONIBILE = _assicura_database_test()

_TABELLE = (
    "log_importazioni",
    "mappe_importazione",
    "impostazioni",
    "viste",
    "sessioni",
    "listini",
    "articoli",
    "marche",
    "campi_personalizzati",
    "utenti",
)


def pytest_collection_modifyitems(config, items):
    if _DATABASE_DISPONIBILE:
        return
    motivo = (
        "PostgreSQL di test non raggiungibile "
        f"({_TEST_DATABASE_URL}). Avvia il container `db` o imposta "
        "GESART_TEST_DATABASE_URL."
    )
    skip = pytest.mark.skip(reason=motivo)
    for item in items:
        if item.path.name != "test_parsing.py":
            item.add_marker(skip)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture()
def db_pulito():
    """Svuota le tabelle operative e restituisce il modulo db."""
    from app import db

    if not _DATABASE_DISPONIBILE:
        pytest.skip("PostgreSQL di test non raggiungibile")
    db.init_db()
    db.execute(
        "TRUNCATE " + ", ".join(_TABELLE) + " RESTART IDENTITY CASCADE"
    )
    return db


@pytest.fixture()
def client(db_pulito):
    """Client HTTP con l'applicazione avviata su un database pulito."""
    from fastapi.testclient import TestClient

    from app.web.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture()
def login(client):
    """Client autenticato come admin."""

    def _login(username="admin", password="admin"):
        import re

        pagina = client.get("/login")
        m = re.search(r'name="csrf_token" value="([^"]+)"', pagina.text)
        assert m, "token CSRF non trovato"
        risposta = client.post(
            "/login",
            data={
                "username": username,
                "password": password,
                "csrf_token": m.group(1),
            },
            follow_redirects=False,
        )
        assert risposta.status_code in (303, 401), risposta.text
        return risposta

    return _login
