"""Chiamate al servizio dell'assistente (``settings.AGENT_BASE_URL``).

L'agent è un servizio FastAPI separato che agisce per conto di un utente con
un ``ApiToken`` di Workflow (``Authorization: Token <chiave>``). Le pagine non
lo chiamano mai direttamente: passano dai proxy ``/agent/chat/`` e
``/agent/confirm/`` di ``core.views``, che tengono il token lato server.

Con ``urllib`` della libreria standard: nel progetto non ci sono ``requests``
né ``httpx`` e per due POST JSON non vale la pena aggiungerli.
"""

import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

TIMEOUT = 120  # secondi: una run dell'agent può durare parecchio


class AgentNonDisponibile(Exception):
    """L'agent non risponde (connessione rifiutata, timeout) o non risponde JSON."""


def chiama_agent(path, body, chiave):
    """POST ``body`` (dict) a ``AGENT_BASE_URL + path`` col token: ``(status, json)``.

    Gli errori HTTP dell'agent (400, 401, 404, 409…) non sono eccezioni: tornano
    come status e JSON, perché il proxy li inoltra al browser così come sono.
    Solleva ``AgentNonDisponibile`` se l'agent non è raggiungibile o la risposta
    non è JSON.
    """
    url = settings.AGENT_BASE_URL + path
    req = Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Token {chiave}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=TIMEOUT) as res:
            status, raw = res.status, res.read()
    except HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("Agent non raggiungibile su %s: %s", url, exc)
        raise AgentNonDisponibile(str(exc)) from exc
    try:
        return status, json.loads(raw)
    except ValueError as exc:
        logger.warning("Risposta non JSON dall'agent (%s %s): %r", status, url, raw[:200])
        raise AgentNonDisponibile("risposta non JSON") from exc
