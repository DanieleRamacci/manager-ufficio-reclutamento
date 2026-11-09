"""Database SQLite del monitoraggio (data-model.md)."""
import json
import sqlite3

from . import config

SCHEMA_VERSION = 17

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
    messaggio TEXT,
    letti INTEGER,
    totale INTEGER
);
"""


SCHEMA_4 = """
CREATE TABLE IF NOT EXISTS utente (
    username TEXT PRIMARY KEY,
    ruolo TEXT NOT NULL CHECK (ruolo IN ('amministratore', 'lettura')),
    email TEXT,
    aggiunto_da TEXT,
    aggiunto_il TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS utente_modifica (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    azione TEXT NOT NULL,
    ruolo TEXT,
    autore TEXT,
    quando TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monitoraggio_mese (
    mese TEXT PRIMARY KEY,
    mese_dati TEXT NOT NULL,
    link_scorrimenti TEXT,
    link_graduatorie TEXT,
    oggetto TEXT,
    testo TEXT,
    creato_da TEXT,
    creato_il TEXT NOT NULL,
    stato TEXT NOT NULL DEFAULT 'aperto' CHECK (stato IN ('aperto', 'chiuso')),
    chiuso_da TEXT,
    chiuso_il TEXT,
    difformita_aggiornate_il TEXT,
    tipologie TEXT,
    verifica_fonti_il TEXT
);

-- Numero di gestione: identificativo interno e stabile di ogni codice, usato negli ID dei messaggi.
CREATE TABLE IF NOT EXISTS gestione (
    numero INTEGER PRIMARY KEY AUTOINCREMENT,
    chiave TEXT NOT NULL UNIQUE,
    creato_il TEXT NOT NULL
);

-- Registro di ogni messaggio ai referenti: inviato, copiato, segnato a mano o di prova.
CREATE TABLE IF NOT EXISTS comunicazione (
    id TEXT PRIMARY KEY,
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    chiave TEXT NOT NULL,
    numero_bando TEXT,
    codice TEXT,
    destinatari TEXT,
    oggetto TEXT,
    corpo TEXT,
    n_difformita INTEGER,
    canale TEXT NOT NULL CHECK (canale IN ('Casella ufficio', 'Copia manuale', 'Client email', 'Segnata a mano', 'Email di prova')),
    stato TEXT NOT NULL CHECK (stato IN ('inviata', 'da confermare', 'prova', 'annullata')),
    data TEXT NOT NULL,
    utente TEXT
);
CREATE INDEX IF NOT EXISTS idx_comunicazione_mese ON comunicazione (mese, chiave, data);

CREATE TABLE IF NOT EXISTS comunicazione_indirizzi (
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    chiave TEXT NOT NULL,
    esclusi TEXT NOT NULL DEFAULT '[]',
    cc TEXT NOT NULL DEFAULT '[]',
    modificata_da TEXT,
    modificata_il TEXT,
    PRIMARY KEY (mese, chiave)
);

CREATE TABLE IF NOT EXISTS attivita (
    chiave TEXT PRIMARY KEY,
    orario TEXT,
    attiva INTEGER
);

CREATE TABLE IF NOT EXISTS esecuzione (
    id INTEGER PRIMARY KEY,
    attivita TEXT NOT NULL,
    data TEXT NOT NULL,
    esito TEXT NOT NULL CHECK (esito IN ('ok', 'avviso', 'errore', 'in_corso')),
    durata_s INTEGER,
    dettaglio TEXT
);
CREATE INDEX IF NOT EXISTS idx_esecuzione ON esecuzione (attivita, id);

CREATE TABLE IF NOT EXISTS utente_accesso (
    username TEXT PRIMARY KEY,
    quando TEXT NOT NULL
);

-- Fotografia del mese alla chiusura: non cambia più se cambiano le fonti. Niente dati dei candidati.
CREATE TABLE IF NOT EXISTS monitoraggio_versione (
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    versione INTEGER NOT NULL,
    creata_da TEXT,
    creata_il TEXT NOT NULL,
    motivo TEXT,
    PRIMARY KEY (mese, versione)
);

CREATE TABLE IF NOT EXISTS monitoraggio_riga (
    id INTEGER PRIMARY KEY,
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    versione INTEGER NOT NULL DEFAULT 1,
    numero_bando TEXT,
    codice TEXT,
    titolo_bando TEXT,
    tipologia TEXT,
    atto TEXT NOT NULL,
    sottotipo TEXT,
    data TEXT,
    protocollo TEXT,
    sol_stato TEXT,
    sol_protocollo TEXT,
    urp_stato TEXT,
    urp_protocollo TEXT,
    segreteria_stato TEXT,
    segreteria_protocollo TEXT,
    rdp TEXT,
    note TEXT,
    difforme INTEGER NOT NULL DEFAULT 0,
    sollecito_stato TEXT,
    sollecito_autore TEXT,
    sollecito_quando TEXT
);
CREATE INDEX IF NOT EXISTS idx_monitoraggio_riga ON monitoraggio_riga (mese, difforme);

CREATE TABLE IF NOT EXISTS monitoraggio_punteggi (
    id INTEGER PRIMARY KEY,
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    versione INTEGER NOT NULL DEFAULT 1,
    numero_bando TEXT,
    codice TEXT,
    protocollo TEXT,
    data TEXT,
    domande INTEGER,
    con_punteggi INTEGER,
    vincitori INTEGER,
    idonei INTEGER,
    scorrimento INTEGER,
    senza_protocollo INTEGER,
    esito TEXT,
    verificato_il TEXT,
    difformita TEXT
);
CREATE INDEX IF NOT EXISTS idx_monitoraggio_punteggi ON monitoraggio_punteggi (mese);

CREATE TABLE IF NOT EXISTS monitoraggio_fonte (
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    versione INTEGER NOT NULL DEFAULT 1,
    fonte TEXT NOT NULL,
    ultima_raccolta TEXT,
    PRIMARY KEY (mese, versione, fonte)
);

-- Registro delle difformità di ogni mese: restano dopo la correzione. Niente dati dei candidati.
CREATE TABLE IF NOT EXISTS difformita (
    id INTEGER PRIMARY KEY,
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    numero_bando TEXT,
    codice TEXT,
    titolo_bando TEXT,
    tipologia TEXT,
    atto TEXT NOT NULL,
    data TEXT,
    protocollo TEXT,
    protocolli TEXT,
    rilievi_iniziali TEXT NOT NULL,
    rilievi_attuali TEXT NOT NULL,
    stato TEXT NOT NULL CHECK (stato IN ('aperta', 'corretta', 'da_controllare')),
    prima_rilevata_il TEXT NOT NULL,
    corretta_il TEXT,
    ultimo_controllo_il TEXT
);
CREATE INDEX IF NOT EXISTS idx_difformita_mese ON difformita (mese, stato);

CREATE TABLE IF NOT EXISTS difformita_evento (
    id INTEGER PRIMARY KEY,
    difformita_id INTEGER NOT NULL REFERENCES difformita(id),
    quando TEXT NOT NULL,
    tipo TEXT NOT NULL,
    origine TEXT,
    utente TEXT,
    dettaglio TEXT
);

CREATE TABLE IF NOT EXISTS monitoraggio_evento (
    id INTEGER PRIMARY KEY,
    mese TEXT NOT NULL,
    azione TEXT NOT NULL CHECK (azione IN ('creato', 'chiuso', 'riaperto')),
    autore TEXT,
    quando TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS impostazione (
    chiave TEXT PRIMARY KEY,
    valore TEXT,
    modificata_da TEXT,
    modificata_il TEXT
);

CREATE TABLE IF NOT EXISTS sollecito (
    mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese),
    numero_bando TEXT NOT NULL,
    stato TEXT NOT NULL CHECK (stato IN ('inviata', 'inviata_a_mano')),
    autore TEXT,
    quando TEXT NOT NULL,
    destinatari TEXT,
    oggetto TEXT,
    PRIMARY KEY (mese, numero_bando)
);

CREATE TABLE IF NOT EXISTS invio_email (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('compilazione', 'sollecito')),
    mese TEXT,
    numero_bando TEXT,
    utente TEXT,
    quando TEXT NOT NULL,
    destinatari TEXT,
    oggetto TEXT,
    esito TEXT NOT NULL CHECK (esito IN ('inviata', 'prova', 'errore')),
    errore TEXT
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


def _migra_versioni(conn: sqlite3.Connection) -> None:
    """Versione 10: le fotografie salvate con la 9 diventano la versione 1 del loro mese."""
    if "versione" not in {r[1] for r in conn.execute("PRAGMA table_info(monitoraggio_fonte)")}:
        conn.executescript("""
            BEGIN;
            ALTER TABLE monitoraggio_riga ADD COLUMN versione INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE monitoraggio_punteggi ADD COLUMN versione INTEGER NOT NULL DEFAULT 1;
            CREATE TABLE monitoraggio_fonte_10 (
                mese TEXT NOT NULL REFERENCES monitoraggio_mese(mese), versione INTEGER NOT NULL DEFAULT 1,
                fonte TEXT NOT NULL, ultima_raccolta TEXT, PRIMARY KEY (mese, versione, fonte));
            INSERT INTO monitoraggio_fonte_10 (mese, versione, fonte, ultima_raccolta)
                SELECT mese, 1, fonte, ultima_raccolta FROM monitoraggio_fonte;
            DROP TABLE monitoraggio_fonte;
            ALTER TABLE monitoraggio_fonte_10 RENAME TO monitoraggio_fonte;
            INSERT OR IGNORE INTO monitoraggio_versione (mese, versione, creata_da, creata_il)
                SELECT m.mese, 1, m.chiuso_da, COALESCE(m.chiuso_il, m.creato_il) FROM monitoraggio_mese m
                WHERE EXISTS (SELECT 1 FROM monitoraggio_fonte f WHERE f.mese = m.mese);
            COMMIT;
        """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_riga_versione ON monitoraggio_riga (mese, versione)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_punteggi_versione ON monitoraggio_punteggi (mese, versione)")


def _migra_comunicazioni(conn: sqlite3.Connection) -> None:
    """Versione 12: i solleciti già segnati entrano nel registro delle comunicazioni."""
    for r in conn.execute("SELECT s.* FROM sollecito s WHERE NOT EXISTS (SELECT 1 FROM comunicazione c WHERE c.mese = s.mese "
                          "AND c.chiave = s.numero_bando)").fetchall():
        conn.execute("INSERT OR IGNORE INTO comunicazione (id, mese, chiave, numero_bando, codice, destinatari, oggetto, canale, stato, data, utente) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'inviata', ?, ?)",
                     (f"MIGRATA/{r['mese']}/{r['numero_bando']}", r["mese"], r["numero_bando"], r["numero_bando"].split(" ")[0], r["numero_bando"],
                      json.dumps([x for x in (r["destinatari"] or "").split(", ") if x]), r["oggetto"],
                      "Casella ufficio" if r["stato"] == "inviata" else "Segnata a mano", r["quando"], r["autore"]))


def inizializza(conn: sqlite3.Connection) -> None:
    """Crea le tabelle mancanti e aggiorna la versione dello schema (le CREATE sono idempotenti)."""
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA_2)
    conn.executescript(SCHEMA_3)
    conn.executescript(SCHEMA_4)
    colonne_mese = {r[1] for r in conn.execute("PRAGMA table_info(monitoraggio_mese)")}
    for colonna, tipo in (("stato", "TEXT NOT NULL DEFAULT 'aperto'"), ("chiuso_da", "TEXT"), ("chiuso_il", "TEXT"),  # versione 9
                          ("difformita_aggiornate_il", "TEXT"),  # versione 11
                          ("tipologie", "TEXT"), ("verifica_fonti_il", "TEXT")):  # versione 12
        if colonna not in colonne_mese:
            conn.execute(f"ALTER TABLE monitoraggio_mese ADD COLUMN {colonna} {tipo}")
    colonne_referenti = {r[1] for r in conn.execute("PRAGMA table_info(referenti_aggiornamento)")}
    for colonna in ("letti", "totale"):  # versione 14
        if colonna not in colonne_referenti:
            conn.execute(f"ALTER TABLE referenti_aggiornamento ADD COLUMN {colonna} INTEGER")
    if "cc" not in {r[1] for r in conn.execute("PRAGMA table_info(comunicazione)")}:  # versione 17
        conn.execute("ALTER TABLE comunicazione ADD COLUMN cc TEXT")
    _migra_versioni(conn)
    _migra_comunicazioni(conn)
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
        if "email" not in {r[1] for r in conn.execute("PRAGMA table_info(utente)")}:  # versione 8
            conn.execute("ALTER TABLE utente ADD COLUMN email TEXT")
        for versione, tipi in ((15, ("categorie_protette",)), (16, ("reclutamento_speciale", "comando"))):
            if riga["versione"] < versione:  # tipologie escluse dal monitoraggio mensile
                elenco = ", ".join(f"'{t}'" for t in tipi)
                fuori = (f"FROM difformita WHERE tipologia IN ({elenco}) OR numero_bando IN "
                         f"(SELECT numero_bando FROM bando WHERE tipologia IN ({elenco}))")
                conn.execute(f"DELETE FROM difformita_evento WHERE difformita_id IN (SELECT id {fuori})")
                conn.execute(f"DELETE {fuori}")
        conn.execute("UPDATE schema_version SET versione = ?", (SCHEMA_VERSION,))
