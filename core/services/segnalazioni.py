from django.db.models import Case, Count, IntegerField, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone

from ..models import (
    Segnalazione,
    SegnalazioneCommento,
    SegnalazioneVoto,
    StatoSegnalazione,
    TipoSegnalazione,
)
from .notifiche import notifica_nuova_segnalazione

TIPO_VALUES = {c.value for c in TipoSegnalazione}
STATO_VALUES = {c.value for c in StatoSegnalazione}
MAX_TITOLO = 200
MAX_TESTO = 8000
MAX_COMMENTO = 2000
MAX_TOP = 50


class SegnalazioneClosed(ValueError):
    """Raised when a mutation is not allowed on a closed thread."""


class SegnalazioneForbidden(PermissionError):
    """Raised when the user is not allowed to close or reopen a thread."""


def _iso(dt):
    return dt.isoformat() if dt else None


def _nome(user):
    if user is None:
        return None
    return user.nome_completo


def _iniziale(user):
    if user is None:
        return "?"
    src = (user.first_name or user.username or "?").strip()
    return src[:1].upper()


def _avatar_url(user):
    if user is None or not getattr(user, "avatar", None):
        return None
    try:
        return user.avatar.url
    except ValueError:
        return None


def serialize_commento(c):
    return {
        "id": c.pk,
        "autore_nome": _nome(c.autore),
        "testo": c.testo,
        "created_at": _iso(c.created_at),
    }


def serialize_segnalazione(s, *, mio_voto=0, up=None, down=None, score=None, commenti=None):
    if up is None or down is None or score is None:
        valori = list(s.voti.values_list("valore", flat=True))
        up = sum(1 for v in valori if v == 1)
        down = sum(1 for v in valori if v == -1)
        score = sum(valori)
    if commenti is None:
        commenti = [
            serialize_commento(c)
            for c in s.commenti.select_related("autore").order_by("created_at")
        ]
    return {
        "id": s.pk,
        "tipo": s.tipo,
        "titolo": s.titolo,
        "testo": s.testo,
        "stato": s.stato,
        "autore_nome": _nome(s.autore),
        "autore_iniziale": _iniziale(s.autore),
        "autore_avatar": _avatar_url(s.autore),
        "created_at": _iso(s.created_at),
        "chiuso_da_nome": _nome(s.chiuso_da) if s.stato == StatoSegnalazione.CHIUSO else None,
        "chiuso_il": _iso(s.chiuso_il) if s.stato == StatoSegnalazione.CHIUSO else None,
        "up": up,
        "down": down,
        "score": score,
        "mio_voto": mio_voto or 0,
        "commenti": commenti,
    }


def _commenti_prefetch():
    return Prefetch(
        "commenti",
        queryset=SegnalazioneCommento.objects.select_related("autore").order_by("created_at"),
    )


