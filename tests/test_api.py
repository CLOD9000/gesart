"""Test delle API JSON e dei percorsi di servizio."""
from __future__ import annotations

import re

from app.importers import service


def login(client):
    risposta = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', risposta.text).group(1)
    return client.post(
        "/login",
        data={"username": "admin", "password": "admin", "csrf_token": token},
        follow_redirects=False,
    )


def test_healthz(client):
    risposta = client.get("/healthz")
    assert risposta.status_code == 200
    assert risposta.json()["stato"] == "ok"


def test_api_restituisce_json_senza_sessione(client):
    risposta = client.get("/api/opzioni", headers={"accept": "application/json"})
    assert risposta.status_code == 401
    assert "detail" in risposta.json()


def test_api_opzioni(client):
    login(client)
    service.commit_import(open("examples/COSMOMAR.csv", "rb").read(), "COSMOMAR.csv", "marche")
    service.commit_import(open("examples/COSMOART.csv", "rb").read(), "COSMOART.csv", "articoli")
    risposta = client.get("/api/opzioni")
    assert risposta.status_code == 200
    dati = risposta.json()
    assert "marche" in dati
    assert "aziende" in dati
    codici = [m["value"] for m in dati["marche"]]
    assert "74" in codici


def test_root_reindirizza(client):
    risposta = client.get("/", follow_redirects=False)
    assert risposta.status_code == 307
    assert risposta.headers["location"] == "/articoli"


def test_pagina_inesistente(client):
    login(client)
    risposta = client.get("/pagina-che-non-esiste")
    assert risposta.status_code == 404


def test_headers_di_sicurezza(client):
    risposta = client.get("/login")
    assert risposta.headers["x-content-type-options"] == "nosniff"
    assert risposta.headers["x-frame-options"] == "SAMEORIGIN"
    assert risposta.headers["referrer-policy"] == "same-origin"
