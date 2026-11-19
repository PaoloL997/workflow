import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage, InMemoryStorage, default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings

from ..models import AVATAR_MAX_BYTE
from ..services import media as media_service
from ..services.media import copia_media_su_storage

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _media_temporanea, _png, _storage_irraggiungibile


class EliminazioneUtenteTests(TestCase):
    """Eliminando un utente i suoi file escono dallo storage."""

    def setUp(self):
        _media_temporanea(self)

    def test_eliminare_l_utente_cancella_l_avatar(self):
        utente = User.objects.create_user("da_eliminare", "da-eliminare@b.it", "pw")
        utente.avatar = default_storage.save("avatars/foto.png", io.BytesIO(_png()))
        utente.save()
        avatar = utente.avatar.name

        with self.captureOnCommitCallbacks(execute=True):
            utente.delete()

        self.assertFalse(default_storage.exists(avatar))

    def test_utente_senza_file_si_elimina_senza_errori(self):
        utente = User.objects.create_user("senza_file", "senza-file@b.it", "pw")
        with self.captureOnCommitCallbacks(execute=True):
            utente.delete()
        self.assertFalse(User.objects.filter(username="senza_file").exists())


class AvatarUtenteTests(TestCase):
    """Foto profilo: servita dall'app, sostituita senza perdere quella vecchia."""

    def setUp(self):
        _media_temporanea(self)
        self.client = Client()
        self.utente = User.objects.create_user(
            "avatar_utente", "avatar-utente@b.it", "pw", first_name="Anna", last_name="Neri"
        )
        self.client.force_login(self.utente)

    def _carica(self, nome="foto.png", contenuto=None):
        return self.client.post(
            "/profilo/",
            {
                "action": "update_profile",
                "first_name": "Anna",
                "last_name": "Neri",
                "email": self.utente.email,
                "avatar": SimpleUploadedFile(nome, contenuto or _png(), "image/png"),
            },
        )

    def test_l_avatar_si_vede_solo_da_utenti_loggati(self):
        self._carica()
        self.utente.refresh_from_db()
        url = self.utente.url_avatar
        self.assertTrue(url.startswith(f"/utenti/{self.utente.pk}/avatar/?v=avatars/"))

        risposta = self.client.get(url)

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "image/png")
        self.assertIn("private", risposta["Cache-Control"])
        self.assertEqual(risposta["X-Content-Type-Options"], "nosniff")
        self.assertEqual(b"".join(risposta.streaming_content), _png())
        self.assertEqual(Client().get(url).status_code, 302)

    def test_foto_profilo_valida_si_salva(self):
        risposta = self._carica()

        self.assertEqual(risposta.status_code, 302)
        self.utente.refresh_from_db()
        self.assertTrue(self.utente.avatar.name.startswith("avatars/"))

    def test_foto_profilo_rifiuta_file_non_validi(self):
        for nome, contenuto, messaggio in (
            # L'apostrofo nell'HTML è &#x27;: si cerca il resto del messaggio.
            ("foto.png", b"non sono un'immagine", "immagine valida: carica un PNG"),
            ("foto.bmp", _png(modo="RGB", formato="BMP"), "Formato non ammesso"),
            ("foto.png", _png() + b"\0" * AVATAR_MAX_BYTE, "al massimo 5 MB"),
        ):
            with self.subTest(nome=nome, messaggio=messaggio):
                risposta = self._carica(nome, contenuto)

                self.assertEqual(risposta.status_code, 200)
                self.assertContains(risposta, messaggio)
                self.utente.refresh_from_db()
                self.assertFalse(self.utente.avatar)

    def test_404_senza_avatar_o_con_file_mancante(self):
        self.assertEqual(self.client.get(f"/utenti/{self.utente.pk}/avatar/").status_code, 404)
        self.assertEqual(self.client.get("/utenti/999999/avatar/").status_code, 404)

        self.utente.avatar = "avatars/sparito.png"
        self.utente.save(update_fields=["avatar"])
        self.assertEqual(self.client.get(f"/utenti/{self.utente.pk}/avatar/").status_code, 404)

    def test_un_file_che_non_e_un_immagine_non_viene_servito(self):
        for nome in ("pagina.html", "disegno.svg"):
            with self.subTest(nome=nome):
                self.utente.avatar = SimpleUploadedFile(nome, b"<script>alert(1)</script>")
                self.utente.save()

                risposta = self.client.get(f"/utenti/{self.utente.pk}/avatar/")

                self.assertEqual(risposta.status_code, 404)

    def test_storage_irraggiungibile_risponde_503(self):
        self._carica()

        with patch.object(FileSystemStorage, "open", side_effect=_storage_irraggiungibile()):
            risposta = self.client.get(f"/utenti/{self.utente.pk}/avatar/")

        self.assertEqual(risposta.status_code, 503)

    def test_dopo_un_errore_lo_storage_non_viene_richiamato_per_un_po(self):
        self._carica()
        with patch.object(FileSystemStorage, "open", side_effect=_storage_irraggiungibile()):
            self.client.get(f"/utenti/{self.utente.pk}/avatar/")

        # Lo storage è tornato, ma per la pausa non lo si interroga subito.
        with patch.object(FileSystemStorage, "open") as apertura:
            risposta = self.client.get(f"/utenti/{self.utente.pk}/avatar/")
        self.assertEqual(risposta.status_code, 503)
        apertura.assert_not_called()

        # Finita la pausa la foto torna a vedersi.
        media_service._storage_giu_fino = 0.0
        risposta = self.client.get(f"/utenti/{self.utente.pk}/avatar/")
        self.assertEqual(risposta.status_code, 200)
        b"".join(risposta.streaming_content)

    def test_le_pagine_usano_l_url_dell_app(self):
        self._carica()

        pagina = self.client.get("/profilo/").content.decode()

        self.assertIn(f"/utenti/{self.utente.pk}/avatar/?v=avatars/", pagina)
        self.assertNotIn("/media/avatars/", pagina)

    def test_nuovo_avatar_cancella_il_vecchio_dopo_il_salvataggio(self):
        self._carica()
        self.utente.refresh_from_db()
        prima = self.utente.avatar.name

        self._carica()
        self.utente.refresh_from_db()

        self.assertNotEqual(self.utente.avatar.name, prima)
        self.assertFalse(default_storage.exists(prima))
        self.assertTrue(default_storage.exists(self.utente.avatar.name))

    def test_storage_irraggiungibile_al_salvataggio_lascia_l_avatar_di_prima(self):
        self._carica()
        self.utente.refresh_from_db()
        prima = self.utente.avatar.name

        with patch.object(FileSystemStorage, "_save", side_effect=OSError("disco pieno")):
            risposta = self._carica()

        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "archivio non raggiungibile")
        self.utente.refresh_from_db()
        self.assertEqual(self.utente.avatar.name, prima)
        self.assertTrue(default_storage.exists(prima))

    def test_segnalazioni_usano_l_url_dell_app(self):
        from core.services.segnalazioni import _avatar_url

        self.utente.avatar = "avatars/a b.png"
        self.utente.save(update_fields=["avatar"])

        self.assertEqual(
            _avatar_url(self.utente), f"/utenti/{self.utente.pk}/avatar/?v=avatars/a%20b.png"
        )
        self.assertIsNone(_avatar_url(None))


