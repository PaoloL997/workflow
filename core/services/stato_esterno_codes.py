"""Canonical letter codes for client response statuses (StatoEsterno)."""

# Letter → canonical display name (import / PDF wording with spaced hyphens).
STATUS_LETTER_MAP = {
    "A": "Approved",
    "I": "Commented - To be issued as Final",
    "C": "Commented - To be resubmitted - Work can proceed",
    "F": "Final - As Built",
    "Z": "For Information",
    "O": "Old",
    "R": "Rejected - Work can not proceed",
    "S": "Superseeded",
}

# Alternate PDF legend wording (fewer spaces around hyphens).
_STATUS_NAME_ALIASES = {
    "Commented-To be issued as Final": "I",
    "Commented-To be resubmitted-Work can proceed": "C",
}

# Letter → PDF legend wording (the alias when there is one, else the name).
PDF_STATUS_LABELS = {
    **STATUS_LETTER_MAP,
    **{letter: alias for alias, letter in _STATUS_NAME_ALIASES.items()},
}

# Letter → colore di default della risposta del cliente. Sono i colori creati
# all'import da Access: valgono finché l'admin non ne configura uno a sistema.
DEFAULT_STATUS_COLORS = {
    "A": "#00B050",
    "C": "#D61D09",
    "F": "#FFC000",
    "I": "#D61D09",
    "O": "#D61D09",
    "R": "#D61D09",
    "S": "#B8B8B8",
    "Z": "#FFC000",
}

# Legenda STATUS di ripiego per il PDF: ``(lettera, nome, colore)`` in ordine
# alfabetico di lettera, usata quando non c'è nessuna risposta del cliente a
# sistema (vedi services/stato_esterno_legenda.py).
DEFAULT_STATUS_LEGEND = [
    (letter, PDF_STATUS_LABELS[letter], colore)
    for letter, colore in sorted(DEFAULT_STATUS_COLORS.items())
]


def _normalize_status_name(nome: str) -> str:
    return "".join(ch for ch in (nome or "").lower() if ch.isalnum())


_NORMALIZED_LETTER_BY_NAME = {
    _normalize_status_name(nome): letter for letter, nome in STATUS_LETTER_MAP.items()
}
for alias, letter in _STATUS_NAME_ALIASES.items():
    _NORMALIZED_LETTER_BY_NAME[_normalize_status_name(alias)] = letter


def letter_for_status_name(nome: str) -> str:
    """Return the status letter for a StatoEsterno name, or '' if unknown."""
    return _NORMALIZED_LETTER_BY_NAME.get(_normalize_status_name(nome), "")
