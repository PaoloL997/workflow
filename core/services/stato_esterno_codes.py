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
