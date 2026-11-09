"""Excel del monitoraggio dai modelli in monitoraggio/modelli (spec 006)."""
import copy
import io
import json
from pathlib import Path

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config, punteggi
from .normalizza import data_iso

MODELLI = Path(__file__).resolve().parent / "modelli"
MODELLO_SCORRIMENTI = "MODELLO-scorrimenti-mese-anno.xlsx"
MODELLO_GRADUATORIE = "MODELLO-Graduatorie-e-bandi-pubblicati-mese-anno.xlsx"
NOTA_TIPOLOGIA = "Indicare se scorrimento, subentro o per rinuncia dopo 6 mesi"
INTESTAZIONI_BANDI = ["Codice bando", "Sede di lavoro", "Struttura di riferimento", "N. Posti", "Profilo/Livello",
                      "Protocollo", "Data pubblicazione"]
TIPOLOGIE_MOBILITA = {"mobilita", "comando"}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
        "novembre", "dicembre"]


def etichetta_file(mese: str) -> str:
    """'2026-05' -> 'maggio-26'."""
    anno, numero = mese.split("-")
    return f"{MESI[int(numero) - 1]}-{anno[2:]}"


def nome_scorrimenti(mese: str) -> str:
    return f"MODELLO-scorrimenti-{etichetta_file(mese)}.xlsx"


def nome_graduatorie(mese: str) -> str:
    return f"MODELLO-Graduatorie-e-bandi-pubblicati-{etichetta_file(mese)}.xlsx"


def _copia_stile(da, a) -> None:
    a.font, a.fill, a.border = copy.copy(da.font), copy.copy(da.fill), copy.copy(da.border)
    a.alignment, a.number_format = copy.copy(da.alignment), da.number_format


def _salva(wb) -> bytes:
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def excel_scorrimenti() -> bytes:
    """Il modello con la colonna TIPOLOGIA: testo libero con una nota, senza menu a tendina (Principio I)."""
    wb = openpyxl.load_workbook(MODELLI / MODELLO_SCORRIMENTI)
    for ws in wb.worksheets:
        ultima = ws.max_column
        nuova = ultima + 1
        lettera = get_column_letter(nuova)
        ws.unmerge_cells(f"A1:{get_column_letter(ultima)}1")
        for riga in range(1, ws.max_row + 1):
            _copia_stile(ws.cell(riga, ultima), ws.cell(riga, nuova))
        ws.merge_cells(f"A1:{lettera}1")
        intestazione = ws.cell(2, nuova, "TIPOLOGIA")
        nota = Comment(NOTA_TIPOLOGIA, "Monitoraggio")
        nota.width, nota.height = 260, 70
        intestazione.comment = nota
        ws.column_dimensions[lettera].width = 28
        if ws.auto_filter.ref:
            inizio, fine = ws.auto_filter.ref.split(":")
            ws.auto_filter.ref = f"{inizio}:{lettera}{fine.lstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
    return _salva(wb)


def excel_graduatorie_vuoto() -> bytes:
    """Il modello con tutte le intestazioni, da compilare a mano: stesse colonne del file con i dati."""
    wb = openpyxl.load_workbook(MODELLI / MODELLO_GRADUATORIE)
    for foglio, intestazioni in (("Bandi pubblicati", INTESTAZIONI_BANDI), ("Mobilità pubblicate", INTESTAZIONI_BANDI),
                                 ("Graduatorie pubblicate", punteggi.INTESTAZIONI_EXCEL), ("Graduatorie mobilità", punteggi.INTESTAZIONI_EXCEL)):
        _compila(wb[foglio], intestazioni, [])
    return _salva(wb)


