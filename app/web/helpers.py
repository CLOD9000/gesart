"""Helper condivisi dalle route web: contesto template, CSRF, filtri."""
from __future__ import annotations

import json
from typing import Any, Sequence

from fastapi import Request
from starlette.responses import RedirectResponse

from .. import db
from ..importers.service import carica_campi_personalizzati
from ..security import current_session, verify_csrf
from .main import templates

RUOLI = ("admin", "operatore")


async def check_csrf(request: Request) -> None:
    """Verifica il token CSRF sui POST (dal form o dall'header htmx)."""
    form = await request.form()
    verify_csrf(
        request,
        form.get("csrf_token"),  # type: ignore[arg-type]
        request.headers.get("X-CSRF-Token"),
    )


def base_context(request: Request, **extra: Any) -> dict[str, Any]:
    """Costruisce il contesto di base per i template."""
    session = current_session(request)
    campi_custom = carica_campi_personalizzati()
    contesto: dict[str, Any] = {
        "request": request,
        "sessione": session,
        "utente": session,
        "csrf_token": (session or {}).get("csrf_token", ""),
        "campi_custom": campi_custom,
        "campi_custom_map": {c["chiave"]: c for c in campi_custom},
        "ruolo": (session or {}).get("ruolo", ""),
        "e_admin": (session or {}).get("ruolo") == "admin",
        "anno": 2026,
    }
    contesto.update(extra)
    return contesto


def render(
    request: Request,
    nome: str,
    contesto: dict[str, Any],
    status_code: int = 200,
    **kwargs: Any,
):
    """Render di un template con il contesto base."""
    completo = base_context(request, **contesto)
    completo.update(kwargs)
    return templates.TemplateResponse(request, nome, completo, status_code=status_code)


# ---------------------------------------------------------------------------
# Filtri: serializzazione nei query param
# ---------------------------------------------------------------------------
def parse_filtri_form(multidict) -> dict[str, Any]:
    """Converte i campi `f__<colonna>__<aspetto>` nel dizionario filtri.

    Accetta sia un FormData (POST) sia un QueryParams (GET).
    """
    filtri: dict[str, Any] = {}
    for key in set(multidict.keys()):
        if not key.startswith("f__"):
            continue
        parti = key.split("__")
        if len(parti) != 3:
            continue
        _prefisso, colonna, aspetto = parti
        valori = multidict.getlist(key)
        spec = filtri.setdefault(colonna, {})
        if aspetto == "val" and len(valori) > 1:
            spec["val"] = [v for v in valori if v.strip() != ""]
        elif valori:
            spec[aspetto] = valori[0]

    puliti: dict[str, Any] = {}
    for colonna, spec in filtri.items():
        op = str(spec.get("op") or "").strip()
        if not op:
            continue
        if op in ("vuoto", "non_vuoto"):
            puliti[colonna] = {"op": op}
            continue
        if op in ("min_max", "da_a"):
            chiavi = ("min", "max") if op == "min_max" else ("da", "a")
            valori = {
                k: v for k, v in spec.items() if k in chiavi and str(v).strip() != ""
            }
            if valori:
                puliti[colonna] = {"op": op, **valori}
            continue
        valore = spec.get("val")
        if valore is None or (isinstance(valore, str) and valore.strip() == ""):
            continue
        puliti[colonna] = {"op": op, "val": valore}
    return puliti


def filtri_da_query(request: Request) -> dict[str, Any]:
    """Legge i filtri dalla query string.

    Sono supportate due forme:
      * `flt=<json>`   -> forma normalizzata (usata anche dalle viste salvate)
      * `f__<col>__..` -> forma prodotta dal form dei filtri
    """
    grezzo = request.query_params.get("flt")
    if grezzo:
        try:
            dati = json.loads(grezzo)
        except json.JSONDecodeError:
            dati = None
        if isinstance(dati, dict):
            return dati
    return parse_filtri_form(request.query_params)


def filtri_da_form(form) -> dict[str, Any]:
    """Legge i filtri da un form POST (`flt` JSON oppure campi `f__*`)."""
    grezzo = form.get("flt")
    if grezzo:
        try:
            dati = json.loads(grezzo)
        except (json.JSONDecodeError, TypeError):
            dati = None
        if isinstance(dati, dict):
            return dati
    return parse_filtri_form(form)


def filtri_in_query(filtri: dict[str, Any]) -> str:
    """Serializza i filtri in un parametro query string."""
    if not filtri:
        return ""
    return json.dumps(filtri, ensure_ascii=False, separators=(",", ":"))


def parametri_paginazione(request: Request) -> dict[str, Any]:
    def intero(nome: str, default: int) -> int:
        try:
            return int(request.query_params.get(nome, default))
        except (TypeError, ValueError):
            return default

    return {
        "ordinamento": request.query_params.get("ord", "codice"),
        "direzione": request.query_params.get("dir", "asc"),
        "pagina": max(1, intero("pag", 1)),
        "per_pagina": max(5, min(intero("per", 50), 500)),
        "listino": request.query_params.get("listino") or None,
    }


def valori_dropdown() -> dict[str, list[dict[str, Any]]]:
    """Valori per i filtri a dropdown (marche, listini, aziende, unita' di misura)."""
    marche = [
        {"value": r["codice"], "label": f"{r['codice']} - {r['descrizione']}".strip(" -")}
        for r in db.query_all("SELECT codice, descrizione FROM marche ORDER BY codice")
    ]
    listini = [
        {"value": r["nome_listino"], "label": r["nome_listino"]}
        for r in db.query_all("SELECT DISTINCT nome_listino FROM listini ORDER BY nome_listino")
    ]
    aziende = [
        {"value": r["azienda"], "label": r["azienda"] or "(vuoto)"}
        for r in db.query_all("SELECT DISTINCT azienda FROM articoli ORDER BY azienda")
    ]
    unita = [
        {"value": r["unita_misura"], "label": r["unita_misura"] or "(vuoto)"}
        for r in db.query_all(
            "SELECT DISTINCT unita_misura FROM articoli WHERE TRIM(unita_misura) <> '' ORDER BY unita_misura"
        )
    ]
    return {"marche": marche, "listini": listini, "aziende": aziende, "unita_misura": unita}


def campo_di_filtro(
    filtri: dict[str, Any], chiave: str, campo: str, default: Any = ""
) -> Any:
    spec = filtri.get(chiave) or {}
    if not isinstance(spec, dict):
        return default
    valore = spec.get(campo, default)
    return default if valore is None else valore


def redirect_con_filtri(url: str, filtri: dict[str, Any], extra: dict[str, Any] | None = None) -> RedirectResponse:
    """Costruisce una redirect conservando i filtri."""
    parametri: list[tuple[str, str]] = []
    if filtri:
        parametri.append(("flt", filtri_in_query(filtri)))
    for chiave, valore in (extra or {}).items():
        if valore not in (None, ""):
            parametri.append((chiave, str(valore)))
    query = "&".join(f"{k}={v}" for k, v in parametri)
    return RedirectResponse(url=url + (f"?{query}" if query else ""), status_code=303)


def campi_personalizzati_or_db() -> Sequence[dict[str, Any]]:
    return carica_campi_personalizzati()
