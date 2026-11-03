"""Classificazione dei documenti in due livelli (research R4).

Livello 1: categoria, da titolo/nome file e tipo SOL. Il tipo SOL distingue la graduatoria
pubblica (``call_classification``) da un allegato generico che può contenere la graduatoria
completa privata. In quest'ultimo caso la sola parola "graduatoria" nel titolo non lo rende
pubblico. Per gli altri documenti le parole nel titolo prevalgono.
Livello 2: sottotipo degli scorrimenti, solo indicativo, ricavato dal titolo.
Le regole sono liste di pattern: per cambiarle basta modificare queste liste.
"""
import re

# Livello 1: in ordine, vince la prima categoria che corrisponde
REGOLE_CATEGORIA = [
    # anche modifica / rimodulazione / riformulazione della graduatoria (indicazione dell'utente, 2026-10-29)
    ("rettifica", [r"rettific", r"errata\s*corrige", r"\b(?:modific|rimodul|riformul)\w*\b.{0,30}graduatori"]),
    ("scorrimento", [
        r"scorriment",
        r"subentr",
        r"utilizz\w*\b.{0,40}graduatori",
        r"assunzion\w*\b.{0,60}idone",
    ]),
    ("graduatoria", [r"graduatori"]),
    ("criteri", [r"\bcriteri(?:di)?\b"]),
    ("tracce", [
        r"\btracc\w+",
        r"^(?!.*\b(?:convoca|avvis|calendari|esit)).*\bprova scritta\b",
        r"^(?!.*\b(?:convoca|avvis|calendari|esit)).*\b(?:prova|prove)\s+teorico[\-\s]?pratic\w*",
        r"^(?!.*\b(?:convoca|avvis|calendari|esit)).*\b(?:prova|prove)\s+oral\w*",
    ]),
]

# Categoria dal tipo di allegato SOL, usata quando il titolo non dice niente
CATEGORIA_TIPO_SOL = {
    "call_recruitment_provision": "scorrimento",
    "call_classification": "graduatoria",
    "call_correction_classification": "rettifica",
    "call_errata_corrige": "rettifica",
    "call_it": "bando",
    "call_en": "bando",
    "call_mobility": "bando",
}

# Livello 2: in ordine, vince il primo sottotipo che corrisponde
REGOLE_SOTTOTIPO = [
    ("subentro", [r"subentr", r"rinunci"]),
    ("ulteriore", [
        r"ulterior",
        r"\b(?:second|terz|quart|quint|sest)[oaie]\b",
        r"\d+\s*°\s*scorriment",
        r"nuovo\s+scorriment",
    ]),
    ("utilizzo", [r"utilizz\w*\b.{0,40}graduatori"]),
]

ORDINALI = {"second": 2, "terz": 3, "quart": 4, "quint": 5, "sest": 6}


def _corrisponde(testo: str, patterns: list[str]) -> bool:
    return any(re.search(p, testo, re.I) for p in patterns)


def _ordinale(testo: str) -> int | None:
    m = re.search(r"\b(second|terz|quart|quint|sest)[oaie]\b", testo, re.I)
    if m:
        return ORDINALI[m.group(1).lower()]
    m = re.search(r"(\d+)\s*°\s*scorriment", testo, re.I)
    return int(m.group(1)) if m else None


def _testo(titolo: str | None) -> str:
    # i nomi file usano _ e - al posto degli spazi
    return re.sub(r"[_\s]+", " ", titolo or "").strip()


def categoria(titolo: str | None, tipo_fonte: str | None = None) -> str:
    testo = _testo(titolo)
    tipo = (tipo_fonte or "").split(":")[-1]
    for nome, patterns in REGOLE_CATEGORIA:
        # Un documento SOL call_generic con "graduatoria" nel titolo può essere la lista
        # completa privata. La graduatoria pubblica è identificata dal tipo call_classification.
        if tipo == "call_generic" and nome == "graduatoria":
            continue
        if _corrisponde(testo, patterns):
            return nome
    return CATEGORIA_TIPO_SOL.get(tipo, "altro")


def sottotipo(titolo: str | None) -> tuple[str, int | None]:
    testo = _testo(titolo)
    for nome, patterns in REGOLE_SOTTOTIPO:
        if _corrisponde(testo, patterns):
            return nome, (_ordinale(testo) if nome == "ulteriore" else None)
    return "non_specificato", None


def classifica(titolo: str | None, tipo_fonte: str | None = None) -> tuple[str, str | None, int | None]:
    """Ritorna (categoria, sottotipo, ordinale); sottotipo solo per gli scorrimenti."""
    cat = categoria(titolo, tipo_fonte)
    if cat != "scorrimento":
        return cat, None, None
    sotto, ordinale = sottotipo(titolo)
    return cat, sotto, ordinale
