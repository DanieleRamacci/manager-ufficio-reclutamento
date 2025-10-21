import requests
from bs4 import BeautifulSoup
import re
import json
import time

BASE_URL = "https://www.urp.cnr.it"
CATEGORIE = {
    "tempo-indeterminato": f"{BASE_URL}/documenti/tempo-indeterminato/",
    "tempo-determinato": f"{BASE_URL}/documenti/tempo-determinato/",
    "categorie-riservatarie": f"{BASE_URL}/documenti/categorie-riservatarie/",
    "direttori-dipartimentiistituti": f"{BASE_URL}/documenti/direttori-dipartimentiistituti/",
    "avviamento-numerico-selezione-ans-categorie-riservatarie": f"{BASE_URL}/documenti/avviamento-numerico-selezione-ans-categorie-riservatarie/"
}
OLD_ARCHIVE_URL = "https://archivio.urp.cnr.it/page.php?level=3&pg=157&Org=4&db=1"
OLD_BASE_URL = "https://archivio.urp.cnr.it/"

def get_numero_documenti(soup):
    text_block = soup.find("div", class_="view-header")
    if not text_block:
        return 0, 0
    testo = text_block.get_text(strip=True)
    match = re.search(r"Numero Documenti:\s*(\d+)\s+di\s+(\d+)", testo)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0

def get_bandi_links_from_page(url_base, pagina):
    url = f"{url_base}?page={pagina}"
    print(f"[+] Scarico pagina: {url}")
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    numero_corrente, numero_totale = get_numero_documenti(soup)
    bandi = soup.select("a.link-apri-documento")
    links = [BASE_URL + b["href"] for b in bandi]
    return links, numero_corrente, numero_totale

def parse_bando(url):
    scorr_uti_presente = False
    data_scorr_uti = None

    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")

    estratto_tag = soup.select_one("div.region--content")
    estratto = estratto_tag.get_text(separator="\n", strip=True) if estratto_tag else ""

    match = re.search(r"Protocollo\s+(\d+)\s+del\s+(\d{2}-\d{2}-\d{4})", estratto)
    numero_protocollo = match.group(1) if match else None
    data_pubblicazione_bando = match.group(2) if match else None

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

        tipo = classifica_graduatoria(titolo)

        allegati.append({
            "titolo": titolo,
            "link": link,
            "protocollo": protocollo,
            "data": data,
            "tipo_graduatoria": tipo
        })

        if tipo == "graduatoria":
            graduatoria_presente = True
            data_pubblicazione_graduatoria = data
        elif tipo == "scorrimento_utilizzo":
            # opzionale: tieni traccia separata
            scorr_uti_presente = True
            data_scorr_uti = data

    return {
        "url": url,
        "data_pubblicazione_bando": data_pubblicazione_bando,
        "numero_protocollo": numero_protocollo,
        "graduatoria_presente": graduatoria_presente,
        "data_pubblicazione_graduatoria": data_pubblicazione_graduatoria,
        "estratto": estratto[:1000],
        "allegati": allegati,
        "scorrimento_utilizzo_presente": scorr_uti_presente,
        "data_scorrimento_utilizzo": data_scorr_uti,

    }

def scrape_categoria(nome_categoria, url_base):
    print(f"[>>] Inizio scraping categoria: {nome_categoria}")
    page = 0
    tutti_i_dati = []
    numero_totale_documenti = None

    while True:
        links, numero_corrente, numero_totale = get_bandi_links_from_page(url_base, page)
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

def classifica_graduatoria(titolo: str) -> str | None:
    t = titolo.lower()
    t = re.sub(r"\s+", " ", t).replace("’", "'")

    # prima intercettiamo scorrimento / utilizzo (stessa classe)
    if (
        re.search(r"\b(scorriment[oi]|utilizz[oa])\b.*\bgraduatori\w*\b", t)
        or re.search(r"\bgraduatori\w*\b.*\b(scorriment[oi]|utilizz[oa])\b", t)
        or re.search(r"\butilizzo graduatori\w*\b", t)
        or re.search(r"\bscorrimento graduatori\w*\b", t)
    ):
        return "scorrimento_utilizzo"

    # altrimenti è una graduatoria generica
    if re.search(r"\bgraduatori\w*\b", t):
        return "graduatoria"

    return None


def parse_archivio_old_urp():
    print(f"[>>] Scarico archivio vecchio: {OLD_ARCHIVE_URL}")
    response = requests.get(OLD_ARCHIVE_URL)
    soup = BeautifulSoup(response.text, "html.parser")
    bandi = []
    blocchi = soup.find_all("dt")

    for dt in blocchi:
        a_tag = dt.find("a")
        dd = dt.find_next_sibling("dd")
        if not a_tag or not dd:
            continue

        url = OLD_BASE_URL + a_tag["href"].lstrip("/")
        descrizione = dd.get_text(separator="\n", strip=True)[:1000]
        titolo = a_tag.get_text(strip=True)

        match_proto = re.search(r"Prot(?:\.|otocoll[io])\s*(\d+)\s+del\s+(\d{2}/\d{2}/\d{4})", titolo)
        numero_protocollo = match_proto.group(1) if match_proto else None
        data_pubblicazione = match_proto.group(2).replace("/", "-") if match_proto else None

        allegati = []
        graduatoria_presente = False
        data_pubblicazione_graduatoria = None

        for li in dd.find_all("li"):
            testo = li.get_text(strip=True)
            link_tag = li.find("a")
            link = OLD_BASE_URL + link_tag["href"].lstrip("/") if link_tag else ""
            data_match = re.search(r"del\s+(\d{2}/\d{2}/\d{4})", testo)
            data = data_match.group(1).replace("/", "-") if data_match else None
            protocollo_match = re.search(r"Prot(?:\.|otocoll[io])\s*(\d+)", testo)
            protocollo = protocollo_match.group(1) if protocollo_match else None

            allegati.append({
                "titolo": testo,
                "link": link,
                "protocollo": protocollo,
                "data": data
            })

            if "graduatoria" in testo.lower():
                graduatoria_presente = True
                data_pubblicazione_graduatoria = data

        bandi.append({
            "url": url,
            "data_pubblicazione_bando": data_pubblicazione,
            "numero_protocollo": numero_protocollo,
            "graduatoria_presente": graduatoria_presente,
            "data_pubblicazione_graduatoria": data_pubblicazione_graduatoria,
            "estratto": descrizione,
            "allegati": allegati
        })

    return bandi

# === MAIN ===
if __name__ == "__main__":
    dati_finali = {}

    for nome_categoria, url_categoria in CATEGORIE.items():
        dati_finali[nome_categoria] = scrape_categoria(nome_categoria, url_categoria)

    dati_finali["archivio-vecchio"] = parse_archivio_old_urp()

    with open("bandi-completi-urp.json", "w", encoding="utf-8") as f:
        json.dump(dati_finali, f, ensure_ascii=False, indent=2)

    print("[OK] File salvato: bandi-completi-urp.json")
