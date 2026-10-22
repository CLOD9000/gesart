"""Motore di importazione: staging, anteprima, validazione e commit.

Flusso:
  1. `salva_staging()` salva il file caricato in <DATA_DIR>/staging con un
     token univoco; il file resta li' finche' non e' importato (o scade).
  2. `analizza()` legge il file, applica la mappa delle colonne e produce
     un'anteprima con anteprima dei primi N record + elenco errori.
  3. `commit_import()` riapre il file in staging, applica la strategia
     scelta e registra il log in `log_importazioni`.

Nessuna scrittura sul database avviene durante l'anteprima.
"""
from __future__ import annotations

import json
import secrets
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .. import db
from ..config import settings
from ..security import build_search_blob
from . import mapping
from .mapping import (
    TIPO_NUMERO,
    CampoTarget,
    campi_per_tipo,
    profilo_per_tipo,
)
from .parsing import (
    SourceTable,
    clean_cell,
    format_decimal,
    format_int,
    parse_decimal,
    read_source,
)

# Strategie di aggiornamento per gli articoli.
STRATEGIA_UPSERT = "upsert"
STRATEGIA_SOLO_INSERIMENTO = "solo_inserimento"
STRATEGIA_SOLO_CAMPI_VUOTI = "solo_campi_vuoti"
STRATEGIE = (STRATEGIA_UPSERT, STRATEGIA_SOLO_INSERIMENTO, STRATEGIA_SOLO_CAMPI_VUOTI)

# Tipi di errore rilevati.
ERR_CAMPO_MANCANTE = "campo_mancante"
ERR_DUPLICATO_FILE = "duplicato_file"
ERR_ESISTENTE = "esistente"
ERR_MARCA_INESISTENTE = "marca_inesistente"
ERR_RIGA_MALFORMATA = "riga_malformata"
ERR_FORMATO_NON_VALIDO = "formato_non_valido"
ERR_ARTICOLO_INESISTENTE = "articolo_inesistente"
ERR_LISTINO_SCONOSCIUTO = "listino_sconosciuto"

DESCRIZIONE_ERRORI = {
    ERR_CAMPO_MANCANTE: "Campo obbligatorio mancante",
    ERR_DUPLICATO_FILE: "Codice duplicato nel file",
    ERR_ESISTENTE: "Record gia' presente nel database",
    ERR_MARCA_INESISTENTE: "Codice marca non presente in anagrafica",
    ERR_RIGA_MALFORMATA: "Numero di colonne non coerente",
    ERR_FORMATO_NON_VALIDO: "Valore numerico non valido",
    ERR_ARTICOLO_INESISTENTE: "Articolo non presente in anagrafica",
    ERR_LISTINO_SCONOSCIUTO: "Nome listino non valido",
}


@dataclass
class ErroreImport:
    riga: int
    codice: str
    tipo: str
    messaggio: str
    valore: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Anteprima:
    tipo: str
    file: str
    formato: str
    encoding: str
    delimiter: str
    n_colonne: int
    totale_righe: int
    colonne: list[dict[str, Any]] = field(default_factory=list)
    mappa: dict[str, int] = field(default_factory=dict)
    campi: list[CampoTarget] = field(default_factory=list)
    record: list[dict[str, Any]] = field(default_factory=list)
    errori: list[ErroreImport] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    riga_intestazione: bool = False
    strategia: str = STRATEGIA_UPSERT


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------
def _staging_path(token: str) -> Path:
    return settings.staging_dir / f"{token}.dat"


def _staging_meta_path(token: str) -> Path:
    return settings.staging_dir / f"{token}.json"


def salva_staging(raw: bytes, filename: str, tipo: str, strategia: str = STRATEGIA_UPSERT) -> str:
    """Salva il file caricato in staging e restituisce il token."""
    settings.staging_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(16)
    _staging_path(token).write_bytes(raw)
    meta = {
        "token": token,
        "file": filename,
        "tipo": tipo,
        "strategia": strategia if strategia in STRATEGIE else STRATEGIA_UPSERT,
        "creato": datetime.now(timezone.utc).isoformat(),
    }
    _staging_meta_path(token).write_text(json.dumps(meta), encoding="utf-8")
    return token


