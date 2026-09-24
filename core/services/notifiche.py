from django.utils import timezone

from ..models import Notifica, SegnalazioneCommento, TipoSegnalazione, User

MAX_NOTIFICHE = 50

TESTO_PER_TIPO = {
    TipoSegnalazione.FEATURE: "{nome} ha proposto una nuova feature",
    TipoSegnalazione.PROBLEMA: "{nome} ha evidenziato un problema",
}

TESTO_COMMENTO = "{nome} ha commentato «{titolo}»"
MAX_TITOLO_NOTIFICA = 120


def _iso(dt):
    return dt.isoformat() if dt else None


def testo_segnalazione(segnalazione):
    """Notification text for a new segnalazione, e.g. "Luca Rossi ha proposto…"."""
    template = TESTO_PER_TIPO.get(segnalazione.tipo, TESTO_PER_TIPO[TipoSegnalazione.FEATURE])
    return template.format(nome=segnalazione.autore.nome_completo)


def testo_commento(commento):
    """Notification text for a new comment, e.g. "Anna Bianchi ha commentato «Titolo»"."""
    titolo = commento.segnalazione.titolo
    if len(titolo) > MAX_TITOLO_NOTIFICA:
        titolo = titolo[: MAX_TITOLO_NOTIFICA - 1].rstrip() + "…"
    return TESTO_COMMENTO.format(nome=commento.autore.nome_completo, titolo=titolo)


def serialize_notifica(n):
    # Le notifiche create prima del campo "autore" ricadono sull'autore della segnalazione.
    autore = n.autore or n.segnalazione.autore
    return {
        "id": n.pk,
        "testo": n.testo,
        # Il nome dell'autore va reso in grassetto nel testo della notifica.
        "autore": autore.nome_completo,
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
        [
            Notifica(
                destinatario=u,
                segnalazione=segnalazione,
                autore=segnalazione.autore,
                testo=testo,
            )
            for u in destinatari
        ],
        ignore_conflicts=True,
    )


def notifica_nuovo_commento(commento):
    """Notify the thread author and everyone who commented on it, except the commenter.

    Args:
        commento: The freshly created SegnalazioneCommento instance.

    Returns:
        The list of Notifica rows created or refreshed.
    """
    segnalazione = commento.segnalazione
    partecipanti = set(
        SegnalazioneCommento.objects.filter(segnalazione=segnalazione).values_list(
            "autore_id", flat=True
        )
    )
    partecipanti.add(segnalazione.autore_id)
    partecipanti.discard(commento.autore_id)
    if not partecipanti:
        return []
    destinatari = User.objects.filter(is_active=True, pk__in=partecipanti)
    testo = testo_commento(commento)
    return [_upsert_notifica(u, segnalazione, commento.autore, testo) for u in destinatari]


def _upsert_notifica(destinatario, segnalazione, autore, testo):
    """Create the notification, or bring back the existing one for that thread.

    Il vincolo di unicità tiene una sola notifica per destinatario e segnalazione:
    quando ce n'è già una la si riporta a non letta con il testo aggiornato.
    """
    n, creata = Notifica.objects.get_or_create(
        destinatario=destinatario,
        segnalazione=segnalazione,
        defaults={"autore": autore, "testo": testo},
    )
    if not creata:
        n.autore = autore
        n.testo = testo
        n.letta_il = None
        n.created_at = timezone.now()
        n.save(update_fields=["autore", "testo", "letta_il", "created_at"])
    return n


def _non_lette_qs(user):
    return (
        Notifica.objects.filter(destinatario=user, letta_il__isnull=True)
        .select_related("autore", "segnalazione", "segnalazione__autore")
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
