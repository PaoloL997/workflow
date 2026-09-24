"""Browser titles: on commessa pages the job number replaces the word "Commessa"."""

from __future__ import annotations

COMMESSA_FALLBACK = "Commessa"
TITLE_SEPARATOR = " · "


def format_commessa_page_title(job, section: str = "") -> str:
    """Build the ``<title>`` of a commessa page.

    Args:
        job: Numero di commessa (``testata.job``); può mancare.
        section: Nome della sezione (es. ``Lista documenti``); vuoto sulla
            pagina principale della commessa.

    Returns:
        ``25056`` sulla pagina della commessa, ``25056 · Lista documenti`` nelle
        sue sezioni; senza numero resta il nome della sezione, o ``Commessa``.
    """
    numero = "" if job is None else str(job).strip()
    sezione = "" if section is None else str(section).strip()
    if not numero:
        return sezione or COMMESSA_FALLBACK
    if not sezione:
        return numero
    return f"{numero}{TITLE_SEPARATOR}{sezione}"
