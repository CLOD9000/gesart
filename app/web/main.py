"""Applicazione FastAPI: creazione app, middleware, template e router."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import db
from ..config import settings
from ..security import ensure_utenti_iniziali, purge_expired_sessions

logger = logging.getLogger("gesart")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

templates = Jinja2Templates(directory=str(settings.resolved_templates_dir()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db()
    ensure_utenti_iniziali()
    purge_expired_sessions()
    logger.info("gesart pronto - database: %s", settings.resolved_db_path())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gesart - Gestionale Articoli",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
    )

    app.mount(
        "/static",
        StaticFiles(directory=str(settings.resolved_static_dir())),
        name="static",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Le pagine HTML reindirizzano al login; le API rispondono in JSON."""
        accetta = request.headers.get("accept", "")
        # I browser chiedono HTML; i client API chiedono JSON esplicitamente.
        accetta_html = "application/json" not in accetta and not request.url.path.startswith("/api")
        if exc.status_code == 401 and accetta_html:
            return RedirectResponse(url="/login", status_code=303)
        if accetta_html and exc.status_code == 403:
            return templates.TemplateResponse(
                request,
                "errore.html",
                {
                    "request": request,
                    "titolo": "Accesso non consentito",
                    "messaggio": str(exc.detail),
                },
                status_code=403,
            )
        if accetta_html:
            return templates.TemplateResponse(
                request,
                "errore.html",
                {
                    "request": request,
                    "titolo": f"Errore {exc.status_code}",
                    "messaggio": str(exc.detail),
                },
                status_code=exc.status_code,
            )
        return Response(
            content=f'{{"detail": "{exc.detail}"}}',
            status_code=exc.status_code,
            media_type="application/json",
        )

    from . import admin, articoli, auth, imports, viste

    app.include_router(auth.router)
    app.include_router(articoli.router)
    app.include_router(articoli.api_router)
    app.include_router(viste.router)
    app.include_router(imports.router)
    app.include_router(admin.router)

    @app.get("/", include_in_schema=False)
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/articoli", status_code=307)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"stato": "ok"}

    return app


app = create_app()
