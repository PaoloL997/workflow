"""Autenticazione delle API con un token legato all'utente (``ApiToken``).

Un servizio esterno che agisce per conto di un utente manda l'header
``Authorization: Token <chiave>``: la richiesta vale come fatta da
quell'utente, con i suoi permessi (``api_write_required`` e gli altri
controlli guardano ``request.user``). Senza l'header resta la sessione.

CSRF: il controllo protegge i cookie, che il browser allega da solo anche a
una richiesta partita da un altro sito. Un header ``Authorization`` invece lo
mette solo chi conosce la chiave (un sito terzo non può aggiungerlo senza
CORS, che qui non c'è), quindi per le richieste col token il controllo non
serve, e un client che non è un browser non avrebbe comunque un cookie CSRF
da rimandare.

Le viste con ``api_login_required`` sono ``csrf_exempt`` e il controllo lo
rifà ``autentica_api``, con lo stesso codice di ``CsrfViewMiddleware``, per
ogni richiesta senza token: per la sessione esito e risposta 403 restano
quelli di prima. Preferito a un middleware che spegne il controllo con
``request._dont_enforce_csrf_checks`` perché resta confinato alle viste che
accettano il token (un middleware lo spegnerebbe su qualsiasi vista, anche
dove il token non autentica nessuno) e non tocca ``MIDDLEWARE`` né attributi
privati di Django pensati per i test.
"""

from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils import timezone

from .models import ApiToken


def chiave_dall_header(request):
    """La chiave dell'header ``Authorization: Token <chiave>``.

    ``None`` se l'header manca o usa un altro schema: la richiesta resta
    sulla sessione. Stringa vuota se c'è ``Token`` ma senza una chiave ben
    formata, così che valga come token non valido.
    """
    parti = request.headers.get("Authorization", "").split()
    if not parti or parti[0].lower() != "token":
        return None
    return parti[1] if len(parti) == 2 else ""


def token_valido(chiave):
    """L'``ApiToken`` valido con questa chiave in chiaro, o ``None``."""
    if not chiave:
        return None
    token = ApiToken.objects.select_related("user").filter(key=ApiToken.hash_chiave(chiave)).first()
    if token is None or not token.is_valid():
        return None
    return token


def _rifiuto_csrf(request):
    """La risposta 403 che darebbe ``CsrfViewMiddleware``, o ``None`` se la richiesta passa."""
    return CsrfViewMiddleware(lambda request: None).process_view(request, None, (), {})


def autentica_api(request):
    """Autentica una richiesta alle API; la risposta di errore da dare, o ``None``.

    Con l'header ``Token``: se il token è valido ``request.user`` diventa il
    suo utente e ``request.api_token`` il token, altrimenti 401. Senza: la
    sessione, col controllo CSRF di sempre. Resta al chiamante verificare che
    ci sia un utente autenticato.
    """
    chiave = chiave_dall_header(request)
    if chiave is None:
        return _rifiuto_csrf(request)
    token = token_valido(chiave)
    if token is None:
        return JsonResponse({"error": "Token non valido."}, status=401)
    token.last_used_at = timezone.now()
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=token.last_used_at)
    request.user = token.user
    request.api_token = token
    return None
