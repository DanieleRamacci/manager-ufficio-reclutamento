import requests
import json
from bs4 import BeautifulSoup
import time
import re

def fetch_bandi(query):
    url = "https://selezionionline.cnr.it/jconon/rest/search"
    params = {
        "guest": "true",
        "ajax": "true",
        "maxItems": 200,
        "skipCount": 0,
        "fetchCmisObject": "true",
        "calculateTotalNumItems": "true",
        "q": query
    }
    headers = {
        "Accept": "application/json"
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

def check_graduatoria_allegata(codice_bando):
    url = f"https://selezionionline.cnr.it/jconon/call-detail?callCode={codice_bando.replace(' ', '%20')}"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Selettori più ampi (a volte i contenitori differiscono)
        items = []
        items += soup.select("div.well.shadow ul li")
        items += soup.select("div.well ul li")
        items += soup.select("ul li")

        pattern = re.compile(r"\b(graduatori\w+|decreto\s+graduatori\w+|approvazi\w*\s+graduatori\w+|pubblicazi\w*\s+graduatori\w+)\b", re.IGNORECASE)

        for li in items:
            text = li.get_text(" ", strip=True)
            if pattern.search(text):
                return True  # trovato per testo

            a = li.find("a")
            if a:
                a_text = a.get_text(" ", strip=True) or ""
                href = a.get("href", "") or ""
                if pattern.search(a_text) or pattern.search(href):
                    return True  # trovato per testo link o href

        return False
    except Exception as e:
        print(f"[!] Errore con bando {codice_bando}: {e}")
        return False


# Query SQL CMIS per tutti i bandi pubblicati
query = """
SELECT * FROM jconon_call:folder root
WHERE (
    root.cmis:objectTypeId = 'F:jconon_call_tind:folder_concorsi_pubblici'
    AND IN_TREE (root,'713d4376-4cbd-43b6-ad14-9401b5029c51')
)
ORDER BY jconon_call:data_fine_invio_domande_index DESC
"""

def main():
    data = fetch_bandi(query)
    bandi_info = []
    counter = 0

    total = len(data.get("items", []))
    print(f"[INFO] Trovati {total} bandi")

    for i, item in enumerate(data.get("items", []), 1):
        codice = item.get("jconon_call:codice")
        titolo = item.get("cmis:name")
        data_pubbl_inpa = item.get("jconon_call:data_pubblicazione_inpa")
        data_pubbl_graduatoria = item.get("jconon_call:data_pubbl_graduatoria")

        print(f"[{i}/{total}] Controllo bando: {codice} - {titolo}")

        graduatoria_allegata = check_graduatoria_allegata(codice)

        graduatoria_allegata = check_graduatoria_allegata(codice)

        # graduatoria PRESENTE se: c'è la data da API oppure lo scraping trova l'allegato
        graduatoria_presente = bool(data_pubbl_graduatoria) or bool(graduatoria_allegata)

        bandi_info.append({
            "codice": codice,
            "titolo": titolo,
            "data_pubblicazione_inpa": data_pubbl_inpa,
            "data_pubblicazione_graduatoria": data_pubbl_graduatoria,
            "graduatoria_allegato": bool(graduatoria_allegata),  # solo scraping
            "graduatoria_presente": bool(graduatoria_presente)   # API OR scraping
        })


        counter += 1

        # Salvataggio temporaneo ogni 5 bandi
        if counter % 5 == 0:
            with open("bandi_temp.json", "w", encoding="utf-8") as f:
                json.dump(bandi_info, f, ensure_ascii=False, indent=2)
            print(f"[TEMP] Salvati {counter} bandi in bandi_temp.json")

        time.sleep(1)  # Per evitare troppe richieste in poco tempo

    # Salvataggio finale
    with open("bandi-concorsi-pubblici-sol.json", "w", encoding="utf-8") as f:
        json.dump(bandi_info, f, ensure_ascii=False, indent=2)
    print("[OK] File salvato: bandi-concorsi-pubblici-sol.json")

if __name__ == "__main__":
    main()
