import hashlib
import json
import tempfile
from datetime import date, datetime, timedelta
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group
from django.core.management import CommandError, call_command
from django.test import Client, TestCase, override_settings
from django.utils import timezone
from django.utils.crypto import get_random_string

from ..models import ApiToken, Documento, Permesso, Revisione, StatoEsterno, Testata
from ..permissions import (
    GRUPPO_SERVIZIO,
    is_service_user,
    user_can_write,
    user_can_write_trasmittal_interno,
)
from ._fixtures import User

URL_TOKEN = "/api/agent/token/"
URL_ME = "/api/agent/me/"
URL_STATI = "/api/stati-esterni/"
URL_MANUALE = "/api/manuale/"


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


def _utente_di_servizio(username="workflow-agent", **kwargs):
    """Utente del gruppo "Servizio", con la password inutilizzabile come lo crea il comando."""
    user = User.objects.create_user(username, f"{username}@example.com", **kwargs)
    user.groups.add(Group.objects.get(name=GRUPPO_SERVIZIO))
    return user


class _ConManualeDiProva:
    """``GET /api/manuale/`` su un file temporaneo, non sul manuale vero."""

    def _usa_manuale_di_prova(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        percorso = Path(tmp.name) / "MANUALE_UTENTE.md"
        percorso.write_text("# Manuale\n\n## 1. Prova\n\nTesto.\n", encoding="utf-8")
        override = override_settings(MANUALE_UTENTE_PATH=percorso)
        override.enable()
        self.addCleanup(override.disable)


class TokenDiServizioTests(_ConManualeDiProva, TestCase):
    def setUp(self):
        self._usa_manuale_di_prova()
        self.client = Client()
        self.servizio = _utente_di_servizio()
        self.token, self.chiave = ApiToken.crea_per_utente(self.servizio, senza_scadenza=True)

    def test_il_token_non_ha_scadenza(self):
        self.assertIsNone(self.token.expires_at)
        self.assertTrue(self.token.is_valid())

    def test_legge_il_manuale(self):
        res = self.client.get(URL_MANUALE, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 200)
        self.assertIn("Prova", res.json()["content"])

    def test_me_dice_che_non_scrive(self):
        res = self.client.get(URL_ME, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["username"], "workflow-agent")
        self.assertIs(res.json()["can_write"], False)

    def test_risposta_cliente_403(self):
        testata = Testata.objects.create(job="26900")
        documento = Documento.objects.create(testata=testata, vendor_doc="26900-A")
        rev = Revisione.objects.create(
            documento=documento, rev_no=0, rec_act_date=date(2026, 4, 20), int_status="ricevuto"
        )
        stato = StatoEsterno.objects.create(nome="Approved", lettera="A", crea_nuova_rev=False)
        res = self.client.post(
            f"/api/revisioni/{rev.pk}/risposta-cliente/",
            data=json.dumps({"ext_status_id": stato.pk}),
            content_type="application/json",
            headers=_token(self.chiave),
        )
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"], "Permesso negato.")
        rev.refresh_from_db()
        self.assertIsNone(rev.ext_status_id)

    def test_non_scrive_qualunque_sia_il_permesso(self):
        # Anche con Admin e il flag del trasmittal interno, dati per errore dall'admin.
        self.servizio.permesso = Permesso.ADMIN
        self.servizio.trasmittal_interno_writer = True
        self.servizio.save()
        self.assertFalse(user_can_write(self.servizio))
        self.assertFalse(user_can_write_trasmittal_interno(self.servizio))
        me = self.client.get(URL_ME, headers=_token(self.chiave))
        self.assertIs(me.json()["can_write"], False)
        res = _nuovo_stato(self.client, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 403)
        self.assertFalse(StatoEsterno.objects.exists())

    def test_senza_scadenza_su_utente_normale_401(self):
        normale = User.objects.create_user("mrossi", "mrossi@example.com", "pw")
        _, chiave = ApiToken.crea_per_utente(normale, senza_scadenza=True)
        for url in (URL_MANUALE, URL_ME):
            res = self.client.get(url, headers=_token(chiave))
            self.assertEqual(res.status_code, 401)
            self.assertEqual(res.json()["error"], "Token non valido.")

    def test_tolto_dal_gruppo_il_token_non_vale_piu(self):
        self.servizio.groups.clear()
        res = self.client.get(URL_MANUALE, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 401)

    def test_utente_di_servizio_disattivato_401(self):
        self.servizio.is_active = False
        self.servizio.save()
        res = self.client.get(URL_MANUALE, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 401)

    def test_la_pulizia_dei_token_scaduti_non_tocca_quelli_senza_scadenza(self):
        altro = User.objects.create_user("altro", "altro@example.com", "pw")
        scaduto, _ = ApiToken.crea_per_utente(altro)
        ApiToken.objects.filter(pk=scaduto.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        ApiToken.crea_per_utente(altro)
        self.assertFalse(ApiToken.objects.filter(pk=scaduto.pk).exists())
        self.assertTrue(ApiToken.objects.filter(pk=self.token.pk).exists())
        res = self.client.get(URL_MANUALE, headers=_token(self.chiave))
        self.assertEqual(res.status_code, 200)

    def test_api_agent_token_emette_sempre_con_scadenza(self):
        normale = User.objects.create_user("mrossi", "mrossi@example.com", "pw")
        self.client.force_login(normale)
        res = self.client.post(URL_TOKEN)
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.json()["expires_at"])
        self.assertIsNotNone(normale.api_tokens.get().expires_at)


class LoginUtenteDiServizioTests(TestCase):
    def _login(self, username, password):
        return self.client.post("/login/", {"username": username, "password": password})

    def test_password_inutilizzabile(self):
        servizio = _utente_di_servizio()
        self.assertFalse(servizio.has_usable_password())
        res = self._login("workflow-agent", "")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_rifiutato_anche_con_una_password(self):
        servizio = _utente_di_servizio()
        servizio.set_password("pw-servizio")
        servizio.save()
        res = self._login("workflow-agent", "pw-servizio")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Credenziali non valide")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(URL_ME).status_code, 401)

    def test_un_utente_normale_entra_come_prima(self):
        User.objects.create_user("mrossi", "mrossi@example.com", "pw-mrossi")
        res = self._login("mrossi", "pw-mrossi")
        self.assertEqual(res.status_code, 302)
        self.assertEqual(self.client.get(URL_ME).json()["username"], "mrossi")


class CreaTokenServizioCommandTests(_ConManualeDiProva, TestCase):
    def setUp(self):
        self._usa_manuale_di_prova()

    def _esegui(self, *args):
        out = StringIO()
        call_command("crea_token_servizio", *args, stdout=out)
        return out.getvalue()

    def _chiave_stampata(self, output):
        # La chiave sta da sola su una riga rientrata, per copiarla senza altro testo.
        righe = [r.strip() for r in output.splitlines() if r.startswith("    ") and r.strip()]
        self.assertEqual(len(righe), 1, output)
        return righe[0]

    def _stato(self, chiave):
        return Client().get(URL_MANUALE, headers=_token(chiave)).status_code

    def test_crea_utente_gruppo_e_token(self):
        Group.objects.filter(name=GRUPPO_SERVIZIO).delete()
        output = self._esegui("workflow-agent")

        user = User.objects.get(username="workflow-agent")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.permesso, Permesso.READING)
        self.assertTrue(Group.objects.filter(name=GRUPPO_SERVIZIO).exists())
        self.assertTrue(is_service_user(user))

        token = user.api_tokens.get()
        self.assertIsNone(token.expires_at)
        chiave = self._chiave_stampata(output)
        self.assertEqual(token.key, ApiToken.hash_chiave(chiave))
        self.assertIn("non verrà più mostrata", output)
        self.assertEqual(self._stato(chiave), 200)

    def test_la_seconda_esecuzione_revoca_il_token_precedente(self):
        prima = self._chiave_stampata(self._esegui("workflow-agent"))
        output = self._esegui("workflow-agent")
        seconda = self._chiave_stampata(output)

        self.assertNotEqual(prima, seconda)
        self.assertIn("Token precedenti revocati: 1.", output)
        self.assertEqual(User.objects.get(username="workflow-agent").api_tokens.count(), 1)
        self.assertEqual(self._stato(prima), 401)
        self.assertEqual(self._stato(seconda), 200)

    def test_revoca_lascia_l_utente_senza_token(self):
        chiave = self._chiave_stampata(self._esegui("workflow-agent"))
        output = self._esegui("workflow-agent", "--revoca")

        user = User.objects.get(username="workflow-agent")
        self.assertFalse(user.api_tokens.exists())
        self.assertTrue(is_service_user(user))
        self.assertIn("Token revocati", output)
        self.assertNotIn(chiave, output)
        self.assertEqual(self._stato(chiave), 401)

    def test_revoca_di_un_utente_inesistente(self):
        with self.assertRaises(CommandError):
            self._esegui("nessuno", "--revoca")

    def test_non_converte_un_utente_normale_esistente(self):
        normale = User.objects.create_user("mrossi", "mrossi@example.com", "pw")
        _, chiave = ApiToken.crea_per_utente(normale)
        with self.assertRaises(CommandError):
            self._esegui("mrossi")
        normale.refresh_from_db()
        self.assertFalse(is_service_user(normale))
        self.assertTrue(normale.has_usable_password())
        self.assertEqual(self._stato(chiave), 200)

    def test_rifiuta_se_un_altro_utente_ha_gia_l_email_vuota(self):
        User.objects.create_user("senza-email", "", "pw")
        with self.assertRaises(CommandError):
            self._esegui("workflow-agent")
        self.assertFalse(User.objects.filter(username="workflow-agent").exists())

    def test_toglie_la_password_a_un_utente_di_servizio_esistente(self):
        servizio = _utente_di_servizio()
        servizio.set_password("pw-servizio")
        servizio.save()
        self._esegui("workflow-agent")
        servizio.refresh_from_db()
        self.assertFalse(servizio.has_usable_password())