def _compila(ws, intestazioni: list[str], righe: list[tuple[list, bool]]) -> None:
    """Riempie un foglio del modello: titolo in riga 1, intestazioni in riga 2, dati dalla 3."""
    stile_intestazione, stile_dato = ws.cell(2, 1), ws.cell(3, 1)
    colonne = len(intestazioni)
    for intervallo in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(intervallo))
    _titolo = ws.cell(1, 1)
    for colonna in range(2, colonne + 1):
        _copia_stile(_titolo, ws.cell(1, colonna))
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=colonne)
    for colonna, testo in enumerate(intestazioni, 1):
        cella = ws.cell(2, colonna, testo)
        _copia_stile(stile_intestazione, cella)
        cella.font = Font(bold=True)
        lettera = get_column_letter(colonna)
        ws.column_dimensions[lettera].width = max(ws.column_dimensions[lettera].width or 0, min(len(testo) + 6, 26))
    giallo = PatternFill("solid", fgColor=punteggi.GIALLO_EXCEL)
    for indice, (valori, evidenzia) in enumerate(righe, 3):
        for colonna, valore in enumerate(valori, 1):
            cella = ws.cell(indice, colonna, valore)
            _copia_stile(stile_dato, cella)
            if evidenzia:
                cella.fill = giallo
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:{get_column_letter(colonne)}{max(2 + len(righe), 3)}"
    if not righe:  # da compilare a mano: la griglia del modello si estende a tutte le colonne
        for riga in range(3, ws.max_row + 1):
            for colonna in range(1, colonne + 1):
                _copia_stile(stile_dato, ws.cell(riga, colonna))
        ws.auto_filter.ref = f"A2:{get_column_letter(colonne)}{ws.max_row}"


def _bandi(conn, dal: str, al: str) -> list:
    return [s for s in conn.execute("SELECT * FROM scheda WHERE fonte = 'sol' AND presente = 1 AND data_pubblicazione BETWEEN ? AND ? "
                                    "ORDER BY data_pubblicazione, codice_originale", (dal, al)) if config.nel_monitoraggio(s["tipologia"])]


def graduatorie_periodo(conn, dal: str, al: str) -> list:
    return [s for s in punteggi.schede_periodo(conn, dal, al) if config.nel_monitoraggio(s["tipologia"])]


def _riga_bando(s) -> tuple[list, bool]:
    extra = json.loads(s["dati_extra"]) if s["dati_extra"] else {}
    data = data_iso(s["data_pubblicazione"])
    return ([s["codice_originale"], extra.get("sede"), extra.get("struttura_destinataria"), extra.get("numero_posti"),
             extra.get("profilo"), s["protocollo_originale"], "/".join(reversed(data.split("-"))) if data else ""], False)


def _righe_graduatoria(s) -> list[tuple[list, bool]]:
    righe = punteggi.righe_excel_scheda(s)
    if righe:
        return righe
    extra = json.loads(s["dati_extra"]) if s["dati_extra"] else {}
    vuota = [s["codice_originale"], extra.get("sede"), extra.get("struttura_destinataria"), extra.get("numero_posti"),
             extra.get("profilo")] + [None] * (len(punteggi.INTESTAZIONI_EXCEL) - 5)
    vuota[punteggi.INTESTAZIONI_EXCEL.index("Note")] = "Elenco non caricato: eseguire la verifica dei punteggi"
    return [(vuota, False)]


def graduatorie_senza_elenco(conn, dal: str, al: str) -> int:
    return sum(1 for s in graduatorie_periodo(conn, dal, al) if not punteggi.righe_excel_scheda(s))


def excel_graduatorie(conn, dal: str, al: str) -> bytes:
    """Il modello compilato con i bandi e le graduatorie del periodo."""
    wb = openpyxl.load_workbook(MODELLI / MODELLO_GRADUATORIE)
    bandi = _bandi(conn, dal, al)
    graduatorie = graduatorie_periodo(conn, dal, al)
    mobilita = lambda s: s["tipologia"] in TIPOLOGIE_MOBILITA  # noqa: E731
    _compila(wb["Bandi pubblicati"], INTESTAZIONI_BANDI, [_riga_bando(s) for s in bandi if not mobilita(s)])
    _compila(wb["Mobilità pubblicate"], INTESTAZIONI_BANDI, [_riga_bando(s) for s in bandi if mobilita(s)])
    _compila(wb["Graduatorie pubblicate"], punteggi.INTESTAZIONI_EXCEL,
             [r for s in graduatorie if not mobilita(s) for r in _righe_graduatoria(s)])
    _compila(wb["Graduatorie mobilità"], punteggi.INTESTAZIONI_EXCEL,
             [r for s in graduatorie if mobilita(s) for r in _righe_graduatoria(s)])
    return _salva(wb)
