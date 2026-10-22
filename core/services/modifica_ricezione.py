"""Correzione o annullamento di una ricezione registrata male.

La ricezione (``commesse.esegui_ricezione``) segna la revisione come rientrata:
``rec_act_date`` alla data di rientro, ``ext_status`` alla risposta del cliente,
``int_status = "ricevuto"``, ``crea_nuova_rev`` e, se richiesto, crea la
revisione successiva con l'invio pianificato a partire dalla data di rientro
(``commesse.data_invio_successiva``). Qui si corregge la data di rientro, o si
torna indietro del tutto quando il documento in realtà non è rientrato.
"""

from django.db import transaction
from django.utils import timezone

from ..models import Revisione
from .commesse import data_invio_successiva, serialize_revisione
from .risposta_cliente import (
    ELIMINATA,
    NESSUNA,
    RevisioneSuccessivaInLavorazione,
    revisione_vuota,
    revisioni_successive,
)
from .stato_interno import INVIATO, RICEVUTO

AGGIORNATA = "aggiornata"


class RicezioneNonModificabile(ValueError):
    """La modifica non si può fare così com'è chiesta (revisione non rientrata,
    data non ammessa o uguale a quella attuale)."""


@transaction.atomic
def modifica_ricezione(pk, rec_act_date):
    """Corregge la data di rientro della revisione ``pk``, o annulla la ricezione.

    Con una data, la imposta come data di rientro. Se la revisione successiva
    (stesso documento, ``rev_no + 1``) è vuota (vedi ``revisione_vuota``) la sua
    data di invio pianificata si ricalcola come alla ricezione; se è già in
    lavorazione, o se la commessa non ha i giorni del vendor da cui ricalcolarla,
    resta com'è.

    Con ``None`` annulla la ricezione: la revisione torna "inviata al cliente",
    senza data di rientro né risposta e con ``crea_nuova_rev`` spento; data di
    invio e data di ricezione prevista restano, perché vengono dall'invio. La
    revisione successiva vuota si elimina. Tutto o niente: se la successiva è
    già in lavorazione non si salva nulla.

    Args:
        pk: La revisione.
        rec_act_date: La nuova data di rientro (``date``), o ``None`` per
            annullare la ricezione.

    Returns:
        ``{"revisione": ..., "successiva": {"azione": ..., "revisione": ...}}``
        con ``azione`` fra ``"aggiornata"``, ``"eliminata"`` e ``"nessuna"``.
        ``successiva.revisione`` è la revisione aggiornata, quella eliminata
        (com'era prima di eliminarla) o quella già presente; ``None`` se non ce
        n'è.

    Raises:
        Revisione.DoesNotExist: la revisione non esiste.
        RicezioneNonModificabile: la revisione non è rientrata, o la data è
            precedente all'invio, nel futuro o uguale a quella attuale.
        RevisioneSuccessivaInLavorazione: si annulla la ricezione ma la
            revisione successiva ha già dati propri.
    """
    rev = (
        Revisione.objects.select_for_update(of=("self",))
        .select_related("documento__testata", "ext_status")
        .get(pk=pk)
    )
    if rev.int_status != RICEVUTO or rev.rec_act_date is None:
        raise RicezioneNonModificabile(
            "La revisione non risulta rientrata dal cliente: niente da modificare."
        )
    if rec_act_date is not None:
        _controlla_data(rev, rec_act_date)

    successive = revisioni_successive(rev)
    vuote = bool(successive) and all(revisione_vuota(s) for s in successive)
    successiva = successive[-1] if successive else None
    testata = rev.documento.testata

    azione = NESSUNA
    if rec_act_date is None:
        if successive and not vuote:
            raise RevisioneSuccessivaInLavorazione(
                "La revisione successiva è già in lavorazione, correggere manualmente."
            )
        rev.rec_act_date = None
        rev.ext_status = None
        rev.int_status = INVIATO
        rev.crea_nuova_rev = False
        rev.save(update_fields=["rec_act_date", "ext_status", "int_status", "crea_nuova_rev"])
        if vuote:
            azione = ELIMINATA
    else:
        rev.rec_act_date = rec_act_date
        rev.save(update_fields=["rec_act_date"])
        dis_plan_date = data_invio_successiva(testata, rec_act_date)
        # Senza giorni del vendor la regola non dà una data: quella presente
        # (magari scritta a mano) resta, invece di essere cancellata.
        if vuote and dis_plan_date is not None:
            azione = AGGIORNATA
            for s in successive:
                s.dis_plan_date = dis_plan_date
                s.save(update_fields=["dis_plan_date"])

    dati_successiva = serialize_revisione(successiva, testata=testata) if successiva else None
    if azione == ELIMINATA:
        Revisione.objects.filter(pk__in=[s.pk for s in successive]).delete()
    return {
        "revisione": serialize_revisione(rev, testata=testata),
        "successiva": {"azione": azione, "revisione": dati_successiva},
    }


def _controlla_data(rev, rec_act_date):
    """Solleva ``RicezioneNonModificabile`` se ``rec_act_date`` non è ammessa per ``rev``."""
    if rec_act_date == rev.rec_act_date:
        raise RicezioneNonModificabile("La data di rientro è già questa: niente da correggere.")
    # Le revisioni importate dal vecchio Access possono non avere la data di invio.
    if rev.dis_act_date is not None and rec_act_date < rev.dis_act_date:
        raise RicezioneNonModificabile(
            "La data di rientro non può essere precedente alla data di invio al cliente."
        )
    if rec_act_date > timezone.localdate():
        raise RicezioneNonModificabile("La data di rientro non può essere nel futuro.")