class CopiaMediaSuStorageTests(TestCase):
    """Copia delle foto profilo dalla cartella media allo storage S3."""

    def setUp(self):
        self.con_file = User.objects.create_user("copia_uno", "copia-uno@b.it", "pw")
        self.con_file.avatar = "avatars/a.png"
        self.con_file.save()
        self.senza_file = User.objects.create_user("copia_due", "copia-due@b.it", "pw")
        self.senza_file.avatar = "avatars/manca.png"
        self.senza_file.save()
        User.objects.create_user("copia_tre", "copia-tre@b.it", "pw")

        self.sorgente = InMemoryStorage()
        for nome in ("avatars/a.png", "avatars/orfano.png"):
            self.sorgente.save(nome, io.BytesIO(nome.encode()))
        self.destinazione = InMemoryStorage()

    def test_copia_i_file_in_uso_con_lo_stesso_nome(self):
        report = copia_media_su_storage(self.sorgente, self.destinazione)

        self.assertEqual(report.copiati, ["avatars/a.png"])
        self.assertEqual(report.mancanti, [("avatars/manca.png", ["copia_due"])])
        with self.destinazione.open("avatars/a.png") as file:
            self.assertEqual(file.read(), b"avatars/a.png")
        # Un file che nessuno usa più non viene ricopiato.
        self.assertFalse(self.destinazione.exists("avatars/orfano.png"))

    def test_si_puo_rilanciare(self):
        copia_media_su_storage(self.sorgente, self.destinazione)

        report = copia_media_su_storage(self.sorgente, self.destinazione)

        self.assertEqual(report.copiati, [])
        self.assertEqual(report.gia_presenti, ["avatars/a.png"])

    def test_dry_run_non_scrive_nulla(self):
        report = copia_media_su_storage(self.sorgente, self.destinazione, dry_run=True)

        self.assertEqual(report.da_copiare, ["avatars/a.png"])
        self.assertFalse(self.destinazione.exists("avatars/a.png"))

    def test_comando_copia_nello_storage_configurato(self):
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        (Path(cartella.name) / "avatars").mkdir()
        (Path(cartella.name) / "avatars" / "a.png").write_bytes(b"png")
        uscita = io.StringIO()

        with override_settings(
            STORAGES={
                **settings.STORAGES,
                "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
            }
        ):
            call_command(
                "copia_media_su_storage",
                sorgente=cartella.name,
                stdout=uscita,
                stderr=io.StringIO(),
            )
            self.assertTrue(default_storage.exists("avatars/a.png"))

        self.assertIn("1 copiati", uscita.getvalue())
        self.assertIn("1 mancanti", uscita.getvalue())

    def test_comando_rifiuta_di_copiare_la_cartella_su_se_stessa(self):
        media = _media_temporanea(self)

        with self.assertRaises(CommandError):
            call_command("copia_media_su_storage", sorgente=media, stdout=io.StringIO())


