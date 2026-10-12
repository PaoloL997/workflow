import json

from django.contrib import admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, RequestFactory, TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from ..models import (
    Permesso,
    Testata,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User


class PermessiTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            "admin_user", "admin@example.com", "pw", permesso=Permesso.ADMIN
        )
        self.writing_user = User.objects.create_user(
            "writing_user", "writing@example.com", "pw", permesso=Permesso.WRITING
        )
        self.reading_user = User.objects.create_user(
            "reading_user", "reading@example.com", "pw", permesso=Permesso.READING
        )

    def test_reading_can_list_commesse(self):
        self.client.force_login(self.reading_user)
        response = self.client.get("/api/commesse/")
        self.assertEqual(response.status_code, 200)

    def test_reading_cannot_create_commessa(self):
        self.client.force_login(self.reading_user)
        response = self.client.post(
            "/api/commesse/",
            data=json.dumps({"job": "READ-001"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Permesso negato.")

    def test_writing_can_create_commessa(self):
        self.client.force_login(self.writing_user)
        response = self.client.post(
            "/api/commesse/",
            data=json.dumps({"job": "WRITE-001"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)

    def test_delete_commessa_sends_request_email_without_deleting(self):
        Testata.objects.create(job="DEL-001", job_detail="Prova eliminazione")
        self.client.force_login(self.writing_user)
        response = self.client.delete("/api/commesse/DEL-001/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(Testata.objects.filter(job="DEL-001").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["plitta@brembanarolle.com"])
        self.assertIn("writing_user", mail.outbox[0].body)
        self.assertIn("DEL-001", mail.outbox[0].body)
        self.assertIn("ha richiesto l'eliminazione della commessa", mail.outbox[0].body)

    def test_admin_delete_commessa_removes_it(self):
        Testata.objects.create(job="DEL-ADM", job_detail="Eliminazione admin")
        self.client.force_login(self.admin_user)
        response = self.client.delete("/api/commesse/DEL-ADM/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(Testata.objects.filter(job="DEL-ADM").exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_reading_cannot_access_admin(self):
        self.client.force_login(self.reading_user)
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, (302, 403))

    def test_admin_can_access_admin(self):
        self.client.force_login(self.admin_user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_registration_defaults_to_reading(self):
        response = self.client.post(
            "/register/",
            data={
                "username": "new_reader",
                "email": "reader@brembanarolle.com",
                "first_name": "Nuovo",
                "last_name": "Lettore",
                "password1": "securepass123",
                "password2": "securepass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="new_reader")
        self.assertEqual(user.permesso, Permesso.READING)
        self.assertFalse(user.is_staff)

    def test_registration_rejects_non_company_email(self):
        response = self.client.post(
            "/register/",
            data={
                "username": "external_user",
                "email": "user@example.com",
                "first_name": "Esterno",
                "last_name": "Utente",
                "password1": "securepass123",
                "password2": "securepass123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@brembanarolle.com")
        self.assertFalse(User.objects.filter(username="external_user").exists())

    def test_admin_syncs_is_staff(self):
        self.assertTrue(self.admin_user.is_staff)
        self.assertTrue(self.writing_user.is_staff)
        self.assertFalse(self.reading_user.is_staff)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.user = User.objects.create_user(
            username="reset_user",
            email="reset@brembanarolle.com",
            password="oldpass123",
        )

    def test_password_reset_page_renders(self):
        response = self.client.get("/password-reset/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Recupera password")

    def test_password_reset_sends_email_for_known_user(self):
        response = self.client.post(
            "/password-reset/",
            data={"email": "reset@brembanarolle.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/password-reset/done/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("reset@brembanarolle.com", mail.outbox[0].to)
        self.assertIn("/reset/", mail.outbox[0].body)
        self.assertRegex(mail.outbox[0].body, r"/reset/[^/\s]+/[^/\s]+/")

    def test_password_reset_unknown_email_shows_done_without_leak(self):
        response = self.client.post(
            "/password-reset/",
            data={"email": "unknown@brembanarolle.com"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/password-reset/done/")
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_rejects_non_company_email(self):
        response = self.client.post(
            "/password-reset/",
            data={"email": "user@example.com"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "@brembanarolle.com")
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_sets_new_password(self):
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        # Django redirects to .../set-password/ to avoid token leakage via Referer
        initial_url = f"/reset/{uid}/{token}/"
        self.client.get(initial_url)  # stores token in session, redirects to set-password
        confirm_url = f"/reset/{uid}/set-password/"
        response = self.client.post(
            confirm_url,
            data={
                "new_password1": "newsecurepass123",
                "new_password2": "newsecurepass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, "/reset/done/")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("newsecurepass123"))
        self.assertIsNotNone(authenticate(username="reset_user", password="newsecurepass123"))

    def test_login_page_has_reset_link(self):
        response = self.client.get("/login/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/password-reset/"')
        self.assertContains(response, "Recuperala")


class AccessoEPasswordTests(TestCase):
    """Login: ``next`` solo verso questo sito; password con i validatori di Django."""

    def setUp(self):
        self.client = Client()
        self.utente = User.objects.create_user(
            "accesso_utente", "accesso@brembanarolle.com", "Pw-robusta-2026!"
        )

    def _login(self, query="", **extra):
        return self.client.post(
            f"/login/{query}",
            {"username": "accesso_utente", "password": "Pw-robusta-2026!", **extra},
        )

    def test_next_verso_un_altro_host_viene_ignorato(self):
        for next_url in ("https://altro.example/", "//altro.example/", "http://altro.example"):
            with self.subTest(next=next_url):
                self.client.logout()
                risposta = self._login(f"?next={next_url}")

                self.assertEqual(risposta.status_code, 302)
                self.assertEqual(risposta["Location"], "/")

    def test_next_interno_viene_rispettato(self):
        risposta = self._login("?next=/commesse/")

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(risposta["Location"], "/commesse/")

    def test_next_nel_form_viene_rispettato(self):
        risposta = self._login(next="/commesse/")

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(risposta["Location"], "/commesse/")

    def test_next_vuoto_porta_alla_home_senza_errori(self):
        risposta = self._login("?next=")

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(risposta["Location"], "/")

    def _registra(self, password, username="nuovo_utente"):
        return self.client.post(
            "/register/",
            {
                "username": username,
                "email": f"{username}@brembanarolle.com",
                "first_name": "Nuovo",
                "last_name": "Utente",
                "password1": password,
                "password2": password,
            },
        )

    def test_registrazione_rifiuta_una_password_troppo_comune(self):
        risposta = self._registra("password1")

        self.assertEqual(risposta.status_code, 200)
        self.assertIsNotNone(risposta.context["error"])
        self.assertFalse(User.objects.filter(username="nuovo_utente").exists())

    def test_registrazione_rifiuta_una_password_uguale_allo_username(self):
        risposta = self._registra("nuovo_utente", username="nuovo_utente")

        self.assertEqual(risposta.status_code, 200)
        self.assertIsNotNone(risposta.context["error"])
        self.assertFalse(User.objects.filter(username="nuovo_utente").exists())

    def test_registrazione_rifiuta_ancora_una_password_corta(self):
        risposta = self._registra("Ab1!xyz")

        self.assertEqual(risposta.status_code, 200)
        self.assertIsNotNone(risposta.context["error"])
        self.assertFalse(User.objects.filter(username="nuovo_utente").exists())

    def test_registrazione_accetta_una_password_robusta(self):
        risposta = self._registra("Fr4se-lunga-e-robusta")

        self.assertEqual(risposta.status_code, 302)
        self.assertTrue(User.objects.filter(username="nuovo_utente").exists())

    def _cambia_password(self, nuova):
        self.client.force_login(self.utente)
        return self.client.post(
            "/profilo/",
            {
                "action": "change_password",
                "old_password": "Pw-robusta-2026!",
                "new_password1": nuova,
                "new_password2": nuova,
            },
        )

    def test_profilo_rifiuta_una_password_troppo_comune(self):
        risposta = self._cambia_password("password1")

        self.assertEqual(risposta.status_code, 200)
        self.assertIn("password", risposta.context["errors"])
        self.utente.refresh_from_db()
        self.assertTrue(self.utente.check_password("Pw-robusta-2026!"))

    def test_profilo_accetta_una_password_robusta(self):
        risposta = self._cambia_password("Altr4-frase-robusta")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.context["success"], "password")
        self.utente.refresh_from_db()
        self.assertTrue(self.utente.check_password("Altr4-frase-robusta"))


class AdminUtentiFieldsetsTests(TestCase):
    """I permessi dell'app stanno in un solo fieldset, senza campi doppi.

    Il filtro sul fieldset dei permessi di Django va fatto sui campi e non
    sul titolo, che con l'admin in italiano è «Permessi» e non «Permissions»:
    altrimenti ``is_staff`` compare due volte nel form di modifica e
    ``permesso``/``trasmittal_interno_writer`` due volte in quello di creazione.
    """

    def setUp(self):
        self.model_admin = admin.site._registry[User]
        self.superuser = User.objects.create_superuser("fs_admin", "fs-admin@b.it", "pw")
        self.request = RequestFactory().get("/admin/core/user/")
        self.request.user = self.superuser

    def _campi(self, obj):
        campi = []
        for _titolo, opzioni in self.model_admin.get_fieldsets(self.request, obj):
            campi.extend(opzioni["fields"])
        return campi

    def test_form_di_modifica_senza_campi_doppi(self):
        campi = self._campi(self.superuser)

        self.assertEqual(len(campi), len(set(campi)), campi)
        for campo in ("permesso", "trasmittal_interno_writer", "is_staff", "is_superuser"):
            self.assertIn(campo, campi)

    def test_form_di_creazione_senza_campi_doppi(self):
        campi = self._campi(None)

        self.assertEqual(len(campi), len(set(campi)), campi)
        self.assertIn("permesso", campi)
        self.assertIn("trasmittal_interno_writer", campi)

    def test_pagine_admin_utente_si_aprono(self):
        self.client.force_login(self.superuser)

        for url in ("/admin/core/user/add/", f"/admin/core/user/{self.superuser.pk}/change/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class LogoutTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.client.force_login(User.objects.create_user("logout_utente", "lo@b.it", "pw"))

    def test_logout_in_post_chiude_la_sessione(self):
        risposta = self.client.post("/logout/")

        self.assertEqual(risposta.status_code, 302)
        self.assertEqual(self.client.get("/commesse/").status_code, 302)

    def test_logout_in_get_non_chiude_la_sessione(self):
        """Un <img src="/logout/"> su un'altra pagina non deve bastare."""
        risposta = self.client.get("/logout/")

        self.assertEqual(risposta.status_code, 405)
        self.assertEqual(self.client.get("/commesse/").status_code, 200)
