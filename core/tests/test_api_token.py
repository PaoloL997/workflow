import hashlib
import json
from datetime import datetime, timedelta

from django.conf import settings
from django.test import Client, TestCase
from django.utils import timezone
from django.utils.crypto import get_random_string

from ..models import ApiToken, Permesso, StatoEsterno
from ._fixtures import User

URL_TOKEN = "/api/agent/token/"
URL_ME = "/api/agent/me/"
URL_STATI = "/api/stati-esterni/"


def _token(chiave):
    return {"Authorization": f"Token {chiave}"}


def _nuovo_stato(client, nome="Stato via API", **kwargs):
    return client.post(
        URL_STATI,
        data=json.dumps({"nome": nome, "lettera": "Z"}),
        content_type="application/json",
        **kwargs,
    )


class EmissioneTokenTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("agente", "agente@example.com", "pw")

    def test_con_sessione_emette_il_token(self):
        self.client.force_login(self.user)
        prima = timezone.now()
        res = self.client.post(URL_TOKEN)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(len(data["token"]), 40)
        scadenza = datetime.fromisoformat(data["expires_at"])
        self.assertGreaterEqual(scadenza, prima + timedelta(seconds=settings.SESSION_COOKIE_AGE))
        self.assertLess(scadenza, prima + timedelta(seconds=settings.SESSION_COOKIE_AGE + 60))
        self.assertEqual(self.user.api_tokens.count(), 1)

    def test_senza_sessione_401(self):
        res = self.client.post(URL_TOKEN)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Non autenticato.")
        self.assertFalse(ApiToken.objects.exists())

    def test_un_token_non_ne_emette_un_altro(self):
        _, chiave = ApiToken.crea_per_utente(self.user)
        res = self.client.post(URL_TOKEN, headers=_token(chiave))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(ApiToken.objects.count(), 1)

    def test_emissione_richiede_il_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        res = client.post(URL_TOKEN)
        self.assertEqual(res.status_code, 403)
        self.assertFalse(ApiToken.objects.exists())

    def test_nel_db_resta_solo_l_hash_della_chiave(self):
        self.client.force_login(self.user)
        chiave = self.client.post(URL_TOKEN).json()["token"]
        token = ApiToken.objects.get()
        self.assertEqual(token.key, hashlib.sha256(chiave.encode()).hexdigest())
        self.assertNotEqual(token.key, chiave)
        self.assertFalse(ApiToken.objects.filter(key=chiave).exists())

    def test_piu_token_attivi_insieme(self):
        self.client.force_login(self.user)
        chiavi = [self.client.post(URL_TOKEN).json()["token"] for _ in range(2)]
        anonimo = Client()
        for chiave in chiavi:
            self.assertEqual(anonimo.get(URL_STATI, headers=_token(chiave)).status_code, 200)

    def test_alla_creazione_spariscono_i_token_scaduti(self):
        altro = User.objects.create_user("altro", "altro@example.com", "pw")
        scaduto, _ = ApiToken.crea_per_utente(altro)
        ApiToken.objects.filter(pk=scaduto.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        ancora_valido, _ = ApiToken.crea_per_utente(altro)
        self.client.force_login(self.user)
        self.client.post(URL_TOKEN)
        self.assertFalse(ApiToken.objects.filter(pk=scaduto.pk).exists())
        self.assertTrue(ApiToken.objects.filter(pk=ancora_valido.pk).exists())


class AutenticazioneTokenTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("agente", "agente@example.com", "pw")
        self.token, self.chiave = ApiToken.crea_per_utente(self.user)

    def test_get_con_token_valido(self):
        res = self.client.get(URL_STATI, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 200)
        self.assertIn("stati", res.json())

    def test_l_uso_aggiorna_last_used_at(self):
        self.assertIsNone(self.token.last_used_at)
        self.client.get(URL_STATI, headers=_token(self.chiave))
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_token_scaduto_401(self):
        ApiToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        res = self.client.get(URL_STATI, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Token non valido.")

    def test_chiave_inesistente_401(self):
        res = self.client.get(URL_STATI, headers=_token("chiave-che-non-esiste"))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Token non valido.")

    def test_header_token_senza_chiave_401(self):
        res = self.client.get(URL_STATI, headers={"Authorization": "Token"})
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Token non valido.")

    def test_utente_disattivato_401(self):
        self.user.is_active = False
        self.user.save()
        res = self.client.get(URL_STATI, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Token non valido.")

    def test_senza_header_e_senza_sessione_401_come_prima(self):
        res = self.client.get(URL_STATI)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Non autenticato.")

    def test_un_token_non_valido_non_ricade_sulla_sessione(self):
        self.client.force_login(self.user)
        res = self.client.get(URL_STATI, headers=_token("chiave-che-non-esiste"))
        self.assertEqual(res.status_code, 401)


class CsrfTokenTests(TestCase):
    """Il CSRF vale per la sessione come prima, non per le richieste col token."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.user = User.objects.create_user(
            "agente", "agente@example.com", "pw", permesso=Permesso.WRITING
        )

    def test_post_col_token_senza_csrf_passa(self):
        _, chiave = ApiToken.crea_per_utente(self.user)
        res = _nuovo_stato(self.client, headers=_token(chiave))
        self.assertEqual(res.status_code, 201)
        self.assertTrue(StatoEsterno.objects.filter(nome="Stato via API").exists())

    def test_post_con_sessione_senza_csrf_403(self):
        self.client.force_login(self.user)
        res = _nuovo_stato(self.client)
        self.assertEqual(res.status_code, 403)
        # La pagina di errore CSRF di Django, non il 403 JSON dei permessi.
        self.assertTrue(res["Content-Type"].startswith("text/html"))
        self.assertFalse(StatoEsterno.objects.filter(nome="Stato via API").exists())

    def test_post_con_sessione_e_csrf_passa(self):
        self.client.force_login(self.user)
        segreto = get_random_string(32)
        self.client.cookies[settings.CSRF_COOKIE_NAME] = segreto
        res = _nuovo_stato(self.client, headers={"X-CSRFToken": segreto})
        self.assertEqual(res.status_code, 201)


class PermessiTokenTests(TestCase):
    """Col token valgono gli stessi permessi dell'utente che con la sessione."""

    def test_utente_in_sola_lettura_stesso_esito_della_sessione(self):
        lettore = User.objects.create_user(
            "lettore", "lettore@example.com", "pw", permesso=Permesso.READING
        )
        _, chiave = ApiToken.crea_per_utente(lettore)
        col_token = _nuovo_stato(Client(), headers=_token(chiave))

        client = Client()
        client.force_login(lettore)
        con_sessione = _nuovo_stato(client)

        self.assertEqual(col_token.status_code, 403)
        self.assertEqual(col_token.status_code, con_sessione.status_code)
        self.assertEqual(col_token.json(), con_sessione.json())
        self.assertFalse(StatoEsterno.objects.exists())


class RevocaTokenTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("agente", "agente@example.com", "pw")
        self.client.force_login(self.user)

    def test_revoca_disattiva_tutti_i_token_dell_utente(self):
        chiavi = [self.client.post(URL_TOKEN).json()["token"] for _ in range(2)]
        res = self.client.delete(URL_TOKEN)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["revocati"], 2)
        anonimo = Client()
        for chiave in chiavi:
            self.assertEqual(anonimo.get(URL_STATI, headers=_token(chiave)).status_code, 401)

    def test_revoca_non_tocca_i_token_degli_altri(self):
        altro = User.objects.create_user("altro", "altro@example.com", "pw")
        _, chiave_altro = ApiToken.crea_per_utente(altro)
        self.client.delete(URL_TOKEN)
        res = Client().get(URL_STATI, headers=_token(chiave_altro))
        self.assertEqual(res.status_code, 200)

    def test_revoca_senza_sessione_401(self):
        _, chiave = ApiToken.crea_per_utente(self.user)
        res = Client().delete(URL_TOKEN, headers=_token(chiave))
        self.assertEqual(res.status_code, 401)
        self.assertTrue(ApiToken.objects.exists())


class AgentMeTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "agente",
            "agente@example.com",
            "pw",
            first_name="Mario",
            last_name="Rossi",
            permesso=Permesso.WRITING,
        )
        self.token, self.chiave = ApiToken.crea_per_utente(self.user)

    def test_con_token_valido(self):
        res = self.client.get(URL_ME, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res.json(), {"username": "agente", "full_name": "Mario Rossi", "can_write": True}
        )

    def test_can_write_segue_il_permesso_dell_utente(self):
        lettore = User.objects.create_user(
            "lettore", "lettore@example.com", "pw", permesso=Permesso.READING
        )
        _, chiave = ApiToken.crea_per_utente(lettore)
        res = self.client.get(URL_ME, headers=_token(chiave))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["username"], "lettore")
        self.assertIs(res.json()["can_write"], False)
        # Stesso esito di api_write_required: lo stesso utente non può scrivere.
        self.assertEqual(_nuovo_stato(Client(), headers=_token(chiave)).status_code, 403)

    def test_con_sessione(self):
        self.client.force_login(self.user)
        res = self.client.get(URL_ME)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["username"], "agente")

    def test_senza_autenticazione_401(self):
        res = self.client.get(URL_ME)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Non autenticato.")

    def test_token_scaduto_401(self):
        ApiToken.objects.filter(pk=self.token.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        res = self.client.get(URL_ME, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["error"], "Token non valido.")

    def test_solo_get(self):
        res = self.client.post(URL_ME, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 405)


class ApiTokenAdminTests(TestCase):
    def test_la_chiave_non_compare_nell_admin(self):
        admin_user = User.objects.create_superuser("root", "root@example.com", "pw")
        token, chiave = ApiToken.crea_per_utente(admin_user)
        self.client.force_login(admin_user)
        for url in ("/admin/core/apitoken/", f"/admin/core/apitoken/{token.pk}/change/"):
            res = self.client.get(url)
            self.assertEqual(res.status_code, 200)
            self.assertNotContains(res, chiave)
            self.assertNotContains(res, token.key)
