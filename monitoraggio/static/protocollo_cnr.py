"""Monitoraggio bandi CNR - lettura delle email di protocollo (Titulus) in copia.

Legge le email «Il sistema di protocollo le ha assegnato il seguente documento ...» e manda al sito del monitoraggio
SOLO: numero e data di protocollo, segnatura, oggetto, link Titulus, data di ricezione e un identificativo dell'email.
Non manda il resto delle email, non apre i documenti su Titulus, non modifica né sposta niente nella posta.

Dove legge:
  - Outlook classico installato sul PC (senza password): Posta in arrivo e sottocartelle (--tutte-le-cartelle: tutta la casella);
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


def da_outlook(giorni: int, tutte: bool = False) -> tuple[list[dict], str]:
    try:
        import win32com.client  # pywin32: solo con Outlook classico
    except ImportError:
        raise SystemExit("Manca pywin32: avvia il programma dai file .bat, che lo installano.")
    try:
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception:
        raise SystemExit("Outlook classico non risponde. Con il «nuovo Outlook» usa la modalità cartella (vedi LEGGIMI.txt).")
    casella = ""
    try:
        casella = ns.CurrentUser.AddressEntry.GetExchangeUser().PrimarySmtpAddress or ""
    except Exception:
        casella = str(getattr(ns.CurrentUser, "Name", "") or "")
    limite = datetime.now() - timedelta(days=giorni)
    trovate: list[dict] = []

    def cartella(f, profondita=0):
        try:
            elementi = f.Items
            elementi.Sort("[ReceivedTime]", True)
        except Exception:
            return
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
                    trovate.append(v)
            except Exception:
                continue
        if profondita < 4:
            for sotto in f.Folders:
                cartella(sotto, profondita + 1)

    inbox = ns.GetDefaultFolder(6)
    cartella(inbox.Parent if tutte else inbox)  # Posta in arrivo e sottocartelle, o tutta la casella
    return trovate, casella


def da_cartella(percorso: str) -> tuple[list[dict], str]:
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
                trovate.append(v)
        except Exception as e:
            print(f"  {f.name}: non letto ({type(e).__name__})")
    return trovate, ""


def invia(chiave: str, voci: list[dict], casella: str) -> dict:
    corpo = json.dumps({"casella": casella, "voci": voci}).encode("utf-8")
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
        raise SystemExit(f"Il sito ha risposto con un errore: {messaggio}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Sito non raggiungibile ({e.reason}): controlla la rete o la VPN.")


def un_giro(arg, config) -> None:
    voci, casella = da_cartella(arg.cartella) if arg.cartella else da_outlook(arg.giorni, arg.tutte_le_cartelle)
    voci = list({(v["numero"], v["data"], v["id_messaggio"]): v for v in voci}.values())
    print(f"{datetime.now():%d/%m/%Y %H:%M} · email di protocollo trovate: {len(voci)}" + (f" · casella {casella}" if casella else ""))
    for v in voci[:15]:
        print(f"   N. {v['numero']} del {v['data'][6:8]}/{v['data'][4:6]}/{v['data'][:4]} · {v['oggetto'][:90]}")
    if len(voci) > 15:
        print(f"   ... e altre {len(voci) - 15}")
    if arg.prova:
        print("Prova: niente è stato mandato al sito.")
        return
    if not voci:
        return
    inviate = {"nuove": 0, "gia_presenti": 0}
    for i in range(0, len(voci), 400):
        r = invia(config["chiave"], voci[i:i + 400], casella)
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
    a.add_argument("--cartella", help="cartella con le email salvate (.eml/.msg), al posto di Outlook")
    a.add_argument("--chiave", help="la chiave personale generata nella pagina «File segreteria»")
    arg = a.parse_args()
    config = leggi_config()
    if arg.chiave:
        config["chiave"] = arg.chiave.strip()
        salva_config(config)
    if not arg.prova and not config.get("chiave"):
        chiave = input("Incolla la chiave personale (pagina «File segreteria» > Documenti in uscita protocollo > Genera chiave): ").strip()
        if not chiave.startswith("mp_"):
            raise SystemExit("La chiave deve iniziare con mp_")
        config["chiave"] = chiave
        salva_config(config)
    while True:
        un_giro(arg, config)
        if not arg.continuo:
            break
        print(f"Prossimo controllo tra {arg.minuti} minuti (chiudi la finestra per fermarlo).")
        time.sleep(arg.minuti * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
