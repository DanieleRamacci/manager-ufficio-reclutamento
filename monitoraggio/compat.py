"""Compatibilità con le pagine esistenti (contracts/api.md, "Compatibilità").

Ricostruisce dal database i JSON che index.html, mobilita-urp.html e report-mese.html
leggevano dai file scritti dai vecchi script.
"""
import json
from collections import defaultdict

from . import config

TIPO_DOCUMENTO_LEGACY = {"criteri": "criteri", "tracce": "tracce_prova_scritta"}
TIPOLOGIA_SOL_LEGACY = {"tempo_indeterminato": "concorsi_pubblici"}


def _data_it(iso: str | None) -> str | None:
    """'2024-08-01' -> '01-08-2024', il formato dei vecchi JSON URP."""
    return "-".join(reversed(iso.split("-"))) if iso else None


def _documenti_per_scheda(conn, fonte: str) -> dict[int, list]:
    risultato = defaultdict(list)
    for d in conn.execute(
            "SELECT d.* FROM documento d JOIN scheda s ON s.id = d.scheda_id WHERE s.fonte = ? AND d.presente = 1 "
            "ORDER BY d.id", (fonte,)):
        risultato[d["scheda_id"]].append(d)
    return risultato


def _bando_urp(s, documenti) -> dict:
    extra = json.loads(s["dati_extra"]) if s["dati_extra"] else {}
    allegati, grad, scorr = [], [], []
    for d in documenti:
        if d["categoria"] == "bando":
            continue  # i vecchi JSON non elencavano il documento principale tra gli allegati
        tipo_grad = {"graduatoria": "graduatoria", "scorrimento": "scorrimento_utilizzo"}.get(d["categoria"])
        if tipo_grad == "graduatoria":
            grad.append(d)
        elif tipo_grad:
            scorr.append(d)
        allegati.append({
            "titolo": d["titolo"], "link": d["url"], "protocollo": d["protocollo_originale"],
            "data": _data_it(d["data_protocollo"]), "data_iso": d["data_protocollo"],
            "tipo_documento": TIPO_DOCUMENTO_LEGACY.get(d["categoria"]), "tipo_graduatoria": tipo_grad,
            "access_check": json.loads(d["accessibilita"]) if d["accessibilita"] else {},
        })
    ultima = lambda docs: docs[-1]["data_protocollo"] if docs else None  # noqa: E731
    return {
        "url": s["url"], "titolo_bando": extra.get("titolo_bando") or s["titolo"], "codice_bando": s["codice_originale"],
        "data_pubblicazione_bando": _data_it(s["data_pubblicazione"]), "numero_protocollo": s["protocollo_originale"],
        "graduatoria_presente": bool(grad), "data_pubblicazione_graduatoria": ultima(grad),
        "estratto": extra.get("estratto", ""), "allegati": allegati,
        "scorrimento_utilizzo_presente": bool(scorr), "data_scorrimento_utilizzo": ultima(scorr),
        "fonte": "urp_archivio" if s["sezione"] == config.URP_ARCHIVIO_SEZIONE else "urp_nuovo",
    }


def export_urp(conn) -> dict:
    """Formato di bandi-completi-urp.json: { sezione: [bando, ...] } (mobilità esclusa)."""
    documenti = _documenti_per_scheda(conn, "urp")
    risultato = defaultdict(list)
    for s in conn.execute("SELECT * FROM scheda WHERE fonte = 'urp' AND presente = 1 AND sezione != "
                          "'bandi-pubblici-mobilita' ORDER BY data_pubblicazione DESC"):
        risultato[s["sezione"]].append(_bando_urp(s, documenti[s["id"]]))
    return dict(risultato)


def export_mobilita(conn) -> list:
    """Formato di bandi-mobilita.json (scraper-mobilita.py)."""
    documenti = _documenti_per_scheda(conn, "urp")
    risultato = []
    for s in conn.execute("SELECT * FROM scheda WHERE fonte = 'urp' AND presente = 1 AND sezione = "
                          "'bandi-pubblici-mobilita' ORDER BY data_pubblicazione DESC"):
        extra = json.loads(s["dati_extra"]) if s["dati_extra"] else {}
        docs = [d for d in documenti[s["id"]] if d["categoria"] != "bando"]
        grad = [d for d in docs if d["categoria"] == "graduatoria"]
        risultato.append({
            "url": s["url"], "data_pubblicazione_bando": _data_it(s["data_pubblicazione"]),
            "numero_protocollo": s["protocollo_originale"], "graduatoria_presente": bool(grad),
            "data_pubblicazione_graduatoria": _data_it(grad[-1]["data_protocollo"]) if grad else None,
            "estratto": extra.get("estratto", ""),
            "allegati": [{"titolo": d["titolo"], "link": d["url"], "protocollo": d["protocollo_originale"],
                          "data": _data_it(d["data_protocollo"])} for d in docs],
            "tipologia": "comando" if s["tipologia"] == "comando" else "mobilità",
            "codice": extra.get("titolo_bando") or s["codice_originale"] or "--",
        })
    return risultato


def export_sol(conn) -> list:
    """Formato di bandi-concorsi-pubblici-sol.json (scraper-sol-tutti-bandi.py)."""
    con_graduatoria = {r[0] for r in conn.execute(
        "SELECT DISTINCT d.scheda_id FROM documento d JOIN scheda s ON s.id = d.scheda_id "
        "WHERE s.fonte = 'sol' AND d.presente = 1 AND d.categoria = 'graduatoria'")}
    risultato = []
    for s in conn.execute("SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 ORDER BY data_pubblicazione DESC"):
        allegato = s["id"] in con_graduatoria
        risultato.append({
            "codice": s["codice_originale"], "titolo": s["titolo"],
            "data_pubblicazione_inpa": f"{s['data_pubblicazione']}T12:00:00Z" if s["data_pubblicazione"] else None,
            "data_pubblicazione_graduatoria": f"{s['data_pubbl_graduatoria']}T12:00:00Z" if s["data_pubbl_graduatoria"] else None,
            "graduatoria_allegato": allegato,
            "graduatoria_presente": bool(s["data_pubbl_graduatoria"]) or allegato,
            "tipologia": TIPOLOGIA_SOL_LEGACY.get(s["tipologia"], s["tipologia"]),
        })
    return risultato


EXPORT = {
    "bandi-completi-urp.json": ("urp", export_urp),
    "bandi-concorsi-pubblici-sol.json": ("sol", export_sol),
    "bandi-mobilita.json": ("urp", export_mobilita),
}


def ultima_riuscita(conn, fonte: str) -> str | None:
    riga = conn.execute("SELECT fine FROM raccolta WHERE fonte = ? AND esito IN ('completata', 'completata_con_errori') "
                        "ORDER BY id DESC LIMIT 1", (fonte,)).fetchone()
    return riga["fine"] if riga else None
