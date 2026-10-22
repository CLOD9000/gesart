"""Autenticazione, hashing password, sessioni e controllo dei ruoli.

Password: PBKDF2-HMAC-SHA256 (600.000 iterazioni) con salt casuale - algoritmo
raccomandato da OWASP, implementato con la sola libreria standard per non
richiedere compilatori nel container.
Sessioni: token casuale (32 byte) memorizzato nel DB, cookie HttpOnly.
CSRF: token per sessione, verificato su ogni POST.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from . import db
from .config import settings

PBKDF2_ALGO = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
PBKDF2_SALT_BYTES = 16


# ---------------------------------------------------------------------------
# Hashing password
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """Restituisce `pbkdf2_sha256$iterations$salt_hex$hash_hex`."""
    if not password:
        raise ValueError("Password non puo' essere vuota")
    salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{PBKDF2_ALGO}${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verifica a tempo costante la password rispetto all'hash salvato."""
    try:
        algo, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algo != PBKDF2_ALGO:
            return False
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(candidate, expected)


# ---------------------------------------------------------------------------
# Normalizzazione testo (ricerca senza accenti)
# ---------------------------------------------------------------------------
def normalize_text(value: str) -> str:
    """Maiuscole, rimozione accenti e spazi ridotti."""
    if not value:
        return ""
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", without_accents.upper()).strip()


def build_search_blob(*parts: str) -> str:
    return " | ".join(p for p in (normalize_text(x) for x in parts) if p)


# ---------------------------------------------------------------------------
# Utenti
# ---------------------------------------------------------------------------
def get_utente_by_username(username: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM utenti WHERE username = ?", (username,))
    return dict(row) if row else None


def create_utente(username: str, password: str, ruolo: str, nome: str = "") -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cur = db.execute(
        """INSERT INTO utenti (username, password_hash, nome, ruolo, attivo, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1, ?, ?)""",
        (username, hash_password(password), nome or username, ruolo, now, now),
    )
    return int(cur.lastrowid)


def ensure_utenti_iniziali() -> None:
    """Crea l'admin (e l'operatore) al primo avvio, se assenti.

    Le credenziali arrivano da variabili d'ambiente: se un utente esiste gia'
    non viene sovrascritto (l'admin puo' cambiare la password dall'interfaccia).
    """
    if not get_utente_by_username(settings.admin_username):
        create_utente(
            settings.admin_username,
            settings.admin_password,
            "admin",
            settings.admin_name,
        )
    if settings.seed_demo_users and not get_utente_by_username(settings.operator_username):
        create_utente(
            settings.operator_username,
            settings.operator_password,
            "operatore",
            "Operatore",
        )


# ---------------------------------------------------------------------------
# Sessioni
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(utente_id: int) -> tuple[str, str]:
    """Crea una sessione e restituisce (token, csrf_token)."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    expires = _now() + timedelta(hours=settings.session_ttl_hours)
    db.execute(
        """INSERT INTO sessioni (token, utente_id, csrf_token, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            token,
            utente_id,
            csrf_token,
            _now().strftime("%Y-%m-%d %H:%M:%S"),
            expires.strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return token, csrf_token


def load_session(token: str | None) -> dict[str, Any] | None:
    """Carica la sessione (e l'utente) se il token esiste e non e' scaduta."""
    if not token:
        return None
    row = db.query_one(
        """SELECT s.token, s.csrf_token, s.expires_at, u.id AS utente_id, u.username,
                  u.nome, u.ruolo, u.attivo
             FROM sessioni s JOIN utenti u ON u.id = s.utente_id
            WHERE s.token = ?""",
        (token,),
    )
    if row is None:
        return None
    try:
        expires = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    if expires < _now():
        delete_session(token)
        return None
    if not row["attivo"]:
        return None
    return dict(row)


def delete_session(token: str) -> None:
    db.execute("DELETE FROM sessioni WHERE token = ?", (token,))


def purge_expired_sessions() -> None:
    db.execute("DELETE FROM sessioni WHERE expires_at < ?", (_now().strftime("%Y-%m-%d %H:%M:%S"),))


# ---------------------------------------------------------------------------
# Dipendenze FastAPI
# ---------------------------------------------------------------------------
def current_session(request: Request) -> dict[str, Any] | None:
    """Sessione corrente (memoizzata per request)."""
    if not hasattr(request.state, "gesart_session"):
        token = request.cookies.get(settings.session_cookie)
        request.state.gesart_session = load_session(token)
    return request.state.gesart_session


def require_user(request: Request) -> dict[str, Any]:
    session = current_session(request)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticazione richiesta"
        )
    return session


def require_admin(request: Request) -> dict[str, Any]:
    session = require_user(request)
    if session["ruolo"] != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Permessi insufficienti"
        )
    return session


async def login_redirect(request: Request) -> RedirectResponse:
    """Dependency alternativa: reindirizza al login invece di rispondere 401."""
    session = current_session(request)
    if session is None:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url=request.url.path, status_code=303)


def verify_csrf(request: Request, form_token: str | None, header_token: str | None = None) -> None:
    """Verifica il token CSRF.

    Accetta il token dal form (`csrf_token`) o dall'header `X-CSRF-Token`
    (usato da htmx per le richieste non-GET).

    Se l'utente non e' ancora autenticato (pagina di login) il token atteso
    e' quello del cookie double-submit `gesart_csrf`.
    """
    session = current_session(request)
    provided = header_token or form_token or ""
    if session:
        expected = session.get("csrf_token") or ""
    else:
        expected = request.cookies.get(settings.csrf_cookie) or ""
    if not expected or not hmac.compare_digest(expected, provided):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Token CSRF non valido"
        )
