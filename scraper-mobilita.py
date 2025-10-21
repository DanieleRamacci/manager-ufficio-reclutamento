import requests
from bs4 import BeautifulSoup
import re
import json
import time

BASE_URL = "https://www.urp.cnr.it"
LIST_URL = f"{BASE_URL}/documenti/bandi-pubblici-mobilita"

def get_numero_documenti(soup):
    text_block = soup.find("div", class_="view-header")
    if not text_block:
        return 0, 0
    testo = text_block.get_text(strip=True)
    match = re.search(r"Numero Documenti:\s*(\d+)\s+di\s+(\d+)", testo)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0

def get_bandi_links_from_page(pagina):
    url = f"{LIST_URL}?page={pagina}"
    print(f"[+] Scarico pagina: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    numero_corrente, numero_totale = get_numero_documenti(soup)
    bandi = soup.select("a.link-apri-documento")
    links = [BASE_URL + b["href"] for b in bandi]
    return links, numero_corrente, numero_totale

def parse_bando(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    estratto_tag = soup.select_one("div.region--content")
    estratto = estratto_tag.get_text(separator="\n", strip=True) if estratto_tag else ""

    # Estrai protocollo principale
    match = re.search(r"Protocollo\s+(\d+)\s+del\s+(\d{2}-\d{2}-\d{4})", estratto)
    if match:
        numero_protocollo = match.group(1)
        data_pubblicazione_bando = match.group(2)
    else:
        numero_protocollo = None
        data_pubblicazione_bando = None

    allegati = []
    graduatoria_presente = False
    data_pubblicazione_graduatoria = None

    allegati_container = soup.select("div.eva-allegati .views-view-responsive-grid__item-inner")
    for item in allegati_container:
        titolo_tag = item.select_one("span.views-field-field-allegato a")
        protocollo_tag = item.select_one("span.views-field-field-protocollo-numero")
        data_tag = item.select_one("span.views-field-field-protocollo-data")

        titolo = titolo_tag.text.strip() if titolo_tag else ""
        link = BASE_URL + titolo_tag["href"] if titolo_tag and "href" in titolo_tag.attrs else ""
        protocollo = protocollo_tag.text.strip().replace("- Protocollo ", "") if protocollo_tag else None
        data = data_tag.text.strip().replace("del ", "") if data_tag else None

        allegati.append({
            "titolo": titolo,
            "link": link,
            "protocollo": protocollo,
            "data": data
        })

        if "graduatoria" in titolo.lower():
            graduatoria_presente = True
            data_pubblicazione_graduatoria = data

    # Estrai codice bando leggibile (es. "BANDO N. 365.194 CTER IBPM")
    codice_tag = soup.select_one("div.field--name-field-documento a")
    codice_bando = codice_tag.get_text(strip=True) if codice_tag else "--"

    # Determina la tipologia: 'mobilità' o 'comando'
    tipologia = "mobilità"
    if "comando" in estratto.lower():
        tipologia = "comando"

    return {
        "url": url,
        "data_pubblicazione_bando": data_pubblicazione_bando,
        "numero_protocollo": numero_protocollo,
        "graduatoria_presente": graduatoria_presente,
        "data_pubblicazione_graduatoria": data_pubblicazione_graduatoria,
        "estratto": estratto[:1000],
        "allegati": allegati,
        "tipologia": tipologia,
        "codice": codice_bando
    }


def scrape_mobilita():
    page = 0
    tutti_i_dati = []
    numero_totale_documenti = None

    while True:
        links, numero_corrente, numero_totale = get_bandi_links_from_page(page)
        if numero_totale_documenti is None:
            numero_totale_documenti = numero_totale
        if not links:
            break

        for link in links:
            dati = parse_bando(link)
            tutti_i_dati.append(dati)
            time.sleep(0.5)

        if len(tutti_i_dati) >= numero_totale_documenti:
            break
        page += 1

    return tutti_i_dati

if __name__ == "__main__":
    dati = scrape_mobilita()
    with open("bandi-mobilita.json", "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)
    print("📁 File salvato: bandi-mobilita.json")
