"""Test del motore di importazione: strategie, duplicati, errori, log."""
from __future__ import annotations

import json

import pytest

from app import db
from app.importers import service
from app.importers.mapping import auto_mapping

ESEMPI = "examples"


def leggi(nome: str) -> bytes:
    with open(f"{ESEMPI}/{nome}", "rb") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Anagrafica marche
# ---------------------------------------------------------------------------
def test_import_marche(db_pulito):
    riepilogo = service.commit_import(
        leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche", strategia="upsert"
    )
    assert riepilogo["inseriti"] == 3
    assert riepilogo["aggiornati"] == 0
    assert riepilogo["scartati"] == 0

    righe = db.query_all("SELECT * FROM marche ORDER BY codice")
    assert [r["codice"] for r in righe] == ["000", "74", "951"]
    assert righe[1]["descrizione"] == "MARCA A"
    assert righe[0]["azienda"] == "EUCOMO"


def test_import_marche_upsert_aggiorna(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    riepilogo = service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    assert riepilogo["inseriti"] == 0
    assert riepilogo["aggiornati"] == 3


def test_import_marche_solo_inserimento(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    riepilogo = service.commit_import(
        leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche", strategia="solo_inserimento"
    )
    assert riepilogo["inseriti"] == 0
    assert riepilogo["aggiornati"] == 0


# ---------------------------------------------------------------------------
# Anagrafica articoli
# ---------------------------------------------------------------------------
def test_import_articoli(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    riepilogo = service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="upsert"
    )
    assert riepilogo["inseriti"] == 7
    assert riepilogo["scartati"] == 0

    riga = db.query_one("SELECT * FROM articoli WHERE codice = '8194700'")
    assert riga is not None
    assert riga["descrizione"] == "KIT GUAINA 4MT X FILO FE/INOX D.0,6/0,8"
    assert riga["unita_misura"] == "Pz."
    assert riga["azienda"] == "EUCOMO"
    assert riga["codice_marca"] == "74"
    assert riga["barcode"] == "00000000000"


def test_import_articoli_preserva_campi_extra(db_pulito):
    """Le colonne non mappate (4, 5, 8, 10, 11, 12) non devono perdersi."""
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    riga = db.query_one("SELECT campi_extra FROM articoli WHERE codice = '8194700'")
    extra = json.loads(riga["campi_extra"])
    assert extra["4"] == "1"
    assert extra["5"] == "00000001.000"
    assert extra["10"] == "00000000.000"
    assert extra["12"] == "1"
    # Le colonne vuote non vengono memorizzate
    assert "8" not in extra
    assert "11" not in extra


def test_import_articoli_con_marca_inesistente(db_pulito):
    riepilogo = service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="upsert"
    )
    assert riepilogo["inseriti"] == 0
    assert riepilogo["scartati"] == 7
    tipi = {e["tipo"] for e in riepilogo["errori"]}
    assert "marca_inesistente" in tipi


def test_import_articoli_upsert_aggiorna(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    riepilogo = service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="upsert"
    )
    assert riepilogo["inseriti"] == 0
    assert riepilogo["aggiornati"] == 7


def test_import_articoli_solo_inserimento_scarta_esistenti(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    riepilogo = service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="solo_inserimento"
    )
    assert riepilogo["inseriti"] == 0
    assert riepilogo["aggiornati"] == 0
    assert riepilogo["scartati"] == 7


def test_import_articoli_solo_campi_vuoti(db_pulito):
    """La strategia 'solo campi vuoti' non deve sovrascrivere i dati presenti."""
    db.execute(
        """INSERT INTO articoli (codice, descrizione, unita_misura, barcode, azienda,
                                codice_marca, created_at, updated_at)
           VALUES ('8194700', 'DESCRIZIONE ORIGINALE', 'Mt', '111', 'EUCOMO', '74',
                   datetime('now'), datetime('now'))"""
    )
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="solo_campi_vuoti"
    )
    riga = db.query_one("SELECT * FROM articoli WHERE codice = '8194700'")
    assert riga["descrizione"] == "DESCRIZIONE ORIGINALE"
    assert riga["unita_misura"] == "Mt"
    assert riga["barcode"] == "111"


def test_import_articoli_upsert_sovrascrive(db_pulito):
    db.execute(
        """INSERT INTO articoli (codice, descrizione, unita_misura, barcode, azienda,
                                codice_marca, created_at, updated_at)
           VALUES ('8194700', 'VECCHIA', 'Mt', '111', 'EUCOMO', '74',
                   datetime('now'), datetime('now'))"""
    )
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(
        leggi("COSMOART.csv"), "COSMOART.csv", "articoli", strategia="upsert"
    )
    riga = db.query_one("SELECT * FROM articoli WHERE codice = '8194700'")
    assert riga["descrizione"] == "KIT GUAINA 4MT X FILO FE/INOX D.0,6/0,8"


