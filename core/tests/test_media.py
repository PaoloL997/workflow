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
from PIL import Image

from ..models import (
    AVATAR_MAX_BYTE,
    FIRMA_MAX_BYTE,
    Permesso,
)
from ..services import media as media_service
from ..services.media import copia_media_su_storage

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _dai_firma, _media_temporanea, _png, _storage_irraggiungibile


class FirmaUtenteTests(TestCase):
    """Validatore dell'immagine di firma e upload/rimozione dal profilo."""

    def setUp(self):
        _media_temporanea(self)

        self.client = Client()
        self.writer = User.objects.create_user(
            "firma_writer",
            "firma-writer@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Mario",
            last_name="Rossi",
        )
        _dai_firma(self.writer)
        self.client.force_login(self.writer)

    def _profilo(self, **campi):
        # Il modulo del profilo manda tutti i campi: uno che manca si svuota.
        dati = {
            "action": "update_profile",
            "first_name": "Mario",
            "last_name": "Rossi",
            "email": self.writer.email,
        }
        return self.client.post("/profilo/", {**dati, **campi})

    def test_upload_di_una_immagine_di_firma_valida(self):
        risposta = self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))

        self.assertEqual(risposta.status_code, 302)
        self.writer.refresh_from_db()
        self.assertTrue(self.writer.firma.name.startswith("firme/"))
        self.assertNotEqual(self.writer.firma.name, "firme/prova.png")
        # Il file si legge e si chiude subito: su Windows un file aperto non si
        # cancella, e il prossimo upload sostituisce quello vecchio.
        with self.writer.firma.open("rb") as file:
            contenuto = file.read()
        with Image.open(io.BytesIO(contenuto)) as immagine:
            self.assertEqual((immagine.format, immagine.mode), ("PNG", "RGBA"))
        # Anche un JPEG va bene.
        risposta = self._profilo(
            firma=SimpleUploadedFile("firma.jpg", _png(modo="RGB", formato="JPEG"), "image/jpeg")
        )
        self.assertEqual(risposta.status_code, 302)

    def test_upload_rifiuta_un_file_che_non_e_un_immagine(self):
        for nome, contenuto, messaggio in (
            # L'apostrofo nell'HTML è &#x27;: si cerca il resto del messaggio.
            ("firma.png", b"non sono un'immagine", "immagine valida: carica un PNG"),
            ("firma.gif", _png(modo="RGB", formato="GIF"), "Formato non ammesso"),
        ):
            with self.subTest(nome=nome):
                risposta = self._profilo(firma=SimpleUploadedFile(nome, contenuto, "image/png"))

                self.assertEqual(risposta.status_code, 200)
                self.assertContains(risposta, messaggio)
                # L'immagine che c'era resta.
                self.writer.refresh_from_db()
                self.assertEqual(self.writer.firma.name, "firme/prova.png")

    def test_foto_profilo_valida_si_salva(self):
        risposta = self._profilo(avatar=SimpleUploadedFile("foto.png", _png(), "image/png"))

        self.assertEqual(risposta.status_code, 302)
        self.writer.refresh_from_db()
        self.assertTrue(self.writer.avatar.name.startswith("avatars/"))

    def test_foto_profilo_rifiuta_file_non_validi(self):
        for nome, contenuto, messaggio in (
            ("foto.png", b"non sono un'immagine", "immagine valida: carica un PNG"),
            ("foto.bmp", _png(modo="RGB", formato="BMP"), "Formato non ammesso"),
            ("foto.png", _png() + b"\0" * AVATAR_MAX_BYTE, "al massimo 5 MB"),
        ):
            with self.subTest(nome=nome, messaggio=messaggio):
                risposta = self._profilo(avatar=SimpleUploadedFile(nome, contenuto, "image/png"))

                self.assertEqual(risposta.status_code, 200)
                self.assertContains(risposta, messaggio)
                self.writer.refresh_from_db()
                self.assertFalse(self.writer.avatar)

    def test_upload_rifiuta_un_file_oltre_il_limite(self):
        pesante = _png() + b"\0" * FIRMA_MAX_BYTE

        risposta = self._profilo(firma=SimpleUploadedFile("firma.png", pesante, "image/png"))

        self.assertContains(risposta, "al massimo 1 MB")

    def test_l_immagine_di_firma_si_toglie_dal_profilo(self):
        self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))

        self._profilo(rimuovi_firma="1")

        self.writer.refresh_from_db()
        self.assertFalse(self.writer.firma)
        pagina = self.client.get("/profilo/").content.decode()
        self.assertIn("Nessuna immagine di firma caricata.", pagina)
        self.assertNotIn("firma digitale", pagina.lower())

    def test_rimuovere_o_sostituire_la_firma_cancella_il_file_vecchio(self):
        self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))
        self.writer.refresh_from_db()
        prima = self.writer.firma.name

        self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))
        self.writer.refresh_from_db()
        seconda = self.writer.firma.name

        # Stesso nome caricato: il nuovo file ne prende un altro, il vecchio sparisce.
        self.assertNotEqual(prima, seconda)
        self.assertFalse(default_storage.exists(prima))
        self.assertTrue(default_storage.exists(seconda))

        self._profilo(rimuovi_firma="1")
        self.assertFalse(default_storage.exists(seconda))

    def test_la_vista_della_firma_serve_l_immagine_solo_agli_utenti_loggati(self):
        self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))
        url = f"/utenti/{self.writer.pk}/firma/"

        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "image/png")
        self.assertEqual(risposta["Cache-Control"], "private, no-cache")
        self.assertEqual(b"".join(risposta.streaming_content), _png())

        self.assertEqual(Client().get(url).status_code, 302)
        senza_firma = User.objects.create_user("senza_firma", "senza-firma@b.it", "pw")
        self.assertEqual(self.client.get(f"/utenti/{senza_firma.pk}/firma/").status_code, 404)

    def test_storage_irraggiungibile_al_salvataggio_lascia_la_firma_di_prima(self):
        with patch.object(FileSystemStorage, "_save", side_effect=OSError("disco pieno")):
            risposta = self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))

        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "archivio non raggiungibile")
        self.writer.refresh_from_db()
        self.assertEqual(self.writer.firma.name, "firme/prova.png")


