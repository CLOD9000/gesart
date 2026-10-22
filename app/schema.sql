-- Schema del database SQLite di gesart.
-- Applicato idempotentemente all'avvio (vedi app/db.py).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- Anagrafica marche
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marche (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    codice      TEXT    NOT NULL,
    descrizione TEXT    NOT NULL DEFAULT '',
    azienda     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (codice, azienda)
);

-- ---------------------------------------------------------------------------
-- Anagrafica articoli (unisce COSMOART + marca + listino via query)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS articoli (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codice        TEXT    NOT NULL,
    descrizione   TEXT    NOT NULL DEFAULT '',
    unita_misura  TEXT    NOT NULL DEFAULT '',
    barcode       TEXT    NOT NULL DEFAULT '',
    azienda       TEXT    NOT NULL DEFAULT '',
    codice_marca  TEXT    NOT NULL DEFAULT '',
    -- Campi non ancora standardizzati, preservati per non perdere dati.
    -- JSON: {"<indice_colonna_sorgente>": "valore grezzo"}
    campi_extra   TEXT    NOT NULL DEFAULT '{}',
    -- Valori dei campi personalizzati, JSON: {"<chiave_campo>": valore}
    campi_personalizzati TEXT NOT NULL DEFAULT '{}',
    -- Blob di ricerca normalizzato (maiuscole, senza accenti).
    search_blob   TEXT    NOT NULL DEFAULT '',
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (codice, azienda)
);

CREATE INDEX IF NOT EXISTS idx_articoli_marca    ON articoli (codice_marca);
CREATE INDEX IF NOT EXISTS idx_articoli_barcode  ON articoli (barcode);
CREATE INDEX IF NOT EXISTS idx_articoli_azienda  ON articoli (azienda);
CREATE INDEX IF NOT EXISTS idx_articoli_search   ON articoli (search_blob);

-- ---------------------------------------------------------------------------
-- Listini / prezzi: piu' righe per articolo (una per listino)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS listini (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    codice_articolo TEXT    NOT NULL,
    azienda         TEXT    NOT NULL DEFAULT '',
    nome_listino    TEXT    NOT NULL DEFAULT 'DEFAULT',
    prezzo          REAL,
    prezzo_iva      REAL,
    data_validita   TEXT,
    campi_extra     TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (codice_articolo, azienda, nome_listino)
);

CREATE INDEX IF NOT EXISTS idx_listini_articolo ON listini (codice_articolo);
CREATE INDEX IF NOT EXISTS idx_listini_listino  ON listini (nome_listino);
CREATE INDEX IF NOT EXISTS idx_listini_prezzo   ON listini (prezzo);

-- ---------------------------------------------------------------------------
-- Campi personalizzati (definiti da admin)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS campi_personalizzati (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chiave       TEXT    NOT NULL UNIQUE,   -- slug stabile, usato come chiave nel JSON
    etichetta    TEXT    NOT NULL,
    tipo         TEXT    NOT NULL CHECK (tipo IN ('testo', 'numero', 'data', 'flag', 'lista')),
    opzioni      TEXT    NOT NULL DEFAULT '[]',  -- JSON array (solo tipo 'lista')
    obbligatorio INTEGER NOT NULL DEFAULT 0 CHECK (obbligatorio IN (0, 1)),
    ordine       INTEGER NOT NULL DEFAULT 0,
    attivo       INTEGER NOT NULL DEFAULT 1 CHECK (attivo IN (0, 1)),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------------
-- Utenti e sessioni
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS utenti (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    nome          TEXT    NOT NULL DEFAULT '',
    ruolo         TEXT    NOT NULL DEFAULT 'operatore' CHECK (ruolo IN ('admin', 'operatore')),
    attivo        INTEGER NOT NULL DEFAULT 1 CHECK (attivo IN (0, 1)),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessioni (
    token      TEXT    PRIMARY KEY,
    utente_id  INTEGER NOT NULL REFERENCES utenti (id) ON DELETE CASCADE,
    csrf_token TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessioni_scadenza ON sessioni (expires_at);

-- ---------------------------------------------------------------------------
-- Viste salvate (filtri personalizzati)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS viste (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nome       TEXT    NOT NULL,
    ambito     TEXT    NOT NULL DEFAULT 'personale' CHECK (ambito IN ('personale', 'condivisa')),
    utente_id  INTEGER REFERENCES utenti (id) ON DELETE CASCADE,
    filtri     TEXT    NOT NULL DEFAULT '{}',  -- JSON
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_viste_utente ON viste (utente_id);

-- ---------------------------------------------------------------------------
-- Log importazioni
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_importazioni (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file         TEXT    NOT NULL,
    tipo         TEXT    NOT NULL,             -- articoli | marche | listini
    formato      TEXT    NOT NULL DEFAULT 'csv',   -- csv | xlsx
    strategia    TEXT    NOT NULL DEFAULT 'upsert',
    stato        TEXT    NOT NULL DEFAULT 'completata',
    timestamp    TEXT    NOT NULL DEFAULT (datetime('now')),
    righe_totali INTEGER NOT NULL DEFAULT 0,
    inseriti     INTEGER NOT NULL DEFAULT 0,
    aggiornati   INTEGER NOT NULL DEFAULT 0,
    scartati     INTEGER NOT NULL DEFAULT 0,
    errori       TEXT    NOT NULL DEFAULT '[]',  -- JSON array
    dettaglio    TEXT    NOT NULL DEFAULT '{}',  -- JSON (mappa colonne, ecc.)
    utente_id    INTEGER REFERENCES utenti (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_log_import_timestamp ON log_importazioni (timestamp DESC);

-- ---------------------------------------------------------------------------
-- Impostazioni chiave/valore
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS impostazioni (
    chiave TEXT PRIMARY KEY,
    valore TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Mappe di importazione salvate (per xlsx con campi da mappare)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mappe_importazione (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo       TEXT    NOT NULL,
    nome       TEXT    NOT NULL,
    mappa      TEXT    NOT NULL DEFAULT '{}',  -- JSON {"campo_target": indice_colonna}
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (tipo, nome)
);
