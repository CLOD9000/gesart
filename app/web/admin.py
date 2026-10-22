"""Area amministrazione: campi personalizzati, utenti, import da cartella."""
from __future__ import annotations

import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..importers.mapping import TIPI_CAMPO
from ..security import hash_password, require_admin
from .helpers import check_csrf, render

router = APIRouter(prefix="/admin", tags=["admin"])


def _slug(testo: str) -> str:
    """Converte un'etichetta in una chiave stabile (usata nel JSON)."""
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", testo.strip().lower()).strip("_")
    return base or "campo"


def _slug_univo(candidato: str, escludi_id: int | None = None) -> str:
    slug = _slug(candidato)
    i = 2
    while True:
        query = "SELECT id FROM campi_personalizzati WHERE chiave = ?"
        params: list[Any] = [slug]
        if escludi_id:
            query += " AND id <> ?"
            params.append(escludi_id)
        if db.query_one(query, params) is None:
            return slug
        slug = f"{_slug(candidato)}_{i}"
        i += 1


# ---------------------------------------------------------------------------
# Campi personalizzati
# ---------------------------------------------------------------------------
@router.get("/campi")
async def lista_campi(request: Request, session: dict = Depends(require_admin)):
    from ..importers.service import carica_campi_personalizzati

    campi = carica_campi_personalizzati(solo_attivi=False)
    return render(
        request,
        "admin/campi.html",
        {"titolo": "Campi personalizzati", "campi": campi, "tipi": TIPI_CAMPO},
    )


@router.post("/campi")
async def crea_campo(request: Request, session: dict = Depends(require_admin)):
    await check_csrf(request)
    form = await request.form()
    etichetta = str(form.get("etichetta") or "").strip()
    tipo = str(form.get("tipo") or "testo")
    if etichetta and tipo in TIPI_CAMPO:
        opzioni = _estrai_opzioni(form)
        db.execute(
            """INSERT INTO campi_personalizzati
                 (chiave, etichetta, tipo, opzioni, obbligatorio, ordine, attivo,
                  created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
            (
                _slug_univo(etichetta),
                etichetta,
                tipo,
                json.dumps(opzioni, ensure_ascii=False),
                1 if form.get("obbligatorio") else 0,
                int(form.get("ordine") or 0),
            ),
        )
    return RedirectResponse(url="/admin/campi", status_code=303)


def _estrai_opzioni(form) -> list[str]:
    raw = str(form.get("opzioni") or "").strip()
    if not raw:
        return []
    return [opzione.strip() for opzione in raw.split("\n") if opzione.strip()]


@router.post("/campi/{campo_id}")
async def aggiorna_campo(request: Request, campo_id: int, session: dict = Depends(require_admin)):
    await check_csrf(request)
    form = await request.form()
    etichetta = str(form.get("etichetta") or "").strip()
    tipo = str(form.get("tipo") or "testo")
    riga = db.query_one("SELECT * FROM campi_personalizzati WHERE id = ?", (campo_id,))
    if riga is not None and etichetta and tipo in TIPI_CAMPO:
        # La chiave (slug) non viene cambiata: i dati gia' salvati restano
        # validi anche se l'etichetta viene rinominata.
        db.execute(
            """UPDATE campi_personalizzati
                  SET etichetta = ?, tipo = ?, opzioni = ?, obbligatorio = ?, ordine = ?,
                      attivo = ?, updated_at = datetime('now')
                WHERE id = ?""",
            (
                etichetta,
                tipo,
                json.dumps(_estrai_opzioni(form), ensure_ascii=False),
                1 if form.get("obbligatorio") else 0,
                int(form.get("ordine") or 0),
                0 if form.get("disattivato") else 1,
                campo_id,
            ),
        )
    return RedirectResponse(url="/admin/campi", status_code=303)


@router.post("/campi/{campo_id}/elimina")
async def elimina_campo(request: Request, campo_id: int, session: dict = Depends(require_admin)):
    await check_csrf(request)
    riga = db.query_one("SELECT chiave FROM campi_personalizzati WHERE id = ?", (campo_id,))
    if riga is not None:
        db.execute("DELETE FROM campi_personalizzati WHERE id = ?", (campo_id,))
        # Rimuove il valore da tutti gli articoli, ma NON i campi_extra.
        db.execute(
            "UPDATE articoli SET campi_personalizzati = json_remove(campi_personalizzati, ?)",
            (f'$."{riga["chiave"]}"',),
        )
    return RedirectResponse(url="/admin/campi", status_code=303)


# ---------------------------------------------------------------------------
# Utenti
# ---------------------------------------------------------------------------
@router.get("/utenti")
async def lista_utenti(request: Request, session: dict = Depends(require_admin)):
    utenti = [dict(r) for r in db.query_all("SELECT * FROM utenti ORDER BY username")]
    return render(request, "admin/utenti.html", {"titolo": "Utenti", "utenti": utenti})


@router.post("/utenti")
async def crea_utente(request: Request, session: dict = Depends(require_admin)):
    await check_csrf(request)
    form = await request.form()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    ruolo = str(form.get("ruolo") or "operatore")
    nome = str(form.get("nome") or "").strip()
    if username and password and ruolo in ("admin", "operatore"):
        esistente = db.query_one("SELECT id FROM utenti WHERE username = ?", (username,))
        if esistente is None:
            db.execute(
                """INSERT INTO utenti (username, password_hash, nome, ruolo, attivo,
                                      created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, datetime('now'), datetime('now'))""",
                (username, hash_password(password), nome or username, ruolo),
            )
    return RedirectResponse(url="/admin/utenti", status_code=303)


@router.post("/utenti/{utente_id}/password")
async def cambia_password(
    request: Request, utente_id: int, session: dict = Depends(require_admin)
):
    await check_csrf(request)
    form = await request.form()
    password = str(form.get("password") or "")
    if password:
        db.execute(
            "UPDATE utenti SET password_hash = ?, updated_at = datetime('now') WHERE id = ?",
            (hash_password(password), utente_id),
        )
    return RedirectResponse(url="/admin/utenti", status_code=303)


@router.post("/utenti/{utente_id}/attivo")
async def cambia_attivo(
    request: Request, utente_id: int, session: dict = Depends(require_admin)
):
    await check_csrf(request)
    riga = db.query_one("SELECT attivo FROM utenti WHERE id = ?", (utente_id,))
    if riga is not None:
        db.execute(
            "UPDATE utenti SET attivo = ?, updated_at = datetime('now') WHERE id = ?",
            (0 if riga["attivo"] else 1, utente_id),
        )
    return RedirectResponse(url="/admin/utenti", status_code=303)
