# Gesart

Gestionale articoli self-hosted: importa, gestisce, filtra ed esporta un
catalogo articoli originato da tre CSV distinti (`COSMOART`, `COSMOLIB`,
`COSMOMAR`), con interfaccia web server-rendered e database SQLite in un
singolo file.

- **Backend**: FastAPI + SQLite (WAL), nessun servizio esterno.
- **Frontend**: Jinja2 + htmx (vendorizzato in locale, nessuna CDN: funziona
  anche senza connessione a internet).
- **Dipendenze**: solo librerie Python, niente Node, niente build step.

---

## Indice

1. [Funzionalità](#funzionalità)
2. [Avvio con Docker](#avvio-con-docker)
3. [Configurazione](#configurazione)
4. [Utenti e ruoli](#utenti-e-ruoli)
5. [Formato dei file di origine](#formato-dei-file-di-origine)
6. [Importazione](#importazione)
7. [Uso quotidiano](#uso-quotidiano)
8. [Sviluppo locale](#sviluppo-locale)
9. [Backup e ripristino](#backup-e-ripristino)
10. [Struttura del progetto](#struttura-del-progetto)
11. [API](#api)

---

## Funzionalità

- **Importazione** di file CSV o XLSX con riconoscimento automatico di
  encoding, delimitatore e formato; anteprima con statistiche ed errori
  **prima** di scrivere il database; tre strategie di import
  (`upsert`, `solo inserimento`, `solo campi vuoti`).
- **Nessuna perdita di dati**: le colonne del file sorgente che non
  corrispondono a un campo standard vengono conservate in un JSON
  `campi_extra` (chiave = indice della colonna nel file) e sono visibili e
  modificabili nella scheda articolo.
- **Anagrafica unificata**: `COSMOART` (articoli), `COSMOMAR` (marche) e
  `COSMOLIB` (listini) vengono uniti in un'unica vista con marca, prezzo e
  listino, mantenendo l'isolamento per **azienda** (multi-tenant: il codice
  articolo è univoco per coppia `codice + azienda`).
- **Elenco filtrabile e ordinabile** con filtri su ogni colonna
  (contiene, uguale, min/max, vuoto/non vuoto, elenco valori), ricerca
  testuale full-text, paginazione lato server.
- **Viste salvate**: un insieme di filtri con nome, personale o condiviso.
- **Campi personalizzati** definiti dall'amministratore (testo, numero,
  data, flag, lista a scelta): diventano colonne dell'elenco, campi del
  form e filtri.
- **Export** in tre formati: CSV semplice, formato **COSMO** (identico
  all'originale, colonna per colonna) e CSV dei campi personalizzati.
  L'export rispetta i filtri attivi.
- **Ruoli**: `admin` (tutto) e `operatore` (solo consultazione e gestione
  articoli).
- **Log delle importazioni** con righe lette/inserite/aggiornate/scartate e
  download del report errori in CSV.

---

## Avvio con Docker

### Requisiti

Docker e Docker Compose v2. Nient'altro.

### Primi passi

```bash
# 1. configurazione (contiene le credenziali: NON versionare)
cp stack.env.example stack.env
$EDITOR stack.env          # cambia le password

# 2. avvio
docker compose up -d --build

# 3. verifica
docker compose ps
curl -fsS http://localhost:9080/healthz     # -> {"stato":"ok"}
```

L'applicazione e' raggiungibile su **http://localhost:9080**.

### Comandi utili

```bash
docker compose logs -f gesart      # log
docker compose restart gesart      # riavvio
docker compose down                # stop (il volume dei dati resta)
docker compose down -v             # stop + CANCELLA i dati (pericoloso)
```

### Volumi

| Percorso nel container | Contenuto | Note |
| --- | --- | --- |
| `/data` | database SQLite + staging delle importazioni | volume `gesart-data`, **non perderlo** |
| `/imports` | CSV/XLSX depositati da importare | bind mount `./imports` in sola lettura |

### Aggiornamento

```bash
git pull
docker compose up -d --build
```

Lo schema del database viene aggiornato automaticamente all'avvio
(`CREATE TABLE IF NOT EXISTS`): i dati esistenti non vengono toccati.

---

## Configurazione

Tutte le variabili sono facoltative: con i default l'app si avvia comunque.
I valori per Docker stanno in `stack.env` (vedi `stack.env.example`).

| Variabile | Default | Descrizione |
| --- | --- | --- |
| `GESART_PORT` | `9080` | porta esposta sull'host |
| `GESART_HOST` | `0.0.0.0` | indirizzo di ascolto nel container |
| `GESART_DATA_DIR` | `/data` | directory di database e staging |
| `GESART_DB_PATH` | `<data_dir>/gesart.sqlite3` | percorso esplicito del DB |
| `GESART_IMPORTS_DIR` | `/imports` | cartella dei file da importare |
| `GESART_TEMPLATES_DIR` | `app/templates` | solo per sviluppo |
| `GESART_STATIC_DIR` | `app/static` | solo per sviluppo |
| `GESART_ADMIN_USER` | `admin` | username dell'admin creato al primo avvio |
| `GESART_ADMIN_PASSWORD` | `admin` | password dell'admin |
| `GESART_ADMIN_NAME` | `Amministratore` | nome mostrato |
| `GESART_OPERATOR_USER` | `operatore` | username dell'operatore |
| `GESART_OPERATOR_PASSWORD` | `operatore` | password dell'operatore |
| `GESART_SEED_OPERATOR` | `true` | se creare anche l'utente operatore |
| `GESART_SESSION_TTL_HOURS` | `12` | durata della sessione |
| `GESART_SECURE_COOKIES` | `false` | `true` se servito via HTTPS |
| `GESART_SESSION_COOKIE` | `gesart_session` | nome del cookie di sessione |
| `GESART_MAX_UPLOAD_MB` | `64` | dimensione massima di un file caricato |
| `GESART_STAGING_TTL_HOURS` | `24` | scadenza delle importazioni in attesa |
| `GESART_DEFAULT_AZIENDA` | _(vuoto)_ | azienda di default in importazione |

> Le credenziali iniziali valgono **solo per il primo avvio a database
> vuoto**. Cambiare `GESART_ADMIN_PASSWORD` dopo il primo avvio non modifica
> la password esistente: va cambiata dalla pagina **Utenti**.

---

## Utenti e ruoli

| Ruolo | Permessi |
| --- | --- |
| `admin` | articoli, viste, import, campi personalizzati, utenti |
| `operatore` | consultazione e modifica articoli, viste personali, export |

La gestione utenti e' in **Admin -> Utenti**. Le password sono memorizzate
con PBKDF2-HMAC-SHA256 (600.000 iterazioni, salt casuale per utente).
Ogni sessione ha un token CSRF distinto, verificato su ogni POST.

---

## Formato dei file di origine

I tre file di esempio sono in `examples/`.

### COSMOMAR.csv - anagrafica marche

```
"74 ";"MARCA A";"EUCOMO  ";
```

| # | Campo | Tipo |
| --- | --- | --- |
| 1 | codice marca | testo |
| 2 | descrizione | testo |
| 3 | azienda | testo |

### COSMOART.csv - anagrafica articoli

```
"8194700        ";"KIT GUAINA 4MT X FILO FE/INOX D.0,6/0,8           ";"Pz.  ";"1";"00000001.000";"00000000000";"EUCOMO  ";"   ";"74 ";"00000000.000";" ";"1";
```

| # | Campo | Tipo |
| --- | --- | --- |
| 1 | codice articolo | testo |
| 2 | descrizione | testo |
| 3 | unita' di misura | testo |
| 4 | (campo intero) | intero |
| 5 | (campo decimale) | decimale |
| 6 | barcode | testo |
| 7 | azienda | testo |
| 8 | (campo testo) | testo |
| 9 | codice marca | testo (FK su COSMOMAR) |
| 10 | (campo decimale) | decimale |
| 11 | (campo testo) | testo |
| 12 | (campo flag) | intero |

### COSMOLIB.csv - listini

| # | Campo | Tipo |
| --- | --- | --- |
| 1 | codice articolo | testo |
| 2..6 | campi testuali | testo |
| 7 | prezzo | decimale |
| 8..10 | campi testuali | testo |
| 11 | prezzo secondario | decimale |
| 12..16 | campi testuali | testo |
| 17 | azienda | testo |

### Regole di parsing

- **Encoding**: UTF-8 (con o senza BOM), Latin-1/CP1252, Windows-1252
  riconosciuti automaticamente.
- **Delimitatore**: `;` o `,` rilevato sul contenuto.
- **Virgolette**: tutti i campi sono tra apici; il parser gestisce anche campi
  non quotati e virgolette interne.
- **Riga vuota finale**: il file termina con `;` e un terminatore di riga, che
  produce una colonna "fantasma": viene riconosciuta e scartata
  automaticamente.
- **Numeri**: separatore decimale `,` o `.`; i valori vuoti diventano `NULL`.
- **Date**: riconosciute in formato `DD/MM/YYYY`, `YYYY-MM-DD`,
  `DD-MM-YY`.
- **Colonne in piu'**: se il file ha piu' colonne del profilo standard, le
  eccedenti vengono conservate in `campi_extra` e proposte nel form
  articolo. Se ne ha meno, i campi mancanti restano vuoti.

---

## Importazione

**Import -> Nuova importazione**. Le tre fasi sono separate: nessun dato
entra nel database finche' non si conferma.

1. **Carica** - selezionare il file (o scegliere un file gia' presente in
   `/imports`) e il tipo (`articoli`, `marche`, `listini`).
2. **Anteprima** - riepilogo: righe lette, da inserire, da aggiornare, da
   scartare, con l'elenco degli errori. Il tipo di file viene riconosciuto
   automaticamente e puo' essere corretto.
3. **Conferma** - l'import viene eseguito con la strategia scelta:

| Strategia | Comportamento |
| --- | --- |
| `upsert` | inserisce le righe nuove e aggiorna quelle esistenti |
| `solo inserimento` | salta le righe gia' presenti |
| `solo campi vuoti` | aggiorna solo i campi attualmente vuoti |

Gli scarti (codice vuoto, marca inesistente, prezzo non numerico, ...)
sono elencati nella pagina di riepilogo e scaricabili come CSV di report
errori.

**Ordine consigliato**: `COSMOMAR` -> `COSMOART` -> `COSMOLIB`. Un articolo
senza marca corrispondente viene scartato con errore
`MARCA_NON_TROVATA`.

---

## Uso quotidiano

### Elenco articoli

- **Ricerca testuale** su codice, descrizione, barcode e marca
  (normalizzata: case-insensitive e senza accenti).
- **Filtri per colonna**: contiene, non contiene, uguale, diverso, min/max,
  vuoto, non vuoto, scelta multipla (per marca, azienda, unita' di misura,
  listino).
- **Ordinamento** su ogni colonna, con direzione crescente/decrescente.
- **Paginazione** lato server (da 50 a 500 righe per pagina).

### Viste salvate

Un insieme di filtri puo' essere salvato con un nome e riaperto con un
click dalla barra laterale. Le viste sono personali o condivise con tutti
gli utenti.

### Campi personalizzati

**Admin -> Campi personalizzati**: si crea un campo (testo, numero, data,
flag o lista a scelta). Da quel momento il campo compare come colonna
nell'elenco, come filtro e come voce del form articolo. Rinominare un campo
non perde i valori gia' inseriti.

### Export

| Formato | Contenuto |
| --- | --- |
| `semplice` | colonne selezionabili, separatore `,`, BOM UTF-8 |
| `cosmo` | identico al file originale (delimitatore `;`, campi quotati, larghezze fisse, numeri con zeri) |
| `campi` | solo i campi personalizzati |

L'export applica i filtri attivi, quindi si puo' esportare esattamente il
risultato mostrato a schermo.

---

## Sviluppo locale

```bash
scripts/dev.sh                 # http://localhost:9080 con reload (crea .venv se manca)
scripts/dev.sh 8080            # porta diversa
```

In alternativa, a mano:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

GESART_DATA_DIR=./data GESART_IMPORTS_DIR=./imports \
  .venv/bin/python -m uvicorn app.web.main:app --reload --port 9080
```

### Test

```bash
scripts/test.sh                # oppure: .venv/bin/python -m pytest tests/ -q
```

I test usano un database temporaneo e non toccano `data/`.

| File | Copertura |
| --- | --- |
| `tests/test_parsing.py` | encoding, delimitatori, numeri, date, colonne fantasma |
| `tests/test_import.py` | strategie, scarti, errori, round-trip |
| `tests/test_export.py` | formato COSMO byte-identico all'originale |
| `tests/test_web.py` | login, ruoli, CRUD, filtri, viste, campi, import da UI |
| `tests/test_api.py` | API JSON, health check, header di sicurezza |

---

## Backup e ripristino

Il database e' un unico file: `gesart.sqlite3` dentro il volume `/data`.

```bash
# backup (container in esecuzione)
docker compose exec gesart \
  python -c "import sqlite3; s=sqlite3.connect('/data/gesart.sqlite3'); d=sqlite3.connect('/data/backup.sqlite3'); s.backup(d)"

# copia fuori dal container
docker cp gesart:/data/gesart.sqlite3 ./backup-$(date +%F).sqlite3
```

Per il ripristino: spegnere il container, sostituire il file nel volume,
riavviare.

```bash
docker compose down
docker run --rm -v gesart-data:/data -v "$PWD":/backup alpine \
  sh -c "cp /backup/backup-2026-01-31.sqlite3 /data/gesart.sqlite3 && rm -f /data/gesart.sqlite3-wal /data/gesart.sqlite3-shm"
docker compose up -d
```

> Copiare il file a runtime senza fermare l'app puo' produrre un backup
> incoerente: usare sempre `sqlite3.backup()` (come sopra) o fermare prima
> il container.

---

## Struttura del progetto

```
app/
  config.py           impostazioni da variabili d'ambiente
  db.py               connessione SQLite, transazioni, migrazioni
  schema.sql          schema del database
  security.py         password, sessioni, CSRF, normalizzazione ricerca
  query.py            motore dei filtri, ordinamento, paginazione
  exporters.py        export CSV (semplice, COSMO, campi personalizzati)
  importers/
    parsing.py        lettura CSV/XLSX, encoding, numeri, date
    mapping.py        profili COSMO e mappatura automatica delle colonne
    service.py        staging, anteprima, commit, log, report errori
  web/
    main.py           app FastAPI, middleware, handler errori
    helpers.py        contesto template, CSRF, filtri
    auth.py articoli.py imports.py viste.py admin.py
  templates/          Jinja2 (base, articoli, import, viste, admin)
  static/             CSS, JS applicativo, htmx vendorizzato
tests/                test automatici
examples/            CSV di esempio
imports/             cartella montata in /imports
scripts/             dev.sh (server locale), test.sh (suite di test)
```

---

## API

Documentazione interattiva: `/api/docs` (Swagger UI).

| Metodo | Percorso | Descrizione |
| --- | --- | --- |
| `GET` | `/healthz` | stato del servizio |
| `GET` | `/api/opzioni` | valori dei dropdown di filtro |
| `GET` | `/articoli` | elenco filtrabile (HTML) |
| `GET` | `/articoli/tabella` | partial HTML della tabella (htmx) |
| `GET` | `/articoli/esporta?formato=cosmo\|semplice` | export CSV |
| `GET` | `/import/log` | storico importazioni |
| `GET` | `/import/log/{id}/errori.csv` | report errori |

Le API rispondono in JSON quando la richiesta accetta `application/json`,
in HTML altrimenti. Le rotte che modificano dati richiedono sessione valida
e token CSRF.
