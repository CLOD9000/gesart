"""Gestione articoli: elenco filtrabile, CRUD, viste salvate ed export."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from .. import db, exporters
from ..importers.mapping import TIPO_LISTA, TIPO_NUMERO
from ..query import (
    ORDINAMENTI,
    carica_articoli,
    carica_tutti_articoli,
    colonne_disponibili,
    listino_effettivo,
)
from ..security import require_user
from .helpers import (
    campo_di_filtro,
    check_csrf,
    filtri_da_query,
    filtri_in_query,
    parametri_paginazione,
    parse_filtri_form,
    render,
    valori_dropdown,
)

router = APIRouter(prefix="/articoli", tags=["articoli"])
api_router = APIRouter(prefix="/api", tags=["api"])


# ---------------------------------------------------------------------------
# Elenco
# ---------------------------------------------------------------------------
@router.get("")
async def lista_articoli(request: Request, session: dict = Depends(require_user)):
    filtri = filtri_da_query(request)
    paginazione = parametri_paginazione(request)
    from ..importers.service import carica_campi_personalizzati

    campi_custom = carica_campi_personalizzati()
    risultato = carica_articoli(
        filtri=filtri,
        ordinamento=paginazione["ordinamento"],
        direzione=paginazione["direzione"],
        pagina=paginazione["pagina"],
        per_pagina=paginazione["per_pagina"],
        campi_custom=campi_custom,
        listino=paginazione["listino"],
    )
    return render(
        request,
        "articoli/lista.html",
        {
            "titolo": "Articoli",
            "risultato": risultato,
            "filtri": filtri,
            "filtri_json": filtri_in_query(filtri),
            "paginazione": paginazione,
            "colonne": colonne_disponibili(campi_custom),
            "dropdown": valori_dropdown(),
            "ordinamenti": ORDINAMENTI,
            "filtri_viste": _carica_viste(session),
            "campi_custom": campi_custom,
        },
    )


@router.get("/tabella")
async def tabella_articoli(request: Request, session: dict = Depends(require_user)):
    """Partial HTML della tabella (usato da htmx)."""
    from ..importers.service import carica_campi_personalizzati

    filtri = filtri_da_query(request)
    paginazione = parametri_paginazione(request)
    campi_custom = carica_campi_personalizzati()
    risultato = carica_articoli(
        filtri=filtri,
        ordinamento=paginazione["ordinamento"],
        direzione=paginazione["direzione"],
        pagina=paginazione["pagina"],
        per_pagina=paginazione["per_pagina"],
        campi_custom=campi_custom,
        listino=paginazione["listino"],
    )
    return render(
        request,
        "articoli/_tabella.html",
        {
            "risultato": risultato,
            "filtri": filtri,
            "filtri_json": filtri_in_query(filtri),
            "paginazione": paginazione,
            "colonne": colonne_disponibili(campi_custom),
            "campi_custom": campi_custom,
            "e_admin": session["ruolo"] == "admin",
        },
    )


@api_router.get("/opzioni")
async def api_opzioni(request: Request, session: dict = Depends(require_user)):
    """Valori dropdown per i filtri (marche, listini, aziende)."""
    return valori_dropdown()


def _carica_viste(session: dict) -> list[dict[str, Any]]:
    from .. import db as _db

    righe = _db.query_all(
        """SELECT * FROM viste
            WHERE (ambito = 'condivisa') OR (utente_id = ?)
            ORDER BY nome""",
        (session["utente_id"],),
    )
    return [dict(r) for r in righe]


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@router.get("/esporta")
async def esporta(request: Request, session: dict = Depends(require_user)):
    from ..importers.service import carica_campi_personalizzati

    formato = request.query_params.get("formato", "semplice")
    tipo = request.query_params.get("tipo", "articoli")
    filtri = filtri_da_query(request)
    paginazione = parametri_paginazione(request)
    campi_custom = carica_campi_personalizzati()

    if tipo == "marche":
        righe = [
            dict(r)
            for r in db.query_all("SELECT codice, descrizione, azienda FROM marche ORDER BY codice")
        ]
        nome_file = "marche.csv"
    elif tipo == "listini":
        righe = [
            dict(r)
            for r in db.query_all(
                """SELECT codice_articolo, azienda, nome_listino, prezzo, prezzo_iva,
                          data_validita, campi_extra
                     FROM listini ORDER BY codice_articolo, nome_listino"""
            )
        ]
        for riga in righe:
            try:
                riga["campi_extra"] = json.loads(riga["campi_extra"] or "{}")
            except json.JSONDecodeError:
                riga["campi_extra"] = {}
            riga["codice"] = riga["codice_articolo"]
        nome_file = "listini.csv"
    else:
        righe = carica_tutti_articoli(
            filtri=filtri,
            ordinamento=paginazione["ordinamento"],
            direzione=paginazione["direzione"],
            campi_custom=campi_custom,
            listino=paginazione["listino"],
        )
        nome_file = "articoli.csv"

    if formato == "cosmo":
        contenuto = exporters.esporta_cosmo(righe, tipo, listino=paginazione["listino"])
        media_type = "text/csv; charset=utf-8"
    else:
        colonne = request.query_params.get("colonne", "")
        if colonne:
            selezionate = [c for c in colonne.split(",") if c]
        else:
            selezionate = ["codice", "descrizione", "unita_misura", "barcode", "azienda",
                           "codice_marca", "prezzo", "nome_listino"]
        intestazioni = {
            "codice": "Codice",
            "descrizione": "Descrizione",
            "unita_misura": "Unita' di misura",
            "barcode": "Barcode",
            "azienda": "Azienda",
            "codice_marca": "Codice marca",
            "prezzo": "Prezzo",
            "nome_listino": "Listino",
            "prezzo_iva": "Prezzo secondario",
            "data_validita": "Data validita'",
            "codice_articolo": "Codice articolo",
        }
        contenuto = exporters.esporta_semplice(righe, selezionate, intestazioni)
        media_type = "text/csv; charset=utf-8"

    # BOM UTF-8 per Excel
    return Response(
        content="﻿" + contenuto,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nome_file}"'},
    )


@router.get("/esporta/campi")
async def esporta_campi(request: Request, session: dict = Depends(require_user)):
    from ..importers.service import carica_campi_personalizzati

    campi_custom = carica_campi_personalizzati()
    filtri = filtri_da_query(request)
    paginazione = parametri_paginazione(request)
    righe = carica_tutti_articoli(
        filtri=filtri,
        ordinamento=paginazione["ordinamento"],
        direzione=paginazione["direzione"],
        campi_custom=campi_custom,
        listino=paginazione["listino"],
    )
    contenuto = exporters.esporta_campi_personalizzati(righe, campi_custom)
    return Response(
        content="﻿" + contenuto,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="articoli_campi.csv"'},
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def _marche_disponibili() -> list[dict[str, Any]]:
    return [dict(r) for r in db.query_all("SELECT codice, descrizione FROM marche ORDER BY codice")]


def _listini_disponibili() -> list[str]:
    return [
        r["nome_listino"]
        for r in db.query_all("SELECT DISTINCT nome_listino FROM listini ORDER BY nome_listino")
    ]


@router.get("/nuovo")
async def nuovo_articolo(request: Request, session: dict = Depends(require_user)):
    from ..importers.service import carica_campi_personalizzati

    return render(
        request,
        "articoli/form.html",
        {
            "titolo": "Nuovo articolo",
            "articolo": {},
            "azioni": "crea",
            "marche": _marche_disponibili(),
            "listini": _listini_disponibili(),
            "campi_custom": carica_campi_personalizzati(),
            "valori_custom": {},
        },
    )


@router.get("/{articolo_id}")
async def modifica_articolo(
    request: Request, articolo_id: int, session: dict = Depends(require_user)
):
    from ..importers.service import carica_campi_personalizzati

    riga = db.query_one("SELECT * FROM articoli WHERE id = ?", (articolo_id,))
    if riga is None:
        return RedirectResponse(url="/articoli", status_code=303)
    articolo = dict(riga)
    for chiave in ("campi_personalizzati", "campi_extra"):
        try:
            articolo[chiave] = json.loads(articolo[chiave] or "{}")
        except (json.JSONDecodeError, TypeError):
            articolo[chiave] = {}
    listino = db.query_one(
        """SELECT nome_listino, prezzo, prezzo_iva, data_validita FROM listini
            WHERE codice_articolo = ? AND azienda = ?
            ORDER BY nome_listino LIMIT 1""",
        (articolo["codice"], articolo["azienda"] or ""),
    )
    articolo["nome_listino"] = listino["nome_listino"] if listino else "DEFAULT"
    articolo["prezzo"] = listino["prezzo"] if listino else None
    articolo["prezzo_iva"] = listino["prezzo_iva"] if listino else None
    articolo["data_validita"] = listino["data_validita"] if listino else None
    return render(
        request,
        "articoli/form.html",
        {
            "titolo": f"Articolo {articolo['codice']}",
            "articolo": articolo,
            "azioni": "salva",
            "marche": _marche_disponibili(),
            "listini": _listini_disponibili(),
            "campi_custom": carica_campi_personalizzati(),
            "valori_custom": articolo["campi_personalizzati"],
        },
    )


@router.post("/salva")
async def salva_articolo(request: Request, session: dict = Depends(require_user)):
    await check_csrf(request)
    form = await request.form()
    dati = {k: form.get(k) for k in form.keys() if not k.startswith("f__")}

    codice = str(dati.get("codice") or "").strip()
    if not codice:
        return render(
            request,
            "articoli/form.html",
            {
                "titolo": "Nuovo articolo",
                "articolo": dict(dati),
                "azioni": "crea",
                "errore": "Il codice articolo e' obbligatorio.",
                "marche": _marche_disponibili(),
                "listini": _listini_disponibili(),
                "campi_custom": [],
                "valori_custom": {},
            },
            status_code=400,
        )

    azienda = str(dati.get("azienda") or "").strip()
    campi_pers = _estrai_campi_personalizzati(dati)
    campi_extra = _estrai_campi_extra(dati)
    payload = (
        codice,
        str(dati.get("descrizione") or "").strip(),
        str(dati.get("unita_misura") or "").strip(),
        str(dati.get("barcode") or "").strip(),
        azienda,
        str(dati.get("codice_marca") or "").strip(),
        json.dumps(campi_extra, ensure_ascii=False),
        json.dumps(campi_pers, ensure_ascii=False),
    )

    from ..security import build_search_blob

    articolo_id = dati.get("id")
    if articolo_id:
        try:
            db.execute(
                """UPDATE articoli SET codice = ?, descrizione = ?, unita_misura = ?, barcode = ?,
                       azienda = ?, codice_marca = ?, campi_extra = ?, campi_personalizzati = ?,
                       search_blob = ?, updated_at = datetime('now')
                   WHERE id = ?""",
                payload
                + (
                    build_search_blob(
                        codice,
                        str(dati.get("descrizione") or ""),
                        str(dati.get("barcode") or ""),
                        str(dati.get("codice_marca") or ""),
                    ),
                    int(articolo_id),
                ),
            )
        except sqlite3.IntegrityError:
            return _errore_univocita(
                request, dati, codice, azienda, campi_pers
            )
    else:
        try:
            cur = db.execute(
                """INSERT INTO articoli
                     (codice, descrizione, unita_misura, barcode, azienda, codice_marca,
                      campi_extra, campi_personalizzati, search_blob, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
                payload
                + (
                    build_search_blob(
                        codice,
                        str(dati.get("descrizione") or ""),
                        str(dati.get("barcode") or ""),
                        str(dati.get("codice_marca") or ""),
                    ),
                ),
            )
        except sqlite3.IntegrityError:
            return _errore_univocita(
                request, dati, codice, azienda, campi_pers
            )
        articolo_id = cur.lastrowid

    _salva_prezzo(str(dati.get("codice") or codice), azienda, dati)
    return RedirectResponse(url=f"/articoli/{articolo_id}", status_code=303)


