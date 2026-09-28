from functools import wraps

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect

from .models import Permesso


def user_can_write(user):
    return user.is_authenticated and user.permesso in (Permesso.ADMIN, Permesso.WRITING)


# Trasmittal interno: scrittura riservata a chi ha il flag User.trasmittal_interno_writer
# (impostabile da Django admin), indipendentemente dal permesso generale — tutti gli
# altri possono solo visualizzare la sezione.
def user_can_write_trasmittal_interno(user):
    return user.is_authenticated and user.trasmittal_interno_writer


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
                {"error": "Permesso negato: solo alcuni utenti possono modificare il trasmittal interno."},
                status=403,
            )
        return view_func(request, *args, **kwargs)

    return wrapper


def write_required(view_func):
    """Decorator that blocks HTML views for users without write permission."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not user_can_write(request.user):
            messages.error(request, "Non hai i permessi per eseguire questa operazione.")
            return redirect("home")
        return view_func(request, *args, **kwargs)

    return wrapper
