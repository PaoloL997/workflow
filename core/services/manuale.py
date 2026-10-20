"""Lettura del manuale utente (``MANUALE_UTENTE.md``) per ``GET /api/manuale/``.

Il file viene indicizzato da un servizio esterno (ricerca semantica): oltre al
testo serve una versione per sapere se l'indice è ancora aggiornato. La
versione è lo SHA-256 del contenuto (primi 16 esadecimali), così cambia solo
quando cambia il testo; ``updated_at`` è la data di modifica del file.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from django.conf import settings


def percorso_manuale():
    """Path del manuale: ``settings.MANUALE_UTENTE_PATH`` (nella repo)."""
    return Path(settings.MANUALE_UTENTE_PATH)


def leggi_manuale():
    """Legge il manuale e ne calcola versione e data di modifica.

    Returns:
        ``{"version": ..., "updated_at": ..., "content": ...}``.

    Raises:
        FileNotFoundError: il file non esiste.
    """
    percorso = percorso_manuale()
    content = percorso.read_text(encoding="utf-8")
    mtime = percorso.stat().st_mtime
    return {
        "version": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16],
        "updated_at": datetime.fromtimestamp(mtime, tz=UTC).isoformat(),
        "content": content,
    }
