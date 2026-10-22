"""Test dell'interfaccia web: login, ruoli, CRUD articoli, filtri, export."""
from __future__ import annotations

import json
import re

import pytest

from app import db
from app.importers import service

ESEMPI = "examples"


def leggi(nome: str) -> bytes:
    with open(f"{ESEMPI}/{nome}", "rb") as fh:
        return fh.read()


def csrf(client) -> str:
    """Estrae il token CSRF dalla pagina di login."""
    risposta = client.get("/login")
    m = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text)
    assert m, "token CSRF non trovato"
    return m.group(1)


def login(client, username="admin", password="admin"):
    risposta = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf(client)},
        follow_redirects=False,
    )
    return risposta


def carica_dati(client):
    """Importa i tre file di esempio."""
    service.commit_import(leggi("COSMOMAR.csv"), "COSMOMAR.csv", "marche")
    service.commit_import(leggi("COSMOART.csv"), "COSMOART.csv", "articoli")
    service.commit_import(leggi("COSMOLIB.csv"), "COSMOLIB.csv", "listini")


# ---------------------------------------------------------------------------
# Autenticazione
# ---------------------------------------------------------------------------
def test_login_necessario(client):
    risposta = client.get("/articoli", follow_redirects=False)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/login"


def test_login_valido(client):
    risposta = login(client)
    assert risposta.status_code == 303
    assert risposta.headers["location"] == "/articoli"


def test_login_non_valido(client):
    risposta = login(client, password="sbagliata")
    assert risposta.status_code == 401
    assert "Credenziali non valide" in risposta.text


def test_csrf_obbligatorio(client):
    risposta = client.post(
        "/login", data={"username": "admin", "password": "admin"}, follow_redirects=False
    )
    assert risposta.status_code == 403


def test_logout(client):
    login(client)
    risposta = client.get("/articoli")
    assert risposta.status_code == 200
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post("/logout", data={"csrf_token": token})
    assert client.get("/articoli", follow_redirects=False).status_code == 303


def test_password_hash_non_in_chiaro(db_pulito):
    from app.security import create_utente, verify_password

    create_utente("prova", "segreta123", "operatore")
    riga = db.query_one("SELECT password_hash FROM utenti WHERE username = 'prova'")
    assert "segreta123" not in riga["password_hash"]
    assert riga["password_hash"].startswith("pbkdf2_sha256$")
    assert verify_password("segreta123", riga["password_hash"])
    assert not verify_password("altra", riga["password_hash"])


# ---------------------------------------------------------------------------
# Ruoli
# ---------------------------------------------------------------------------
def test_operatore_non_accede_all_import(client):
    login(client, "operatore", "operatore")
    assert client.get("/import", follow_redirects=False).status_code == 403


def test_operatore_non_accede_alla_gestione_campi(client):
    login(client, "operatore", "operatore")
    assert client.get("/admin/campi", follow_redirects=False).status_code == 403


def test_operatore_puede_vedere_gli_articoli(client):
    login(client, "operatore", "operatore")
    assert client.get("/articoli").status_code == 200


