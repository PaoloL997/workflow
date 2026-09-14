"""Anagrafiche per il trasmittal interno (form MQ 7.5-04)."""

from django.db import transaction

from ..models import (
    DestinazioneDocumento,
    IndirizzoStabilimento,
    Stabilimento,
    TipoIndirizzoStabilimento,
)


def indirizzi_per_siti(codici_bc):
    """Email TO/CC attive per un elenco di siti, per il trasmittal interno.

    Args:
        codici_bc: Iterable di codici sito Business Central (``Stabilimento.codice_bc``).

    Returns:
        ``{"to": [...], "cc": [...]}``, liste di email senza duplicati
        (confronto case-insensitive) e senza sovrapposizioni: un indirizzo
        presente sia tra i TO che tra i CC di uno o più siti compare solo
        tra i TO. Un elenco di codici vuoto, o senza corrispondenze, dà
        ``{"to": [], "cc": []}``.
    """
    codici = list(codici_bc or [])
    if not codici:
        return {"to": [], "cc": []}

    indirizzi = IndirizzoStabilimento.objects.filter(
        stabilimento__codice_bc__in=codici, attivo=True
    ).values_list("email", "tipo")

    to, cc = [], []
    visti_to, visti_cc = set(), set()
    for email, tipo in indirizzi:
        chiave = email.strip().lower()
        if tipo == TipoIndirizzoStabilimento.TO:
            if chiave not in visti_to:
                visti_to.add(chiave)
                to.append(email)
        elif chiave not in visti_cc:
            visti_cc.add(chiave)
            cc.append(email)

    cc = [email for email in cc if email.strip().lower() not in visti_to]
    return {"to": to, "cc": cc}


def siti_del_documento(documento):
    """Stabilimenti destinatari della copia cartacea di un documento, per codice sito."""
    return list(
        Stabilimento.objects.filter(documenti_destinati__documento=documento).order_by("codice_bc")
    )


def imposta_destinazioni(documento, codici_bc):
    """Sostituisce l'intero set di stabilimenti destinatari di un documento.

    Non accumula: le destinazioni già registrate ma non più presenti in
    ``codici_bc`` vengono rimosse. Un elenco vuoto azzera le destinazioni del
    documento. Solo gli stabilimenti con un codice sito valorizzato possono
    essere destinazioni: un codice senza corrispondenza è ignorato.
    """
    stabilimenti = Stabilimento.objects.filter(codice_bc__in=list(codici_bc or []))
    with transaction.atomic():
        DestinazioneDocumento.objects.filter(documento=documento).delete()
        DestinazioneDocumento.objects.bulk_create(
            DestinazioneDocumento(documento=documento, stabilimento=stabilimento)
            for stabilimento in stabilimenti
        )


def siti_coinvolti(documenti):
    """Unione, deduplicata e ordinata per codice sito, delle destinazioni di più documenti."""
    return list(
        Stabilimento.objects.filter(documenti_destinati__documento__in=documenti)
        .distinct()
        .order_by("codice_bc")
    )