class ApiTokenAdminServizioTests(TestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser("root", "root@example.com", "pw")
        self.client.force_login(self.admin_user)
        self.servizio_token, self.servizio_chiave = ApiToken.crea_per_utente(
            _utente_di_servizio(), senza_scadenza=True
        )
        self.normale_token, _ = ApiToken.crea_per_utente(self.admin_user)

    def test_lista_con_di_servizio_e_scadenza_mai(self):
        res = self.client.get("/admin/core/apitoken/")
        self.assertEqual(res.status_code, 200)
        changelist = res.context["cl"]
        righe = {r.pk: r for r in changelist.result_list}
        model_admin = changelist.model_admin
        self.assertIs(model_admin.di_servizio(righe[self.servizio_token.pk]), True)
        self.assertIs(model_admin.di_servizio(righe[self.normale_token.pk]), False)
        self.assertEqual(model_admin.scadenza(righe[self.servizio_token.pk]), "mai")
        self.assertEqual(
            model_admin.scadenza(righe[self.normale_token.pk]), self.normale_token.expires_at
        )
        self.assertContains(res, "Di servizio")
        self.assertNotContains(res, self.servizio_chiave)
        self.assertNotContains(res, self.servizio_token.key)

    def test_azione_revoca_elimina_i_token_selezionati(self):
        res = self.client.post(
            "/admin/core/apitoken/",
            {"action": "revoca", "_selected_action": [self.servizio_token.pk]},
        )
        self.assertEqual(res.status_code, 302)
        self.assertFalse(ApiToken.objects.filter(pk=self.servizio_token.pk).exists())
        self.assertTrue(ApiToken.objects.filter(pk=self.normale_token.pk).exists())

    def test_il_dettaglio_mostra_scadenza_mai(self):
        res = self.client.get(f"/admin/core/apitoken/{self.servizio_token.pk}/change/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "mai")
        self.assertNotContains(res, self.servizio_token.key)
