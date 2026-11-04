"""Collega Selezioni Online: apre Chrome, aspetta il login e invia il ticket al sito del monitoraggio.

Come la prova locale: Chrome parte con un profilo temporaneo, separato dal tuo, e il cookie `ticket` si
legge da quella finestra. Il ticket va solo a SERVER, non viene scritto su disco né mostrato. Solo libreria
standard di Python: non serve installare nulla.
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

SERVER = "__SERVER__"
SOL = os.environ.get("COLLEGA_SOL_URL", "https://selezionionline.cnr.it/jconon").rstrip("/")
ATTESA_LOGIN_S = 300

PERCORSI_BROWSER = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


class Errore(Exception):
    pass


def trova_browser() -> str:
    for percorso in PERCORSI_BROWSER:
        if os.path.exists(percorso):
            return percorso
    for nome in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        if shutil.which(nome):
            return shutil.which(nome)
    raise Errore("Chrome o Edge non trovati: installane uno oppure incolla il ticket nella pagina di accesso.")


class CanaleDevTools:
    """WebSocket minimo verso Chrome (solo 127.0.0.1) per chiedere i cookie della finestra aperta."""

    def __init__(self, url: str):
        parti = urllib.parse.urlparse(url)
        self.sock = socket.create_connection((parti.hostname, parti.port), timeout=10)
        chiave = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {parti.path} HTTP/1.1\r\nHost: {parti.hostname}:{parti.port}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {chiave}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        risposta = b""
        while b"\r\n\r\n" not in risposta:
            blocco = self.sock.recv(4096)
            if not blocco:
                raise Errore("Chrome ha chiuso il collegamento")
            risposta += blocco
        if b" 101 " not in risposta.split(b"\r\n", 1)[0]:
            raise Errore("Chrome ha rifiutato il collegamento")
        self.resto = risposta.split(b"\r\n\r\n", 1)[1]
        self.ultimo_id = 0

    def _leggi(self, n: int) -> bytes:
        while len(self.resto) < n:
            blocco = self.sock.recv(65536)
            if not blocco:
                raise Errore("Chrome è stato chiuso")
            self.resto += blocco
        dati, self.resto = self.resto[:n], self.resto[n:]
        return dati

    def _invia(self, testo: str) -> None:
        dati = testo.encode()
        maschera = os.urandom(4)
        if len(dati) < 126:
            intestazione = bytes([0x81, 0x80 | len(dati)])
        else:
            intestazione = bytes([0x81, 0x80 | 126]) + struct.pack(">H", len(dati))
        self.sock.sendall(intestazione + maschera + bytes(b ^ maschera[i % 4] for i, b in enumerate(dati)))

    def _ricevi(self) -> str:
        messaggio = b""
        while True:
            primo, secondo = self._leggi(2)
            lunghezza = secondo & 0x7F
            if lunghezza == 126:
                lunghezza = struct.unpack(">H", self._leggi(2))[0]
            elif lunghezza == 127:
                lunghezza = struct.unpack(">Q", self._leggi(8))[0]
            corpo = self._leggi(lunghezza)
            codice = primo & 0x0F
            if codice == 8:
                raise Errore("Chrome è stato chiuso")
            if codice in (0, 1, 2):
                messaggio += corpo
                if primo & 0x80:
                    return messaggio.decode()

    def chiedi(self, metodo: str) -> dict:
        self.ultimo_id += 1
        self._invia(json.dumps({"id": self.ultimo_id, "method": metodo}))
        while True:
            risposta = json.loads(self._ricevi())
            if risposta.get("id") == self.ultimo_id:
                return risposta.get("result") or {}


def apri_devtools(cartella: str, processo) -> CanaleDevTools:
    file_porta = os.path.join(cartella, "DevToolsActivePort")
    for _ in range(100):
        if processo.poll() is not None:
            raise Errore("Chrome si è chiuso subito dopo l'avvio")
        if os.path.exists(file_porta):
            with open(file_porta) as f:
                righe = f.read().split()
            if len(righe) >= 2:
                return CanaleDevTools(f"ws://127.0.0.1:{righe[0]}{righe[1]}")
        time.sleep(0.2)
    raise Errore("Chrome non risponde")


def aspetta_ticket(canale: CanaleDevTools, processo) -> str:
    dominio = urllib.parse.urlparse(SOL).hostname
    fine = time.monotonic() + ATTESA_LOGIN_S
    while time.monotonic() < fine:
        if processo.poll() is not None:
            raise Errore("Finestra chiusa prima del login")
        for cookie in canale.chiedi("Storage.getCookies").get("cookies", []):
            if cookie.get("name") == "ticket" and cookie.get("value") and cookie.get("domain", "").lstrip(".") == dominio:
                return cookie["value"]
        time.sleep(1)
    raise Errore("Login non completato entro 5 minuti")


def invia_al_server(ticket: str) -> dict:
    """Con curl se c'è: alcune installazioni di Python su Mac non hanno i certificati. Il ticket passa
    sempre da stdin, mai dagli argomenti, che sono visibili agli altri programmi."""
    corpo = urllib.parse.urlencode({"ticket": ticket}).encode()
    url = f"{SERVER.rstrip('/')}/api/sol/ticket"
    curl = shutil.which("curl")
    if curl:
        r = subprocess.run([curl, "-sS", "--max-time", "60", "-X", "POST", "--data-binary", "@-", url], input=corpo,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if r.returncode:
            raise Errore("Il sito del monitoraggio non risponde")
        testo = r.stdout.decode(errors="replace")
    else:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=corpo), timeout=60) as risposta:
                testo = risposta.read().decode()
        except urllib.error.HTTPError as e:
            testo = e.read().decode(errors="replace")
        except OSError:
            raise Errore("Il sito del monitoraggio non risponde")
    try:
        return json.loads(testo)
    except ValueError:
        raise Errore("Risposta inattesa dal sito del monitoraggio")


def main() -> int:
    cartella = tempfile.mkdtemp(prefix="collega-sol-")
    argomenti = [trova_browser(), f"--user-data-dir={cartella}", "--remote-debugging-port=0", "--no-first-run",
                 "--no-default-browser-check", *os.environ.get("COLLEGA_SOL_CHROME_ARGS", "").split(), f"{SOL}/sso/login"]
    processo = subprocess.Popen(argomenti, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        print("Fai il login su Selezioni Online nella finestra che si è aperta...")
        canale = apri_devtools(cartella, processo)
        ticket = aspetta_ticket(canale, processo)
        print("Login riuscito, invio al sito del monitoraggio...")
        risposta = invia_al_server(ticket)
    except (Errore, OSError) as e:
        print(f"Non riuscito: {e}")
        return 1
    finally:
        processo.terminate()
        try:
            processo.wait(timeout=5)
        except subprocess.TimeoutExpired:
            processo.kill()
        shutil.rmtree(cartella, ignore_errors=True)
    if not risposta.get("ok"):
        print(f"Non riuscito: {risposta.get('error', 'errore sconosciuto')}")
        return 1
    print(f"Collegato come {risposta.get('utente')}: si apre il sito. Puoi chiudere questa finestra.")
    webbrowser.open(risposta["link"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
