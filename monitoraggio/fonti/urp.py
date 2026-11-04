"""URP: elenco delle sezioni e dettaglio dei bandi.

Il parsing riprende parse_bando di scraper-urp.py; qui non si scaricano PDF.
"""
import json
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .. import config
from ..classifica import classifica
from ..normalizza import codice_norm, codice_sotto, data_iso, norm_space, numero_bando, protocollo
from .http import FonteErrore

_NUMERO_DOCUMENTI = re.compile(r"Numero Documenti:\s*(\d+)\s+di\s+(\d+)")
_PROTOCOLLO_BANDO = re.compile(r"Protocollo\s+(\d+)\s+del\s+(\d{2}-\d{2}-\d{4})")
# "BANDO N. <codice>" oppure "BANDO <numero> ..." (senza "N." solo se segue un numero)
_CODICE = re.compile(r"\bbando\s*(?:n(?:\.|°|r\.?)?\s*(.+)|(\d.*))$", re.I)
_CODICE_COMANDO = re.compile(r"((?:[A-Z0-9]+-)?\d{2}\s*-\s*COMANDO\s*-\s*\d{4}(?:[\s-]+[A-Z0-9]+)?)", re.I)
MAX_PAGINE = 200


def parse_elenco(html: str) -> tuple[list[str], int, int]:
    """Ritorna (link dei bandi, documenti mostrati finora, totale dichiarato)."""
    soup = BeautifulSoup(html, "html.parser")
    header = soup.find("div", class_="view-header")
    m = _NUMERO_DOCUMENTI.search(header.get_text(strip=True)) if header else None
    corrente, totale = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    links = [urljoin(config.URP_BASE, a["href"]) for a in soup.select("a.link-apri-documento") if a.get("href")]
    return links, corrente, totale


def url_pagina(sezione: str, pagina: int) -> str:
    # L'ordinamento predefinito (data di protocollo) non è stabile tra le pagine: a parità di
    # data i bandi cambiano posto e alcuni non compaiono mai. Per titolo l'elenco è completo.
    return f"{config.urp_url_sezione(sezione)}?order=title&sort=asc&page={pagina}"


def elenco_sezione(client, sezione: str) -> tuple[list[str], int]:
    """Tutti i link dei bandi di una sezione, seguendo le pagine fino al totale dichiarato."""
    links: list[str] = []
    totale = None
    for pagina in range(MAX_PAGINE):
        nuovi, _, dichiarato = parse_elenco(client.get_text(url_pagina(sezione, pagina)))
        if totale is None:
            totale = dichiarato
        if not nuovi:
            break
        links.extend(link for link in nuovi if link not in links)
        if len(links) >= totale:
            break
    if not links:
        raise FonteErrore(f"Elenco vuoto per la sezione URP {sezione}")
    if len(links) < totale:
        raise FonteErrore(f"Sezione URP {sezione}: trovati {len(links)} bandi su {totale} dichiarati")
    return links, totale


def _codice_da_testo(testo: str) -> str | None:
    """'BANDO N. 367.444 DT SAC - E' stato esercitato...' -> '367.444 DT SAC';
    'AVVISO “02-COMANDO-2024 DCGR”' -> '02-COMANDO-2024 DCGR' (comandi)."""
    s = norm_space(testo)
    m = _CODICE.search(s)
    if m:
        codice = re.split(r"\s+-\s+", m.group(1) or m.group(2))[0].strip(" -.")
        return codice or None
    m = _CODICE_COMANDO.search(s)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _documento(id_esterno: str, titolo: str, prot: str | None, data: str | None, url: str,
               categoria_forzata: str | None = None) -> dict:
    cat, sotto, ordinale = classifica(titolo)
    if categoria_forzata:
        cat, sotto, ordinale = categoria_forzata, None, None
    return {
        "id_esterno": id_esterno,
        "titolo": titolo,
        "categoria": cat,
        "sottotipo": sotto,
        "sottotipo_ordinale": ordinale,
        "sottotipo_origine": "titolo" if sotto else None,
        "tipo_fonte": None,
        "protocollo": protocollo(prot),
        "protocollo_originale": prot,
        "data_protocollo": data_iso(data),
        "url": url,
    }


