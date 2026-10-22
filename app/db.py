"""Accesso al database SQLite.

Una sola connessione per processo (FastAPI con threadpool): SQLite in WAL mode
supporta letture concorrenti e scritture serializzate, il che e' piu' che
sufficiente per il carico atteso (migliaia di articoli, uso interno LAN).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .config import settings

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_local = threading.local()
_write_lock = threading.Lock()


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_conn() -> sqlite3.Connection:
    """Restituisce la connessione thread-local, creandola se necessaria."""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect(settings.resolved_db_path())
        _local.conn = conn
    return conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Contesto di scrittura atomica (con lock applicativo per evitare
    'database is locked' in caso di scritture concorrenti)."""
    conn = get_conn()
    with _write_lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def init_db() -> None:
    """Crea il database e applica lo schema (idempotente)."""
    conn = get_conn()
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def query_all(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> list[sqlite3.Row]:
    return list(get_conn().execute(sql, params).fetchall())


def query_one(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, params).fetchone()


def query_scalar(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> Any:
    row = query_one(sql, params)
    return row[0] if row is not None else None


def execute(sql: str, params: Sequence[Any] | dict[str, Any] = ()) -> sqlite3.Cursor:
    with transaction() as conn:
        return conn.execute(sql, params)


def executemany(sql: str, seq_params: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
    with transaction() as conn:
        return conn.executemany(sql, seq_params)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
