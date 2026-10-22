"""Login, logout e gestione sessioni."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import security
from ..config import settings
from .helpers import check_csrf, render

router = APIRouter()


def _token_csrf_anonimo(request: Request) -> str:
    """Token CSRF per gli utenti non ancora autenticati (double-submit cookie)."""
    token = request.cookies.get(settings.csrf_cookie)
    if not token:
        token = secrets.token_urlsafe(24)
    return token


@router.get("/login")
async def login_form(request: Request):
    if security.current_session(request):
        return RedirectResponse(url="/articoli", status_code=303)
    token = _token_csrf_anonimo(request)
    risposta = render(
        request, "auth/login.html", {"titolo": "Accesso", "csrf_token": token}
    )
    risposta.set_cookie(
        settings.csrf_cookie,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )
    return risposta


@router.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    await check_csrf(request)
    utente = security.get_utente_by_username(username.strip())
    if utente and utente["attivo"] and security.verify_password(password, utente["password_hash"]):
        token, csrf = security.create_session(utente["id"])
        risposta = RedirectResponse(url="/articoli", status_code=303)
        risposta.set_cookie(
            settings.session_cookie,
            token,
            httponly=True,
            samesite="lax",
            secure=settings.secure_cookies,
            max_age=settings.session_ttl_hours * 3600,
            path="/",
        )
        # Il cookie CSRF anonimo non serve piu': si rimuove.
        risposta.delete_cookie(settings.csrf_cookie, path="/")
        return risposta
    token = _token_csrf_anonimo(request)
    risposta = render(
        request,
        "auth/login.html",
        {
            "titolo": "Accesso",
            "errore": "Credenziali non valide.",
            "username": username,
            "csrf_token": token,
        },
        status_code=401,
    )
    risposta.set_cookie(
        settings.csrf_cookie,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )
    return risposta


@router.post("/logout")
async def logout(request: Request):
    await check_csrf(request)
    session = security.current_session(request)
    if session:
        security.delete_session(session["token"])
    risposta = RedirectResponse(url="/login", status_code=303)
    risposta.delete_cookie(settings.session_cookie, path="/")
    return risposta
