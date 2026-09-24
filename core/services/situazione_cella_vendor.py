"""Colore della cella B&R Doc nella vista orizzontale di situazione documenti.

La colonna B&R Doc riassume da sola come sta il documento, così le celle Status
delle singole revisioni restano senza colore. Il colore è quello dell'ultimo
stato dell'ultima revisione: la risposta del cliente quando è arrivata, il
giallo dell'«inviato al cliente» quando il documento è partito e la risposta
manca ancora, il grigio del «da inviare» finché la revisione non è partita.

Vale allo stesso modo a schermo, nell'export Excel e nel PDF.
"""

from .stato_esterno_colori import (
    DA_INVIARE_BG,
    INVIATO_BG,
    cell_colors,
    da_inviare_cell_colors,
    inviato_cell_colors,
)
from .stato_interno import DA_INVIARE_LABEL, INVIATO, in_attesa_di_risposta, stato_interno_label

CELLA_VUOTA = {"bg": "", "fg": "", "label": ""}


def colori_cella_vendor(revs) -> dict:
    """Return ``{"bg", "fg", "label"}`` for a document's B&R Doc cell.

    Args:
        revs: The document's serialized revisions, ordered by ``rev_no``.

    Returns:
        Background, text color and the label describing the state. Tutto vuoto
        per un documento senza revisioni: non c'è ancora nulla da dire.
    """
    revs = list(revs or [])
    if not revs:
        return dict(CELLA_VUOTA)
    ultima = revs[-1]
    risposta = (ultima.get("ext_status_label") or "").strip()
    if risposta:
        colori = cell_colors(ultima.get("ext_status_colore") or "")
        return {
            "bg": (ultima.get("ext_status_bg") or "").strip() or colori["bg"],
            "fg": (ultima.get("ext_status_fg") or "").strip() or colori["fg"],
            "label": risposta,
        }
    if in_attesa_di_risposta(ultima):
        return {**inviato_cell_colors(), "label": stato_interno_label(INVIATO)}
    return {**da_inviare_cell_colors(), "label": DA_INVIARE_LABEL}


def colore_cella_vendor(revs) -> str:
    """Solo il colore di fondo della cella B&R Doc (``#RRGGBB``), '' se non c'è."""
    return colori_cella_vendor(revs)["bg"]


__all__ = [
    "DA_INVIARE_BG",
    "INVIATO_BG",
    "colore_cella_vendor",
    "colori_cella_vendor",
]
