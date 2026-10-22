"""Test dell'esportazione: fedelt' al formato Cosmo e CSV semplice."""
from __future__ import annotations

import csv
import io

import pytest

from app import db
from app.exporters import (
    esporta_campi_personalizzati,
    esporta_cosmo,
    esporta_semplice,
)
from app.importers import service

ESEMPI = "examples"


def leggi(nome: str) -> bytes:
    with open(f"{ESEMPI}/{nome}", "rb") as fh:
        return fh.read()


def righe_csv(testo: str) -> list[list[str]]:
    """Legge il CSV; elimina la colonna fantasma finale (come il parser)."""
    righe = list(csv.reader(io.StringIO(testo), delimiter=";"))
    return [riga[:-1] if riga and riga[-1] == "" else riga for riga in righe]


def _record_articolo(codice, descrizione, marca="951", prezzo=18.0, extra=None):
    return {
        "codice": codice,
        "descrizione": descrizione,
        "unita_misura": "Pz.",
        "barcode": "00000000000",
        "azienda": "EUCOMO",
        "codice_marca": marca,
        "prezzo": prezzo,
        "prezzo_iva": prezzo,
        "nome_listino": "DEFAULT",
        "campi_extra": extra or {},
        "campi_personalizzati": {},
    }


# ---------------------------------------------------------------------------
# Formato Cosmo
# ---------------------------------------------------------------------------
def test_esporta_cosmo_articoli_riproduce_il_formato(db_pulito):
    """L'export deve riprodurre il file originale (larghezze e zeri iniziali)."""
    servizio = service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    assert servizio["inseriti"] == 3
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")

    righe = [
        {
            "codice": r["codice"],
            "descrizione": r["descrizione"],
            "unita_misura": r["unita_misura"],
            "barcode": r["barcode"],
            "azienda": r["azienda"],
            "codice_marca": r["codice_marca"],
            "prezzo": None,
            "campi_extra": __import__("json").loads(r["campi_extra"]),
            "campi_personalizzati": {},
        }
        for r in db.query_all("SELECT * FROM articoli ORDER BY codice")
    ]
    testo = esporta_cosmo(righe, "articoli")
    righe_esportate = righe_csv(testo)

    assert len(righe_esportate) == 7
    assert len(righe_esportate[0]) == 12
    # Larghezza fissa del codice
    assert len(righe_esportate[0][0]) == 15
    assert righe_esportate[0][0] == "8194700        "
    # La riga termina con il separatore (formato originale)
    assert testo.splitlines()[0].endswith(";")
    # Numeri con zeri iniziali nella colonna 5
    assert righe_esportate[0][4] == "00000001.000"
    # Colonne non mappate recuperate da campi_extra
    assert righe_esportate[0][3] == "1"
    assert righe_esportate[0][9] == "00000000.000"
    assert righe_esportate[0][11] == "1"


def test_esporta_cosmo_listini_riproduce_il_formato(db_pulito):
    service.commit_import(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")
    righe = []
    for r in db.query_all("SELECT * FROM listini ORDER BY codice_articolo"):
        righe.append(
            {
                "codice_articolo": r["codice_articolo"],
                "codice": r["codice_articolo"],
                "azienda": r["azienda"],
                "nome_listino": r["nome_listino"],
                "prezzo": r["prezzo"],
                "prezzo_iva": r["prezzo_iva"],
                "data_validita": r["data_validita"],
                "campi_extra": __import__("json").loads(r["campi_extra"]),
            }
        )
    testo = esporta_cosmo(righe, "listini")
    righe_esportate = righe_csv(testo)

    assert len(righe_esportate) == 7
    assert len(righe_esportate[0]) == 17
    assert righe_esportate[0][6] == "000000018.0000000"   # prezzo
    assert righe_esportate[0][10] == "000000018.0000000"  # prezzo secondario
    assert righe_esportate[0][1] == "000000000.0000000"
    assert righe_esportate[0][2] == "0000.000"
    assert righe_esportate[0][16] == "EUCOMO  "


def test_esporta_cosmo_marche_riproduce_il_formato(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    righe = [dict(r) for r in db.query_all("SELECT * FROM marche ORDER BY codice")]
    testo = esporta_cosmo(righe, "marche")
    righe_esportate = righe_csv(testo)
    assert len(righe_esportate) == 3
    assert len(righe_esportate[0]) == 3
    assert righe_esportate[0][0] == "000"
    assert righe_esportate[0][2] == "EUCOMO  "


def test_round_trip_cosmoart_identico_all_originale(db_pulito):
    """Import -> export deve ricostruire il file sorgente byte per byte."""
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    righe = [
        {
            "codice": r["codice"],
            "descrizione": r["descrizione"],
            "unita_misura": r["unita_misura"],
            "barcode": r["barcode"],
            "azienda": r["azienda"],
            "codice_marca": r["codice_marca"],
            "campi_extra": __import__("json").loads(r["campi_extra"]),
        }
        for r in db.query_all("SELECT * FROM articoli ORDER BY id")
    ]
    esportato = esporta_cosmo(righe, "articoli")
    originale = leggi("COSMOART.csv").decode("utf-8")
    # L'originale ha il terminatore di riga ";", l'export pure lo stesso formato.
    assert esportato.splitlines() == originale.splitlines()


def test_round_trip_cosmolib_identico_all_originale(db_pulito):
    service.commit_import(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")
    righe = []
    for r in db.query_all("SELECT * FROM listini ORDER BY id"):
        righe.append(
            {
                "codice_articolo": r["codice_articolo"],
                "azienda": r["azienda"],
                "nome_listino": r["nome_listino"],
                "prezzo": r["prezzo"],
                "prezzo_iva": r["prezzo_iva"],
                "campi_extra": __import__("json").loads(r["campi_extra"]),
            }
        )
    esportato = esporta_cosmo(righe, "listini")
    originale = leggi("COSMOLIB.csv").decode("utf-8")
    assert esportato.splitlines() == originale.splitlines()


# ---------------------------------------------------------------------------
# CSV semplice
# ---------------------------------------------------------------------------
def test_esporta_semplice(db_pulito):
    righe = [_record_articolo("90035", "TUBO BINATO", prezzo=167.38)]
    testo = esporta_semplice(
        righe,
        ["codice", "descrizione", "prezzo"],
        {"codice": "Codice", "descrizione": "Descrizione", "prezzo": "Prezzo"},
    )
    righe_esportate = list(csv.reader(io.StringIO(testo)))
    assert righe_esportate[0] == ["Codice", "Descrizione", "Prezzo"]
    assert righe_esportate[1] == ["90035", "TUBO BINATO", "167.38"]


def test_esporta_campi_personalizzati(db_pulito):
    campi = [
        {"chiave": "colore", "etichetta": "Colore"},
        {"chiave": "peso", "etichetta": "Peso"},
    ]
    righe = [
        {
            "codice": "90035",
            "descrizione": "TUBO",
            "campi_personalizzati": {"colore": "rosso", "peso": 12},
        }
    ]
    testo = esporta_campi_personalizzati(righe, campi)
    righe_esportate = list(csv.reader(io.StringIO(testo)))
    assert righe_esportate[0] == ["Codice", "Descrizione", "Colore", "Peso"]
    assert righe_esportate[1] == ["90035", "TUBO", "rosso", "12"]
