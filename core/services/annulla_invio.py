"""Annullamento di un invio al cliente registrato per errore.

L'emissione (``commesse.esegui_emissione``, chiamata anche dal trasmittal) marca
la revisione corrente come inviata: ``int_status = "inviato_al_cliente"``,
``dis_act_date`` alla data di emissione e ``rec_plan_date`` a quella data più i
giorni concessi al cliente (``Testata.time_cli_doc_rev``). Qui si tornano
indietro quei tre campi, finché il cliente non ha ancora risposto. Trasmittal e
file collegati non si toccano.
"""

from django.db import transaction

from ..models import Revisione
from .commesse import serialize_revisione
from .stato_interno import INVIATO

DA_EMETTERE = "da_emettere"


class InvioNonAnnullabile(ValueError):
    """La revisione non è in uno stato in cui l'invio si possa annullare."""


@transaction.atomic
def annulla_invio_cliente(pk):
    """Annulla l'invio al cliente della revisione ``pk``.

    Riporta ``int_status`` a ``"da_emettere"`` e azzera ``dis_act_date`` e
    ``rec_plan_date``, i soli campi che l'emissione valorizza. Il trasmittal in
    cui la revisione è stata emessa e i file restano com'erano.

    Returns:
        ``{"revisione": serialize_revisione(rev)}``.

    Raises:
        Revisione.DoesNotExist: la revisione non esiste.
        InvioNonAnnullabile: la revisione non risulta inviata al cliente, oppure
            è già rientrata (data di ricezione o risposta del cliente presenti).
    """
    rev = Revisione.objects.select_for_update(of=("self",)).get(pk=pk)
    if rev.int_status != INVIATO:
        raise InvioNonAnnullabile(
            "La revisione non risulta inviata al cliente: niente da annullare."
        )
    if rev.rec_act_date is not None or rev.ext_status_id is not None:
        raise InvioNonAnnullabile(
            "La revisione è già rientrata dal cliente: l'invio non si può annullare."
        )

    rev.int_status = DA_EMETTERE
    rev.dis_act_date = None
    rev.rec_plan_date = None
    rev.save(update_fields=["int_status", "dis_act_date", "rec_plan_date"])

    return {"revisione": serialize_revisione(rev)}
