import requests
import json
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime

SEARCH_URL = "https://selezionionline.cnr.it/jconon/rest/search"
TREE_UUID = "713d4376-4cbd-43b6-ad14-9401b5029c51"


def fetch_bandi(query):
    """Chiama l'endpoint REST di Selezioni Online con la query CMIS indicata."""
    params = {
        "guest": "true",
        "ajax": "true",
        "maxItems": 200,
        "skipCount": 0,
        "fetchCmisObject": "true",
        "calculateTotalNumItems": "true",
        "q": query
    }
    headers = {"Accept": "application/json"}
    resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def check_graduatoria_allegata(codice_bando):
    """Controlla via scraping HTML se nella call-detail esiste un allegato di graduatoria."""
    url = f"https://selezionionline.cnr.it/jconon/call-detail?callCode={codice_bando.replace(' ', '%20')}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        items = []
        items += soup.select("div.well.shadow ul li")
        items += soup.select("div.well ul li")
        items += soup.select("ul li")

        pattern = re.compile(
            r"\b(graduatori\w+|decreto\s+graduatori\w+|approvazi\w*\s+graduatori\w+|pubblicazi\w*\s+graduatori\w+)\b",
            re.IGNORECASE,
        )

        for li in items:
            text = li.get_text(" ", strip=True)
            if pattern.search(text):
                return True

            a = li.find("a")
            if a:
                a_text = a.get_text(" ", strip=True) or ""
                href = a.get("href", "") or ""
                if pattern.search(a_text) or pattern.search(href):
                    return True

        return False
    except Exception as e:
        print(f"[!] Errore con bando {codice_bando}: {e}")
        return False


def build_query_concorsi_pubblici():
    """Query CMIS per concorsi pubblici a tempo indeterminato (come prima)."""
    return f"""
SELECT * FROM jconon_call:folder root
WHERE (
    root.cmis:objectTypeId = 'F:jconon_call_tind:folder_concorsi_pubblici'
    AND IN_TREE (root,'{TREE_UUID}')
)
ORDER BY jconon_call:data_fine_invio_domande_index DESC
""".strip()


def build_query_borse_ricerca():
    """
    Query CMIS per borse di ricerca, modellata su quella usata dal sito.
    Usa la data/ora attuale in UTC per il filtro data_inizio_invio_domande_index.
    """
    now_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return f"""
SELECT * FROM jconon_call:folder root
WHERE (
    root.cmis:objectTypeId = 'F:jconon_call_bstd:folder'
    AND (
        root.jconon_call:data_inizio_invio_domande_index <= TIMESTAMP '{now_utc}'
        OR root.cmis:createdBy = 'guest'
    )
    AND IN_TREE (root,'{TREE_UUID}')
)
ORDER BY jconon_call:data_fine_invio_domande_index DESC
""".strip()


def main():
    bandi_info = []
    counter = 0

    # Lista di "tipologie" da scaricare: (etichetta_tipologia, funzione_costruzione_query)
    datasets = [
        ("concorsi_pubblici", build_query_concorsi_pubblici),
        ("borse_ricerca", build_query_borse_ricerca),
    ]

    for tipologia, build_query in datasets:
        query = build_query()
        print(f"[INFO] Avvio fetch {tipologia}…")
        data = fetch_bandi(query)

        items = data.get("items", [])
        total = len(items)
        print(f"[INFO] {tipologia}: trovati {total} bandi")

        for i, item in enumerate(items, 1):
            counter += 1
            codice = item.get("jconon_call:codice")
            titolo = item.get("cmis:name")
            data_pubbl_inpa = item.get("jconon_call:data_pubblicazione_inpa")
            data_pubbl_graduatoria = item.get("jconon_call:data_pubbl_graduatoria")

            print(f"[{counter}] ({tipologia}) Controllo bando: {codice} - {titolo}")

            graduatoria_allegata = check_graduatoria_allegata(codice)

            # graduatoria PRESENTE se: c'è la data da API oppure lo scraping trova l'allegato
            graduatoria_presente = bool(data_pubbl_graduatoria) or bool(graduatoria_allegata)

            bandi_info.append({
                "codice": codice,
                "titolo": titolo,
                "data_pubblicazione_inpa": data_pubbl_inpa,
                "data_pubblicazione_graduatoria": data_pubbl_graduatoria,
                "graduatoria_allegato": bool(graduatoria_allegata),
                "graduatoria_presente": bool(graduatoria_presente),
                "tipologia": tipologia,  # <- concorsi_pubblici | borse_ricerca
            })

            # Salvataggio temporaneo ogni 5 bandi (totale fra concorsi + borse)
            if counter % 5 == 0:
                with open("bandi_temp.json", "w", encoding="utf-8") as f:
                    json.dump(bandi_info, f, ensure_ascii=False, indent=2)
                print(f"[TEMP] Salvati {counter} bandi in bandi_temp.json")

            time.sleep(1)  # per non stressare troppo il server

    # Salvataggio finale (stesso nome di prima per non toccare frontend/backend)
    with open("bandi-concorsi-pubblici-sol.json", "w", encoding="utf-8") as f:
        json.dump(bandi_info, f, ensure_ascii=False, indent=2)
    print("[OK] File salvato: bandi-concorsi-pubblici-sol.json")


if __name__ == "__main__":
    main()
