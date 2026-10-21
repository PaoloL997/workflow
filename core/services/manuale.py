"""Lettura del manuale utente (``MANUALE_UTENTE.md``) per ``GET /api/manuale/``.

Il file viene indicizzato da un servizio esterno (ricerca semantica): oltre al
testo serve una versione per sapere se l'indice è ancora aggiornato. La
versione è lo SHA-256 del contenuto (primi 16 esadecimali), così cambia solo
quando cambia il testo; ``updated_at`` è la data di modifica del file.

L'eventuale sezione "Indice" (sommario con i link ai capitoli) non viene mai
servita: per la ricerca è rumore, e il manuale è pensato senza.
"""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings

# Sezione "Indice" (titolo di qualsiasi livello, eventualmente preceduta dal
# marcatore ``<!-- no-index -->``) fino al titolo successivo o alla fine del file.
_INDICE = re.compile(
    r"^(?:<!--\s*no-index\s*-->[ \t]*\n)?#{1,6}[ \t]+Indice[ \t]*\n.*?(?=^#{1,6}[ \t]|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)


def percorso_manuale():
    """Path del manuale: ``settings.MANUALE_UTENTE_PATH`` (nella repo)."""
    return Path(settings.MANUALE_UTENTE_PATH)


def senza_indice(testo):
    """Il testo del manuale senza la sezione "Indice"."""
    return _INDICE.sub("", testo)


def leggi_manuale():
    """Legge il manuale (senza indice) e ne calcola versione e data di modifica.

    Returns:
        ``{"version": ..., "updated_at": ..., "content": ...}``.

    Raises:
        FileNotFoundError: il file non esiste.
    """
    percorso = percorso_manuale()
    content = senza_indice(percorso.read_text(encoding="utf-8"))
    mtime = percorso.stat().st_mtime
    return {
        "version": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        "updated_at": datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
        "content": content,
    }
