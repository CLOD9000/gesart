"""Parsing robusto di CSV (e XLSX) per l'importazione.

Il parser deve reggere i CSV "di sistema" tipici degli ERP:
  - ogni campo racchiuso tra doppi apici, delimitatore `;`;
  - valori a larghezza fissa con padding a destra (`"8194700        "`);
  - separatore finale di riga che produce una colonna fantasma;
  - numeri con zeri iniziali e separatore decimale `.` (`000000018.0000000`);
  - descrizioni che contengono sia `,` che `;` dentro le virgolette.

Le funzioni sono pure (nessun accesso al DB) per essere testabili.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

CANDIDATE_DELIMITERS = (";", ",", "\t", "|")
ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


# ---------------------------------------------------------------------------
# Rilevamento encoding
# ---------------------------------------------------------------------------
def sniff_encoding(raw: bytes) -> tuple[str, str]:
    """Rileva la codifica del file.

    Ritorna (testo, nome_codifica). L'ordine e' importante: `utf-8-sig`
    gestisce la BOM, `latin-1` e' l'ultimo risorsa perche' decodifica
    qualunque sequenza di byte senza errori.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError:
            pass
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


# ---------------------------------------------------------------------------
# Rilevamento separatore
# ---------------------------------------------------------------------------
def _count_outside_quotes(text: str, delimiter: str, max_lines: int = 50) -> int:
    """Conta i separatori presenti FUORI dalle virgolette.

    Le descrizioni degli articoli contengono caratteri separatori (es.
    `D.0,6/0,8`): contarli senza considerare le virgolette darebbe falsi positivi.
    """
    count = 0
    in_quotes = False
    lines = 0
    for ch in text:
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == delimiter and not in_quotes:
            count += 1
        elif ch == "\n":
            lines += 1
            if lines >= max_lines:
                break
    return count


def sniff_delimiter(text: str, candidates: Sequence[str] = CANDIDATE_DELIMITERS) -> str:
    """Sceglie il separatore piu' probabile, escludendo i valori dentro le virgolette."""
    sample = "\n".join(text.splitlines()[:50])
    scores = {d: _count_outside_quotes(sample, d) for d in candidates}
    best = max(scores, key=lambda d: (scores[d], d == ";"))
    if scores[best] == 0:
        # Nessun separatore trovato: fallback su `;` (formato di default Cosmo).
        return ";"
    # Disambigua fra `;` e `,`: in caso di parita' preferiamo il `;` perche'
    # e' il separatore usato dai file Cosmo e le descrizioni contengono piu'
    # virgole che punti e virgola.
    return best


# ---------------------------------------------------------------------------
# Parsing righe
# ---------------------------------------------------------------------------
@dataclass
class ParseResult:
    rows: list[list[str]] = field(default_factory=list)
    delimiter: str = ";"
    encoding: str = "utf-8"
    # Righe che non hanno lo stesso numero di colonne della prima riga.
    malformed_rows: list[tuple[int, int]] = field(default_factory=list)  # (indice_riga, n_colonne)
    trailing_empty_stripped: bool = False

    @property
    def n_columns(self) -> int:
        return max((len(r) for r in self.rows), default=0)


