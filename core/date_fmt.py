"""Display formatting for dates: ``10 jan 2026``."""

from __future__ import annotations

from datetime import date, datetime

from django.utils import timezone

_MONTHS_SHORT = (
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
    """Format a date/datetime/ISO string as ``d mon yyyy`` (e.g. ``10 jan 2026``)."""
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
    return f"{value.day} {_MONTHS_SHORT[value.month - 1]} {value.year}"