class StorageMediaDaEnvTests(SimpleTestCase):
    """Scelta dello storage dei file caricati in base al .env."""

    def _con_env(self, **valori):
        from config.settings import storage_media_da_env

        chiavi = ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY", "S3_ENDPOINT_URL", "S3_REGION")
        with patch.dict("os.environ", {k: "" for k in chiavi}):
            import os

            os.environ.update(valori)
            return storage_media_da_env()

    def test_senza_bucket_resta_la_cartella_locale(self):
        self.assertEqual(self._con_env()["BACKEND"], "django.core.files.storage.FileSystemStorage")

    def test_con_bucket_usa_s3_path_style_senza_sovrascrivere(self):
        from storages.backends.s3 import S3Storage

        config = self._con_env(
            S3_BUCKET="workflow-media",
            S3_ACCESS_KEY="GK0123",
            S3_SECRET_KEY="segreto",
            S3_ENDPOINT_URL="http://127.0.0.1:3900",
        )

        self.assertEqual(config["BACKEND"], "storages.backends.s3.S3Storage")
        opzioni = config["OPTIONS"]
        self.assertEqual(opzioni["bucket_name"], "workflow-media")
        self.assertEqual(opzioni["endpoint_url"], "http://127.0.0.1:3900")
        self.assertEqual(opzioni["region_name"], "us-east-1")
        self.assertEqual(opzioni["client_config"].s3, {"addressing_style": "path"})
        self.assertEqual(opzioni["client_config"].signature_version, "s3v4")
        # Il backend si costruisce con queste opzioni senza collegarsi a niente.
        storage = S3Storage(**opzioni)
        self.assertFalse(storage.file_overwrite)
        self.assertIsNone(storage.default_acl)

    def test_senza_endpoint_usa_seaweedfs_in_locale(self):
        config = self._con_env(S3_BUCKET="b", S3_ACCESS_KEY="k", S3_SECRET_KEY="s")

        self.assertEqual(config["OPTIONS"]["endpoint_url"], "http://127.0.0.1:3900")

    def test_bucket_senza_chiavi_e_un_errore_di_configurazione(self):
        with self.assertRaises(ImproperlyConfigured):
            self._con_env(S3_BUCKET="workflow-media")