# ---------------------------------------------------------------------------
# Articoli
# ---------------------------------------------------------------------------
def test_elenco_articoli(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli")
    assert risposta.status_code == 200
    assert "8194700" in risposta.text
    assert "TUBO BINATO" in risposta.text


def test_ricerca_testuale(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli", params={"flt": json.dumps({"q": "binato"})})
    assert "90035" in risposta.text
    assert "8194700" not in risposta.text


def test_filtro_per_colonna(client):
    login(client)
    carica_dati(client)
    filtri = {"codice": {"op": "contiene", "val": "900"}}
    risposta = client.get("/articoli", params={"flt": json.dumps(filtri)})
    assert "90035" in risposta.text
    assert "823013" not in risposta.text


def test_filtro_prezzo_min_max(client):
    login(client)
    carica_dati(client)
    filtri = {"prezzo": {"op": "min_max", "min": "1000", "max": "2000"}}
    risposta = client.get("/articoli", params={"flt": json.dumps(filtri)})
    assert "90050" in risposta.text   # 1422,90
    assert "8194700" not in risposta.text  # 18,00


def test_filtro_marca_dropdown(client):
    login(client)
    carica_dati(client)
    filtri = {"codice_marca": {"op": "in", "val": ["74"]}}
    risposta = client.get("/articoli", params={"flt": json.dumps(filtri)})
    assert "8194700" in risposta.text
    assert "90035" not in risposta.text


def test_ordinamento(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli", params={"ord": "codice", "dir": "desc"})
    assert risposta.status_code == 200
    posizione = risposta.text.find("90182/W")
    assert posizione > 0


def test_paginazione_server_side(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli", params={"per": "5", "pag": "1"})
    assert risposta.status_code == 200
    assert "Risultati" in risposta.text


def test_creazione_articolo(client):
    login(client)
    risposta = client.get("/articoli/nuovo")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        "/articoli/salva",
        data={
            "csrf_token": token,
            "codice": "TEST01",
            "descrizione": "Articolo di prova",
            "unita_misura": "Pz.",
            "barcode": "12345",
            "azienda": "EUCOMO",
            "codice_marca": "951",
            "nome_listino": "DEFAULT",
            "prezzo": "12,50",
        },
        follow_redirects=False,
    )
    assert risposta.status_code == 303
    riga = db.query_one("SELECT * FROM articoli WHERE codice = 'TEST01'")
    assert riga is not None
    assert riga["descrizione"] == "Articolo di prova"
    prezzo = db.query_one("SELECT * FROM listini WHERE codice_articolo = 'TEST01'")
    assert prezzo["prezzo"] == pytest.approx(12.5)


def test_modifica_articolo(client):
    login(client)
    carica_dati(client)
    riga = db.query_one("SELECT * FROM articoli WHERE codice = '8194700'")
    risposta = client.get(f"/articoli/{riga['id']}")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post(
        "/articoli/salva",
        data={
            "csrf_token": token,
            "id": str(riga["id"]),
            "codice": "8194700",
            "descrizione": "Descrizione modificata",
            "unita_misura": "Mt",
            "barcode": "00000000000",
            "azienda": "EUCOMO",
            "codice_marca": "74",
        },
        follow_redirects=False,
    )
    aggiornato = db.query_one("SELECT * FROM articoli WHERE id = ?", (riga["id"],))
    assert aggiornato["descrizione"] == "Descrizione modificata"
    assert aggiornato["unita_misura"] == "Mt"


def test_eliminazione_articolo(client):
    login(client)
    carica_dati(client)
    riga = db.query_one("SELECT * FROM articoli WHERE codice = '8194700'")
    risposta = client.get(f"/articoli/{riga['id']}")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        f"/articoli/{riga['id']}/elimina",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert risposta.status_code == 303
    assert db.query_one("SELECT * FROM articoli WHERE id = ?", (riga["id"],)) is None


def test_codice_duplicato_rifiutato(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli/nuovo")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        "/articoli/salva",
        data={
            "csrf_token": token,
            "codice": "8194700",
            "descrizione": "Dup",
            "azienda": "EUCOMO",
        },
        follow_redirects=False,
    )
    assert risposta.status_code == 409
    assert "esiste gia" in risposta.text
    assert db.query_scalar("SELECT COUNT(*) FROM articoli WHERE codice = '8194700'") == 1


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
def test_export_semplice(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli/esporta", params={"formato": "semplice"})
    assert risposta.status_code == 200
    assert "text/csv" in risposta.headers["content-type"]
    assert "attachment" in risposta.headers["content-disposition"]
    assert "8194700" in risposta.text
    assert "Codice,Descrizione" in risposta.text


def test_export_formato_cosmo(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli/esporta", params={"formato": "cosmo"})
    assert risposta.status_code == 200
    righe = [r for r in risposta.text.lstrip("﻿").splitlines() if r.strip()]
    assert len(righe) == 7
    assert righe[0].startswith('"8194700        "')
    assert righe[0].endswith(";")


def test_export_rispetta_i_filtri(client):
    login(client)
    carica_dati(client)
    filtri = {"codice": {"op": "contiene", "val": "900"}}
    risposta = client.get(
        "/articoli/esporta", params={"formato": "semplice", "flt": json.dumps(filtri)}
    )
    righe = [r for r in risposta.text.lstrip("﻿").splitlines() if r.strip()]
    # intestazione + 3 articoli con codice che inizia per 900
    assert len(righe) == 4


# ---------------------------------------------------------------------------
# Campi personalizzati
# ---------------------------------------------------------------------------
def test_creazione_campo_personalizzato(client):
    login(client)
    risposta = client.get("/admin/campi")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post(
        "/admin/campi",
        data={"csrf_token": token, "etichetta": "Colore", "tipo": "lista", "opzioni": "rosso\nverde"},
        follow_redirects=False,
    )
    riga = db.query_one("SELECT * FROM campi_personalizzati WHERE chiave = 'colore'")
    assert riga is not None
    assert json.loads(riga["opzioni"]) == ["rosso", "verde"]


def test_campo_personalizzato_presente_in_tabella_e_filtri(client):
    login(client)
    db.execute(
        """INSERT INTO campi_personalizzati (chiave, etichetta, tipo, opzioni, obbligatorio,
                                              ordine, attivo, created_at, updated_at)
           VALUES ('colore', 'Colore', 'lista', '["rosso","verde"]', 0, 1, 1,
                   datetime('now'), datetime('now'))"""
    )
    carica_dati(client)
    risposta = client.get("/articoli")
    assert "Colore" in risposta.text
    assert "f__cf_colore__op" in risposta.text


def test_valore_campo_personalizzato_nel_crud(client):
    login(client)
    db.execute(
        """INSERT INTO campi_personalizzati (chiave, etichetta, tipo, opzioni, obbligatorio,
                                              ordine, attivo, created_at, updated_at)
           VALUES ('colore', 'Colore', 'testo', '[]', 0, 1, 1,
                   datetime('now'), datetime('now'))"""
    )
    risposta = client.get("/articoli/nuovo")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post(
        "/articoli/salva",
        data={"csrf_token": token, "codice": "CP01", "descrizione": "x", "cp_colore": "rosso"},
        follow_redirects=False,
    )
    riga = db.query_one("SELECT * FROM articoli WHERE codice = 'CP01'")
    assert json.loads(riga["campi_personalizzati"])["colore"] == "rosso"


def test_rename_campo_non_perde_dati(client):
    login(client)
    db.execute(
        """INSERT INTO campi_personalizzati (chiave, etichetta, tipo, opzioni, obbligatorio,
                                              ordine, attivo, created_at, updated_at)
           VALUES ('colore', 'Colore', 'testo', '[]', 0, 1, 1,
                   datetime('now'), datetime('now'))"""
    )
    db.execute(
        """INSERT INTO articoli (codice, descrizione, campi_personalizzati, created_at, updated_at)
           VALUES ('CP01', 'x', '{"colore":"rosso"}', datetime('now'), datetime('now'))"""
    )
    risposta = client.get("/admin/campi")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    campo = db.query_one("SELECT * FROM campi_personalizzati WHERE chiave = 'colore'")
    client.post(
        f"/admin/campi/{campo['id']}",
        data={"csrf_token": token, "etichetta": "Colore articolo", "tipo": "testo"},
        follow_redirects=False,
    )
    riga = db.query_one("SELECT * FROM campi_personalizzati WHERE id = ?", (campo["id"],))
    assert riga["etichetta"] == "Colore articolo"
    assert riga["chiave"] == "colore"
    articolo = db.query_one("SELECT * FROM articoli WHERE codice = 'CP01'")
    assert json.loads(articolo["campi_personalizzati"])["colore"] == "rosso"


# ---------------------------------------------------------------------------
# Viste salvate
# ---------------------------------------------------------------------------
def test_salvataggio_vista(client):
    login(client)
    carica_dati(client)
    filtri = {"codice": {"op": "contiene", "val": "900"}}
    risposta = client.get("/articoli")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post(
        "/viste/salva",
        data={"csrf_token": token, "nome": "Articoli 900", "flt": json.dumps(filtri)},
        follow_redirects=False,
    )
    vista = db.query_one("SELECT * FROM viste WHERE nome = 'Articoli 900'")
    assert vista is not None
    assert json.loads(vista["filtri"])["filtri"]["codice"]["val"] == "900"


def test_applicazione_vista(client):
    login(client)
    carica_dati(client)
    risposta = client.get("/articoli")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    client.post(
        "/viste/salva",
        data={
            "csrf_token": token,
            "nome": "Vista test",
            "flt": json.dumps({"codice": {"op": "contiene", "val": "900"}}),
        },
        follow_redirects=False,
    )
    vista = db.query_one("SELECT * FROM viste WHERE nome = 'Vista test'")
    risposta = client.get(f"/viste/applica/{vista['id']}", follow_redirects=False)
    assert risposta.status_code == 303
    assert "flt=" in risposta.headers["location"]


# ---------------------------------------------------------------------------
# Import via interfaccia
# ---------------------------------------------------------------------------
def test_import_da_interfaccia(client):
    login(client)
    risposta = client.get("/import")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        "/import/carica",
        data={"csrf_token": token, "tipo": "marche", "strategia": "upsert"},
        files={"file": ("COSMOMAR.csv", leggi("COSMOMAR.csv"), "text/csv")},
        follow_redirects=False,
    )
    assert risposta.status_code == 303
    assert "/import/preview/" in risposta.headers["location"]
    url_preview = risposta.headers["location"]

    # Anteprima
    risposta = client.get(url_preview)
    assert "COSMOMAR.csv" in risposta.text
    assert "MARCA A" in risposta.text

    # Commit
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        f"/import/commit/{url_preview.rsplit('/', 1)[-1]}",
        data={"csrf_token": token, "strategia": "upsert"},
        follow_redirects=False,
    )
    assert risposta.status_code == 200
    assert "Importazione completata" in risposta.text
    assert db.query_scalar("SELECT COUNT(*) FROM marche") == 3


def test_report_errori_scaricabile(client):
    login(client)
    contenuto = (
        '"90035          ";"TUBO";"Pz.";"1";"1.000";"0";"EUCOMO";" ";"MARCA-X";"0.000";" ";"1";\n'
    ).encode("utf-8")
    service.commit_import(contenuto, "err.csv", "articoli")
    log_id = db.query_scalar("SELECT MAX(id) FROM log_importazioni")
    risposta = client.get(f"/import/log/{log_id}/errori.csv")
    assert risposta.status_code == 200
    assert "MARCA-X" in risposta.text


def test_import_da_cartella_imports(client, tmp_path):
    from app.config import settings

    cartella = tmp_path / "imports"
    cartella.mkdir()
    (cartella / "COSMOMAR.csv").write_bytes(leggi("COSMOMAR.csv"))
    settings.__dict__["imports_dir"] = cartella

    login(client)
    risposta = client.get("/import")
    assert "COSMOMAR.csv" in risposta.text

    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        "/import/carica-da-cartella",
        data={"csrf_token": token, "tipo": "marche", "strategia": "upsert", "nome": "COSMOMAR.csv"},
        follow_redirects=False,
    )
    assert risposta.status_code == 303
    assert "/import/preview/" in risposta.headers["location"]

    risposta = client.get(risposta.headers["location"])
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        f"/import/commit/{risposta.url.path.rsplit('/', 1)[-1]}",
        data={"csrf_token": token, "strategia": "upsert"},
        follow_redirects=False,
    )
    assert risposta.status_code == 200
    assert db.query_scalar("SELECT COUNT(*) FROM marche") == 3


def test_import_da_cartella_ignora_path_traversal(client, tmp_path):
    from app.config import settings

    cartella = tmp_path / "imports"
    cartella.mkdir()
    (cartella / "ok.csv").write_bytes(b"x")
    settings.__dict__["imports_dir"] = cartella

    login(client)
    risposta = client.get("/import")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    risposta = client.post(
        "/import/carica-da-cartella",
        data={"csrf_token": token, "tipo": "marche", "nome": "../ok.csv"},
        follow_redirects=False,
    )
    assert risposta.status_code == 400
    assert "non trovato" in risposta.text
