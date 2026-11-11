"""Profili seguiti dai coordinatori.

Decisioni dell'utente del 2026-11-11: ogni profilo ha al più un coordinatore; chi vuole un profilo già preso lo chiede,
l'avviso arriva a entrambi, chi lo ha può cederlo e l'amministratore decide in ultima istanza.
I profili sono quelli del contratto, senza il livello («Collaboratore tecnico enti di ricerca» vale per IV, V e VI): l'elenco
è completo anche prima che un bando di quel profilo sia letto da Selezioni Online, e la scelta vale per i bandi futuri.
In più c'è la voce «Mobilità», esclusiva come un profilo: comprende tutti i bandi di mobilità (e i comandi), di ogni profilo.
Così ogni bando ha un solo coordinatore: quello di «Mobilità» per la mobilità, quello del profilo per gli altri.
Altre eccezioni si aggiungono qui, se serviranno.
"""
import json
import logging
import re
from datetime import datetime, timezone

from . import config, posta

log = logging.getLogger(__name__)
APERTA, ACCOLTA, RESPINTA = "aperta", "accolta", "respinta"


def _adesso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# profili degli enti di ricerca, dal più alto al più basso; i livelli sono dentro il profilo
LIVELLI = {
    "Ricercatore": "Dirigente di ricerca (I), Primo ricercatore (II), Ricercatore (III)",
    "Tecnologo": "Dirigente tecnologo (I), Primo tecnologo (II), Tecnologo (III)",
    "Funzionario di amministrazione": "IV e V livello",
    "Collaboratore tecnico enti di ricerca": "IV, V e VI livello",
    "Collaboratore di amministrazione": "V, VI e VII livello",
    "Operatore tecnico": "VI, VII e VIII livello",
    "Operatore di amministrazione": "VII e VIII livello",
}
CATALOGO = tuple(LIVELLI)
MOBILITA = "Mobilità"
TIPI_MOBILITA = ("mobilita", "comando")  # l'URP distingue il comando solo dal testo del bando
LIVELLI[MOBILITA] = "Tutti i bandi di mobilità e i comandi, di ogni profilo"
_LIVELLO = re.compile(r"\b(?:livello\s+(?:[ivx]+|\d+)|(?:[ivx]+|\d+)\s*[°^]?\s*livello)\b", re.I)


def famiglia(profilo_sol: str | None) -> str | None:
    """Il profilo senza il livello, dal testo di Selezioni Online («I Tecnologo II livello» -> «Tecnologo»)."""
    if not profilo_sol or not profilo_sol.strip():
        return None
    t = " ".join(profilo_sol.lower().replace(".", " ").split())
    regole = (("collaboratore tecnico" in t or re.search(r"\bc\s?t\s?e\s?r\b", t), "Collaboratore tecnico enti di ricerca"),
              ("operatore tecnico" in t, "Operatore tecnico"),
              ("amministrazione" in t and "funzionario" in t, "Funzionario di amministrazione"),
              ("amministrazione" in t and "collaboratore" in t, "Collaboratore di amministrazione"),
              ("amministrazione" in t and "operatore" in t, "Operatore di amministrazione"),
              ("tecnologo" in t, "Tecnologo"),
              ("ricercatore" in t or "dirigente di ricerca" in t, "Ricercatore"))
    for vero, nome in regole:
        if vero:
            return nome
    resto = " ".join(_LIVELLO.sub(" ", profilo_sol).replace("-", " ").split()).strip(" ,;:")
    return (resto[:1].upper() + resto[1:]) if resto else None


def voce(tipologia: str | None, profilo: str | None) -> str | None:
    """La voce dell'elenco a cui appartiene un bando: «Mobilità» per la mobilità, altrimenti il suo profilo."""
    return MOBILITA if tipologia in TIPI_MOBILITA else profilo


def disponibili(conn) -> list[str]:
    """Tutti i profili del contratto, più quelli letti da Selezioni Online che non vi rientrano, e «Mobilità»."""
    altri = set()
    for s in conn.execute("SELECT dati_extra FROM scheda WHERE fonte = 'sol' AND presente = 1 AND dati_extra IS NOT NULL"):
        nome = famiglia(json.loads(s["dati_extra"]).get("profilo"))
        if nome and nome not in CATALOGO:
            altri.add(nome)
    return [*CATALOGO, *sorted(altri), MOBILITA]


def per_bando(conn) -> tuple[dict, dict, dict]:
    """La voce dell'elenco (profilo senza livello, o «Mobilità») per scheda, per bando e per numero del bando."""
    scheda, bando, numero = {}, {}, {}
    for s in conn.execute("SELECT id, bando_id, numero_bando, tipologia, dati_extra FROM scheda WHERE fonte = 'sol' AND presente = 1 AND dati_extra IS NOT NULL"):
        nome = voce(s["tipologia"], famiglia(json.loads(s["dati_extra"]).get("profilo")))
        if nome:
            scheda[s["id"]] = nome
            bando.setdefault(s["bando_id"], nome)
            numero.setdefault(s["numero_bando"], nome)
    return scheda, bando, numero


def titolari(conn) -> dict[str, str]:
    return {r["profilo"]: r["email"] for r in conn.execute("SELECT profilo, email FROM profilo_coordinato")}


def di(conn, email: str) -> list[str]:
    return [r["profilo"] for r in conn.execute("SELECT profilo FROM profilo_coordinato WHERE email = ? ORDER BY profilo", (email,))]