def _has_trailing_delimiter(text: str, delimiter: str) -> bool:
    """True se OGNI riga non vuota finisce con il separatore.

    E' il segnale della "colonna fantasma" generata dal `;` di fine riga.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    return all(ln.rstrip().endswith(delimiter) for ln in lines)


def parse_csv_text(text: str, delimiter: str | None = None) -> ParseResult:
    """Esegue il parsing del testo CSV in una lista di righe."""
    if delimiter is None:
        delimiter = sniff_delimiter(text)
    result = ParseResult(delimiter=delimiter)

    reader = csv.reader(
        io.StringIO(text, newline=""),
        delimiter=delimiter,
        quotechar='"',
        doublequote=True,
        skipinitialspace=False,
    )
    raw_rows = list(reader)

    # Rimuove le righe interamente vuote (spazi): non sono record.
    raw_rows = [row for row in raw_rows if any((c or "").strip() != "" for c in row)]

    if not raw_rows:
        return result

    # Colonna fantasma da separatore finale: la togliamo solo se il file
    # nel suo complesso presenta il trailing delimiter.
    if _has_trailing_delimiter(text, delimiter):
        stripped = []
        for row in raw_rows:
            if row and row[-1].strip() == "":
                row = row[:-1]
            stripped.append(row)
        raw_rows = stripped
        result.trailing_empty_stripped = True

    expected = max(len(r) for r in raw_rows)
    for idx, row in enumerate(raw_rows):
        if len(row) != expected:
            result.malformed_rows.append((idx, len(row)))
        result.rows.append(row)

    return result


def clean_cell(value: str | None) -> str:
    """Rimuove il padding a larghezza fissa dagli estremi del valore.

    NB: gli spazi interni vengono conservati (l'originale puo' contenerne
    piu' di uno) per non alterare il dato; la normalizzazione per la ricerca
    avviene in `security.normalize_text`.
    """
    if value is None:
        return ""
    return value.replace("\xa0", " ").strip()


# ---------------------------------------------------------------------------
# Parsing numerico
# ---------------------------------------------------------------------------
_EURO_INT = re.compile(r"^-?\d{1,3}(\.\d{3})+(,\d{1,2})?$")
_COMMA_DEC = re.compile(r"^-?\d+,\d{1,2}$")
_PLAIN_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def parse_decimal(value: str | None) -> float | None:
    """Converte un numero in float gestendo i formati europei e anglosassoni.

    Rischi da evitare:
      - `000000018.0000000` -> 18.0 (non 180.0!)
      - `1.234,56` -> 1234.56 (formato italiano)
      - `1,50` -> 1.5
    """
    if value is None:
        return None
    raw = clean_cell(value)
    if raw == "":
        return None
    raw = raw.replace("€", "").replace(" ", "").replace(" ", "")
    negative = raw.startswith("-")
    raw = raw.lstrip("+-")
    if raw == "":
        return None

    if _EURO_INT.match(raw):
        # Separatore migliaia `.` e decimale `,`
        raw = raw.replace(".", "").replace(",", ".")
    elif _COMMA_DEC.match(raw):
        # Virgola decimale con 1-2 cifre
        raw = raw.replace(",", ".")
    elif raw.count(",") == 1 and "." not in raw:
        parts = raw.split(",")
        raw = parts[0] + "." + parts[1] if len(parts[1]) <= 2 else parts[0] + parts[1]

    if not _PLAIN_NUM.match(raw):
        return None
    try:
        result = float(raw)
    except ValueError:
        return None
    return -result if negative else result


def parse_int(value: str | None) -> int | None:
    number = parse_decimal(value)
    return int(number) if number is not None else None


def format_decimal(value: float | None, int_digits: int, dec_digits: int) -> str:
    """Riproduce il formato numerico dei file Cosmo (zeri iniziali fissi).

    Esempio: format_decimal(18.0, 9, 7) -> '000000018.0000000'
    """
    if value is None:
        value = 0.0
    text = f"{value:.{dec_digits}f}"
    if "." in text:
        integer_part, decimal_part = text.split(".", 1)
    else:
        integer_part, decimal_part = text, ""
    sign = ""
    if integer_part.startswith("-"):
        sign = "-"
        integer_part = integer_part[1:]
    integer_part = integer_part.zfill(int_digits)
    return f"{sign}{integer_part}.{decimal_part}"


def format_int(value: int | None, digits: int) -> str:
    if value is None:
        value = 0
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value):0{digits}d}"


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------
def read_xlsx(raw: bytes) -> list[list[str]]:
    """Legge il primo foglio di un file XLSX restituendo le righe come stringhe."""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheet = workbook[workbook.sheetnames[0]]
        rows: list[list[str]] = []
        for row in sheet.iter_rows(values_only=True):
            cells = []
            for cell in row:
                if cell is None:
                    cells.append("")
                elif isinstance(cell, float):
                    # Evita la notazione scientifica e i float come 1.0
                    cells.append(repr(cell) if cell != int(cell) else str(int(cell)))
                else:
                    cells.append(str(cell))
            # Rimuove le celle None in coda (openpyxl le aggiunge a ogni riga)
            while cells and cells[-1] == "":
                cells.pop()
            if cells:
                rows.append(cells)
        return rows
    finally:
        workbook.close()


# ---------------------------------------------------------------------------
# Lettura file grezza -> righe
# ---------------------------------------------------------------------------
@dataclass
class SourceTable:
    rows: list[list[str]]
    delimiter: str
    encoding: str
    formato: str  # csv | xlsx
    malformed_rows: list[tuple[int, int]] = field(default_factory=list)
    trailing_empty_stripped: bool = False

    @property
    def n_columns(self) -> int:
        return max((len(r) for r in self.rows), default=0)

    @property
    def headers(self) -> list[str]:
        return [f"Colonna {i + 1}" for i in range(self.n_columns)]


def read_source(raw: bytes, filename: str = "") -> SourceTable:
    """Legge un file CSV o XLSX e restituisce le righe normalizzate."""
    is_xlsx = filename.lower().endswith((".xlsx", ".xlsm")) or raw[:2] == b"PK"
    if is_xlsx:
        rows = read_xlsx(raw)
        return SourceTable(
            rows=rows,
            delimiter="",
            encoding="n/a",
            formato="xlsx",
        )

    text, encoding = sniff_encoding(raw)
    parsed = parse_csv_text(text)
    return SourceTable(
        rows=parsed.rows,
        delimiter=parsed.delimiter,
        encoding=encoding,
        formato="csv",
        malformed_rows=parsed.malformed_rows,
        trailing_empty_stripped=parsed.trailing_empty_stripped,
    )


def iter_records(rows: Sequence[Sequence[str]]) -> Iterator[tuple[int, list[str]]]:
    """Itera (indice_riga_1based, riga) saltando l'eventuale riga di intestazione."""
    for index, row in enumerate(rows):
        yield index + 1, list(row)