def parse_dettaglio(html: str, url: str, sezione: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    contenuto = soup.select_one("div.region--content")
    estratto = contenuto.get_text(separator="\n", strip=True) if contenuto else ""
    righe = estratto.split("\n")

    link_documento = soup.select(".field--name-field-documento a")
    codice = None
    for a in link_documento:
        codice = _codice_da_testo(a.get_text(" ", strip=True))
        if codice:
            break
    if not codice:
        codice = next((c for c in map(_codice_da_testo, righe) if c), None)

    m = _PROTOCOLLO_BANDO.search(estratto)
    prot_bando, data_bando = (m.group(1), m.group(2)) if m else (None, None)

    # titolo: le righe tra "del <data>" e "BANDO N. ..."
    titolo_righe = []
    dentro = False
    for riga in righe:
        if dentro and (_CODICE.search(riga) or riga == "Allegati"):
            break
        if dentro:
            titolo_righe.append(riga)
        if re.match(r"^del\s+\d{2}-\d{2}-\d{4}$", riga.strip()):
            dentro = True
    titolo = norm_space(" ".join(titolo_righe)) or (f"Bando {codice}" if codice else "")

    tipologia = config.URP_TIPOLOGIA.get(sezione)
    if sezione == "bandi-pubblici-mobilita" and "comando" in estratto.lower():
        tipologia = "comando"

    documenti: list[dict] = []
    visti: set[str] = set()

    def aggiungi(doc: dict) -> None:
        base, n = doc["id_esterno"], 2
        while doc["id_esterno"] in visti:
            doc["id_esterno"] = f"{base}#{n}"
            n += 1
        visti.add(doc["id_esterno"])
        documenti.append(doc)

    if link_documento and link_documento[0].get("href"):
        principale = link_documento[0]
        link = urljoin(config.URP_BASE, principale["href"])
        aggiungi(_documento(link, principale.get_text(" ", strip=True), prot_bando, data_bando, link,
                            categoria_forzata="bando"))

    for item in soup.select("div.eva-allegati .views-view-responsive-grid__item-inner"):
        titolo_tag = item.select_one("span.views-field-field-allegato a")
        prot_tag = item.select_one("span.views-field-field-protocollo-numero")
        data_tag = item.select_one("span.views-field-field-protocollo-data")
        titolo_doc = titolo_tag.get_text(strip=True) if titolo_tag else ""
        link = urljoin(config.URP_BASE, titolo_tag["href"]) if titolo_tag and titolo_tag.get("href") else ""
        prot = prot_tag.get_text(strip=True).replace("- Protocollo ", "") if prot_tag else None
        data = data_tag.get_text(strip=True).replace("del ", "") if data_tag else None
        aggiungi(_documento(link or f"{titolo_doc}|{prot}", titolo_doc, prot, data, link))

    titolo_legacy = None
    if link_documento:
        testo = norm_space(link_documento[0].get_text(" ", strip=True))
        m_leg = re.search(r"\bbando\s*n?\.?\s*(.+)$", testo, flags=re.I)
        titolo_legacy = f"Codice Bando {m_leg.group(1).strip()}" if m_leg else testo

    return {
        "id_esterno": urlparse(url).path,
        "sezione": sezione,
        "tipologia": tipologia,
        "codice_originale": codice,
        "codice_norm": codice_norm(codice),
        "numero_bando": numero_bando(codice) or numero_bando(estratto),
        "codice_sotto": codice_sotto(codice),
        "titolo": titolo,
        "protocollo": protocollo(prot_bando),
        "protocollo_originale": prot_bando,
        "data_pubblicazione": data_iso(data_bando),
        "data_pubbl_graduatoria": None,
        "url": url,
        "dati_extra": json.dumps({"estratto": estratto[:1000], "titolo_bando": titolo_legacy},
                                 ensure_ascii=False, sort_keys=True),
        "modificata_fonte_il": None,
        "documenti": documenti,
    }


_ARCHIVIO_PROTOCOLLO = re.compile(r"\bProt(?:\.|ocoll[io])?\s*(?:[A-Z]{3,}\s*)?(?:n\.?\s*)?[:\-]?\s*(\d+)", re.I)
_ARCHIVIO_DATA = re.compile(r"\b(?:del|in data)\s+(\d{2}[/.\- ]\d{2}[/.\- ]\d{4})", re.I)
_ARCHIVIO_CODICE = re.compile(r"Codice\s+Bando\s+(.+?)(?:\s+-\s+Prot|\s*$)", re.I)


def _prot_e_data(testo: str) -> tuple[str | None, str | None]:
    """'Prot. AMMCEN n. 0079161/2021 del 24/11/2021' o, senza protocollo, 'Pubb. sito URP in data 21/02/2023'."""
    prot = _ARCHIVIO_PROTOCOLLO.search(testo)
    data = _ARCHIVIO_DATA.search(testo)
    return prot.group(1) if prot else None, re.sub(r"[/. ]", "-", data.group(1)) if data else None


def parse_archivio(html: str) -> list[dict]:
    """Archivio storico URP: ogni bando è un <dt> con il link al bando e un <dd> con gli allegati."""
    schede: dict[str, dict] = {}
    soup = BeautifulSoup(html, "html.parser")
    for dt in soup.find_all("dt"):
        a = dt.find("a")
        dd = dt.find_next_sibling("dd")
        if not a or not dd:
            continue
        titolo = norm_space(a.get_text(" ", strip=True))
        url = urljoin(config.URP_ARCHIVIO_BASE, a.get("href", "").lstrip("/"))
        m = _ARCHIVIO_CODICE.search(titolo)
        codice = norm_space(m.group(1)) if m else None
        prot, data = _prot_e_data(titolo)
        estratto = dd.get_text("\n", strip=True)
        documenti = [_documento(url, titolo, prot, data, url, categoria_forzata="bando")]
        visti = {url}
        for li in dd.find_all("li"):
            testo = norm_space(li.get_text(" ", strip=True))
            link = li.find("a")
            href = urljoin(config.URP_ARCHIVIO_BASE, link["href"].lstrip("/")) if link and link.get("href") else ""
            id_doc, n = href or testo, 2
            while id_doc in visti:
                id_doc = f"{href or testo}#{n}"
                n += 1
            visti.add(id_doc)
            documenti.append(_documento(id_doc, testo, *_prot_e_data(testo), href))
        id_esterno = urlparse(url).path or titolo
        while id_esterno in schede:
            id_esterno += "#2"
        schede[id_esterno] = {
            "id_esterno": id_esterno, "sezione": config.URP_ARCHIVIO_SEZIONE, "tipologia": None,
            "codice_originale": codice, "codice_norm": codice_norm(codice), "numero_bando": numero_bando(codice),
            "codice_sotto": codice_sotto(codice), "titolo": titolo, "protocollo": protocollo(prot),
            "protocollo_originale": prot, "data_pubblicazione": data_iso(data), "data_pubbl_graduatoria": None,
            "url": url, "dati_extra": json.dumps({"estratto": estratto[:1000], "titolo_bando": titolo},
                                                 ensure_ascii=False, sort_keys=True),
            "modificata_fonte_il": None, "documenti": documenti,
        }
    return list(schede.values())


def elenco_archivio(client) -> list[dict]:
    schede = parse_archivio(client.get_text(config.URP_ARCHIVIO_BASE + config.URP_ARCHIVIO_PAGINA))
    if not schede:
        raise FonteErrore("Archivio URP: nessun bando trovato nella pagina")
    return schede


def dettaglio_bando(client, url: str, sezione: str) -> dict:
    return parse_dettaglio(client.get_text(url), url, sezione)
