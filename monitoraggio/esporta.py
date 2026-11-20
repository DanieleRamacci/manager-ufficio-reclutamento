"""Esportazione in Excel delle righe di una tabella (spec 012, FR-005).

La pagina manda le colonne scelte e le righe già filtrate, con i valori come li vede: qui si fa solo il file.
Valori solo testo o numeri; un testo che comincia con «=» resta testo (niente formule nel file).
"""
import io
import re
from datetime import date

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

MAX_RIGHE = 20000
MAX_COLONNE = 60
MAX_TESTO = 5000


class DatiNonValidi(ValueError):
    pass


def _valore(v):
    if v is None or isinstance(v, bool):
        return "" if v is None else ("sì" if v else "no")
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v[:MAX_TESTO]
    raise DatiNonValidi("valori ammessi: testo o numeri")


def nome_file(nome: str | None) -> str:
    base = re.sub(r"[^\w\-. ]+", "", nome or "").strip()[:80] or "esportazione"
    return f"{base}-{date.today().isoformat()}.xlsx"


def xlsx(colonne: list, righe: list, foglio: str = "Dati") -> bytes:
    if not isinstance(colonne, list) or not colonne or len(colonne) > MAX_COLONNE:
        raise DatiNonValidi("scegli almeno una colonna")
    if not isinstance(righe, list) or len(righe) > MAX_RIGHE:
        raise DatiNonValidi(f"troppe righe (al massimo {MAX_RIGHE})")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = re.sub(r"[\[\]\*\?/\\:]", "", foglio)[:31] or "Dati"
    ws.append([str(_valore(c)) for c in colonne])
    for cella in ws[1]:
        cella.font = Font(bold=True)
        cella.fill = PatternFill("solid", fgColor="E7EFFB")
    larghezze = [len(str(c)) for c in colonne]
    for n, riga in enumerate(righe, start=2):
        if not isinstance(riga, list) or len(riga) != len(colonne):
            raise DatiNonValidi("ogni riga deve avere un valore per colonna")
        for i, v in enumerate(riga, start=1):
            valore = _valore(v)
            cella = ws.cell(row=n, column=i, value=valore)
            if isinstance(valore, str) and valore.startswith("="):
                cella.data_type = "s"
            larghezze[i - 1] = max(larghezze[i - 1], min(len(str(valore)), 60))
    for i, w in enumerate(larghezze, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, w + 2)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def risposta(dati):
    """Risposta Flask con il file, oppure errore 400."""
    from flask import jsonify, send_file
    dati = dati if isinstance(dati, dict) else {}
    try:
        contenuto = xlsx(dati.get("colonne"), dati.get("righe"), dati.get("foglio") or "Dati")
    except DatiNonValidi as e:
        return jsonify({"error": str(e)}), 400
    r = send_file(io.BytesIO(contenuto), as_attachment=True, download_name=nome_file(dati.get("nome")),
                  mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    r.headers["Cache-Control"] = "no-store"
    return r
