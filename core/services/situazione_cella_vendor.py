"""Colore della cella B&R Doc nella vista orizzontale di situazione documenti.

La colonna B&R Doc riassume da sola come sta il documento, così le celle Status
delle singole revisioni restano senza colore. Il colore è quello dell'ultimo
stato: il giallo dell'«inviato al cliente» se l'ultima revisione è partita e la
risposta manca ancora, altrimenti il colore dell'ultima risposta arrivata. Il
grigio del «da inviare» resta solo per i documenti su cui il cliente non si è
mai espresso e che non sono mai partiti.

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

CELLA_VUOTA = {"bg": "", "fg": "", "label": "", "lettera": ""}


def colori_cella_vendor(revs) -> dict:
    """Return ``{"bg", "fg", "label", "lettera"}`` for a document's B&R Doc cell.

    Args:
        revs: The document's serialized revisions, ordered by ``rev_no``.

    Returns:
        Background, text color, the label describing the state and the letter
        della risposta quando ce n'è una. Tutto vuoto per un documento senza
        revisioni: non c'è ancora nulla da dire.
    """
    revs = list(revs or [])
    if not revs:
        return dict(CELLA_VUOTA)
    if in_attesa_di_risposta(revs[-1]):
        return {
            **inviato_cell_colors(),
            "label": stato_interno_label(INVIATO),
            "lettera": "",
        }
    # Nessun invio in attesa: vale l'ultima risposta arrivata, anche quando sta
    # su una revisione precedente.
    for rev in reversed(revs):
        risposta = (rev.get("ext_status_label") or "").strip()
        if not risposta:
            continue
        colori = cell_colors(rev.get("ext_status_colore") or "")
        return {
            "bg": (rev.get("ext_status_bg") or "").strip() or colori["bg"],
            "fg": (rev.get("ext_status_fg") or "").strip() or colori["fg"],
            "label": risposta,
            "lettera": (rev.get("ext_status_lettera") or "").strip(),
        }
    # Il cliente non si è mai espresso e il documento non è mai partito.
    return {**da_inviare_cell_colors(), "label": DA_INVIARE_LABEL, "lettera": ""}


def colore_cella_vendor(revs) -> str:
    """Solo il colore di fondo della cella B&R Doc (``#RRGGBB``), '' se non c'è."""
    return colori_cella_vendor(revs)["bg"]


__all__ = [
    "DA_INVIARE_BG",
    "INVIATO_BG",
    "colore_cella_vendor",
    "colori_cella_vendor",
]