def _errore_univocita(request, dati, codice, azienda, campi_pers):
    """Mostra il form con l'errore di codice articolo duplicato."""
    from ..importers.service import carica_campi_personalizzati

    return render(
        request,
        "articoli/form.html",
        {
            "titolo": "Nuovo articolo",
            "articolo": dict(dati),
            "azioni": "crea",
            "errore": (
                f"L'articolo '{codice}' esiste gia' per l'azienda '{azienda or '(vuota)'}'."
            ),
            "marche": _marche_disponibili(),
            "listini": _listini_disponibili(),
            "campi_custom": carica_campi_personalizzati(),
            "valori_custom": campi_pers,
        },
        status_code=409,
    )


def _salva_prezzo(codice: str, azienda: str, dati) -> None:
    """Salva prezzo e listino dell'articolo (se valorizzati)."""
    nome_listino = str(dati.get("nome_listino") or "").strip() or "DEFAULT"
    prezzo_raw = str(dati.get("prezzo") or "").strip()
    if prezzo_raw == "":
        return
    try:
        prezzo = float(prezzo_raw.replace(",", "."))
    except ValueError:
        return
    esistente = db.query_one(
        """SELECT id FROM listini WHERE codice_articolo = ? AND azienda = ? AND nome_listino = ?""",
        (codice, azienda, nome_listino),
    )
    if esistente:
        db.execute(
            "UPDATE listini SET prezzo = ?, updated_at = datetime('now') WHERE id = ?",
            (prezzo, esistente["id"]),
        )
    else:
        db.execute(
            """INSERT INTO listini (codice_articolo, azienda, nome_listino, prezzo,
                                     created_at, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (codice, azienda, nome_listino, prezzo),
        )


def _estrai_campi_personalizzati(dati) -> dict[str, Any]:
    valori: dict[str, Any] = {}
    for chiave, valore in dati.items():
        if not chiave.startswith("cp_"):
            continue
        nome = chiave[3:]
        testo = str(valore or "").strip()
        if testo != "":
            valori[nome] = testo
    return valori


def _estrai_campi_extra(dati) -> dict[str, str]:
    valori: dict[str, str] = {}
    for chiave, valore in dati.items():
        if not chiave.startswith("ce_"):
            continue
        testo = str(valore or "").strip()
        if testo != "":
            valori[chiave[3:]] = testo
    return valori


@router.post("/{articolo_id}/elimina")
async def elimina_articolo(
    request: Request, articolo_id: int, session: dict = Depends(require_user)
):
    await check_csrf(request)
    db.execute("DELETE FROM listini WHERE codice_articolo = (SELECT codice FROM articoli WHERE id = ?)", (articolo_id,))
    db.execute("DELETE FROM articoli WHERE id = ?", (articolo_id,))
    return RedirectResponse(url="/articoli", status_code=303)