class EliminazioneUtenteTests(TestCase):
    """Eliminando un utente i suoi file escono dallo storage."""

    def setUp(self):
        _media_temporanea(self)

    def test_eliminare_l_utente_cancella_avatar_e_firma(self):
        utente = User.objects.create_user("da_eliminare", "da-eliminare@b.it", "pw")
        utente.avatar = default_storage.save("avatars/foto.png", io.BytesIO(_png()))
        utente.firma = default_storage.save("firme/firma.png", io.BytesIO(_png()))
        utente.save()
        avatar, firma = utente.avatar.name, utente.firma.name

        with self.captureOnCommitCallbacks(execute=True):
            utente.delete()

        self.assertFalse(default_storage.exists(avatar))
        self.assertFalse(default_storage.exists(firma))

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

    def test_admin_linka_la_firma_tramite_l_app(self):
        admin_utente = User.objects.create_superuser("media_admin", "media-admin@b.it", "pw")
        _dai_firma(self.utente)
        self.client.force_login(admin_utente)

        pagina = self.client.get(f"/admin/core/user/{self.utente.pk}/change/")

        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, f'href="/utenti/{self.utente.pk}/firma/"')


class CopiaMediaSuStorageTests(TestCase):
    """Copia di foto profilo e firme dalla cartella media allo storage S3."""

    def setUp(self):
        self.con_file = User.objects.create_user("copia_uno", "copia-uno@b.it", "pw")
        self.con_file.avatar = "avatars/a.png"
        self.con_file.firma = "firme/f.png"
        self.con_file.save()
        self.senza_file = User.objects.create_user("copia_due", "copia-due@b.it", "pw")
        self.senza_file.firma = "firme/manca.png"
        self.senza_file.save()
        User.objects.create_user("copia_tre", "copia-tre@b.it", "pw")

        self.sorgente = InMemoryStorage()
        for nome in ("avatars/a.png", "firme/f.png", "avatars/orfano.png"):
            self.sorgente.save(nome, io.BytesIO(nome.encode()))
        self.destinazione = InMemoryStorage()

    def test_copia_i_file_in_uso_con_lo_stesso_nome(self):
        report = copia_media_su_storage(self.sorgente, self.destinazione)

        self.assertEqual(report.copiati, ["avatars/a.png", "firme/f.png"])
        self.assertEqual(report.mancanti, [("firme/manca.png", ["copia_due"])])
        with self.destinazione.open("firme/f.png") as file:
            self.assertEqual(file.read(), b"firme/f.png")
        # Un file che nessuno usa più non viene ricopiato.
        self.assertFalse(self.destinazione.exists("avatars/orfano.png"))

    def test_si_puo_rilanciare(self):
        copia_media_su_storage(self.sorgente, self.destinazione)

        report = copia_media_su_storage(self.sorgente, self.destinazione)

        self.assertEqual(report.copiati, [])
        self.assertEqual(report.gia_presenti, ["avatars/a.png", "firme/f.png"])

    def test_dry_run_non_scrive_nulla(self):
        report = copia_media_su_storage(self.sorgente, self.destinazione, dry_run=True)

        self.assertEqual(report.da_copiare, ["avatars/a.png", "firme/f.png"])
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
        self.assertIn("2 mancanti", uscita.getvalue())

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
