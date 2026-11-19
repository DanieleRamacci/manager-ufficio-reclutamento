"""Monitoraggio bandi CNR - lettura delle email di protocollo (Titulus) in copia.

Legge le email «Il sistema di protocollo le ha assegnato il seguente documento ...» e manda al sito del monitoraggio
SOLO: numero e data di protocollo, segnatura, oggetto, link Titulus, data di ricezione e un identificativo dell'email.
Non manda il resto delle email, non apre i documenti su Titulus, non modifica né sposta niente nella posta.

Dove legge:
  - Outlook classico installato sul PC (senza password): tutte le caselle collegate al profilo (personale, generale della
    segreteria, ...), Posta in arrivo e sottocartelle (--tutte-le-cartelle: tutte le cartelle); --caselle per sceglierle;
  - oppure una cartella di Windows con le email salvate (.eml o .msg), con --cartella "C:\\percorso".

Uso (dai file .bat):  Prova-senza-inviare.bat  ·  Leggi-e-invia.bat  ·  Controllo-continuo.bat
"""
from __future__ import annotations

import argparse
import email
import email.policy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

SERVER = "__SERVER__"
VERSIONE = "1.2"
FRASE = "Il sistema di protocollo"
NUMERO = re.compile(r"N\.\s*(\d{1,7})\s+del\s+(\d{8})\s*\(([^)\s]+)\)")
CONFIG = Path(os.environ.get("APPDATA") or Path.home()) / "MonitoraggioProtocollo" / "config.json"


def leggi_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_config(dati: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(dati, indent=2), encoding="utf-8")


def analizza(oggetto_email: str, corpo: str, ricevuta: str, identificativo: str) -> dict | None:
    """I dati di un'email di Titulus; None se non lo è."""
    if FRASE not in (corpo or ""):
        return None
    m = NUMERO.search(corpo)
    if not m:
        return None
    o = re.search(r"Oggetto:\s*(.+)", corpo)
    link = re.search(r"https://titulus[^\s<>\"']+", corpo)
    oggetto = (o.group(1) if o else re.sub(r"^\s*\[CC\]\s*:?\s*", "", oggetto_email or "")).strip()
    return {"numero": m.group(1), "data": m.group(2), "segnatura": m.group(3), "oggetto": " ".join(oggetto.split()),
            "link": link.group(0) if link else "", "ricevuta_il": ricevuta, "id_messaggio": identificativo}


def _outlook():
    try:
        import win32com.client  # pywin32: solo con Outlook classico
    except ImportError:
        raise SystemExit("Manca pywin32: avvia il programma dai file .bat, che lo installano.")
    try:
        return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        raise SystemExit("Outlook classico non risponde. Con il «nuovo Outlook» usa la modalità cartella (vedi LEGGIMI.txt).")


def _elementi(collezione, cosa: str = "elemento"):
    """Gli elementi di una raccolta di Outlook uno per uno: se uno non risponde (casella condivisa non raggiungibile, archivio
    .pst scollegato, account che chiede la password) si salta, invece di fermare tutto (errore OLE 0xc2040111)."""
    try:
        quanti = collezione.Count
    except Exception:
        return
    for i in range(1, quanti + 1):
        try:
            yield collezione.Item(i)
        except Exception as e:
            print(f"   {cosa} {i} non leggibile, saltato ({_errore(e)})")


def _errore(e) -> str:
    try:
        return f"{e.args[1]} {hex(e.args[0] & 0xFFFFFFFF)}"
    except Exception:
        return type(e).__name__


def caselle(ns) -> list:
    """Le caselle collegate al profilo di Outlook (personale, generale della segreteria, altri account), senza cartelle pubbliche."""
    trovate = []
    for store in _elementi(ns.Stores, "casella"):
        try:
            if getattr(store, "ExchangeStoreType", None) == 2:  # cartelle pubbliche
                continue
            trovate.append((store, str(store.DisplayName or "").strip() or "casella senza nome"))
        except Exception as e:
            print(f"   una casella non risponde, saltata ({_errore(e)})")
    return trovate


