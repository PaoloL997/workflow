import io
import json
from datetime import timedelta
from unittest import mock
from urllib.error import HTTPError, URLError

from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ..models import ApiToken, Permesso, Testata
from ..views import AGENT_TOKEN_SESSION_KEY
from ._fixtures import User

TOGGLE = "core/partials/agent_toggle.html"
PANEL = "core/partials/agent_panel.html"

URL_CHAT = "/agent/chat/"
URL_CONFIRM = "/agent/confirm/"
AGENT = "http://agent.test"


class AgentWidgetTemplateTests(TestCase):
    """Pulsante e pannello di Workflow Agent: accanto al pulsante del tema, solo dopo il login."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "agent_reader", "agent-reader@example.com", "pw", permesso=Permesso.READING
        )

    def _assert_widget(self, res):
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, TOGGLE)
        self.assertTemplateUsed(res, PANEL)
        self.assertContains(res, 'id="agent-toggle-btn"', count=1)
        self.assertContains(res, 'aria-label="Apri Workflow Agent"')
        self.assertContains(res, 'id="agent-panel"', count=1)
        self.assertContains(res, "core/agent_widget.css")
        self.assertContains(res, "core/agent_widget.js")
        self.assertContains(res, 'id="agent-panel-info"', count=1)
        self.assertContains(res, 'id="agent-info-backdrop"', count=1)
        self.assertContains(res, 'id="agent-panel-new"', count=1)
        # Campo e Invia attivi: la chat c'è
        self.assertContains(res, 'id="agent-input"', count=1)
        self.assertContains(res, 'id="agent-send"', count=1)
        self.assertNotContains(res, 'id="agent-send" disabled')
        self.assertNotRegex(res.content.decode(), r'id="agent-input"[^>]*\bdisabled\b')

    def test_pagina_col_toggle_del_tema_ha_pulsante_e_pannello(self):
        self.client.force_login(self.user)
        res = self.client.get("/segnalazioni/")

        self.assertTemplateUsed(res, "core/partials/theme_toggle.html")
        self._assert_widget(res)

    def test_home_ha_pulsante_e_pannello(self):
        self.client.force_login(self.user)

        self._assert_widget(self.client.get("/"))

    def test_login_anonimo_non_ha_pulsante_ne_pannello(self):
        res = self.client.get("/login/")

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "core/partials/theme_toggle.html")
        self.assertTemplateNotUsed(res, TOGGLE)
        self.assertTemplateNotUsed(res, PANEL)
        self.assertNotContains(res, 'id="agent-toggle-btn"')
        self.assertNotContains(res, 'id="agent-panel"')
        self.assertNotContains(res, "agent_widget.css")
        self.assertNotContains(res, "agent_widget.js")

    def test_reset_password_non_ha_il_pulsante_anche_dopo_il_login(self):
        self.client.force_login(self.user)
        res = self.client.get("/password-reset/")

        self.assertEqual(res.status_code, 200)
        self.assertTemplateNotUsed(res, TOGGLE)
        self.assertNotContains(res, 'id="agent-toggle-btn"')

    def test_pagina_di_commessa_passa_il_job_al_pannello(self):
        Testata.objects.create(job="25056")
        self.client.force_login(self.user)
        res = self.client.get("/commesse/25056/")

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="agent-panel"', count=1)
        self.assertRegex(res.content.decode(), r'id="agent-panel"[^>]*data-job="25056"')

    def test_fuori_dalla_commessa_il_pannello_non_ha_il_job(self):
        self.client.force_login(self.user)
        res = self.client.get("/")

        self.assertContains(res, 'id="agent-panel"', count=1)
        self.assertNotRegex(res.content.decode(), r'id="agent-panel"[^>]*data-job')

    def test_scheda_informazioni_divisa_per_permesso(self):
        self.client.force_login(self.user)
        res = self.client.get("/")

        self.assertContains(
            res,
            "<h3 class='agent-info-title' id='agent-info-title'>Informazioni sull'agent</h3>",
            html=True,
        )
        self.assertContains(res, "Utente standard")
        self.assertContains(res, "Utente con permesso di scrittura (PM / Document Controller)")
        # Non promette più una ricerca che l'agent non sa fare.
        self.assertNotContains(res, "Cercare commesse, documenti e revisioni")


# ── Proxy verso l'agent ──────────────────────────────────────────────────────


class FakeAgent:
    """Rimpiazza ``urlopen`` in ``core.services.agent``: registra le richieste e risponde a copione.

    ``risposte`` è una lista di ``(status, dict)`` consumata in ordine, oppure
    di eccezioni da sollevare (agent non raggiungibile). Gli status di errore
    arrivano come ``HTTPError``, come fa ``urllib``.
    """

    def __init__(self, *risposte):
        self.risposte = list(risposte)
        self.richieste = []  # (Request, timeout)

    def __call__(self, req, timeout=None):
        self.richieste.append((req, timeout))
        risposta = self.risposte.pop(0)
        if isinstance(risposta, BaseException):
            raise risposta
        status, payload = risposta
        raw = json.dumps(payload).encode()
        if status >= 400:
            raise HTTPError(req.full_url, status, "error", {}, io.BytesIO(raw))
        return _Risposta(status, raw)

    @property
    def ultima(self):
        return self.richieste[-1][0]

    def body(self, i=-1):
        return json.loads(self.richieste[i][0].data)

    def chiave(self, i=-1):
        schema, chiave = self.richieste[i][0].get_header("Authorization").split()
        assert schema == "Token"
        return chiave


class _Risposta:
    def __init__(self, status, raw):
        self.status = status
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(conversation_id="c1", reply="Ciao!", pending=None):
    return 200, {"conversation_id": conversation_id, "reply": reply, "pending": pending or []}


@override_settings(AGENT_BASE_URL=AGENT)
class AgentProxyTests(TestCase):
    """``/agent/chat/`` e ``/agent/confirm/``: sessione + CSRF, token lato server, agent simulato."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "agent_user", "agent-user@example.com", "pw", permesso=Permesso.READING
        )
        self.client.force_login(self.user)

    def _agent(self, *risposte):
        """L'agent simulato al posto di ``urlopen``, fino alla fine del test."""
        fake = FakeAgent(*risposte)
        patcher = mock.patch("core.services.agent.urlopen", fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def _post(self, url, body, **kwargs):
        return self.client.post(
            url, data=json.dumps(body), content_type="application/json", **kwargs
        )

    def _token_di(self, chiave):
        return ApiToken.objects.get(key=ApiToken.hash_chiave(chiave))

    def test_chat_inoltra_body_e_token_dell_utente(self):
        fake = self._agent(_ok(reply="Eccomi"))
        body = {"message": "ciao", "context": {"job": "25056"}}

        res = self._post(URL_CHAT, body)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), {"conversation_id": "c1", "reply": "Eccomi", "pending": []})
        req, timeout = fake.richieste[0]
        self.assertEqual(req.full_url, f"{AGENT}/chat")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(timeout, 120)
        self.assertEqual(fake.body(), body)
        self.assertEqual(req.get_header("Content-type"), "application/json")
        token = self._token_di(fake.chiave())
        self.assertEqual(token.user, self.user)
        self.assertTrue(token.is_valid())

    def test_confirm_inoltra_a_confirm(self):
        fake = self._agent(_ok(reply="Fatto"))
        body = {"conversation_id": "c1", "approvals": {"t1": True, "t2": False}}

        res = self._post(URL_CONFIRM, body)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(fake.ultima.full_url, f"{AGENT}/confirm")
        self.assertEqual(fake.body(), body)
        self.assertEqual(self._token_di(fake.chiave()).user, self.user)

    def test_il_token_non_arriva_al_browser(self):
        fake = self._agent(_ok())

        res = self._post(URL_CHAT, {"message": "ciao"})

        self.assertNotIn(fake.chiave(), res.content.decode())
        self.assertNotIn(fake.chiave(), str(res.cookies))

    def test_riusa_il_token_in_sessione_finche_e_valido(self):
        fake = self._agent(_ok(), _ok())

        self._post(URL_CHAT, {"message": "uno"})
        self._post(URL_CONFIRM, {"conversation_id": "c1", "approvals": {}})

        self.assertEqual(fake.chiave(0), fake.chiave(1))
        self.assertEqual(self.user.api_tokens.count(), 1)
        self.assertEqual(self.client.session[AGENT_TOKEN_SESSION_KEY], fake.chiave())

    def test_token_in_sessione_scaduto_ne_emette_uno_nuovo(self):
        fake = self._agent(_ok(), _ok())
        self._post(URL_CHAT, {"message": "uno"})
        ApiToken.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        self._post(URL_CHAT, {"message": "due"})

        self.assertNotEqual(fake.chiave(0), fake.chiave(1))
        self.assertTrue(self._token_di(fake.chiave(1)).is_valid())

    def test_token_in_sessione_di_un_altro_utente_non_viene_usato(self):
        altro = User.objects.create_user("altro", "altro@example.com", "pw")
        _, chiave_altro = ApiToken.crea_per_utente(altro)
        session = self.client.session
        session[AGENT_TOKEN_SESSION_KEY] = chiave_altro
        session.save()
        fake = self._agent(_ok())

        self._post(URL_CHAT, {"message": "ciao"})

        self.assertNotEqual(fake.chiave(), chiave_altro)
        self.assertEqual(self._token_di(fake.chiave()).user, self.user)

    def test_401_dell_agent_ritenta_una_volta_con_token_nuovo(self):
        fake = self._agent((401, {"detail": "Token non valido"}), _ok(reply="Ora sì"))

        res = self._post(URL_CHAT, {"message": "ciao"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["reply"], "Ora sì")
        self.assertEqual(len(fake.richieste), 2)
        self.assertNotEqual(fake.chiave(0), fake.chiave(1))
        self.assertEqual(fake.body(0), fake.body(1))
        self.assertEqual(self.client.session[AGENT_TOKEN_SESSION_KEY], fake.chiave(1))
        self.assertEqual(self._token_di(fake.chiave(1)).user, self.user)

    def test_401_anche_al_secondo_tentativo_viene_propagato(self):
        fake = self._agent((401, {"detail": "Token non valido"}), (401, {"detail": "Ancora no"}))

        res = self._post(URL_CHAT, {"message": "ciao"})

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json(), {"detail": "Ancora no"})
        self.assertEqual(len(fake.richieste), 2)

    def test_errori_dell_agent_tornano_con_lo_stesso_status_e_json(self):
        casi = [
            (400, {"detail": "Body non valido", "expected": "message", "received": "msg"}),
            (404, {"detail": "Conversazione non trovata"}),
            (409, {"detail": "Nessuna azione pending"}),
            (500, {"detail": "Errore interno"}),
        ]
        for status, payload in casi:
            with self.subTest(status=status):
                self._agent((status, payload))
                res = self._post(URL_CHAT, {"message": "ciao"})
                self.assertEqual(res.status_code, status)
                self.assertEqual(res.json(), payload)

    def test_agent_non_raggiungibile_503(self):
        for errore in (URLError("connection refused"), TimeoutError("timed out")):
            with self.subTest(errore=type(errore).__name__):
                self._agent(errore)
                res = self._post(URL_CHAT, {"message": "ciao"})
                self.assertEqual(res.status_code, 503)
                self.assertEqual(res.json(), {"error": "Assistente non disponibile."})

    def test_risposta_non_json_dell_agent_503(self):
        def html(req, timeout=None):
            return _Risposta(200, b"<html>")

        with mock.patch("core.services.agent.urlopen", html):
            res = self._post(URL_CHAT, {"message": "ciao"})

        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json(), {"error": "Assistente non disponibile."})

    def test_anonimo_401_senza_chiamare_l_agent(self):
        fake = self._agent(_ok())
        self.client.logout()

        res = self._post(URL_CHAT, {"message": "ciao"})

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json(), {"error": "Non autenticato."})
        self.assertEqual(fake.richieste, [])
        self.assertFalse(ApiToken.objects.exists())

    def test_richiede_il_csrf(self):
        fake = self._agent(_ok())
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        res = client.post(
            URL_CHAT, data=json.dumps({"message": "ciao"}), content_type="application/json"
        )

        self.assertEqual(res.status_code, 403)
        self.assertEqual(fake.richieste, [])

    def test_solo_post(self):
        fake = self._agent(_ok())

        self.assertEqual(self.client.get(URL_CHAT).status_code, 405)
        self.assertEqual(self.client.get(URL_CONFIRM).status_code, 405)
        self.assertEqual(fake.richieste, [])

    def test_body_non_json_400(self):
        fake = self._agent(_ok())

        res = self.client.post(URL_CHAT, data="non json", content_type="application/json")

        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.json(), {"error": "Body JSON non valido."})
        self.assertEqual(fake.richieste, [])