def _annotated_qs():
    return (
        Segnalazione.objects.select_related("autore", "chiuso_da")
        .prefetch_related(_commenti_prefetch())
        .annotate(
            score=Coalesce(Sum("voti__valore"), Value(0), output_field=IntegerField()),
            up=Count("voti", filter=Q(voti__valore=1)),
            down=Count("voti", filter=Q(voti__valore=-1)),
            is_closed=Case(
                When(stato=StatoSegnalazione.CHIUSO, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
    )


def _miei_voti(user, ids):
    if not ids:
        return {}
    return dict(
        SegnalazioneVoto.objects.filter(utente=user, segnalazione_id__in=ids).values_list(
            "segnalazione_id", "valore"
        )
    )


def _serialize_annotated(s, miei):
    return serialize_segnalazione(
        s,
        mio_voto=miei.get(s.pk, 0),
        up=s.up,
        down=s.down,
        score=s.score,
        commenti=[serialize_commento(c) for c in s.commenti.all()],
    )


def get_segnalazione(pk, user):
    s = _annotated_qs().get(pk=pk)
    miei = _miei_voti(user, [s.pk])
    return _serialize_annotated(s, miei)


def list_segnalazioni(user, tipo=None, stato=None, mine=False, top=None):
    qs = _annotated_qs()
    if tipo:
        if tipo not in TIPO_VALUES:
            raise ValueError("Tipo non valido.")
        qs = qs.filter(tipo=tipo)
    if stato:
        if stato not in STATO_VALUES:
            raise ValueError("Stato non valido.")
        qs = qs.filter(stato=stato)
    if mine:
        qs = qs.filter(autore=user)
    if top is not None:
        try:
            top = int(top)
        except (TypeError, ValueError) as exc:
            raise ValueError("Parametro top non valido.") from exc
        if top <= 0 or top > MAX_TOP:
            raise ValueError("Parametro top non valido.")
        rows = list(qs.order_by("-score", "-created_at")[:top])
    else:
        # Elenco cronologico: le più recenti in cima, le chiuse in fondo.
        # Per le più votate c'è già il filtro "Top 10 per voti".
        rows = list(qs.order_by("is_closed", "-created_at", "-id"))
    miei = _miei_voti(user, [s.pk for s in rows])
    return [_serialize_annotated(s, miei) for s in rows]


def create_segnalazione(user, tipo, titolo, testo):
    tipo = (tipo or "").strip()
    titolo = (titolo or "").strip()
    testo = (testo or "").strip()
    if tipo not in TIPO_VALUES:
        raise ValueError("Scegli se è una feature o un problema.")
    if not titolo:
        raise ValueError("Il titolo è obbligatorio.")
    if len(titolo) > MAX_TITOLO:
        raise ValueError(f"Il titolo può avere al massimo {MAX_TITOLO} caratteri.")
    if not testo:
        raise ValueError("La descrizione è obbligatoria.")
    if len(testo) > MAX_TESTO:
        raise ValueError(f"La descrizione può avere al massimo {MAX_TESTO} caratteri.")
    s = Segnalazione.objects.create(autore=user, tipo=tipo, titolo=titolo, testo=testo)
    notifica_nuova_segnalazione(s)
    return get_segnalazione(s.pk, user)


def set_voto(user, pk, valore):
    try:
        valore = int(valore)
    except (TypeError, ValueError) as exc:
        raise ValueError("Valore voto non valido.") from exc
    if valore not in (-1, 0, 1):
        raise ValueError("Valore voto non valido.")
    s = Segnalazione.objects.get(pk=pk)
    if valore == 0:
        SegnalazioneVoto.objects.filter(segnalazione=s, utente=user).delete()
    else:
        SegnalazioneVoto.objects.update_or_create(
            segnalazione=s,
            utente=user,
            defaults={"valore": valore},
        )
    return get_segnalazione(s.pk, user)


def create_commento(user, pk, testo):
    testo = (testo or "").strip()
    if not testo:
        raise ValueError("Il commento non può essere vuoto.")
    if len(testo) > MAX_COMMENTO:
        raise ValueError(f"Il commento può avere al massimo {MAX_COMMENTO} caratteri.")
    s = Segnalazione.objects.get(pk=pk)
    if s.stato == StatoSegnalazione.CHIUSO:
        raise SegnalazioneClosed("Il thread è chiuso.")
    SegnalazioneCommento.objects.create(segnalazione=s, autore=user, testo=testo)
    return get_segnalazione(s.pk, user)


def chiudi_segnalazione(user, pk):
    if not user.is_app_admin:
        raise SegnalazioneForbidden("Permesso negato.")
    s = Segnalazione.objects.select_related("autore", "chiuso_da").get(pk=pk)
    if s.stato != StatoSegnalazione.CHIUSO:
        s.stato = StatoSegnalazione.CHIUSO
        s.chiuso_da = user
        s.chiuso_il = timezone.now()
        s.save(update_fields=["stato", "chiuso_da", "chiuso_il"])
    return get_segnalazione(s.pk, user)


def riapri_segnalazione(user, pk):
    if not user.is_app_admin:
        raise SegnalazioneForbidden("Permesso negato.")
    s = Segnalazione.objects.select_related("autore", "chiuso_da").get(pk=pk)
    if s.stato != StatoSegnalazione.APERTO:
        s.stato = StatoSegnalazione.APERTO
        s.chiuso_da = None
        s.chiuso_il = None
        s.save(update_fields=["stato", "chiuso_da", "chiuso_il"])
    return get_segnalazione(s.pk, user)
