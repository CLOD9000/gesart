"""Importazione CSV/XLSX: caricamento, anteprima, commit e log."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from .. import db
from ..importers import service
from ..importers.mapping import (
    TIPI_ENTITA,
    campi_per_tipo,
    profilo_per_tipo,
)
from ..security import require_admin
from .helpers import check_csrf, render

router = APIRouter(prefix="/import", tags=["import"])


@router.get("")
async def pagina_import(request: Request, session: dict = Depends(require_admin)):
    from ..config import settings

    return render(
        request,
        "import/index.html",
        {
            "titolo": "Importazione",
            "tipi": TIPI_ENTITA,
            "strategie": service.STRATEGIE,
            "imports_dir": str(settings.imports_dir),
            "file_disponibili": _file_disponibili(),
            "log": _carica_log(10),
        },
    )


ESTENSIONI_AMMESSE = (".csv", ".txt", ".tsv", ".xlsx", ".xlsm")


def _file_disponibili() -> list[dict[str, Any]]:
    """Elenca i file depositati nella cartella /imports montata nel container."""
    from ..config import settings

    cartella = settings.imports_dir
    if not cartella.is_dir():
        return []
    trovati: list[dict[str, Any]] = []
    try:
        elementi = sorted(cartella.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    for percorso in elementi:
        if not percorso.is_file():
            continue
        if percorso.suffix.lower() not in ESTENSIONI_AMMESSE:
            continue
        try:
            stat = percorso.stat()
        except OSError:
            continue
        trovati.append(
            {
                "nome": percorso.name,
                "byte": stat.st_size,
                "data": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            }
        )
    return trovati


def _carica_log(limite: int = 50) -> list[dict[str, Any]]:
    righe = db.query_all(
        """SELECT id, file, tipo, formato, strategia, stato, timestamp, righe_totali,
                  inseriti, aggiornati, scartati
             FROM log_importazioni ORDER BY id DESC LIMIT ?""",
        (limite,),
    )
    return [dict(r) for r in righe]


@router.post("/carica")
async def carica(
    request: Request,
    tipo: str = Form(...),
    strategia: str = Form(service.STRATEGIA_UPSERT),
    file: UploadFile = File(...),
    session: dict = Depends(require_admin),
):
    await check_csrf(request)
    if tipo not in TIPI_ENTITA:
        return RedirectResponse(url="/import", status_code=303)

    contenuto = await file.read()
    if not contenuto:
        return render(
            request,
            "import/index.html",
            {
                "titolo": "Importazione",
                "tipi": TIPI_ENTITA,
                "strategie": service.STRATEGIE,
                "errore": "Il file caricato e' vuoto.",
                "log": _carica_log(10),
            },
            status_code=400,
        )

    token = service.salva_staging(contenuto, file.filename or "file.csv", tipo, strategia)
    return RedirectResponse(url=f"/import/preview/{token}", status_code=303)


@router.post("/carica-da-cartella")
async def carica_da_cartella(
    request: Request,
    tipo: str = Form(...),
    strategia: str = Form(service.STRATEGIA_UPSERT),
    nome: str = Form(...),
    session: dict = Depends(require_admin),
):
    """Importa un file gia' presente nella cartella /imports."""
    await check_csrf(request)
    from ..config import settings

    if tipo not in TIPI_ENTITA:
        return RedirectResponse(url="/import", status_code=303)

    # Solo il nome del file: nessun percorso.
    nome_grezzo = str(nome).strip()
    nome = Path(nome_grezzo).name
    percorso = settings.imports_dir / nome
    if (
        not nome
        or nome != nome_grezzo
        or "/" in nome_grezzo
        or "\\" in nome_grezzo
        or ".." in nome_grezzo
        or Path(nome).suffix.lower() not in ESTENSIONI_AMMESSE
        or percorso.resolve().parent != settings.imports_dir.resolve()
        or not percorso.is_file()
    ):
        return render(
            request,
            "import/index.html",
            {
                "titolo": "Importazione",
                "tipi": TIPI_ENTITA,
                "strategie": service.STRATEGIE,
                "imports_dir": str(settings.imports_dir),
                "file_disponibili": _file_disponibili(),
                "errore": "File non trovato nella cartella di importazione.",
                "log": _carica_log(10),
            },
            status_code=400,
        )

    contenuto = percorso.read_bytes()
    token = service.salva_staging(contenuto, nome, tipo, strategia)
    return RedirectResponse(url=f"/import/preview/{token}", status_code=303)


