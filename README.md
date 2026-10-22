# Gesart

Gestionale articoli self-hosted: importa, gestisce, filtra ed esporta un
catalogo articoli originato da tre CSV distinti (`COSMOART`, `COSMOLIB`,
`COSMOMAR`), con interfaccia web server-rendered e database **PostgreSQL**
in un container dedicato.

- **Backend**: FastAPI + PostgreSQL 16 (container `db`, rete interna).
- **Frontend**: Jinja2 + htmx (vendorizzato in locale, nessuna CDN: funziona
  anche senza connessione a internet).
- **Dipendenze**: solo librerie Python, niente Node, niente build step.
- **Accesso in sola lettura**: altri applicativi possono leggere il catalogo
  tramite un ruolo dedicato e le viste `v_*` (vedi
  [Accesso in sola lettura](#accesso-in-sola-lettura)).

---

## Indice

1. [Funzionalità](#funzionalità)
2. [Avvio con Docker](#avvio-con-docker)
3. [Configurazione](#configurazione)
4. [Utenti e ruoli](#utenti-e-ruoli)
5. [Formato dei file di origine](#formato-dei-file-di-origine)
6. [Importazione](#importazione)
7. [Uso quotidiano](#uso-quotidiano)
8. [Accesso in sola lettura](#accesso-in-sola-lettura)
9. [Sviluppo locale](#sviluppo-locale)
10. [Backup e ripristino](#backup-e-ripristino)
11. [Struttura del progetto](#struttura-del-progetto)
12. [API](#api)

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
$EDITOR stack.env          # cambia le password (app, PostgreSQL, sola lettura)

# 2. avvio (app + database)
docker compose --env-file stack.env up -d --build

# 3. verifica
docker compose ps
curl -fsS http://localhost:9080/healthz     # -> {"stato":"ok"}
```

L'applicazione e' raggiungibile su **http://localhost:9080**.

> `--env-file stack.env` serve a docker compose per interpolare `GESART_PORT`
> e per passare le variabili ai container. In alternativa si puo' copiare
> `stack.env` in `.env` (ignorato da git).

### Architettura

```
host :9080
   |
   v
[gesart]  --rete interna gesart-net-->  [db: postgres:16-alpine]
 FastAPI                                  volume gesart-db
```

- Il database **non pubblica porte**: e' raggiungibile solo dai container
  collegati alla rete `gesart-net`.
- L'applicazione applica lo schema all'avvio (`app/schema.sql`) ed e' l'unica
  a scrivere.
- Gli altri applicativi si collegano alla stessa rete Docker e usano il ruolo
  di sola lettura (vedi [Accesso in sola lettura](#accesso-in-sola-lettura)).

### Comandi utili

```bash
docker compose --env-file stack.env logs -f gesart   # log applicazione
docker compose --env-file stack.env logs -f db       # log PostgreSQL
docker compose --env-file stack.env restart gesart   # riavvio
docker compose --env-file stack.env down             # stop (i volumi restano)
docker compose --env-file stack.env down -v          # stop + CANCELLA i dati
docker compose --env-file stack.env exec db \
  psql -U gesart -d gesart -c '\dt'                  # ispezione tabelle
```

### Volumi

| Volume | Contenuto | Note |
| --- | --- | --- |
| `gesart-db` | dati PostgreSQL (`/var/lib/postgresql/data`) | **il catalogo vive qui** |
| `gesart-data` | staging delle importazioni (`/data`) | rigenerabile |
| `./imports` | CSV/XLSX depositati da importare | bind mount in sola lettura |

### Aggiornamento

```bash
git pull
docker compose --env-file stack.env up -d --build
```

Lo schema del database viene aggiornato automaticamente all'avvio
(`CREATE TABLE IF NOT EXISTS` / `CREATE OR REPLACE VIEW`): i dati esistenti
non vengono toccati.

---

## Configurazione

Tutte le variabili sono facoltative: con i default l'app si avvia comunque.
I valori per Docker stanno in `stack.env` (vedi `stack.env.example`).

| Variabile | Default | Descrizione |
| --- | --- | --- |
| `GESART_PORT` | `9080` | porta esposta sull'host |
| `GESART_HOST` | `0.0.0.0` | indirizzo di ascolto nel container |
| `GESART_DATA_DIR` | `/data` | directory dello staging import |
| `GESART_IMPORTS_DIR` | `/imports` | cartella dei file da importare |
| `GESART_TEMPLATES_DIR` | `app/templates` | solo per sviluppo |
| `GESART_STATIC_DIR` | `app/static` | solo per sviluppo |
| `GESART_DATABASE_URL` | _(vuoto)_ | URL completo; se impostato vince sugli altri |
| `GESART_DB_HOST` | `localhost` (`db` in compose) | host PostgreSQL |
| `GESART_DB_PORT` | `5432` | porta PostgreSQL |
| `GESART_DB_NAME` / `POSTGRES_DB` | `gesart` | nome del database |
| `GESART_DB_USER` / `POSTGRES_USER` | `gesart` | utente applicativo (scrive) |
| `GESART_DB_PASSWORD` / `POSTGRES_PASSWORD` | `gesart` | password dell'utente applicativo |
| `GESART_DB_POOL_MIN` | `1` | connessioni minime nel pool |
| `GESART_DB_POOL_MAX` | `10` | connessioni massime nel pool |
| `GESART_DB_CONNECT_TIMEOUT` | `30` | timeout di connessione (secondi) |
| `GESART_DB_READONLY_ROLE` | `gesart_lettura` | ruolo di sola lettura (vuoto = disabilitato) |
| `GESART_DB_READONLY_PASSWORD` | _(vuoto)_ | password del ruolo di sola lettura |
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

> Le variabili `POSTGRES_*` sono quelle lette dall'immagine ufficiale
> PostgreSQL e vengono usate dall'app come fallback: in `stack.env` basta
> definirle una volta sola.

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

## Accesso in sola lettura

PostgreSQL non e' pubblicato sull'host. Per leggere il catalogo da un altro
applicativo:

1. collegare il container dell'applicativo alla rete `gesart-net` (la rete
   creata da questo stack, nome `<progetto>_gesart-net`);
2. usare l'utente `GESART_DB_READONLY_ROLE` (default `gesart_lettura`) e la
   password `GESART_DB_READONLY_PASSWORD`.

Il ruolo viene creato/aggiornato automaticamente all'avvio dell'app e puo'
solo eseguire `SELECT` sulle viste esposte:

| Vista | Contenuto |
| --- | --- |
| `v_articoli` | articoli con descrizione marca e campi JSON (`jsonb`) |
| `v_articoli_listini` | articoli per listino (prezzo, validita') |
| `v_marche` | anagrafica marche |
| `v_listini` | listini/prezzi |

Le tabelle interne (utenti, sessioni, log importazioni) **non** sono
accessibili al ruolo di lettura.

Esempio con un container sulla stessa rete:

```bash
docker run --rm --network gesart_gesart-net -e PGPASSWORD=... \
  postgres:16-alpine \
  psql -h db -U gesart_lettura -d gesart \
       -c "SELECT codice, descrizione FROM v_articoli LIMIT 5"
```

Esempio di stringa di connessione per un altro servizio:

```
postgresql://gesart_lettura:<password>@db:5432/gesart
```

> Il nome host `db` funziona solo per i container collegati a `gesart-net`.
> Per un database esterno impostare `GESART_DATABASE_URL` e allineare i
> permessi manualmente.

---

## Sviluppo locale

```bash
# PostgreSQL locale (solo sviluppo: pubblica 5432 su 127.0.0.1)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db

scripts/dev.sh                 # http://localhost:9080 con reload (crea .venv se manca)
scripts/dev.sh 8080            # porta diversa
```

In alternativa, a mano:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d db

GESART_DATA_DIR=./data GESART_IMPORTS_DIR=./imports \
GESART_DB_HOST=localhost GESART_DB_USER=gesart GESART_DB_PASSWORD=<password> \
  .venv/bin/python -m uvicorn app.web.main:app --reload --port 9080
```

### Test

```bash
# in locale: serve PostgreSQL raggiungibile (vedi sopra)
GESART_TEST_DATABASE_URL=postgresql://gesart:<password>@localhost:5432/gesart_test \
  scripts/test.sh

# completamente dentro Docker (usa il database del compose)
docker compose --env-file stack.env --profile test run --rm test
```

I test usano un database dedicato (`gesart_test`, creato automaticamente se
manca) e svuotano le tabelle a ogni test: non toccano il database
applicativo. Se PostgreSQL non e' raggiungibile i test che lo richiedono
vengono saltati, mentre `tests/test_parsing.py` gira comunque.

| File | Copertura |
| --- | --- |
| `tests/test_parsing.py` | encoding, delimitatori, numeri, date, colonne fantasma |
| `tests/test_import.py` | strategie, scarti, errori, round-trip |
| `tests/test_export.py` | formato COSMO byte-identico all'originale |
| `tests/test_web.py` | login, ruoli, CRUD, filtri, viste, campi, import da UI |
| `tests/test_api.py` | API JSON, health check, header di sicurezza |

---

## Backup e ripristino

Il catalogo vive nel volume `gesart-db`. Il backup consistente si fa con
`pg_dump`:

```bash
# dump compresso fuori dal container
docker compose --env-file stack.env exec -T db \
  pg_dump -U gesart -d gesart -Fc > backup-$(date +%F).dump
```

Ripristino (con stack fermo):

```bash
docker compose --env-file stack.env down
docker compose --env-file stack.env up -d db
docker compose --env-file stack.env exec -T db \
  pg_restore -U gesart -d gesart --clean --if-exists < backup-2026-01-31.dump
docker compose --env-file stack.env up -d
```

In alternativa, un dump SQL leggibile:

```bash
docker compose --env-file stack.env exec -T db \
  pg_dump -U gesart -d gesart --no-owner > backup-$(date +%F).sql
```

> Non copiare i file del volume `gesart-db` a container acceso: usare
> `pg_dump` (oppure fermare il database prima della copia).

---

## Struttura del progetto

```
app/
  config.py           impostazioni da variabili d'ambiente
  db.py               pool PostgreSQL, transazioni, init schema
  schema.sql          schema PostgreSQL + viste di sola lettura
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
docker-compose.yml      app + PostgreSQL (rete interna)
docker-compose.dev.yml  override per lo sviluppo (5432 su 127.0.0.1)
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
