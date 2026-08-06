"""Display formatting for dates: ``10 jan 2026``."""

from __future__ import annotations

from datetime import date, datetime

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


def format_display_date(value) -> str:
    """Format a date/datetime/ISO string as ``d mon yyyy`` (e.g. ``10 jan 2026``)."""
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    elif not isinstance(value, date):
        return str(value)
    return f"{value.day} {_MONTHS_SHORT[value.month - 1]} {value.year}"
