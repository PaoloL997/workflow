"""Display formatting for dates: ``10 gen 2026`` (``10 jan 2026`` nei PDF)."""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

# Schermate: abbreviazioni italiane, come il resto dell'interfaccia. Stessa
# lista di ``MONTHS_SHORT`` in ``core/templates/core/base.html``.
_MONTHS_SHORT = (
    "gen",
    "feb",
    "mar",
    "apr",
    "mag",
    "giu",
    "lug",
    "ago",
    "set",
    "ott",
    "nov",
    "dic",
)

# PDF dei trasmittal: sono documenti in inglese e tengono i mesi in inglese.
_MONTHS_SHORT_EN = (
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
)


def parse_iso_date(value, *, strict: bool = False) -> date | None:
    """Data da una stringa ISO (``YYYY-MM-DD``) o da una ``date``; ``None`` se vuoto.

    Un valore malformato dà ``None`` (es. campi liberi di un payload) oppure,
    con ``strict=True``, solleva ``ValueError`` (es. una data che l'utente ha
    scritto a mano e che va rifiutata, non ignorata).
    """
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        if strict:
            raise
        return None


def format_display_date(value) -> str:
    """Format a date/datetime/ISO string as ``d mon yyyy`` (e.g. ``10 gen 2026``)."""
    return _format(value, _MONTHS_SHORT)


def format_document_date(value) -> str:
    """Come ``format_display_date`` ma con i mesi in inglese (``10 jan 2026``), per i PDF."""
    return _format(value, _MONTHS_SHORT_EN)


def _format(value, months) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        # Un datetime aware (es. ``created_at``, salvato in UTC) va letto nel
        # fuso locale: alle 00:30 di Roma la data UTC è ancora quella di ieri.
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    elif not isinstance(value, date):
        return str(value)
    return f"{value.day} {months[value.month - 1]} {value.year}"
