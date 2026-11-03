"""Configurazione da variabili d'ambiente (contracts/api.md, "Configurazione").

Le funzioni leggono l'ambiente a ogni chiamata, così test e app possono cambiarlo.
"""
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

USER_AGENT = "Mozilla/5.0 (compatible; CNR-BandiBot/1.0)"

# --- URP ---
URP_BASE = "https://www.urp.cnr.it"
URP_SEZIONI_PREDEFINITE = "tempo-indeterminato,bandi-pubblici-mobilita,categorie-riservatarie"
# tipologia del bando per sezione URP (la mobilità può diventare "comando" dal testo)
URP_TIPOLOGIA = {
    "tempo-indeterminato": "tempo_indeterminato",
    "bandi-pubblici-mobilita": "mobilita",
    "categorie-riservatarie": "categorie_protette",
}

# --- Selezioni Online (research R1, R2) ---
SOL_BASE = "https://selezionionline.cnr.it/jconon"
SOL_TREE_UUID = "713d4376-4cbd-43b6-ad14-9401b5029c51"
SOL_PAGE_SIZE = 100
SOL_TIPI = {
    "F:jconon_call_tind:folder_concorsi_pubblici": "tempo_indeterminato",
    "F:jconon_call_tind:folder_reclutamento_speciale": "reclutamento_speciale",
    "F:jconon_call_tind:folder_categorie_protette": "categorie_protette",
    "F:jconon_call_mobility:folder": "mobilita",
    "F:jconon_call_comandi_distacchi:folder": "comando",
}
# finestra dei bandi "attivi" per la raccolta incrementale degli allegati (research R8)
SOL_MESI_ATTIVI = 36

GIORNI_SETTIMANA = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _env(nome: str, predefinito: str) -> str:
    valore = os.environ.get(nome)
    return valore.strip() if valore and valore.strip() else predefinito


def data_dir() -> Path:
    return Path(_env("DATA_DIR", str(ROOT / "instance")))


def db_path() -> Path:
    return data_dir() / "monitoraggio.db"


def sol_search_url() -> str:
    return _env("SOL_SEARCH_URL", f"{SOL_BASE}/rest/search")


def urp_sezioni() -> list[str]:
    return [s.strip() for s in _env("URP_SEZIONI", URP_SEZIONI_PREDEFINITE).split(",") if s.strip()]


def urp_url_sezione(sezione: str) -> str:
    # senza barra finale: con la barra URP risponde 301 (research R7)
    return f"{URP_BASE}/documenti/{sezione}"


def pausa_urp() -> float:
    return float(_env("RACCOLTA_PAUSA_URP", "0.5"))


def pausa_sol() -> float:
    return float(_env("RACCOLTA_PAUSA_SOL", "1.0"))


def raccolta_notturna() -> bool:
    return _env("RACCOLTA_NOTTURNA", "1") not in ("0", "false", "no")


def raccolta_orario() -> tuple[int, int]:
    ore, minuti = _env("RACCOLTA_ORARIO", "02:30").split(":")
    return int(ore), int(minuti)


def raccolta_completa_giorno() -> int:
    """Giorno della raccolta completa settimanale, 0 = lunedì."""
    return GIORNI_SETTIMANA.index(_env("RACCOLTA_COMPLETA_GIORNO", "dom").lower()[:3])


def controllo_pdf() -> bool:
    return _env("RACCOLTA_CONTROLLO_PDF", "1") not in ("0", "false", "no")


def monitoraggio_dal() -> date:
    return date.fromisoformat(_env("MONITORAGGIO_DAL", "2026-01-01"))