def test_import_duplicati_nel_file(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    contenuto = (
        '"90035          ";"TUBO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"951";"0.000";" ";"1";\n'
        '"90035          ";"TUBO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"951";"0.000";" ";"1";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "dup.csv", "articoli")
    assert riepilogo["scartati"] == 1
    assert riepilogo["inseriti"] == 1
    assert any(e["tipo"] == "duplicato_file" for e in riepilogo["errori"])


def test_import_codice_mancante(db_pulito):
    contenuto = (
        '"";"TUBO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"951";"0.000";" ";"1";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "vuoto.csv", "articoli")
    assert riepilogo["scartati"] == 1
    assert any(e["tipo"] == "campo_mancante" for e in riepilogo["errori"])


def test_import_riga_malformata(db_pulito):
    contenuto = (
        '"90035";"TUBO"\n' '"90036";"ALTRO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"951";'
        '"0.000";" ";"1";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "malformato.csv", "articoli")
    assert any(e["tipo"] == "riga_malformata" for e in riepilogo["errori"])


def test_import_prezzo_non_numerico(db_pulito):
    """Un prezzo non numerico nel listino viene segnalato come errore di formato."""
    contenuto = (
        '"90035          ";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
        '"000000000.0000000";"ABC";"0000.000";"0000.000";"0000.000";'
        '"ABC";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
        '"000000000.0000000";"EUCOMO  ";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "prezzo.csv", "listini")
    assert any(e["tipo"] == "formato_non_valido" for e in riepilogo["errori"])
    assert riepilogo["scartati"] == 1


# ---------------------------------------------------------------------------
# Listini
# ---------------------------------------------------------------------------
def test_import_listini(db_pulito):
    riepilogo = service.commit_import(
        leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini", strategia="upsert"
    )
    assert riepilogo["inseriti"] == 7
    riga = db.query_one("SELECT * FROM listini WHERE codice_articolo = '8194700'")
    assert riga is not None
    assert riga["prezzo"] == pytest.approx(18.0)
    assert riga["nome_listino"] == "DEFAULT"
    assert riga["azienda"] == "EUCOMO"


def test_import_listini_aggiorna_prezzo(db_pulito):
    service.commit_import(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")
    contenuto = (
        '"8194700        ";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
        '"000000000.0000000";"000000025.5000000";"0000.000";"0000.000";"0000.000";'
        '"000000025.5000000";"000000000.0000000";"0000.000";"0000.000";"0000.000";'
        '"000000000.0000000";"EUCOMO  ";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "COSMOLIB.csv", "listini")
    assert riepilogo["aggiornati"] == 1
    riga = db.query_one("SELECT * FROM listini WHERE codice_articolo = '8194700'")
    assert riga["prezzo"] == pytest.approx(25.5)


def test_import_listini_supporta_piu_listini(db_pulito):
    """Lo stesso articolo puo' avere prezzi su listini diversi."""
    db.execute(
        """INSERT INTO listini (codice_articolo, azienda, nome_listino, prezzo,
                               created_at, updated_at)
           VALUES ('8194700', 'EUCOMO', 'RIVENDITA', 19.9, datetime('now'), datetime('now'))"""
    )
    service.commit_import(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")
    righe = db.query_all("SELECT * FROM listini WHERE codice_articolo = '8194700'")
    assert len(righe) == 2
    assert {r["nome_listino"] for r in righe} == {"DEFAULT", "RIVENDITA"}


# ---------------------------------------------------------------------------
# Anteprima e log
# ---------------------------------------------------------------------------
def test_anteprima_rileva_encoding_e_delimitatore(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    anteprima = service.analizza(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    assert anteprima.delimiter == ";"
    assert anteprima.n_colonne == 12
    assert anteprima.totale_righe == 7
    assert anteprima.stats["inseriti"] == 7


def test_anteprima_non_scrive_nel_database(db_pulito):
    service.analizza(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    assert db.query_scalar("SELECT COUNT(*) FROM articoli") == 0


def test_anteprima_mappa_automatica(db_pulito):
    anteprima = service.analizza(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")
    assert anteprima.mappa["codice_articolo"] == 1
    assert anteprima.mappa["prezzo"] == 7
    assert anteprima.mappa["azienda"] == 17


def test_auto_mapping_di_default():
    assert auto_mapping("articoli", 12)["codice_marca"] == 9
    assert auto_mapping("marche", 3)["descrizione"] == 2
    assert auto_mapping("listini", 17)["prezzo"] == 7


def test_log_importazione_registrato(db_pulito):
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    riga = db.query_one("SELECT * FROM log_importazioni ORDER BY id DESC LIMIT 1")
    assert riga["tipo"] == "marche"
    assert riga["file"] == "COSMOMAR.csv"
    assert riga["inseriti"] == 3
    assert riga["righe_totali"] == 3


def test_report_errori_csv(db_pulito):
    contenuto = (
        '"90035          ";"TUBO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"MARCA-X";"0.000";" ";"1";\n'
    ).encode("utf-8")
    riepilogo = service.commit_import(contenuto, "err.csv", "articoli")
    report = service.report_errori_csv(riepilogo["errori"])
    assert '"Riga";"Codice";"Tipo"' in report
    assert "MARCA-X" in report
    assert "Codice marca non presente in anagrafica" in report


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------
def test_staging_roundtrip(tmp_path):
    token = service.salva_staging(b"contenuto", "test.csv", "articoli")
    dati = service.leggi_staging(token)
    assert dati is not None
    raw, meta = dati
    assert raw == b"contenuto"
    assert meta["file"] == "test.csv"
    service.elimina_staging(token)
    assert service.leggi_staging(token) is None
