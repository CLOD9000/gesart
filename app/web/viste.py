"""Viste salvate: set di filtri memorizzati con un nome."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..security import require_user
from .helpers import check_csrf, filtri_da_form, filtri_in_query, render

router = APIRouter(prefix="/viste", tags=["viste"])


def _visibili(session: dict) -> list[dict[str, Any]]:
    righe = db.query_all(
        """SELECT * FROM viste
            WHERE ambito = 'condivisa' OR utente_id = %s
            ORDER BY nome""",
        (session["utente_id"],),
    )
    return [dict(r) for r in righe]


@router.get("")
async def lista_viste(request: Request, session: dict = Depends(require_user)):
    return render(
        request,
        "viste/lista.html",
        {"titolo": "Viste salvate", "viste": _visibili(session)},
    )


@router.post("/salva")
async def salva_vista(
    request: Request,
    nome: str = Form(...),
    ambito: str = Form("personale"),
    session: dict = Depends(require_user),
):
    await check_csrf(request)
    form = await request.form()
    filtri = filtri_da_form(form)
    ordinamento = str(form.get("ord") or "codice")
    direzione = str(form.get("dir") or "asc")
    dati = {
        "filtri": filtri,
        "ordinamento": ordinamento,
        "direzione": direzione,
    }
    if not nome.strip():
        return RedirectResponse(url="/viste", status_code=303)
    ambito_valido = "condivisa" if ambito == "condivisa" else "personale"
    esistente = db.query_one(
        "SELECT id FROM viste WHERE nome = %s AND ambito = %s AND utente_id IS NOT DISTINCT FROM %s",
        (nome.strip(), ambito_valido, session["utente_id"] if ambito_valido == "personale" else None),
    )
    payload = json.dumps(dati, ensure_ascii=False)
    if esistente:
        db.execute(
            "UPDATE viste SET filtri = %s, updated_at = to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS') WHERE id = %s",
            (payload, esistente["id"]),
        )
    else:
        db.execute(
            """INSERT INTO viste (nome, ambito, utente_id, filtri, created_at, updated_at)
               VALUES (%s, %s, %s, %s, to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'), to_char(NOW(), 'YYYY-MM-DD HH24:MI:SS'))""",
            (
                nome.strip(),
                ambito_valido,
                session["utente_id"] if ambito_valido == "personale" else None,
                payload,
            ),
        )
    return RedirectResponse(url="/viste", status_code=303)


@router.get("/applica/{vista_id}")
async def applica_vista(request: Request, vista_id: int, session: dict = Depends(require_user)):
    """Reindirizza all'elenco articoli con i filtri della vista salvata."""
    riga = db.query_one("SELECT * FROM viste WHERE id = %s", (vista_id,))
    if riga is None:
        return RedirectResponse(url="/articoli", status_code=303)
    if riga["ambito"] != "condivisa" and riga["utente_id"] != session["utente_id"]:
        return RedirectResponse(url="/articoli", status_code=303)
    try:
        dati = json.loads(riga["filtri"] or "{}")
    except json.JSONDecodeError:
        dati = {}
    filtri = dati.get("filtri", {}) if isinstance(dati, dict) else {}
    ordinamento = dati.get("ordinamento", "codice") if isinstance(dati, dict) else "codice"
    direzione = dati.get("direzione", "asc") if isinstance(dati, dict) else "asc"
    parametri = [("flt", filtri_in_query(filtri)), ("ord", ordinamento), ("dir", direzione)]
    query = "&".join(f"{k}={v}" for k, v in parametri if v)
    return RedirectResponse(url=f"/articoli%s{query}", status_code=303)


@router.post("/{vista_id}/elimina")
async def elimina_vista(request: Request, vista_id: int, session: dict = Depends(require_user)):
    await check_csrf(request)
    riga = db.query_one("SELECT * FROM viste WHERE id = %s", (vista_id,))
    if riga is not None:
        if riga["ambito"] == "condivisa":
            if session["ruolo"] != "admin":
                return RedirectResponse(url="/viste", status_code=303)
        elif riga["utente_id"] != session["utente_id"]:
            return RedirectResponse(url="/viste", status_code=303)
        db.execute("DELETE FROM viste WHERE id = %s", (vista_id,))
    return RedirectResponse(url="/viste", status_code=303)
