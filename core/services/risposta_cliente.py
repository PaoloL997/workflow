"""Correzione della risposta del cliente su una revisione già rientrata.

La ricezione (``commesse.esegui_ricezione``) registra la prima risposta e, se
la risposta lo prevede, crea la revisione successiva. Qui si cambia una
risposta già registrata tenendo coerenti il flag ``crea_nuova_rev`` della
revisione e la revisione successiva: se la nuova risposta non prevede un'altra
revisione, quella successiva ancora vuota si elimina; se la prevede e manca,
si crea come alla ricezione.
"""

from django.db import transaction

from ..models import Revisione, RevisioneFileLink, StatoEsterno
from .commesse import crea_revisione_successiva, serialize_revisione

ELIMINATA = "eliminata"
CREATA = "creata"
NESSUNA = "nessuna"


class RispostaClienteNonCorreggibile(ValueError):
    """La correzione non si può fare così com'è chiesta (risposta inesistente o
    uguale, revisione mai rientrata)."""


class RevisioneSuccessivaInLavorazione(Exception):
    """La revisione successiva ha già dati propri: non si elimina da sola."""


def revisione_vuota(rev):
    """Vero se la revisione non è mai stata toccata dopo la creazione.

    Niente invio, rientro o risposta del cliente, nessun file collegato a mano
    (``RevisioneFileLink``; la ricerca automatica del file parte solo dalle date
    di invio/rientro, già escluse) e in nessun trasmittal emesso, che la
    perderebbe dal proprio elenco se la revisione venisse eliminata.
    """
    return (
        rev.dis_act_date is None
        and rev.rec_act_date is None
        and rev.ext_status_id is None
        and not RevisioneFileLink.objects.filter(revisione=rev).exists()
        and not rev.trasmittal.exists()
    )


def revisioni_successive(rev):
    """Le righe della revisione successiva a ``rev``: stesso documento, ``rev_no + 1``.

    Più righe con lo stesso numero sono possibili (import dal vecchio Access):
    contano tutte, la più recente (l'ultima della lista) è quella che si mostra.
    """
    return list(
        Revisione.objects.filter(documento_id=rev.documento_id, rev_no=(rev.rev_no or 0) + 1)
        .select_related("ext_status")
        .order_by("pk")
    )


@transaction.atomic
def correggi_risposta_cliente(pk, ext_status_id):
    """Cambia la risposta del cliente della revisione ``pk`` in ``ext_status_id``.

    Allinea ``crea_nuova_rev`` alla nuova risposta e la revisione successiva
    (stesso documento, ``rev_no + 1``):

    - la nuova risposta non prevede un'altra revisione e la successiva è vuota
      (vedi ``revisione_vuota``) → la successiva si elimina;
    - la prevede e la successiva non c'è → si crea come alla ricezione;
    - negli altri casi la successiva resta com'è.

    Tutto o niente: se la successiva è già in lavorazione non si salva nulla.

    Returns:
        ``{"revisione": ..., "successiva": {"azione": ..., "revisione": ...}}``
        con ``azione`` fra ``"eliminata"``, ``"creata"`` e ``"nessuna"``.
        ``successiva.revisione`` è la revisione creata, quella eliminata (com'era
        prima di eliminarla) o quella già presente; ``None`` se non ce n'è.

    Raises:
        Revisione.DoesNotExist: la revisione non esiste.
        RispostaClienteNonCorreggibile: risposta inesistente o uguale a quella
            attuale, o revisione ancora senza risposta (va registrata dalla
            ricezione).
        RevisioneSuccessivaInLavorazione: la nuova risposta non prevede
            un'altra revisione ma la successiva ha già dati propri.
    """
    rev = (
        Revisione.objects.select_for_update(of=("self",))
        .select_related("documento__testata", "ext_status")
        .get(pk=pk)
    )
    nuovo_stato = StatoEsterno.objects.filter(pk=ext_status_id).first()
    if nuovo_stato is None:
        raise RispostaClienteNonCorreggibile(f"Risposta cliente non valida: {ext_status_id}.")
    if rev.ext_status_id is None:
        raise RispostaClienteNonCorreggibile(
            "La revisione non ha ancora una risposta del cliente: registrarla da Gestisci ricezione."
        )
    if rev.ext_status_id == nuovo_stato.pk:
        raise RispostaClienteNonCorreggibile(
            "La risposta del cliente è già questa: niente da correggere."
        )

    doc = rev.documento
    successive = revisioni_successive(rev)

    azione, successiva = NESSUNA, (successive[-1] if successive else None)
    if not nuovo_stato.crea_nuova_rev and successive:
        if not all(revisione_vuota(s) for s in successive):
            raise RevisioneSuccessivaInLavorazione(
                "La revisione successiva è già in lavorazione, correggere manualmente."
            )
        azione = ELIMINATA
    elif nuovo_stato.crea_nuova_rev and not successive:
        azione = CREATA

    rev.ext_status = nuovo_stato
    rev.crea_nuova_rev = nuovo_stato.crea_nuova_rev
    rev.save(update_fields=["ext_status", "crea_nuova_rev"])

    # La testata è già caricata con la revisione: l'etichetta non costa query.
    testata = doc.testata
    if azione == ELIMINATA:
        dati_successiva = serialize_revisione(successiva, testata=testata)
        Revisione.objects.filter(pk__in=[s.pk for s in successive]).delete()
    elif azione == CREATA:
        dati_successiva = serialize_revisione(crea_revisione_successiva(doc, rev), testata=testata)
    else:
        dati_successiva = serialize_revisione(successiva, testata=testata) if successiva else None

    return {
        "revisione": serialize_revisione(rev, testata=testata),
        "successiva": {"azione": azione, "revisione": dati_successiva},
    }
