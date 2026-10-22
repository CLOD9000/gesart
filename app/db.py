"""Accesso al database PostgreSQL.

Il database vive in un container dedicato: l'applicazione si collega via rete
(hostname `db` in docker compose) tramite un pool di connessioni psycopg3.

Le righe sono restituite come dizionari (`psycopg.rows.dict_row`), cosi' il
codice applicativo puo' usare `riga["colonna"]` e `dict(riga)` come prima.
"""
from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import settings

logger = logging.getLogger("gesart.db")

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Pool di connessioni
# ---------------------------------------------------------------------------
def get_pool() -> ConnectionPool:
    """Restituisce (creandolo alla prima chiamata) il pool di connessioni."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                pool = ConnectionPool(
                    conninfo=settings.resolved_database_url(),
                    min_size=settings.db_pool_min,
                    max_size=settings.db_pool_max,
                    timeout=settings.db_connect_timeout,
                    kwargs={
                        "row_factory": dict_row,
                        "autocommit": True,
                        # Le query con numero variabile di parametri (IN (...))
                        # produrrebbero molte prepared statement distinte: si
                        # disattiva la preparazione automatica.
                        "prepare_threshold": None,
                    },
                    name="gesart",
                    open=False,
                )
                pool.open(wait=True, timeout=settings.db_connect_timeout)
                _pool = pool
    return _pool


def close_pool() -> None:
    """Chiude il pool (usato dallo shutdown e dai test)."""
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
            _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Contesto di scrittura atomica."""
    with get_pool().connection() as conn:
        with conn.transaction():
            yield conn


# ---------------------------------------------------------------------------
# Inizializzazione
# ---------------------------------------------------------------------------
def init_db() -> None:
    """Crea tabelle, viste e permessi di lettura (idempotente)."""
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with get_pool().connection() as conn:
        with conn.transaction():
            conn.execute(schema)
        _configura_accesso_lettura(conn)


def _configura_accesso_lettura(conn: psycopg.Connection) -> None:
    """Crea/aggiorna il ruolo di sola lettura e concede SELECT sulle viste.

    E' un'operazione best-effort: se l'utente applicativo non ha i privilegi
    necessari (es. PostgreSQL gestito) l'app funziona comunque e viene
    registrato un avviso nel log.
    """
    ruolo = settings.db_readonly_role
    if not ruolo:
        return
    try:
        with conn.transaction():
            esiste = conn.execute(
                "SELECT 1 FROM pg_roles WHERE rolname = %s", (ruolo,)
            ).fetchone()
            if not esiste and not settings.db_readonly_password:
                logger.info(
                    "Ruolo di sola lettura '%s' non creato: impostare "
                    "GESART_DB_READONLY_PASSWORD per abilitarlo.",
                    ruolo,
                )
                return
            if settings.db_readonly_password:
                azione = "ALTER" if esiste else "CREATE"
                conn.execute(
                    sql.SQL("{} ROLE {} WITH LOGIN PASSWORD {}").format(
                        sql.SQL(azione),
                        sql.Identifier(ruolo),
                        sql.Literal(settings.db_readonly_password),
                    )
                )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(settings.db_name), sql.Identifier(ruolo)
                )
            )
            conn.execute(
                sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                    sql.Identifier(ruolo)
                )
            )
            conn.execute(
                sql.SQL(
                    "GRANT SELECT ON v_articoli, v_articoli_listini, v_marche, v_listini TO {}"
                ).format(sql.Identifier(ruolo))
            )
    except psycopg.Error as exc:
        logger.warning(
            "Ruolo di sola lettura '%s' non configurato (%s). "
            "Crearlo manualmente o concedere i privilegi necessari.",
            ruolo,
            exc,
        )


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------
def _execute(cur: psycopg.Cursor, sql_text: str, params: Any) -> None:
    # Con params vuoti si usa il protocollo semplice: nessuna interpretazione
    # dei caratteri '%' presenti nel testo SQL.
    if params:
        cur.execute(sql_text, params)
    else:
        cur.execute(sql_text)


def query_all(
    sql_text: str, params: Sequence[Any] | dict[str, Any] = ()
) -> list[dict[str, Any]]:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            _execute(cur, sql_text, params)
            return cur.fetchall()


def query_one(
    sql_text: str, params: Sequence[Any] | dict[str, Any] = ()
) -> dict[str, Any] | None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            _execute(cur, sql_text, params)
            return cur.fetchone()


def query_scalar(
    sql_text: str, params: Sequence[Any] | dict[str, Any] = ()
) -> Any:
    row = query_one(sql_text, params)
    if row is None:
        return None
    return next(iter(row.values()), None)


def execute(
    sql_text: str, params: Sequence[Any] | dict[str, Any] = ()
) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            _execute(cur, sql_text, params)


def executemany(sql_text: str, seq_params: Iterable[Sequence[Any]]) -> None:
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql_text, list(seq_params))


def insert(sql_text: str, params: Sequence[Any] | dict[str, Any] = ()) -> int:
    """Esegue un INSERT ... RETURNING id e restituisce l'id generato."""
    row = query_one(sql_text, params)
    if row is None:
        raise RuntimeError("INSERT senza RETURNING id")
    return int(next(iter(row.values())))


def row_to_dict(row: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
