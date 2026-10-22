"""Interrogazione articoli: filtri combinabili, ordinamento, paginazione.

Il motore dei filtri e' dichiarativo: un filtro e' un dizionario
``{colonna: {"op": operatore, ...parametri}}``. Ogni colonna e' associata ad un
tipo (testo / numero / data / flag / lista) che determina gli operatori
ammessi e la SQL generata.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from . import db
from .importers.mapping import TIPO_DATA, TIPO_FLAG, TIPO_LISTA, TIPO_NUMERO, TIPO_TESTO

# Colonne statiche filtrabili sulla tabella articoli.
COLONNE_ARTICOLI: tuple[tuple[str, str, str], ...] = (
    # (chiave, etichetta, tipo)
    ("codice", "Codice", TIPO_TESTO),
    ("descrizione", "Descrizione", TIPO_TESTO),
    ("unita_misura", "Unita' di misura", TIPO_TESTO),
    ("barcode", "Barcode", TIPO_TESTO),
    ("azienda", "Azienda", TIPO_TESTO),
    ("codice_marca", "Marca", TIPO_LISTA),
    ("nome_listino", "Listino", TIPO_LISTA),
    ("prezzo", "Prezzo", TIPO_NUMERO),
    ("created_at", "Creato il", TIPO_DATA),
    ("updated_at", "Aggiornato il", TIPO_DATA),
)

ORDINAMENTI = {
    "codice": "a.codice",
    "descrizione": "a.descrizione",
    "unita_misura": "a.unita_misura",
    "barcode": "a.barcode",
    "azienda": "a.azienda",
    "codice_marca": "a.codice_marca",
    "prezzo": "l.prezzo",
    "created_at": "a.created_at",
    "updated_at": "a.updated_at",
}

# Traduzione da chiave campo personalizzato -> percorso JSON
def _json_path(chiave: str) -> str:
    return f"$.\"{chiave}\""


@dataclass
class RisultatoQuery:
    righe: list[dict[str, Any]] = field(default_factory=list)
    totale: int = 0
    pagina: int = 1
    per_pagina: int = 50
    pagine: int = 1

    @property
    def inizio(self) -> int:
        if self.totale == 0:
            return 0
        return (self.pagina - 1) * self.per_pagina + 1

    @property
    def fine(self) -> int:
        return min(self.pagina * self.per_pagina, self.totale)


# ---------------------------------------------------------------------------
# Colonne disponibili (statiche + campi personalizzati)
# ---------------------------------------------------------------------------
def colonne_disponibili(campi_custom: Sequence[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    colonne = [
        {"chiave": chiave, "etichetta": etichetta, "tipo": tipo, "custom": False}
        for chiave, etichetta, tipo in COLONNE_ARTICOLI
    ]
    for campo in campi_custom or []:
        colonne.append(
            {
                "chiave": f"cf_{campo['chiave']}",
                "etichetta": str(campo["etichetta"]),
                "tipo": str(campo["tipo"]),
                "custom": True,
                "campo_custom": campo["chiave"],
                "opzioni": campo.get("opzioni") or [],
            }
        )
    return colonne


def _tipo_colonna(chiave: str, campi_custom: Sequence[dict[str, Any]]) -> str | None:
    for c, e, t in COLONNE_ARTICOLI:
        if c == chiave:
            return t
    if chiave.startswith("cf_"):
        nome = chiave[3:]
        for campo in campi_custom:
            if campo["chiave"] == nome:
                return str(campo["tipo"])
    return None


def _espressione_colonna(chiave: str, campi_custom: Sequence[dict[str, Any]]) -> str | None:
    """Espressione SQL usata nei filtri per la colonna indicata."""
    for c, _e, _t in COLONNE_ARTICOLI:
        if c == chiave:
            if c == "prezzo":
                return "l.prezzo"
            if c == "nome_listino":
                return "l.nome_listino"
            return f"a.{c}"
    if chiave.startswith("cf_"):
        nome = chiave[3:]
        if any(campo["chiave"] == nome for campo in campi_custom):
            return f"json_extract(a.campi_personalizzati, '{_json_path(nome)}')"
    return None


# ---------------------------------------------------------------------------
# Costruzione WHERE
# ---------------------------------------------------------------------------
def costruisci_where(
    filtri: dict[str, Any],
    campi_custom: Sequence[dict[str, Any]],
) -> tuple[str, list[Any]]:
    """Traduce i filtri in una clausola WHERE (senza 'WHERE')."""
    clausole: list[str] = []
    parametri: list[Any] = []

    q = str((filtri.get("q") or "")).strip()
    if q:
        like = f"%{q}%"
        clausole.append(
            "(a.search_blob LIKE ? COLLATE NOCASE"
            " OR a.codice LIKE ? COLLATE NOCASE"
            " OR a.descrizione LIKE ? COLLATE NOCASE"
            " OR a.barcode LIKE ? COLLATE NOCASE"
            " OR a.codice_marca LIKE ? COLLATE NOCASE)"
        )
        parametri.extend([like] * 5)

    for chiave, spec in (filtri or {}).items():
        if chiave == "q" or not isinstance(spec, dict):
            continue
        espressione = _espressione_colonna(chiave, campi_custom)
        if espressione is None:
            continue
        tipo = _tipo_colonna(chiave, campi_custom)
        op = str(spec.get("op") or "").strip()

        if tipo == TIPO_NUMERO:
            clausola, valori = _filtro_numero(espressione, op, spec)
        elif tipo == TIPO_DATA:
            clausola, valori = _filtro_data(espressione, op, spec)
        elif tipo == TIPO_FLAG:
            clausola, valori = _filtro_flag(espressione, op, spec)
        elif tipo == TIPO_LISTA:
            clausola, valori = _filtro_lista(espressione, op, spec)
        else:
            clausola, valori = _filtro_testo(espressione, op, spec)

        if clausola:
            clausole.append(clausola)
            parametri.extend(valori)

    if not clausole:
        return "", []
    return " AND ".join(clausole), parametri


def _filtro_testo(expr: str, op: str, spec: dict[str, Any]) -> tuple[str, list[Any]]:
    valore = str(spec.get("val") or "").strip()
    if op == "vuoto":
        return f"({expr} IS NULL OR TRIM({expr}) = '')", []
    if op == "non_vuoto":
        return f"({expr} IS NOT NULL AND TRIM({expr}) <> '')", []
    if valore == "":
        return "", []
    if op == "uguale":
        return f"{expr} = ? COLLATE NOCASE", [valore]
    if op == "inizia":
        return f"{expr} LIKE ? ESCAPE '\\' COLLATE NOCASE", [f"{_escape_like(valore)}%"]
    if op == "termina":
        return f"{expr} LIKE ? ESCAPE '\\' COLLATE NOCASE", [f"%{_escape_like(valore)}"]
    if op == "non_contiene":
        return f"{expr} NOT LIKE ? ESCAPE '\\' COLLATE NOCASE", [f"%{_escape_like(valore)}%"]
    # default: contiene
    return f"{expr} LIKE ? ESCAPE '\\' COLLATE NOCASE", [f"%{_escape_like(valore)}%"]


def _escape_like(valore: str) -> str:
    return valore.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _filtro_numero(expr: str, op: str, spec: dict[str, Any]) -> tuple[str, list[Any]]:
    try:
        if op == "min_max":
            condizioni = []
            valori = []
            if spec.get("min") not in (None, ""):
                condizioni.append(f"{expr} >= ?")
                valori.append(float(spec["min"]))
            if spec.get("max") not in (None, ""):
                condizioni.append(f"{expr} <= ?")
                valori.append(float(spec["max"]))
            return (" AND ".join(condizioni), valori) if condizioni else ("", [])
        if op == "maggiore":
            return f"{expr} > ?", [float(spec.get("val") or 0)]
        if op == "minore":
            return f"{expr} < ?", [float(spec.get("val") or 0)]
        if op == "vuoto":
            return f"{expr} IS NULL", []
        if op == "non_vuoto":
            return f"{expr} IS NOT NULL", []
        valore = spec.get("val")
        if valore in (None, ""):
            return "", []
        return f"{expr} = ?", [float(valore)]
    except (TypeError, ValueError):
        return "", []


def _filtro_data(expr: str, op: str, spec: dict[str, Any]) -> tuple[str, list[Any]]:
    if op == "vuoto":
        return f"({expr} IS NULL OR TRIM({expr}) = '')", []
    if op == "non_vuoto":
        return f"({expr} IS NOT NULL AND TRIM({expr}) <> '')", []
    da = str(spec.get("da") or spec.get("val") or "").strip()
    a = str(spec.get("a") or "").strip()
    condizioni = []
    valori = []
    if da:
        condizioni.append(f"date({expr}) >= date(?)")
        valori.append(da)
    if a:
        condizioni.append(f"date({expr}) <= date(?)")
        valori.append(a)
    return (" AND ".join(condizioni), valori) if condizioni else ("", [])


def _filtro_flag(expr: str, op: str, spec: dict[str, Any]) -> tuple[str, list[Any]]:
    if op == "vuoto":
        return f"({expr} IS NULL OR {expr} = '')", []
    valore = spec.get("val")
    if valore in (None, ""):
        return "", []
    if str(valore).lower() in ("0", "no", "falso", "false"):
        return f"({expr} IS NULL OR {expr} = 0 OR {expr} = '0')", []
    return f"({expr} = 1 OR {expr} = '1' OR {expr} = 'true')", []


def _filtro_lista(expr: str, op: str, spec: dict[str, Any]) -> tuple[str, list[Any]]:
    if op == "vuoto":
        return f"({expr} IS NULL OR TRIM({expr}) = '')", []
    if op == "non_vuoto":
        return f"({expr} IS NOT NULL AND TRIM({expr}) <> '')", []
    valori = spec.get("val")
    if valori is None:
        valori = []
    if isinstance(valori, str):
        valori = [valori]
    valori = [str(v) for v in valori if str(v).strip() != ""]
    if not valori:
        return "", []
    segnaposto = ",".join("?" * len(valori))
    if op == "non_in":
        return f"({expr} NOT IN ({segnaposto}) OR {expr} IS NULL)", valori
    return f"{expr} IN ({segnaposto})", valori


# ---------------------------------------------------------------------------
# Query principale
# ---------------------------------------------------------------------------
def listino_effettivo(listino: str | None) -> str:
    """Nome del listino da usare per la colonna prezzo."""
    if listino:
        return listino
    riga = db.query_one("SELECT nome_listino FROM listini ORDER BY nome_listino LIMIT 1")
    return riga["nome_listino"] if riga else "DEFAULT"


def _from_base(listino: str) -> tuple[str, list[Any]]:
    """Clausola FROM con i join verso marche e listini."""
    return (
        """FROM articoli a
             LEFT JOIN marche m
                    ON m.codice = a.codice_marca AND m.azienda = a.azienda
             LEFT JOIN listini l
                    ON l.codice_articolo = a.codice
                   AND l.azienda = a.azienda
                   AND l.nome_listino = ?""",
        [listino],
    )


_COLONNE_SELEZIONE = """a.id, a.codice, a.descrizione, a.unita_misura, a.barcode, a.azienda,
          a.codice_marca, a.campi_extra, a.campi_personalizzati,
          a.created_at, a.updated_at,
          m.descrizione AS marca_descrizione,
          l.prezzo, l.prezzo_iva, l.nome_listino, l.data_validita"""


def _select_base(listino: str) -> tuple[str, list[Any]]:
    from_sql, parametri = _from_base(listino)
    return f"SELECT {_COLONNE_SELEZIONE} {from_sql}", parametri


def _post_elabora(riga: Any, campi_custom: Sequence[dict[str, Any]]) -> dict[str, Any]:
    record = dict(riga)
    try:
        record["campi_extra"] = json.loads(record.get("campi_extra") or "{}")
    except json.JSONDecodeError:
        record["campi_extra"] = {}
    try:
        record["campi_personalizzati"] = json.loads(record.get("campi_personalizzati") or "{}")
    except json.JSONDecodeError:
        record["campi_personalizzati"] = {}
    return record


def carica_articoli(
    filtri: dict[str, Any] | None = None,
    ordinamento: str = "codice",
    direzione: str = "asc",
    pagina: int = 1,
    per_pagina: int = 50,
    campi_custom: Sequence[dict[str, Any]] | None = None,
    listino: str | None = None,
) -> RisultatoQuery:
    """Esegue la query paginata degli articoli."""
    campi_custom = campi_custom or []
    filtri = filtri or {}
    per_pagina = max(1, min(int(per_pagina or 50), 500))
    pagina = max(1, int(pagina or 1))
    listino_usato = listino_effettivo(listino)

    where, parametri_where = costruisci_where(filtri, campi_custom)
    from_sql, parametri_select = _from_base(listino_usato)
    select_sql = f"SELECT {_COLONNE_SELEZIONE} {from_sql}"
    where_sql = f" WHERE {where}" if where else ""
    tutti_parametri = list(parametri_select) + parametri_where

    totale = int(
        db.query_scalar(
            f"SELECT COUNT(*) FROM (SELECT a.id {from_sql}{where_sql})",
            tutti_parametri,
        )
        or 0
    )

    colonna_ordine = ORDINAMENTI.get(ordinamento, ORDINAMENTI["codice"])
    dir_sql = "DESC" if str(direzione).lower() == "desc" else "ASC"
    # NULL in fondo in entrambi i casi
    ordine_sql = f"ORDER BY {colonna_ordine} IS NULL, {colonna_ordine} {dir_sql}, a.id ASC"

    righe = db.query_all(
        f"""{select_sql}{where_sql} {ordine_sql} LIMIT ? OFFSET ?""",
        tutti_parametri + [per_pagina, (pagina - 1) * per_pagina],
    )

    risultato = RisultatoQuery(
        righe=[_post_elabora(r, campi_custom) for r in righe],
        totale=totale,
        pagina=pagina,
        per_pagina=per_pagina,
        pagine=max(1, (totale + per_pagina - 1) // per_pagina),
    )
    return risultato


def carica_tutti_articoli(
    filtri: dict[str, Any] | None = None,
    ordinamento: str = "codice",
    direzione: str = "asc",
    campi_custom: Sequence[dict[str, Any]] | None = None,
    listino: str | None = None,
    limite: int | None = None,
) -> list[dict[str, Any]]:
    """Tutte le righe che corrispondono ai filtri (per l'esportazione)."""
    campi_custom = campi_custom or []
    filtri = filtri or {}
    listino_usato = listino_effettivo(listino)

    where, parametri_where = costruisci_where(filtri, campi_custom)
    from_sql, parametri_select = _from_base(listino_usato)
    select_sql = f"SELECT {_COLONNE_SELEZIONE} {from_sql}"
    where_sql = f" WHERE {where}" if where else ""
    colonna_ordine = ORDINAMENTI.get(ordinamento, ORDINAMENTI["codice"])
    dir_sql = "DESC" if str(direzione).lower() == "desc" else "ASC"
    limit_sql = ""
    parametri_extra: list[Any] = []
    if limite:
        limit_sql = " LIMIT ?"
        parametri_extra = [limite]

    righe = db.query_all(
        f"""{select_sql}{where_sql}
             ORDER BY {colonna_ordine} IS NULL, {colonna_ordine} {dir_sql}, a.id ASC{limit_sql}""",
        list(parametri_select) + parametri_where + parametri_extra,
    )
    return [_post_elabora(r, campi_custom) for r in righe]
