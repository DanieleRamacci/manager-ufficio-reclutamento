"""Database SQLite del monitoraggio (data-model.md)."""
import sqlite3

from . import config

SCHEMA_VERSION = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    versione INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bando (
    id INTEGER PRIMARY KEY,
    codice_norm TEXT UNIQUE,
    numero_bando TEXT,
    codice_sotto TEXT,
    codice TEXT,
    tipologia TEXT,
    titolo TEXT,
    profilo TEXT,
    sede TEXT,
    numero_posti INTEGER,
    gruppo_rdp TEXT,
    data_pubblicazione TEXT,
    stato_collegamento TEXT CHECK (stato_collegamento IN
        ('entrambi', 'solo_urp', 'solo_sol', 'fuori_periodo_urp')),
    creato_il TEXT NOT NULL,
    aggiornato_il TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bando_numero ON bando (numero_bando, codice_sotto);

CREATE TABLE IF NOT EXISTS scheda (
    id INTEGER PRIMARY KEY,
    bando_id INTEGER REFERENCES bando (id),
    fonte TEXT NOT NULL CHECK (fonte IN ('urp', 'sol')),
    id_esterno TEXT NOT NULL,
    sezione TEXT NOT NULL,
    tipologia TEXT,
    codice_originale TEXT,
    codice_norm TEXT,
    numero_bando TEXT,
    codice_sotto TEXT,
    titolo TEXT,
    protocollo TEXT,
    protocollo_originale TEXT,
    data_pubblicazione TEXT,
    data_pubbl_graduatoria TEXT,
    url TEXT,
    dati_extra TEXT,
    modificata_fonte_il TEXT,
    prima_rilevazione TEXT NOT NULL,
    ultima_rilevazione TEXT NOT NULL,
    presente INTEGER NOT NULL DEFAULT 1,
    UNIQUE (fonte, id_esterno)
);
CREATE INDEX IF NOT EXISTS idx_scheda_bando ON scheda (bando_id);
CREATE INDEX IF NOT EXISTS idx_scheda_numero ON scheda (numero_bando, codice_sotto);
CREATE INDEX IF NOT EXISTS idx_scheda_protocollo ON scheda (protocollo);

CREATE TABLE IF NOT EXISTS documento (
    id INTEGER PRIMARY KEY,
    scheda_id INTEGER NOT NULL REFERENCES scheda (id),
    id_esterno TEXT NOT NULL,
    titolo TEXT,
    categoria TEXT NOT NULL CHECK (categoria IN
        ('bando', 'graduatoria', 'scorrimento', 'rettifica', 'criteri', 'tracce', 'altro')),
    sottotipo TEXT CHECK (sottotipo IN ('subentro', 'ulteriore', 'utilizzo', 'non_specificato')),
    sottotipo_ordinale INTEGER,
    sottotipo_origine TEXT,
    tipo_fonte TEXT,
    protocollo TEXT,
    protocollo_originale TEXT,
    data_protocollo TEXT,
    url TEXT,
    accessibilita TEXT,
    prima_rilevazione TEXT NOT NULL,
    ultima_rilevazione TEXT NOT NULL,
    presente INTEGER NOT NULL DEFAULT 1,
    UNIQUE (scheda_id, id_esterno)
);
CREATE INDEX IF NOT EXISTS idx_documento_protocollo ON documento (protocollo);
CREATE INDEX IF NOT EXISTS idx_documento_categoria ON documento (categoria, data_protocollo);

CREATE TABLE IF NOT EXISTS raccolta (
    id INTEGER PRIMARY KEY,
    fonte TEXT NOT NULL CHECK (fonte IN ('urp', 'sol')),
    modalita TEXT NOT NULL CHECK (modalita IN ('notturna', 'manuale', 'completa')),
    avviata_da TEXT,
    inizio TEXT NOT NULL,
    fine TEXT,
    esito TEXT NOT NULL CHECK (esito IN
        ('in_corso', 'completata', 'completata_con_errori', 'fallita')),
    bandi_trovati INTEGER NOT NULL DEFAULT 0,
    documenti_trovati INTEGER NOT NULL DEFAULT 0,
    nuovi INTEGER NOT NULL DEFAULT 0,
    aggiornati INTEGER NOT NULL DEFAULT 0,
    totale_dichiarato TEXT,
    messaggio TEXT
);
CREATE INDEX IF NOT EXISTS idx_raccolta_fonte ON raccolta (fonte, esito);

CREATE TABLE IF NOT EXISTS raccolta_errore (
    id INTEGER PRIMARY KEY,
    raccolta_id INTEGER NOT NULL REFERENCES raccolta (id),
    riferimento TEXT,
    messaggio TEXT
);
"""

# spec 002: file della segreteria
SCHEMA_2 = """
CREATE TABLE IF NOT EXISTS segreteria_versione (
    id INTEGER PRIMARY KEY,
    caricata_il TEXT NOT NULL,
    utente TEXT,
    nome_file TEXT,
    impronta TEXT,
    esito TEXT NOT NULL CHECK (esito IN ('in_uso', 'precedente', 'rifiutata')),
    rapporto TEXT,
    righe INTEGER NOT NULL DEFAULT 0,
    atti INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS segreteria_atto (
    id INTEGER PRIMARY KEY,
    versione_id INTEGER NOT NULL REFERENCES segreteria_versione (id),
    categoria TEXT NOT NULL CHECK (categoria IN ('bando', 'graduatoria', 'scorrimento')),
    numero_bando TEXT,
    codice_sotto TEXT,
    codice_originale TEXT,
    protocollo TEXT,
    protocollo_originale TEXT,
    data TEXT,
    protocollo_privato TEXT,
    data_privato TEXT,
    sottotipo TEXT CHECK (sottotipo IN ('ordinario', 'subentro', 'misto')),
    persone INTEGER NOT NULL DEFAULT 0,
    tipo_procedura TEXT,
    titolo TEXT,
    in_ambito INTEGER NOT NULL DEFAULT 1,
    bando_id INTEGER REFERENCES bando (id)
);
CREATE INDEX IF NOT EXISTS idx_segr_atto_bando ON segreteria_atto (versione_id, categoria, numero_bando);
CREATE INDEX IF NOT EXISTS idx_segr_atto_prot ON segreteria_atto (versione_id, protocollo);

CREATE TABLE IF NOT EXISTS segreteria_riga (
    id INTEGER PRIMARY KEY,
    versione_id INTEGER NOT NULL REFERENCES segreteria_versione (id),
    foglio TEXT NOT NULL,
    numero_riga INTEGER NOT NULL,
    valori TEXT NOT NULL,
    atto_id INTEGER REFERENCES segreteria_atto (id)
);
CREATE INDEX IF NOT EXISTS idx_segr_riga_atto ON segreteria_riga (atto_id);
"""

# spec 003: referenti RdP (solo nome, cognome, email istituzionale, username)
SCHEMA_3 = """
CREATE TABLE IF NOT EXISTS referente (
    id INTEGER PRIMARY KEY,
    scheda_id INTEGER NOT NULL REFERENCES scheda (id),
    chiave TEXT NOT NULL,
    nome TEXT,
    cognome TEXT,
    email TEXT,
    username TEXT,
    attivo INTEGER NOT NULL DEFAULT 1,
    prima_rilevazione TEXT NOT NULL,
    ultima_rilevazione TEXT NOT NULL,
    UNIQUE (scheda_id, chiave)
);

-- spec 004: verifica dei punteggi delle graduatorie su SOL (solo conteggi, niente dati dei candidati)
CREATE TABLE IF NOT EXISTS punteggi_verifica (
    id INTEGER PRIMARY KEY,
    scheda_id INTEGER NOT NULL REFERENCES scheda (id),
    verificato_il TEXT NOT NULL,
    domande INTEGER,
    con_punteggi INTEGER,
    vincitori INTEGER,
    idonei INTEGER,
    scorrimento INTEGER,
    senza_protocollo INTEGER,
    senza_esito INTEGER,
    protocollo_diverso INTEGER,
    data_diversa INTEGER,
    scorrimenti_sol TEXT,
    esito TEXT NOT NULL CHECK (esito IN
        ('completi', 'parziali', 'mancanti', 'protocollo_mancante', 'nessuna_domanda', 'errore')),
    messaggio TEXT
);
CREATE INDEX IF NOT EXISTS idx_punteggi_scheda ON punteggi_verifica (scheda_id, verificato_il);

CREATE TABLE IF NOT EXISTS referenti_aggiornamento (
    id INTEGER PRIMARY KEY,
    utente TEXT,
    inizio TEXT NOT NULL,
    fine TEXT,
    esito TEXT NOT NULL CHECK (esito IN ('in_corso', 'completato', 'fallito')),
    bandi INTEGER NOT NULL DEFAULT 0,
    referenti INTEGER NOT NULL DEFAULT 0,
    messaggio TEXT
);
"""


def connetti() -> sqlite3.Connection:
    path = config.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: le transazioni sono aperte esplicitamente con BEGIN
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def inizializza(conn: sqlite3.Connection) -> None:
    """Crea le tabelle mancanti e aggiorna la versione dello schema (le CREATE sono idempotenti)."""
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA_2)
    conn.executescript(SCHEMA_3)
    riga = conn.execute("SELECT versione FROM schema_version").fetchone()
    if riga is None:
        conn.execute("INSERT INTO schema_version (versione) VALUES (?)", (SCHEMA_VERSION,))
    elif riga["versione"] < SCHEMA_VERSION:
        if riga["versione"] < 5:
            # la tabella della versione 4 conteneva solo prove: si ricrea con i nuovi conteggi
            conn.execute("DROP TABLE IF EXISTS punteggi_verifica")
            conn.executescript(SCHEMA_3)
        colonne = {r[1] for r in conn.execute("PRAGMA table_info(punteggi_verifica)")}
        for colonna, tipo in (("senza_esito", "INTEGER"), ("protocollo_diverso", "INTEGER"),  # versione 6
                              ("data_diversa", "INTEGER"), ("scorrimenti_sol", "TEXT")):
            if colonna not in colonne:
                conn.execute(f"ALTER TABLE punteggi_verifica ADD COLUMN {colonna} {tipo}")
        conn.execute("UPDATE schema_version SET versione = ?", (SCHEMA_VERSION,))