def da_outlook(giorni: int, tutte: bool = False, filtro: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Le email di Titulus delle caselle scelte (tutte, se `filtro` è vuoto). Ogni email dice da quale casella arriva."""
    ns = _outlook()
    limite = datetime.now() - timedelta(days=giorni)
    trovate: list[dict] = []
    lette: list[str] = []

    def cartella(f, nome_casella, profondita=0):
        try:
            elementi = f.Items
            elementi.Sort("[ReceivedTime]", True)
            elementi = _elementi(elementi, "email")
        except Exception:
            elementi = []
        for it in elementi:
            try:
                if getattr(it, "Class", 0) != 43:  # solo email
                    continue
                ricevuta = it.ReceivedTime
                quando = datetime(ricevuta.year, ricevuta.month, ricevuta.day, ricevuta.hour, ricevuta.minute)
                if quando < limite:
                    break
                v = analizza(it.Subject or "", it.Body or "", quando.isoformat(timespec="minutes"), it.EntryID)
                if v:
                    v["casella"] = nome_casella
                    trovate.append(v)
            except Exception:
                continue
        if profondita < 4:
            try:
                for sotto in _elementi(f.Folders, "cartella"):
                    cartella(sotto, nome_casella, profondita + 1)
            except Exception:
                pass

    elenco = caselle(ns)
    for store, nome in elenco:
        if filtro and not any(x.lower() in nome.lower() for x in filtro):
            continue
        try:
            inbox = store.GetDefaultFolder(6)
        except Exception:
            inbox = None  # es. archivio .pst o casella senza Posta in arrivo: si legge tutta
        try:
            cartella(store.GetRootFolder() if tutte or inbox is None else inbox, nome)
            lette.append(nome)
        except Exception as e:
            print(f"   casella «{nome}» non leggibile, saltata ({_errore(e)})")
    if not elenco:  # Outlook non dà l'elenco delle caselle: almeno la Posta in arrivo principale
        try:
            cartella(ns.GetDefaultFolder(6), "Posta in arrivo")
            lette.append("Posta in arrivo")
        except Exception as e:
            raise SystemExit(f"Outlook non permette di leggere la posta ({_errore(e)}). Apri Outlook classico e riprova.")
    return trovate, lette


def da_cartella(percorso: str) -> tuple[list[dict], list[str]]:
    trovate = []
    for f in sorted(Path(percorso).glob("*")):
        try:
            if f.suffix.lower() == ".eml":
                msg = email.message_from_bytes(f.read_bytes(), policy=email.policy.default)
                parte = msg.get_body(preferencelist=("plain", "html"))
                corpo = parte.get_content() if parte else ""
                corpo = re.sub(r"<[^>]+>", "\n", corpo)
                v = analizza(str(msg["subject"] or ""), corpo, str(msg["date"] or ""), str(msg["message-id"] or f.name))
            elif f.suffix.lower() == ".msg":
                try:
                    import extract_msg
                except ImportError:
                    print(f"  {f.name}: per i file .msg serve extract_msg (lo installa il .bat); salta")
                    continue
                m = extract_msg.Message(str(f))
                v = analizza(m.subject or "", m.body or "", str(m.date or ""), m.messageId or f.name)
            else:
                continue
            if v:
                v["casella"] = f"cartella {Path(percorso).name}"
                trovate.append(v)
        except Exception as e:
            print(f"  {f.name}: non letto ({type(e).__name__})")
    return trovate, [f"cartella {percorso}"]


class Rifiutato(Exception):
    """Il sito non ha accettato l'invio (es. PC in attesa di abilitazione): si riprova al giro successivo."""


def info_pc(lette: list[str]) -> dict:
    import platform
    return {"nome": os.environ.get("COMPUTERNAME") or platform.node(), "utente": os.environ.get("USERNAME") or os.environ.get("USER") or "",
            "versione": VERSIONE, "caselle": lette}


def invia(chiave: str, voci: list[dict], pc: dict) -> dict:
    corpo = json.dumps({"voci": voci, "pc": pc}).encode("utf-8")  # ogni email dice la sua casella
    req = urllib.request.Request(f"{SERVER}/api/programma-protocollo/ricevi", data=corpo, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {chiave}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            messaggio = json.loads(e.read().decode("utf-8")).get("error")
        except Exception:
            messaggio = str(e)
        raise Rifiutato(messaggio)
    except urllib.error.URLError as e:
        raise Rifiutato(f"Sito non raggiungibile ({e.reason}): controlla la rete o la VPN.")


def un_giro(arg, config) -> None:
    voci, lette = da_cartella(arg.cartella) if arg.cartella else da_outlook(arg.giorni, arg.tutte_le_cartelle, config.get("caselle"))
    voci = list({(v["numero"], v["data"], v["id_messaggio"]): v for v in voci}.values())
    print(f"{datetime.now():%d/%m/%Y %H:%M} · caselle lette: {', '.join(lette) or 'nessuna'}")
    for nome in lette:
        print(f"   {nome}: {sum(1 for v in voci if v.get('casella') == nome)} email di protocollo")
    print(f"Email di protocollo trovate in tutto: {len(voci)}")
    for v in voci[:15]:
        print(f"   N. {v['numero']} del {v['data'][6:8]}/{v['data'][4:6]}/{v['data'][:4]} · [{v.get('casella', '')}] {v['oggetto'][:80]}")
    if len(voci) > 15:
        print(f"   ... e altre {len(voci) - 15}")
    if arg.prova:
        print("Prova: niente è stato mandato al sito.")
        return
    # anche senza email nuove il PC si fa vedere: l'amministratore vede quando è stato attivo l'ultima volta
    inviate = {"nuove": 0, "gia_presenti": 0}
    pc = info_pc(lette)
    for i in range(0, max(len(voci), 1), 400):
        r = invia(config["chiave"], voci[i:i + 400], pc)
        inviate["nuove"] += r.get("nuove", 0)
        inviate["gia_presenti"] += r.get("gia_presenti", 0)
    print(f"Mandate al sito: {inviate['nuove']} nuove, {inviate['gia_presenti']} già presenti (ricevute di nuovo).")


def main() -> None:
    a = argparse.ArgumentParser(description="Legge le email di protocollo (Titulus) e le manda al monitoraggio.")
    a.add_argument("--prova", action="store_true", help="mostra cosa trova senza mandare niente")
    a.add_argument("--continuo", action="store_true", help="ripete ogni --minuti finché non chiudi la finestra")
    a.add_argument("--minuti", type=int, default=10)
    a.add_argument("--giorni", type=int, default=60, help="quanti giorni indietro leggere in Outlook (predefinito 60)")
    a.add_argument("--tutte-le-cartelle", action="store_true", help="legge tutta la casella, non solo Posta in arrivo")
    a.add_argument("--caselle", help='quali caselle leggere, per nome (es. "segreteria"; più nomi separati da virgola; "tutte" per tornare a tutte)')
    a.add_argument("--elenca-caselle", action="store_true", help="mostra le caselle collegate a Outlook ed esce")
    a.add_argument("--cartella", help="cartella con le email salvate (.eml/.msg), al posto di Outlook")
    a.add_argument("--registro", help="scrive in questo file invece che nella finestra (avvio automatico, senza finestra)")
    a.add_argument("--chiave", help="la chiave personale generata nella pagina «File segreteria»")
    arg = a.parse_args()
    if arg.registro:  # avvio automatico senza finestra: tutto nel file di registro, che si accorcia da solo
        registro = Path(arg.registro)
        try:
            if registro.exists() and registro.stat().st_size > 1_000_000:
                registro.write_text(registro.read_text(encoding="utf-8", errors="ignore")[-200_000:], encoding="utf-8")
        except OSError:
            pass
        sys.stdout = sys.stderr = open(registro, "a", encoding="utf-8", buffering=1)
    config = leggi_config()
    if arg.elenca_caselle:
        for _, nome in caselle(_outlook()):
            print(f"   {nome}" + ("   (letta)" if not config.get("caselle") or any(x.lower() in nome.lower() for x in config["caselle"]) else ""))
        return
    if arg.caselle:
        config["caselle"] = [] if arg.caselle.strip().lower() == "tutte" else [x.strip() for x in arg.caselle.split(",") if x.strip()]
        salva_config(config)
        print("Caselle da leggere: " + (", ".join(config["caselle"]) or "tutte"))
    if arg.chiave:
        config["chiave"] = arg.chiave.strip()
        salva_config(config)
    if not arg.prova and not config.get("chiave"):
        if arg.registro:
            raise SystemExit("Manca la chiave: avvia una volta «Leggi-e-invia.bat» e incollala.")
        chiave = input("Incolla la chiave personale (pagina «File segreteria» > Documenti in uscita protocollo > Genera chiave): ").strip()
        if not chiave.startswith("mp_"):
            raise SystemExit("La chiave deve iniziare con mp_")
        config["chiave"] = chiave
        salva_config(config)
    while True:
        try:
            un_giro(arg, config)
        except Rifiutato as e:
            print(f"ATTENZIONE: {e}")
            if not arg.continuo:
                raise SystemExit(1)
        if not arg.continuo:
            break
        print(f"Prossimo controllo tra {arg.minuti} minuti (chiudi la finestra per fermarlo).")
        time.sleep(arg.minuti * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
