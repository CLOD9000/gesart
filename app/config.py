"""Configurazione dell'applicazione, letta dalle variabili d'ambiente.

Tutte le impostazioni hanno un default sensato cosi' che l'app si avvii anche
senza stack.env; i valori di stack.env (docker-compose) hanno la precedenza.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None else value.strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name, "").lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _env_path(name: str) -> Path | None:
    """Legge un percorso dall'ambiente; None se non impostato."""
    raw = _env(name, "")
    return Path(raw) if raw else None


def _env_int(name: str, default: int) -> int:
    raw = _env(name, "")
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # Percorsi locali (staging degli import)
    data_dir: Path = field(default_factory=lambda: Path(_env("GESART_DATA_DIR", "/data")))
    imports_dir: Path = field(default_factory=lambda: Path(_env("GESART_IMPORTS_DIR", "/imports")))
    templates_dir: Path | None = field(default_factory=lambda: _env_path("GESART_TEMPLATES_DIR"))
    static_dir: Path | None = field(default_factory=lambda: _env_path("GESART_STATIC_DIR"))

    # Database PostgreSQL
    database_url: str = field(default_factory=lambda: _env("GESART_DATABASE_URL"))
    db_host: str = field(default_factory=lambda: _env("GESART_DB_HOST", "localhost"))
    db_port: int = field(default_factory=lambda: _env_int("GESART_DB_PORT", 5432))
    # Fallback sulle variabili standard dell'immagine ufficiale postgres.
    db_name: str = field(
        default_factory=lambda: _env("GESART_DB_NAME") or _env("POSTGRES_DB", "gesart")
    )
    db_user: str = field(
        default_factory=lambda: _env("GESART_DB_USER") or _env("POSTGRES_USER", "gesart")
    )
    db_password: str = field(
        default_factory=lambda: _env("GESART_DB_PASSWORD")
        or _env("POSTGRES_PASSWORD", "gesart")
    )
    db_pool_min: int = field(default_factory=lambda: _env_int("GESART_DB_POOL_MIN", 1))
    db_pool_max: int = field(default_factory=lambda: _env_int("GESART_DB_POOL_MAX", 10))
    db_connect_timeout: int = field(default_factory=lambda: _env_int("GESART_DB_CONNECT_TIMEOUT", 30))

    # Utente PostgreSQL di sola lettura per gli applicativi esterni
    db_readonly_role: str = field(default_factory=lambda: _env("GESART_DB_READONLY_ROLE", "gesart_lettura"))
    db_readonly_password: str = field(default_factory=lambda: _env("GESART_DB_READONLY_PASSWORD", ""))

    # Server
    host: str = field(default_factory=lambda: _env("GESART_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("GESART_PORT", 9080))

    # Credenziali iniziali (seed utente admin al primo avvio)
    admin_username: str = field(default_factory=lambda: _env("GESART_ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: _env("GESART_ADMIN_PASSWORD", "admin"))
    admin_name: str = field(default_factory=lambda: _env("GESART_ADMIN_NAME", "Amministratore"))
    operator_username: str = field(default_factory=lambda: _env("GESART_OPERATOR_USER", "operatore"))
    operator_password: str = field(default_factory=lambda: _env("GESART_OPERATOR_PASSWORD", "operatore"))
    seed_demo_users: bool = field(default_factory=lambda: _env_bool("GESART_SEED_OPERATOR", True))

    # Sessioni
    session_cookie: str = field(default_factory=lambda: _env("GESART_SESSION_COOKIE", "gesart_session"))
    csrf_cookie: str = field(default_factory=lambda: _env("GESART_CSRF_COOKIE", "gesart_csrf"))
    session_ttl_hours: int = field(default_factory=lambda: _env_int("GESART_SESSION_TTL_HOURS", 12))
    secure_cookies: bool = field(default_factory=lambda: _env_bool("GESART_SECURE_COOKIES", False))

    # Import
    max_upload_mb: int = field(default_factory=lambda: _env_int("GESART_MAX_UPLOAD_MB", 64))
    staging_ttl_hours: int = field(default_factory=lambda: _env_int("GESART_STAGING_TTL_HOURS", 24))
    default_azienda: str = field(default_factory=lambda: _env("GESART_DEFAULT_AZIENDA", ""))

    def resolved_database_url(self) -> str:
        """URL di connessione: `GESART_DATABASE_URL` oppure composto dai singoli campi."""
        if self.database_url:
            return self.database_url
        user = quote(self.db_user, safe="")
        password = quote(self.db_password, safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.db_host}:{self.db_port}/{quote(self.db_name, safe='')}"
        )

    def database_descrizione(self) -> str:
        """Descrizione della connessione senza password (per i log)."""
        return f"{self.db_host}:{self.db_port}/{self.db_name} (utente {self.db_user})"

    def resolved_templates_dir(self) -> Path:
        if self.templates_dir:
            return self.templates_dir
        return Path(__file__).resolve().parent / "templates"

    def resolved_static_dir(self) -> Path:
        if self.static_dir:
            return self.static_dir
        return Path(__file__).resolve().parent / "static"

    @property
    def staging_dir(self) -> Path:
        return self.data_dir / "staging"


settings = Settings()
