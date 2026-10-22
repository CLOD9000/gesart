"""Definizione dei campi target e dei profili di formato dei file Cosmo.

Un "profilo" descrive sia la posizione delle colonne nei file originali
(usata per l'auto-mapping in import) sia il formato di uscita (usato
dall'esportazione), in modo che l'export riproduca il file byte per byte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

TIPO_TESTO = "testo"
TIPO_NUMERO = "numero"
TIPO_DATA = "data"
TIPO_FLAG = "flag"
TIPO_LISTA = "lista"

TIPI_CAMPO = (TIPO_TESTO, TIPO_NUMERO, TIPO_DATA, TIPO_FLAG, TIPO_LISTA)

TIPI_ENTITA = ("articoli", "marche", "listini")

# Formule numeriche supportate nella definizione dei profili.
#   testo        -> testo
#   int:<n>      -> intero con zeri iniziali (n cifre)
#   dec:<i>,<d>  -> decimale con zeri iniziali (i cifre intere, d decimali)


@dataclass(frozen=True)
class CampoTarget:
    """Un campo che l'utente puo' valorizzare in import."""

    chiave: str
    etichetta: str
    tipo: str = TIPO_TESTO
    obbligatorio: bool = False
    opzioni: tuple[str, ...] = ()


CAMPOS_ARTICOLI: tuple[CampoTarget, ...] = (
    CampoTarget("codice", "Codice articolo", TIPO_TESTO, True),
    CampoTarget("descrizione", "Descrizione", TIPO_TESTO, True),
    CampoTarget("unita_misura", "Unita' di misura", TIPO_TESTO),
    CampoTarget("barcode", "Barcode", TIPO_TESTO),
    CampoTarget("azienda", "Azienda", TIPO_TESTO),
    CampoTarget("codice_marca", "Codice marca", TIPO_TESTO),
)

CAMPOS_MARCHE: tuple[CampoTarget, ...] = (
    CampoTarget("codice", "Codice marca", TIPO_TESTO, True),
    CampoTarget("descrizione", "Descrizione marca", TIPO_TESTO, True),
    CampoTarget("azienda", "Azienda", TIPO_TESTO),
)

CAMPOS_LISTINI: tuple[CampoTarget, ...] = (
    CampoTarget("codice_articolo", "Codice articolo", TIPO_TESTO, True),
    CampoTarget("prezzo", "Prezzo", TIPO_NUMERO, True),
    CampoTarget("prezzo_iva", "Prezzo (secondario)", TIPO_NUMERO),
    CampoTarget("nome_listino", "Nome listino", TIPO_TESTO),
    CampoTarget("data_validita", "Data validita'", TIPO_DATA),
    CampoTarget("azienda", "Azienda", TIPO_TESTO),
)

CAMPI_PER_ENTITA: dict[str, tuple[CampoTarget, ...]] = {
    "articoli": CAMPOS_ARTICOLI,
    "marche": CAMPOS_MARCHE,
    "listini": CAMPOS_LISTINI,
}

# Nomi file "canonici" usati dal prompt / dalla UI.
FILE_CANONICI = {
    "articoli": "COSMOART.csv",
    "marche": "COSMOMAR.csv",
    "listini": "COSMOLIB.csv",
}


@dataclass(frozen=True)
class ColonnaProfilo:
    """Una colonna nel file originale: posizione, semantica e formato."""

    indice: int  # 1-based
    chiave: str  # chiave del campo target ("" = colonna non mappata -> campi_extra)
    etichetta: str
    larghezza: int = 0  # 0 = nessun padding
    formato: str = "testo"

    @property
    def e_mappata(self) -> bool:
        return self.chiave != ""


# ---------------------------------------------------------------------------
# Profili Cosmo (misurati sui file di esempio)
# ---------------------------------------------------------------------------
PROFILO_ART: tuple[ColonnaProfilo, ...] = (
    ColonnaProfilo(1, "codice", "Codice articolo", 15),
    ColonnaProfilo(2, "descrizione", "Descrizione", 50),
    ColonnaProfilo(3, "unita_misura", "Unita' di misura", 5),
    ColonnaProfilo(4, "", "Campo 4 (da definire)", 1, "int:1"),
    ColonnaProfilo(5, "", "Campo 5 (da definire)", 12, "dec:8,3"),
    ColonnaProfilo(6, "barcode", "Barcode", 11),
    ColonnaProfilo(7, "azienda", "Azienda", 8),
    ColonnaProfilo(8, "", "Campo 8 (da definire)", 3),
    ColonnaProfilo(9, "codice_marca", "Codice marca", 3),
    ColonnaProfilo(10, "", "Campo 10 (da definire)", 12, "dec:8,3"),
    ColonnaProfilo(11, "", "Campo 11 (da definire)", 1),
    ColonnaProfilo(12, "", "Campo 12 (da definire)", 1, "int:1"),
)

PROFILO_LIB: tuple[ColonnaProfilo, ...] = (
    ColonnaProfilo(1, "codice_articolo", "Codice articolo", 15),
    ColonnaProfilo(2, "", "Campo 2 (da definire)", 17, "dec:9,7"),
    ColonnaProfilo(3, "", "Campo 3 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(4, "", "Campo 4 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(5, "", "Campo 5 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(6, "", "Campo 6 (da definire)", 17, "dec:9,7"),
    ColonnaProfilo(7, "prezzo", "Prezzo", 17, "dec:9,7"),
    ColonnaProfilo(8, "", "Campo 8 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(9, "", "Campo 9 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(10, "", "Campo 10 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(11, "prezzo_iva", "Prezzo secondario", 17, "dec:9,7"),
    ColonnaProfilo(12, "", "Campo 12 (da definire)", 17, "dec:9,7"),
    ColonnaProfilo(13, "", "Campo 13 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(14, "", "Campo 14 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(15, "", "Campo 15 (da definire)", 8, "dec:4,3"),
    ColonnaProfilo(16, "", "Campo 16 (da definire)", 17, "dec:9,7"),
    ColonnaProfilo(17, "azienda", "Azienda", 8),
)

PROFILO_MAR: tuple[ColonnaProfilo, ...] = (
    ColonnaProfilo(1, "codice", "Codice marca", 3),
    ColonnaProfilo(2, "descrizione", "Descrizione", 50),
    ColonnaProfilo(3, "azienda", "Azienda", 8),
)

PROFILI: dict[str, tuple[ColonnaProfilo, ...]] = {
    "articoli": PROFILO_ART,
    "marche": PROFILO_MAR,
    "listini": PROFILO_LIB,
}

# Ordine canonico per l'export (indice -> colonna del profilo).
PROFILO_PER_ENTITA = PROFILI


def profilo_per_tipo(tipo: str) -> tuple[ColonnaProfilo, ...]:
    return PROFILI.get(tipo, PROFILO_ART)


def campi_per_tipo(tipo: str) -> tuple[CampoTarget, ...]:
    return CAMPI_PER_ENTITA.get(tipo, CAMPOS_ARTICOLI)


# ---------------------------------------------------------------------------
# Auto-mapping
# ---------------------------------------------------------------------------
def auto_mapping(tipo: str, n_colonne: int) -> dict[str, int]:
    """Propone una mappa {campo_target: indice_colonna_1based}.

    Strategia:
      1. se il numero di colonne coincide con un profilo Cosmo noto, si usa
         la mappa canonica (posizioni fisse del gestionale di origine);
      2. altrimenti si applicano euristiche sul contenuto (codice numerico
         corto, presenza di decimali, cardinalita' unica, ecc.).
    """
    profilo = profilo_per_tipo(tipo)
    if n_colonne == len(profilo):
        return {c.chiave: c.indice for c in profilo if c.e_mappata}

    if tipo == "marche":
        # Colonna 1 = codice (breve), 2 = descrizione, 3 = azienda
        mappa: dict[str, int] = {}
        for idx in range(1, n_colonne + 1):
            if idx == 1:
                mappa["codice"] = idx
            elif idx == 2:
                mappa["descrizione"] = idx
            elif idx == 3:
                mappa["azienda"] = idx
        return mappa

    if tipo == "listini":
        mappa = {"codice_articolo": 1, "prezzo": 2, "prezzo_iva": 3}
        if n_colonne >= 4:
            mappa["azienda"] = n_colonne
        return mappa

    # articoli: euristica basata sulla posizione
    mappa = {
        "codice": 1,
        "descrizione": 2,
        "unita_misura": 3,
        "azienda": 7 if n_colonne >= 7 else n_colonne,
        "codice_marca": 9 if n_colonne >= 9 else None,
    }
    return {k: v for k, v in mappa.items() if v}


def profilo_mappato(tipo: str, mappa: dict[str, int], n_colonne: int) -> list[ColonnaProfilo]:
    """Costruisce il profilo di una mappa arbitraria (usato dagli XLSX)."""
    profilo = profilo_per_tipo(tipo)
    if n_colonne == len(profilo) and set(mappa.values()) == {
        c.indice for c in profilo if c.e_mappata
    }:
        return list(profilo)
    inverse = {v: k for k, v in mappa.items()}
    colonne: list[ColonnaProfilo] = []
    for idx in range(1, n_colonne + 1):
        chiave = inverse.get(idx, "")
        if chiave:
            campo = next((c for c in campi_per_tipo(tipo) if c.chiave == chiave), None)
            etichetta = campo.etichetta if campo else chiave
            formato = "numero" if (campo and campo.tipo == TIPO_NUMERO) else "testo"
        else:
            etichetta = f"Colonna {idx}"
            formato = "testo"
        colonne.append(ColonnaProfilo(idx, chiave, etichetta, 0, formato))
    return colonne


def campo_per_chiave(tipo: str, chiave: str) -> CampoTarget | None:
    for campo in campi_per_tipo(tipo):
        if campo.chiave == chiave:
            return campo
    return None
