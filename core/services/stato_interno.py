"""Stato interno effettivo di una revisione.

Lo stato interno vive in ``Revisione.int_status``, ma le righe che arrivano dal
vecchio Access (e quelle sistemate a mano) possono averlo vuoto anche quando il
documento ha già viaggiato. La risposta del cliente, la data di rientro o la
data di invio effettive sono la prova che è stato emesso: in quel caso lo stato
va dedotto, altrimenti la revisione resta nel gruppo «Da inviare».

Lo stato salvato ha sempre la precedenza: si deduce solo quando è vuoto.
"""

from ..models import STATI_INTERNI_CHOICES

INVIATO = "inviato_al_cliente"
RICEVUTO = "ricevuto"

# Etichetta mostrata quando non c'è nessuno stato, né salvato né deducibile.
DA_INVIARE_LABEL = "Da inviare"

_LABELS = dict(STATI_INTERNI_CHOICES)


def stato_interno_effettivo(
    int_status,
    *,
    dis_act_date=None,
    rec_act_date=None,
    ha_risposta_cliente=False,
) -> str:
    """Stato interno da mostrare per una revisione.

    Ritorna lo stato salvato se c'è; altrimenti lo deduce dai fatti registrati
    (risposta del cliente o rientro → ricevuto, invio → inviato al cliente) e
    ritorna stringa vuota quando non c'è ancora nulla.
    """
    code = (int_status or "").strip()
    if code:
        return code
    if rec_act_date or ha_risposta_cliente:
        return RICEVUTO
    if dis_act_date:
        return INVIATO
    return ""


def stato_interno_label(code: str) -> str:
    """Etichetta dello stato interno, «Da inviare» quando è vuoto."""
    code = (code or "").strip()
    if not code:
        return DA_INVIARE_LABEL
    return _LABELS.get(code, code)


def stato_interno_effettivo_da_revisione(rev) -> str:
    """Come :func:`stato_interno_effettivo`, a partire da un ``Revisione``."""
    return stato_interno_effettivo(
        rev.int_status,
        dis_act_date=rev.dis_act_date,
        rec_act_date=rev.rec_act_date,
        ha_risposta_cliente=bool(rev.ext_status_id),
    )