@router.get("/preview/{token}")
async def preview(request: Request, token: str, session: dict = Depends(require_admin)):
    dati = service.leggi_staging(token)
    if dati is None:
        return render(
            request,
            "errore.html",
            {
                "titolo": "File non trovato",
                "messaggio": "La sessione di importazione e' scaduta o il file e' stato rimosso.",
            },
            status_code=404,
        )
    raw, meta = dati
    anteprima = service.analizza(
        raw,
        meta["file"],
        meta["tipo"],
        strategia=meta.get("strategia", service.STRATEGIA_UPSERT),
    )
    return render(
        request,
        "import/preview.html",
        {
            "titolo": f"Anteprima importazione - {meta['file']}",
            "anteprima": anteprima,
            "meta": meta,
            "token": token,
            "strategie": service.STRATEGIE,
            "campi": campi_per_tipo(meta["tipo"]),
            "profilo": profilo_per_tipo(meta["tipo"]),
        },
    )


@router.post("/preview/{token}")
async def rianalizza(request: Request, token: str, session: dict = Depends(require_admin)):
    """Ricalcola l'anteprima con la mappa delle colonne scelta dall'utente."""
    await check_csrf(request)
    form = await request.form()
    dati = service.leggi_staging(token)
    if dati is None:
        return RedirectResponse(url="/import", status_code=303)
    raw, meta = dati

    mappa: dict[str, int] = {}
    for chiave in form.keys():
        if not chiave.startswith("mappa_"):
            continue
        valore = form.get(chiave)
        try:
            indice = int(valore)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if indice > 0:
            mappa[chiave[len("mappa_") :]] = indice

    strategia = str(form.get("strategia") or service.STRATEGIA_UPSERT)
    meta["strategia"] = strategia
    meta["mappa"] = mappa
    service._staging_meta_path(token).write_text(json.dumps(meta), encoding="utf-8")

    anteprima = service.analizza(raw, meta["file"], meta["tipo"], mappa=mappa, strategia=strategia)
    return render(
        request,
        "import/preview.html",
        {
            "titolo": f"Anteprima importazione - {meta['file']}",
            "anteprima": anteprima,
            "meta": meta,
            "token": token,
            "strategie": service.STRATEGIE,
            "campi": campi_per_tipo(meta["tipo"]),
            "profilo": profilo_per_tipo(meta["tipo"]),
        },
    )


@router.post("/commit/{token}")
async def commit(request: Request, token: str, session: dict = Depends(require_admin)):
    await check_csrf(request)
    dati = service.leggi_staging(token)
    if dati is None:
        return RedirectResponse(url="/import", status_code=303)
    raw, meta = dati
    form = await request.form()
    strategia = str(form.get("strategia") or meta.get("strategia") or service.STRATEGIA_UPSERT)

    riepilogo = service.commit_import(
        raw,
        meta["file"],
        meta["tipo"],
        mappa=meta.get("mappa"),
        strategia=strategia,
        utente_id=session["utente_id"],
    )
    service.elimina_staging(token)
    return render(
        request,
        "import/risultato.html",
        {
            "titolo": "Importazione completata",
            "riepilogo": riepilogo,
            "log": _carica_log(10),
        },
    )


@router.get("/log")
async def log_import(request: Request, session: dict = Depends(require_admin)):
    return render(
        request,
        "import/log.html",
        {"titolo": "Log importazioni", "log": _carica_log(200)},
    )


@router.get("/log/{import_id}/errori.csv")
async def errori_csv(request: Request, import_id: int, session: dict = Depends(require_admin)):
    riga = db.query_one("SELECT errori FROM log_importazioni WHERE id = ?", (import_id,))
    errori = json.loads(riga["errori"]) if riga and riga["errori"] else []
    contenuto = service.report_errori_csv(errori)
    return Response(
        content="﻿" + contenuto,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="errori_importazione_{import_id}.csv"'},
    )
