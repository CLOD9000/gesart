"""Esportazione CSV.

Due formati disponibili:

  * `cosmo`  - riproduce fedelmente il file originale (COSMOART / COSMOLIB /
                COSMOMAR): delimitatore `;`, ogni campo racchiuso tra doppi
                apici, riga terminata da `;`, valori a larghezza fissa e
                numeri con zeri iniziali.
  * `semplice` - CSV standard (separatore `,`, intestazione, nessun padding).

Il formato `cosmo` usa il profilo dell'entita' per sapere, per ogni colonna,
il campo semantico, la larghezza e il formato numerico. I valori delle colonne
non mappate vengono recuperati da `campi_extra` (indicizzato per numero di
colonna del file sorgente), cosi' l'export e' fedele all'originale.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Sequence

from . import db
from .importers.mapping import (
    ColonnaProfilo,
    profilo_per_tipo,
)
from .importers.parsing import format_decimal, format_int

FORMATO_COSMO = "cosmo"
FORMATO_SEMPLICE = "semplice"


def _valore_prezzo(record: dict[str, Any], listino: str | None) -> float | None:
    """Prezzo dell'articolo per il listino indicato (default: primo trovato)."""
    prezzi = record.get("prezzi") or {}
    if listino and listino in prezzi:
        return prezzi[listino]
    for valore in prezzi.values():
        if valore is not None:
            return valore
    # Record "piatto" (gia' filtrato sul listino): si usa il prezzo diretto.
    return record.get("prezzo")


def _formatta_colonna(profilo: ColonnaProfilo, valore: Any, larghezza: int) -> str:
    """Applica il formato numerico/testo e il padding della colonna."""
    formato = profilo.formato
    if formato.startswith("int:"):
        testo = format_int(int(valore) if valore is not None else None, int(formato.split(":")[1]))
    elif formato.startswith("dec:"):
        _, parametri = formato.split(":")
        cifre_int, cifre_dec = (int(x) for x in parametri.split(","))
        testo = format_decimal(
            float(valore) if valore is not None else None, cifre_int, cifre_dec
        )
    else:
        testo = "" if valore is None else str(valore)
    if larghezza and len(testo) < larghezza:
        testo = testo.ljust(larghezza)
    return testo


def _valore_campo_target(
    record: dict[str, Any], profilo: ColonnaProfilo
) -> Any:
    """Recupera il valore semantico di una colonna dal record."""
    chiave = profilo.chiave
    if not chiave:
        return None
    if chiave == "prezzo":
        return _valore_prezzo(record, record.get("listino_selezionato"))
    if chiave == "prezzo_iva":
        return record.get("prezzo_iva")
    return record.get(chiave)


def esporta_cosmo(
    righe: Sequence[dict[str, Any]], tipo: str, listino: str | None = None
) -> str:
    """Esporta nel formato Cosmo (identico all'originale)."""
    profilo = profilo_per_tipo(tipo)
    buffer = io.StringIO()
    # Il terminatore di riga e' ";\n": il file originale chiude ogni riga con
    # il separatore (artefatto del gestionale di origine) seguito da newline.
    writer = csv.writer(
        buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator=";\n", quotechar='"'
    )
    for record in righe:
        campi_extra = record.get("campi_extra") or {}
        riga = []
        for colonna in profilo:
            if colonna.e_mappata:
                valore = _valore_campo_target(record, colonna)
                riga.append(_formatta_colonna(colonna, valore, colonna.larghezza))
            else:
                grezzo = campi_extra.get(str(colonna.indice))
                if grezzo is None:
                    # Valore di default del formato (zeri o spazi)
                    riga.append(_formatta_colonna(colonna, None, colonna.larghezza))
                else:
                    riga.append(_formatta_colonna(colonna, grezzo, colonna.larghezza))
        writer.writerow(riga)
    return buffer.getvalue()


def esporta_semplice(
    righe: Sequence[dict[str, Any]],
    colonne: Sequence[str],
    intestazioni: dict[str, str] | None = None,
) -> str:
    """Esporta un CSV semplice con le colonne richieste."""
    intestazioni = intestazioni or {}
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow([intestazioni.get(c, c) for c in colonne])
    for record in righe:
        riga = []
        for colonna in colonne:
            valore = record.get(colonna)
            if colonna == "prezzo":
                valore = _valore_prezzo(record, record.get("listino_selezionato"))
            elif isinstance(valore, (dict, list)):
                valore = json.dumps(valore, ensure_ascii=False)
            riga.append("" if valore is None else valore)
        writer.writerow(riga)
    return buffer.getvalue()


def esporta_campi_personalizzati(
    righe: Sequence[dict[str, Any]], campi_custom: Sequence[dict[str, Any]]
) -> str:
    """Esporta codice + descrizione + campi personalizzati (sintesi)."""
    colonne = ["codice", "descrizione"] + [str(c["chiave"]) for c in campi_custom]
    intestazioni = {"codice": "Codice", "descrizione": "Descrizione"}
    for campo in campi_custom:
        intestazioni[str(campo["chiave"])] = str(campo["etichetta"])
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow([intestazioni[c] for c in colonne])
    for record in righe:
        valori_custom = record.get("campi_personalizzati") or {}
        writer.writerow(
            [
                record.get("codice", ""),
                record.get("descrizione", ""),
                *[
                    valori_custom.get(str(campo["chiave"]), "")
                    for campo in campi_custom
                ],
            ]
        )
    return buffer.getvalue()


def esporta_errori_log(importazione_id: int) -> str:
    """Esporta in CSV gli errori di una specifica importazione."""
    riga = db.query_one(
        "SELECT errori FROM log_importazioni WHERE id = %s", (importazione_id,)
    )
    errori = json.loads(riga["errori"]) if riga and riga["errori"] else []
    from .importers.service import report_errori_csv

    return report_errori_csv(errori)