def leggi_staging(token: str) -> tuple[bytes, dict[str, Any]] | None:
    path = _staging_path(token)
    meta_path = _staging_meta_path(token)
    if not path.exists() or not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return path.read_bytes(), meta


def elimina_staging(token: str) -> None:
    for path in (_staging_path(token), _staging_meta_path(token)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def pulisci_staging_scaduti() -> int:
    """Rimuove i file in staging piu' vecchi di TTL. Restituisce quanti rimossi."""
    if not settings.staging_dir.exists():
        return 0
    limite = datetime.now(timezone.utc) - timedelta(hours=settings.staging_ttl_hours)
    rimossi = 0
    for meta_path in settings.staging_dir.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            creato = datetime.fromisoformat(meta["creato"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if creato < limite:
            elimina_staging(meta_path.stem)
            rimossi += 1
    return rimossi


# ---------------------------------------------------------------------------
# Normalizzazione record
# ---------------------------------------------------------------------------
def _valore_campo(tipo_campo: str, raw: str) -> Any:
    """Converte il valore grezzo nel tipo del campo target."""
    testo = clean_cell(raw)
    if tipo_campo == TIPO_NUMERO:
        return parse_decimal(testo)
    if tipo_campo == "data":
        return _normalizza_data(testo)
    if tipo_campo == "flag":
        return 1 if testo.lower() in ("1", "si", "s", "true", "yes", "x") else 0
    return testo


def _normalizza_data(testo: str) -> str:
    """Normalizza una data in ISO (YYYY-MM-DD). Stringa vuota se non interpretabile."""
    if not testo:
        return ""
    import re

    for pattern, ordine in (
        (r"^(\d{4})-(\d{2})-(\d{2})", "ymd"),
        (r"^(\d{2})/(\d{2})/(\d{4})$", "dmy"),
        (r"^(\d{4})/(\d{2})/(\d{2})$", "ymd"),
    ):
        match = re.match(pattern, testo)
        if match:
            a, b, c = match.groups()
            if ordine == "dmy":
                return f"{c}-{b}-{a}"
            return f"{a}-{b}-{c}"
    return ""


def _estrai_campi_extra(riga: Sequence[str], mappa: dict[str, int]) -> dict[str, str]:
    """Colonne non mappate, conservate per indice (1-based) come stringa."""
    usate = set(mappa.values())
    extra: dict[str, str] = {}
    for idx, valore in enumerate(riga, start=1):
        if idx in usate:
            continue
        testo = clean_cell(valore)
        if testo != "":
            extra[str(idx)] = testo
    return extra


def _estrai_campi_personalizzati(
    riga: Sequence[str], campi_custom: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    """Valori dei campi personalizzati: per default si cercano nelle colonne
    non mappate, abbinandole per nome/posizione (le definizioni riportano
    l'indice della colonna sorgente in `colonna`)."""
    valori: dict[str, Any] = {}
    for campo in campi_custom:
        idx = campo.get("colonna")
        raw = ""
        if idx:
            pos = int(idx) - 1
            if 0 <= pos < len(riga):
                raw = riga[pos]
        elif campo.get("etichetta"):
            # fallback: cerca una colonna il cui nome corrisponde all'etichetta
            etichetta = str(campo["etichetta"]).strip().lower()
            for pos, valore in enumerate(riga, start=1):
                if clean_cell(valore).strip().lower() == etichetta:
                    raw = valore
                    break
        tipo = str(campo.get("tipo", "testo"))
        valore = _valore_campo(tipo, raw)
        if valore not in (None, ""):
            valori[str(campo["chiave"])] = valore
    return valori


# ---------------------------------------------------------------------------
# Campi personalizzati
# ---------------------------------------------------------------------------
def carica_campi_personalizzati(solo_attivi: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM campi_personalizzati"
    if solo_attivi:
        sql += " WHERE attivo = 1"
    sql += " ORDER BY ordine, id"
    righe = db.query_all(sql)
    risultato = []
    for riga in righe:
        item = dict(riga)
        try:
            item["opzioni"] = json.loads(item["opzioni"] or "[]")
        except json.JSONDecodeError:
            item["opzioni"] = []
        item["obbligatorio"] = bool(item["obbligatorio"])
        item["attivo"] = bool(item["attivo"])
        risultato.append(item)
    return risultato


# ---------------------------------------------------------------------------
# Analisi / anteprima
# ---------------------------------------------------------------------------
def _colonne_descrizione(source: SourceTable, mappa: dict[str, int]) -> list[dict[str, Any]]:
    inverse = {v: k for k, v in mappa.items()}
    colonne = []
    for idx in range(1, source.n_columns + 1):
        campioni = [clean_cell(r[idx - 1]) for r in source.rows[:20] if idx - 1 < len(r)]
        campioni = [c for c in campioni if c]
        colonne.append(
            {
                "indice": idx,
                "etichetta": inverse.get(idx, f"Colonna {idx}"),
                "mappata": idx in inverse,
                "campione": campioni[0] if campioni else "",
                "non_vuoti": sum(1 for c in campioni if c),
            }
        )
    return colonne


def analizza(
    raw: bytes,
    filename: str,
    tipo: str,
    mappa: dict[str, int] | None = None,
    strategia: str = STRATEGIA_UPSERT,
    campi_custom: Sequence[dict[str, Any]] | None = None,
    anteprima_rimostra: int = 20,
) -> Anteprima:
    """Analizza il file e produce l'anteprima con gli errori rilevati."""
    source = read_source(raw, filename)
    campi = campi_per_tipo(tipo)
    if mappa is None:
        mappa = mapping.auto_mapping(tipo, source.n_columns)

    mappa = {k: int(v) for k, v in mappa.items() if v}

    campi_custom = campi_custom if campi_custom is not None else carica_campi_personalizzati()

    risultato = Anteprima(
        tipo=tipo,
        file=filename,
        formato=source.formato,
        encoding=source.encoding,
        delimiter=source.delimiter,
        n_colonne=source.n_columns,
        totale_righe=len(source.rows),
        mappa=mappa,
        campi=list(campi),
        colonne=_colonne_descrizione(source, mappa),
        strategia=strategia,
    )

    record_normalizzati, errori = _normalizza_e_valida(source, tipo, mappa, campi_custom)
    risultato.errori = errori
    risultato.record = record_normalizzati[:anteprima_rimostra]
    risultato.stats = _statistiche(risultato, record_normalizzati, errori)
    return risultato


def _normalizza_e_valida(
    source: SourceTable,
    tipo: str,
    mappa: dict[str, int],
    campi_custom: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[ErroreImport]]:
    """Converte le righe in record normalizzati e raccoglie gli errori."""
    errori: list[ErroreImport] = []
    record: list[dict[str, Any]] = []
    visti: set[tuple[str, str]] = set()
    n_colonne_attese = source.n_columns

    campi = {c.chiave: c for c in campi_per_tipo(tipo)}

    # Codici marca presenti in anagrafica (per validare in anticipo).
    marche_inesistenti: set[str] = set()
    if tipo == "articoli":
        marche_inesistenti = _marche_mancanti(source, mappa)

    for indice_riga, riga in enumerate(source.rows, start=1):
        if not any(clean_cell(c) for c in riga):
            continue  # riga vuota
        if len(riga) != n_colonne_attese:
            errori.append(
                ErroreImport(
                    riga=indice_riga,
                    codice=clean_cell(riga[0]) if riga else "",
                    tipo=ERR_RIGA_MALFORMATA,
                    messaggio=f"Attese {n_colonne_attese} colonne, trovate {len(riga)}",
                )
            )
            continue

        valori: dict[str, Any] = {}
        errori_riga: list[ErroreImport] = []
        for chiave, campo in campi.items():
            idx = mappa.get(chiave)
            raw = riga[idx - 1] if idx and 0 < idx <= len(riga) else ""
            valore = _valore_campo(campo.tipo, raw)
            if campo.tipo == TIPO_NUMERO and clean_cell(raw) != "" and valore is None:
                errori_riga.append(
                    ErroreImport(
                        riga=indice_riga,
                        codice=clean_cell(riga[0]) if riga else "",
                        tipo=ERR_FORMATO_NON_VALIDO,
                        messaggio=f"Valore non numerico per '{campo.etichetta}'",
                        valore=clean_cell(raw),
                    )
                )
            valori[chiave] = valore
            if campo.obbligatorio and (valore is None or str(valore).strip() == ""):
                errori_riga.append(
                    ErroreImport(
                        riga=indice_riga,
                        codice=clean_cell(riga[0]) if riga else "",
                        tipo=ERR_CAMPO_MANCANTE,
                        messaggio=f"Campo obbligatorio '{campo.etichetta}' mancante",
                    )
                )

        codice = str(valori.get("codice") or valori.get("codice_articolo") or "")
        azienda = str(valori.get("azienda") or settings.default_azienda or "")

        if tipo == "articoli" and codice and azienda:
            chiave = (codice, azienda)
            if chiave in visti:
                errori_riga.append(
                    ErroreImport(
                        riga=indice_riga,
                        codice=codice,
                        tipo=ERR_DUPLICATO_FILE,
                        messaggio="Codice articolo gia' presente nel file caricato",
                    )
                )
            visti.add(chiave)

        if tipo == "articoli":
            codice_marca = str(valori.get("codice_marca") or "")
            if codice_marca and codice_marca in marche_inesistenti:
                errori_riga.append(
                    ErroreImport(
                        riga=indice_riga,
                        codice=codice,
                        tipo=ERR_MARCA_INESISTENTE,
                        messaggio=f"Marca '{codice_marca}' non presente in anagrafica",
                        valore=codice_marca,
                    )
                )

        if errori_riga:
            errori.extend(errori_riga)
            continue

        valori["_riga"] = indice_riga
        valori["_azienda"] = azienda
        valori["_campi_extra"] = _estrai_campi_extra(riga, mappa)
        valori["_campi_personalizzati"] = _estrai_campi_personalizzati(riga, campi_custom)
        record.append(valori)

    return record, errori


def _marche_mancanti(source: SourceTable, mappa: dict[str, int]) -> set[str]:
    """Codici marca presenti nel file ma assenti dall'anagrafica."""
    idx = mappa.get("codice_marca")
    if not idx:
        return set()
    codici = {
        clean_cell(r[idx - 1])
        for r in source.rows
        if idx - 1 < len(r) and clean_cell(r[idx - 1])
    }
    if not codici:
        return set()
    presenti = set()
    codici_ordinati = sorted(codici)
    for i in range(0, len(codici_ordinati), 400):
        blocco = codici_ordinati[i : i + 400]
        segnaposto = ",".join("?" * len(blocco))
        for riga in db.query_all(
            f"SELECT DISTINCT codice FROM marche WHERE codice IN ({segnaposto})", blocco
        ):
            presenti.add(riga["codice"])
    return codici - presenti


def _statistiche(
    anteprima: Anteprima,
    record: Sequence[dict[str, Any]],
    errori: Sequence[ErroreImport],
) -> dict[str, int]:
    """Calcola le statistiche (inseriti/aggiornati/scartati) per l'anteprima."""
    inseriti = 0
    aggiornati = 0
    # Gli scarti si contano per riga distinta: una riga con due errori resta uno scarto.
    righe_scartate = {e.riga for e in errori}
    scartati = len(righe_scartate)

    if anteprima.tipo == "marche":
        esistenti = _codici_esistenti("marche", [(r["codice"], r["_azienda"]) for r in record])
        for record_ in record:
            if (record_["codice"], record_["_azienda"]) in esistenti:
                aggiornati += 1
            else:
                inseriti += 1
    elif anteprima.tipo == "articoli":
        esistenti = _codici_esistenti("articoli", [(r["codice"], r["_azienda"]) for r in record])
        for record_ in record:
            if (record_["codice"], record_["_azienda"]) in esistenti:
                if anteprima.strategia == STRATEGIA_SOLO_INSERIMENTO:
                    scartati += 1
                else:
                    aggiornati += 1
            else:
                inseriti += 1
    else:  # listini
        esistenti = _listini_esistenti(
            [
                (
                    record_["codice_articolo"],
                    record_["_azienda"],
                    record_.get("nome_listino") or "DEFAULT",
                )
                for record_ in record
            ]
        )
        for record_ in record:
            chiave = (
                record_["codice_articolo"],
                record_["_azienda"],
                record_.get("nome_listino") or "DEFAULT",
            )
            if chiave in esistenti:
                if anteprima.strategia == STRATEGIA_SOLO_INSERIMENTO:
                    scartati += 1
                else:
                    aggiornati += 1
            else:
                inseriti += 1

    return {
        "inseriti": inseriti,
        "aggiornati": aggiornati,
        "scartati": scartati,
        "totale": anteprima.totale_righe,
        "validi": len(record),
        "righe_con_errori": len(righe_scartate),
    }


def _codici_esistenti(tabella: str, chiavi: Sequence[tuple[str, str]]) -> set[tuple[str, str]]:
    if not chiavi:
        return set()
    codici = sorted({c for c, _ in chiavi if c})
    aziende = sorted({a for _, a in chiavi})
    if not codici:
        return set()
    presenti: set[tuple[str, str]] = set()
    for i in range(0, len(codici), 400):
        blocco = codici[i : i + 400]
        segnaposto = ",".join("?" * len(blocco))
        for riga in db.query_all(
            f"SELECT codice, azienda FROM {tabella} WHERE codice IN ({segnaposto})", blocco
        ):
            presenti.add((riga["codice"], riga["azienda"]))
    return {chiave for chiave in chiavi if chiave in presenti}


def _listini_esistenti(chiavi: Sequence[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    if not chiavi:
        return set()
    codici = sorted({c for c, _, _ in chiavi if c})
    presenti: set[tuple[str, str, str]] = set()
    for i in range(0, len(codici), 400):
        blocco = codici[i : i + 400]
        segnaposto = ",".join("?" * len(blocco))
        for riga in db.query_all(
            f"""SELECT codice_articolo, azienda, nome_listino FROM listini
                WHERE codice_articolo IN ({segnaposto})""",
            blocco,
        ):
            presenti.add((riga["codice_articolo"], riga["azienda"], riga["nome_listino"]))
    return {chiave for chiave in chiavi if chiave in presenti}


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------
def commit_import(
    raw: bytes,
    filename: str,
    tipo: str,
    mappa: dict[str, int] | None = None,
    strategia: str = STRATEGIA_UPSERT,
    utente_id: int | None = None,
    campi_custom: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Esegue l'importazione e registra il log. Ritorna il riepilogo."""
    source = read_source(raw, filename)
    campi = campi_per_tipo(tipo)
    if mappa is None:
        mappa = mapping.auto_mapping(tipo, source.n_columns)
    mappa = {k: int(v) for k, v in mappa.items() if v}
    if campi_custom is None:
        campi_custom = carica_campi_personalizzati()

    record, errori = _normalizza_e_valida(source, tipo, mappa, campi_custom)

    # In commit i record con errori vengono scartati (ma restano nel log).
    # Gli scarti si contano per riga distinta: una riga con due errori resta uno scarto.
    inseriti = 0
    aggiornati = 0
    scartati = len({e.riga for e in errori})

    if tipo == "marche":
        inseriti, aggiornati, scartati_gia = _commit_marche(record, strategia)
    elif tipo == "articoli":
        inseriti, aggiornati, scartati_gia = _commit_articoli(record, strategia)
    else:
        inseriti, aggiornati, scartati_gia = _commit_listini(record, strategia)
    scartati += scartati_gia

    riepilogo = {
        "file": filename,
        "tipo": tipo,
        "formato": source.formato,
        "strategia": strategia,
        "righe_totali": len(source.rows),
        "inseriti": inseriti,
        "aggiornati": aggiornati,
        "scartati": scartati,
        "errori": [e.to_dict() for e in errori],
        "encoding": source.encoding,
        "delimiter": source.delimiter,
        "mappa": mappa,
    }

    _registra_log(riepilogo, utente_id)
    return riepilogo


def _ora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _commit_marche(
    record: Sequence[dict[str, Any]], strategia: str
) -> tuple[int, int, int]:
    """Restituisce (inseriti, aggiornati, scartati_gia_esistenti)."""
    inseriti = 0
    aggiornati = 0
    scartati = 0
    for record_ in record:
        codice = record_["codice"]
        azienda = record_["_azienda"]
        esistente = db.query_one(
            "SELECT id FROM marche WHERE codice = ? AND azienda = ?", (codice, azienda)
        )
        if esistente:
            if strategia == STRATEGIA_SOLO_INSERIMENTO:
                continue
            if strategia == STRATEGIA_SOLO_CAMPI_VUOTI:
                db.execute(
                    """UPDATE marche SET descrizione = CASE WHEN TRIM(descrizione) = '' THEN ?
                            ELSE descrizione END,
                              updated_at = ? WHERE id = ?""",
                    (record_["descrizione"], _ora(), esistente["id"]),
                )
            else:
                db.execute(
                    """UPDATE marche SET descrizione = ?, updated_at = ? WHERE id = ?""",
                    (record_["descrizione"], _ora(), esistente["id"]),
                )
            aggiornati += 1
        else:
            db.execute(
                """INSERT INTO marche (codice, descrizione, azienda, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (codice, record_["descrizione"], azienda, _ora(), _ora()),
            )
            inseriti += 1
    return inseriti, aggiornati, scartati


def _commit_articoli(
    record: Sequence[dict[str, Any]], strategia: str
) -> tuple[int, int, int]:
    """Restituisce (inseriti, aggiornati, scartati_gia_esistenti)."""
    inseriti = 0
    aggiornati = 0
    scartati = 0
    for record_ in record:
        codice = record_["codice"]
        azienda = record_["_azienda"]
        campi_extra = json.dumps(record_["_campi_extra"], ensure_ascii=False)
        campi_pers = json.dumps(record_.get("_campi_personalizzati") or {}, ensure_ascii=False)
        descrizione = record_.get("descrizione") or ""
        unita = record_.get("unita_misura") or ""
        barcode = record_.get("barcode") or ""
        codice_marca = record_.get("codice_marca") or ""

        esistente = db.query_one(
            "SELECT * FROM articoli WHERE codice = ? AND azienda = ?", (codice, azienda)
        )
        if esistente:
            if strategia == STRATEGIA_SOLO_INSERIMENTO:
                scartati += 1
                continue
            if strategia == STRATEGIA_SOLO_CAMPI_VUOTI:
                # Aggiorna solo i campi attualmente vuoti nel DB.
                db.execute(
                    """UPDATE articoli SET
                         descrizione  = CASE WHEN TRIM(descrizione)  = '' THEN ? ELSE descrizione END,
                         unita_misura = CASE WHEN TRIM(unita_misura) = '' THEN ? ELSE unita_misura END,
                         barcode      = CASE WHEN TRIM(barcode)      = '' THEN ? ELSE barcode END,
                         codice_marca = CASE WHEN TRIM(codice_marca) = '' THEN ? ELSE codice_marca END,
                         campi_extra  = ?,
                         campi_personalizzati = ?,
                         search_blob  = ?,
                         updated_at   = ?
                       WHERE id = ?""",
                    (
                        descrizione,
                        unita,
                        barcode,
                        codice_marca,
                        campi_extra,
                        campi_pers,
                        build_search_blob(
                            codice, descrizione, barcode, codice_marca
                        ),
                        _ora(),
                        esistente["id"],
                    ),
                )
            else:
                db.execute(
                    """UPDATE articoli SET
                         descrizione = ?, unita_misura = ?, barcode = ?, codice_marca = ?,
                         campi_extra = ?, campi_personalizzati = ?, search_blob = ?, updated_at = ?
                       WHERE id = ?""",
                    (
                        descrizione,
                        unita,
                        barcode,
                        codice_marca,
                        campi_extra,
                        campi_pers,
                        build_search_blob(codice, descrizione, barcode, codice_marca),
                        _ora(),
                        esistente["id"],
                    ),
                )
            aggiornati += 1
        else:
            db.execute(
                """INSERT INTO articoli
                     (codice, descrizione, unita_misura, barcode, azienda, codice_marca,
                      campi_extra, campi_personalizzati, search_blob, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    codice,
                    descrizione,
                    unita,
                    barcode,
                    azienda,
                    codice_marca,
                    campi_extra,
                    campi_pers,
                    build_search_blob(codice, descrizione, barcode, codice_marca),
                    _ora(),
                    _ora(),
                ),
            )
            inseriti += 1
    return inseriti, aggiornati, scartati


def _commit_listini(
    record: Sequence[dict[str, Any]], strategia: str
) -> tuple[int, int, int]:
    """Restituisce (inseriti, aggiornati, scartati_gia_esistenti)."""
    inseriti = 0
    aggiornati = 0
    scartati = 0
    for record_ in record:
        codice = record_["codice_articolo"]
        azienda = record_["_azienda"]
        nome_listino = record_.get("nome_listino") or "DEFAULT"
        prezzo = record_.get("prezzo")
        prezzo_iva = record_.get("prezzo_iva")
        data_validita = record_.get("data_validita") or None
        campi_extra = json.dumps(record_["_campi_extra"], ensure_ascii=False)

        esistente = db.query_one(
            """SELECT id FROM listini
                WHERE codice_articolo = ? AND azienda = ? AND nome_listino = ?""",
            (codice, azienda, nome_listino),
        )
        if esistente:
            if strategia == STRATEGIA_SOLO_INSERIMENTO:
                scartati += 1
                continue
            if strategia == STRATEGIA_SOLO_CAMPI_VUOTI:
                db.execute(
                    """UPDATE listini SET
                         prezzo = CASE WHEN prezzo IS NULL THEN ? ELSE prezzo END,
                         prezzo_iva = CASE WHEN prezzo_iva IS NULL THEN ? ELSE prezzo_iva END,
                         data_validita = CASE WHEN data_validita IS NULL THEN ? ELSE data_validita END,
                         campi_extra = ?, updated_at = ? WHERE id = ?""",
                    (prezzo, prezzo_iva, data_validita, campi_extra, _ora(), esistente["id"]),
                )
            else:
                db.execute(
                    """UPDATE listini SET prezzo = ?, prezzo_iva = ?, data_validita = ?,
                         campi_extra = ?, updated_at = ? WHERE id = ?""",
                    (prezzo, prezzo_iva, data_validita, campi_extra, _ora(), esistente["id"]),
                )
            aggiornati += 1
        else:
            db.execute(
                """INSERT INTO listini
                     (codice_articolo, azienda, nome_listino, prezzo, prezzo_iva,
                      data_validita, campi_extra, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    codice,
                    azienda,
                    nome_listino,
                    prezzo,
                    prezzo_iva,
                    data_validita,
                    campi_extra,
                    _ora(),
                    _ora(),
                ),
            )
            inseriti += 1
    return inseriti, aggiornati, scartati


def _registra_log(riepilogo: dict[str, Any], utente_id: int | None) -> int:
    dettaglio = {
        "encoding": riepilogo.get("encoding"),
        "delimiter": riepilogo.get("delimiter"),
        "mappa": riepilogo.get("mappa"),
    }
    cur = db.execute(
        """INSERT INTO log_importazioni
             (file, tipo, formato, strategia, stato, righe_totali, inseriti,
              aggiornati, scartati, errori, dettaglio, utente_id)
           VALUES (?, ?, ?, ?, 'completata', ?, ?, ?, ?, ?, ?, ?)""",
        (
            riepilogo["file"],
            riepilogo["tipo"],
            riepilogo["formato"],
            riepilogo["strategia"],
            riepilogo["righe_totali"],
            riepilogo["inseriti"],
            riepilogo["aggiornati"],
            riepilogo["scartati"],
            json.dumps(riepilogo["errori"], ensure_ascii=False),
            json.dumps(dettaglio, ensure_ascii=False),
            utente_id,
        ),
    )
    return int(cur.lastrowid)


# ---------------------------------------------------------------------------
# Report errori CSV
# ---------------------------------------------------------------------------
def report_errori_csv(errori: Iterable[dict[str, Any]]) -> str:
    """Genera il report CSV degli errori (separatore `;`, compatibile Excel IT)."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(["Riga", "Codice", "Tipo", "Descrizione errore", "Valore"])
    for errore in errori:
        writer.writerow(
            [
                errore.get("riga", ""),
                errore.get("codice", ""),
                DESCRIZIONE_ERRORI.get(errore.get("tipo", ""), errore.get("tipo", "")),
                errore.get("messaggio", ""),
                errore.get("valore", ""),
            ]
        )
    return buffer.getvalue()
