from functools import wraps

from django.http import JsonResponse

from .models import Permesso

# Utenti di servizio: account con cui un servizio esterno (es. l'ingestion di
# workflow-agent) chiama le API col token, senza agire per conto di una persona.
# Si riconoscono dal gruppo Django, creato dalla migration 0061_gruppo_servizio.
GRUPPO_SERVIZIO = "Servizio"


def is_service_user(user) -> bool:
    """Utente di servizio: nel gruppo "Servizio".

    Non scrive, non fa login via sessione e può avere un token senza scadenza
    (vedi ``ApiToken.is_valid``).
    """
    return user.is_authenticated and user.groups.filter(name=GRUPPO_SERVIZIO).exists()


# Un utente di servizio non scrive, qualunque sia il suo permesso: il controllo
# sul gruppo resta per ultimo, così costa una query solo a chi scriverebbe.
def user_can_write(user):
    return (
        user.is_authenticated
        and user.permesso in (Permesso.ADMIN, Permesso.WRITING)
        and not is_service_user(user)
    )


# Trasmittal interno: scrittura riservata a chi ha il flag User.trasmittal_interno_writer
# (impostabile da Django admin), indipendentemente dal permesso generale — tutti gli
# altri possono solo visualizzare la sezione. Anche qui un utente di servizio non scrive.
def user_can_write_trasmittal_interno(user):
    return user.is_authenticated and user.trasmittal_interno_writer and not is_service_user(user)


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def api_write_required(view_func):
    """Decorator that returns 403 JSON for write requests without write permission."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method not in _SAFE_METHODS and not user_can_write(request.user):
            return JsonResponse({"error": "Permesso negato."}, status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def trasmittal_interno_write_required(view_func):
    """Decorator that returns 403 JSON for write requests without trasmittal interno permission."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if request.method not in _SAFE_METHODS and not user_can_write_trasmittal_interno(
            request.user
        ):
            return JsonResponse(
                {
                    "error": "Permesso negato: solo alcuni utenti possono modificare il trasmittal interno."
                },
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapper
