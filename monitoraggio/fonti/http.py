"""Client HTTP in sola lettura con pausa tra le richieste e retry (Principio III)."""
import time

import requests

from .. import config

STATI_DA_RIPETERE = {429, 500, 502, 503, 504}


class FonteErrore(Exception):
    """La fonte non è raggiungibile o risponde in modo inatteso."""


class Client:
    def __init__(self, pausa: float, tentativi: int = 3, timeout: int = 30):
        self.pausa = pausa
        self.tentativi = tentativi
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["User-Agent"] = config.USER_AGENT
        self._ultima = 0.0

    def _get(self, url: str, params: dict | None, headers: dict | None) -> requests.Response:
        ultimo_errore = None
        for tentativo in range(self.tentativi):
            attesa = self.pausa - (time.monotonic() - self._ultima)
            if attesa > 0:
                time.sleep(attesa)
            try:
                resp = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
                self._ultima = time.monotonic()
                if resp.status_code in STATI_DA_RIPETERE:
                    ultimo_errore = FonteErrore(f"HTTP {resp.status_code} da {url}")
                else:
                    resp.raise_for_status()
                    return resp
            except requests.HTTPError as e:
                # niente parametri nel messaggio: potrebbero contenere dati della richiesta
                raise FonteErrore(f"HTTP {e.response.status_code} da {url.split('?')[0]}") from e
            except requests.RequestException as e:
                self._ultima = time.monotonic()
                ultimo_errore = FonteErrore(f"{type(e).__name__} su {url}: {e}")
            time.sleep(2 ** tentativo)
        raise ultimo_errore

    def get_text(self, url: str, params: dict | None = None) -> str:
        return self._get(url, params, None).text

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        resp = self._get(url, params, {"Accept": "application/json", **(headers or {})})
        try:
            return resp.json()
        except ValueError as e:
            raise FonteErrore(f"Risposta non JSON da {url}") from e
