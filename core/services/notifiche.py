from django.utils import timezone

from ..models import Notifica, TipoSegnalazione, User

MAX_NOTIFICHE = 50

TESTO_PER_TIPO = {
    TipoSegnalazione.FEATURE: "{nome} ha proposto una nuova feature",
    TipoSegnalazione.PROBLEMA: "{nome} ha evidenziato un problema",
}


def _iso(dt):
    return dt.isoformat() if dt else None


def testo_segnalazione(segnalazione):
    """Notification text for a new segnalazione, e.g. "Luca Rossi ha proposto…"."""
    template = TESTO_PER_TIPO.get(segnalazione.tipo, TESTO_PER_TIPO[TipoSegnalazione.FEATURE])
    return template.format(nome=segnalazione.autore.nome_completo)


def serialize_notifica(n):
    return {
        "id": n.pk,
        "testo": n.testo,
        # Il nome dell'autore va reso in grassetto nel testo della notifica.
        "autore": n.segnalazione.autore.nome_completo,
        "segnalazione_id": n.segnalazione_id,
        "tipo": n.segnalazione.tipo,
        "created_at": _iso(n.created_at),
    }


def notifica_nuova_segnalazione(segnalazione):
    """Create one unread notification per active user, except the author.

    Args:
        segnalazione: The freshly created Segnalazione instance.

    Returns:
        The list of created Notifica rows.
    """
    testo = testo_segnalazione(segnalazione)
    destinatari = User.objects.filter(is_active=True).exclude(pk=segnalazione.autore_id)
    return Notifica.objects.bulk_create(
        [Notifica(destinatario=u, segnalazione=segnalazione, testo=testo) for u in destinatari],
        ignore_conflicts=True,
    )


def _non_lette_qs(user):
    return (
        Notifica.objects.filter(destinatario=user, letta_il__isnull=True)
        .select_related("segnalazione", "segnalazione__autore")
        .order_by("-created_at", "-id")
    )


def list_notifiche(user):
    """Unread notifications for the user, newest first."""
    return [serialize_notifica(n) for n in _non_lette_qs(user)[:MAX_NOTIFICHE]]


def count_notifiche(user):
    return Notifica.objects.filter(destinatario=user, letta_il__isnull=True).count()


def segna_lette(user, ids=None):
    """Mark the user's notifications as read so they stop being shown.

    Args:
        user: Recipient whose notifications are marked.
        ids: Optional iterable of notification ids; all unread ones when omitted.

    Returns:
        Number of notifications marked as read.
    """
    qs = Notifica.objects.filter(destinatario=user, letta_il__isnull=True)
    if ids is not None:
        try:
            pks = [int(i) for i in ids]
        except (TypeError, ValueError) as exc:
            raise ValueError("Elenco notifiche non valido.") from exc
        if not pks:
            return 0
        qs = qs.filter(pk__in=pks)
    return qs.update(letta_il=timezone.now())