def prendi(conn, email: str, profilo: str) -> str | None:
    """Assegna il profilo se è libero. Ritorna chi lo ha già, se è un altro."""
    titolare = titolari(conn).get(profilo)
    if titolare and titolare != email:
        return titolare
    conn.execute("INSERT OR IGNORE INTO profilo_coordinato (profilo, email, dal) VALUES (?, ?, ?)", (profilo, email, _adesso()))
    return None


def lascia(conn, email: str, profilo: str) -> bool:
    return conn.execute("DELETE FROM profilo_coordinato WHERE profilo = ? AND email = ?", (profilo, email)).rowcount > 0


def assegna(conn, profilo: str, email: str | None) -> None:
    """Scelta dell'amministratore: vale anche se il profilo era di un altro."""
    conn.execute("DELETE FROM profilo_coordinato WHERE profilo = ?", (profilo,))
    if email:
        conn.execute("INSERT INTO profilo_coordinato (profilo, email, dal) VALUES (?, ?, ?)", (profilo, email, _adesso()))
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_il = ? WHERE profilo = ? AND stato = ? AND richiedente = ?",
                 (ACCOLTA, _adesso(), profilo, APERTA, email or ""))


def togli_coordinatore(conn, email: str) -> None:
    conn.execute("DELETE FROM profilo_coordinato WHERE email = ?", (email,))
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_il = ? WHERE stato = ? AND richiedente = ?",
                 (RESPINTA, _adesso(), APERTA, email))


def richieste(conn, solo_aperte: bool = True) -> list[dict]:
    filtro = "WHERE stato = 'aperta' " if solo_aperte else ""
    return [dict(r) for r in conn.execute(f"SELECT * FROM profilo_richiesta {filtro}ORDER BY id DESC")]


def richiedi(conn, email: str, profilo: str) -> dict:
    """Una sola richiesta aperta per persona e profilo; l'avviso parte solo alla prima."""
    gia = conn.execute("SELECT * FROM profilo_richiesta WHERE profilo = ? AND richiedente = ? AND stato = ?",
                       (profilo, email, APERTA)).fetchone()
    if gia:
        return {**dict(gia), "nuova": False}
    titolare = titolari(conn).get(profilo)
    cur = conn.execute("INSERT INTO profilo_richiesta (profilo, richiedente, titolare, quando) VALUES (?, ?, ?, ?)",
                       (profilo, email, titolare, _adesso()))
    return {"id": cur.lastrowid, "profilo": profilo, "richiedente": email, "titolare": titolare, "stato": APERTA, "nuova": True}


def cedi(conn, richiesta_id: int, email: str) -> dict | None:
    """Chi ha il profilo lo cede a chi l'ha chiesto."""
    r = conn.execute("SELECT * FROM profilo_richiesta WHERE id = ? AND stato = ?", (richiesta_id, APERTA)).fetchone()
    if not r or titolari(conn).get(r["profilo"]) != email:
        return None
    assegna(conn, r["profilo"], r["richiedente"])
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ?", (ACCOLTA, email, _adesso(), richiesta_id))
    return dict(r)


def chiudi(conn, richiesta_id: int, accolta: bool, autore: str | None) -> dict | None:
    """Decisione dell'amministratore su una richiesta aperta."""
    r = conn.execute("SELECT * FROM profilo_richiesta WHERE id = ? AND stato = ?", (richiesta_id, APERTA)).fetchone()
    if not r:
        return None
    if accolta:
        assegna(conn, r["profilo"], r["richiedente"])
    conn.execute("UPDATE profilo_richiesta SET stato = ?, gestita_da = ?, gestita_il = ? WHERE id = ?",
                 (ACCOLTA if accolta else RESPINTA, autore, _adesso(), richiesta_id))
    return dict(r)


def avvisa_richiesta(richiesta: dict) -> bool:
    """Avvisa entrambi: chi chiede e chi ha già il profilo."""
    destinatari = [x for x in (richiesta["titolare"], richiesta["richiedente"]) if x]
    corpo = (f"Buongiorno,\n\n{richiesta['richiedente']} ha chiesto di coordinare il profilo «{richiesta['profilo']}», "
             f"che oggi risulta coordinato da {richiesta['titolare'] or 'nessuno'}.\n\n"
             "Un profilo può avere un solo coordinatore. Chi lo coordina oggi può cederlo dalla pagina dei profili dell'area referenti:\n"
             f"{config.sito_url()}/referenti/profili\n\n"
             "In caso contrario decide l'Ufficio reclutamento.\n")
    try:
        posta.invia(destinatari, f"Richiesta del profilo «{richiesta['profilo']}» nel monitoraggio bandi", corpo, sempre_reale=True)
        return True
    except posta.PostaErrore:
        log.warning("Avviso della richiesta di profilo non inviato")
        return False


def avvisa_cessione(richiesta: dict) -> None:
    destinatari = [x for x in (richiesta["titolare"], richiesta["richiedente"]) if x]
    try:
        posta.invia(destinatari, f"Profilo «{richiesta['profilo']}» ora coordinato da {richiesta['richiedente']}",
                    f"Buongiorno,\n\nil profilo «{richiesta['profilo']}» è ora coordinato da {richiesta['richiedente']}.\n", sempre_reale=True)
    except posta.PostaErrore:
        log.warning("Avviso della cessione del profilo non inviato")
