"""Test del parser CSV/XLSX: encoding, separatori, padding, numeri, malformati."""
from __future__ import annotations

import io

import pytest

from app.importers.parsing import (
    clean_cell,
    format_decimal,
    format_int,
    parse_csv_text,
    parse_decimal,
    read_source,
    sniff_delimiter,
    sniff_encoding,
)

ESEMPIO_ART = (
    '"8194700        ";"KIT GUAINA 4MT X FILO FE/INOX D.0,6/0,8           ";"Pz.  ";"1";'
    '"00000001.000";"00000000000";"EUCOMO  ";"   ";"74 ";"00000000.000";" ";"1";'
)

ESEMPIO_LIB = (
    '"8194700        ";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
    '"000000000.0000000";"000000018.0000000";"0000.000";"0000.000";"0000.000";'
    '"000000018.0000000";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
    '"000000000.0000000";"EUCOMO  ";\n'
)


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------
def test_sniff_encoding_utf8():
    testo, codifica = sniff_encoding("caffè".encode("utf-8"))
    assert codifica == "utf-8"
    assert testo == "caffè"


def test_sniff_encoding_utf8_bom():
    testo, codifica = sniff_encoding("caffè".encode("utf-8-sig"))
    assert codifica == "utf-8-sig"
    assert testo == "caffè"


def test_sniff_encoding_latin1():
    # 0xE8 = 'è' in Latin-1, non valido in UTF-8
    testo, codifica = sniff_encoding("caffè".encode("latin-1"))
    assert codifica in ("cp1252", "latin-1")
    assert "caff" in testo


def test_sniff_encoding_su_file_di_esempio():
    with open("examples/COSMOART.csv", "rb") as fh:
        _testo, codifica = sniff_encoding(fh.read())
    assert codifica in ("utf-8", "utf-8-sig")


# ---------------------------------------------------------------------------
# Separatore
# ---------------------------------------------------------------------------
def test_sniff_delimitatore_punto_e_virgola():
    assert sniff_delimiter(ESEMPIO_ART) == ";"


def test_separatore_virgola():
    assert sniff_delimiter("a,b,c\n1,2,3\n") == ","


def test_la_virgola_dentro_le_virgolette_non_conta():
    """Le descrizioni contengono virgole: non devono falsare il rilevamento."""
    testo = '"KIT GUAINA D.0,6/0,8";"altro, con virgole"\n'
    assert sniff_delimiter(testo) == ";"


def test_separatore_misto_senza_virgolette():
    testo = "a;b;c\n1;2;3\n"
    assert sniff_delimiter(testo) == ";"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_parse_trae_colonna_fantasma():
    """Il `;` finale di ogni riga crea una colonna vuota: va rimossa."""
    risultato = parse_csv_text(ESEMPIO_ART)
    assert risultato.trailing_empty_stripped is True
    assert risultato.n_columns == 12
    assert risultato.rows[0][0] == "8194700        "
    assert risultato.rows[0][8] == "74 "


def test_parse_senza_colonna_fantasma():
    testo = '"a";"b"\n"1";"2"\n'
    risultato = parse_csv_text(testo)
    assert risultato.trailing_empty_stripped is False
    assert risultato.n_columns == 2


def test_parse_righe_malformate():
    testo = '"a";"b";"c"\n"1";"2"\n"3";"4";"5"\n'
    risultato = parse_csv_text(testo)
    assert len(risultato.malformed_rows) == 1
    assert risultato.malformed_rows[0][1] == 2


def test_parse_gestisce_riga_vuota():
    testo = '"a";"b"\n\n"1";"2"\n\n'
    risultato = parse_csv_text(testo)
    assert len(risultato.rows) == 2


def test_parse_riga_con_delimitatore_dentro_le_virgolette():
    testo = '"a;b";"c"\n'
    risultato = parse_csv_text(testo)
    assert risultato.rows[0][0] == "a;b"


def test_parse_doppi_apici_interni():
    testo = '"a""b";"c"\n'
    risultato = parse_csv_text(testo)
    assert risultato.rows[0][0] == 'a"b'


# ---------------------------------------------------------------------------
# Pulizia e numeri
# ---------------------------------------------------------------------------
def test_clean_cell_rimuove_padding():
    assert clean_cell("8194700        ") == "8194700"
    assert clean_cell("Pz.  ") == "Pz."
    assert clean_cell("   ") == ""
    assert clean_cell(None) == ""


def test_clean_cell_conserva_spazi_interni():
    """Gli spazi interni al dato originale non devono essere alterati."""
    assert clean_cell("LAVAPISTOLE  MANUALE") == "LAVAPISTOLE  MANUALE"
    assert clean_cell("A\nB") == "A\nB"


@pytest.mark.parametrize(
    "grezzo,atteso",
    [
        ("000000018.0000000", 18.0),
        ("0000.000", 0.0),
        ("00000001.000", 1.0),
        ("1.234,56", 1234.56),
        ("1,50", 1.5),
        ("-12,75", -12.75),
        ("18", 18.0),
        ("", None),
        (None, None),
        ("abc", None),
        ("1.234.567,89", 1234567.89),
    ],
)
def test_parse_decimal(grezzo, atteso):
    assert parse_decimal(grezzo) == atteso


def test_format_decimal_riproduce_formato_cosmo():
    assert format_decimal(18.0, 9, 7) == "000000018.0000000"
    assert format_decimal(0.0, 4, 3) == "0000.000"
    assert format_decimal(1.0, 8, 3) == "00000001.000"
    assert format_decimal(1422.9, 9, 7) == "000001422.9000000"


def test_format_int():
    assert format_int(8194700, 11) == "00008194700"
    assert format_int(1, 1) == "1"


# ---------------------------------------------------------------------------
# Sorgenti
# ---------------------------------------------------------------------------
def test_read_source_csv():
    sorgente = read_source(ESEMPIO_LIB.encode("utf-8"), "COSMOLIB.csv")
    assert sorgente.formato == "csv"
    assert sorgente.n_columns == 17
    assert sorgente.rows[0][6] == "000000018.0000000"


def test_read_source_xlsx(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    foglio = wb.active
    foglio.append(["codice", "prezzo"])
    foglio.append(["123", 18.5])
    foglio.append(["456", 20.0])
    buffer = io.BytesIO()
    wb.save(buffer)

    sorgente = read_source(buffer.getvalue(), "listini.xlsx")
    assert sorgente.formato == "xlsx"
    assert sorgente.rows[0] == ["codice", "prezzo"]
    assert sorgente.rows[1][0] == "123"
    assert float(sorgente.rows[1][1]) == 18.5


def test_read_source_xlsx_riga_vuota_trascurata():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    foglio = wb.active
    foglio.append(["a"])
    foglio.append([])
    buffer = io.BytesIO()
    wb.save(buffer)
    sorgente = read_source(buffer.getvalue(), "x.xlsx")
    assert len(sorgente.rows) == 1
