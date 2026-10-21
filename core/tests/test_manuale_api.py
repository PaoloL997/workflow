"""Manuale utente per l'indicizzazione esterna: ``GET /api/manuale/``."""

import hashlib
import tempfile
from pathlib import Path

from django.test import Client, TestCase, override_settings

from ..models import ApiToken, Permesso
from ..services.manuale import senza_indice
from ._fixtures import User

URL = "/api/manuale/"


class ManualeApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "manuale_reader", "manuale-reader@b.it", "pw", permesso=Permesso.READING
        )
        self.client.force_login(self.user)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.percorso = Path(self.tmp.name) / "MANUALE_UTENTE.md"
        self.percorso.write_text("# Manuale\n\n## 1. Prova\n\nTesto.\n", encoding="utf-8")
        override = override_settings(MANUALE_UTENTE_PATH=self.percorso)
        override.enable()
        self.addCleanup(override.disable)

    def _version_attesa(self):
        contenuto = self.percorso.read_text(encoding="utf-8")
        return hashlib.sha256(contenuto.encode("utf-8")).hexdigest()[:16]

    def test_restituisce_contenuto_versione_e_data(self):
        res = self.client.get(URL)

        self.assertEqual(res.status_code, 200)
        dati = res.json()
        self.assertEqual(dati["content"], self.percorso.read_text(encoding="utf-8"))
        self.assertTrue(dati["content"])
        self.assertEqual(dati["version"], self._version_attesa())
        self.assertEqual(len(dati["version"]), 16)
        self.assertTrue(dati["updated_at"])
        self.assertEqual(res["ETag"], dati["version"])

    def test_version_stabile_e_cambia_col_contenuto(self):
        prima = self.client.get(URL).json()["version"]
        seconda = self.client.get(URL).json()["version"]
        self.assertEqual(prima, seconda)

        self.percorso.write_text("# Manuale\n\n## 1. Prova\n\nTesto nuovo.\n", encoding="utf-8")

        terza = self.client.get(URL).json()["version"]
        self.assertNotEqual(terza, prima)
        self.assertEqual(terza, self._version_attesa())

    def test_only_version_non_contiene_il_contenuto(self):
        res = self.client.get(URL, {"only_version": "1"})

        self.assertEqual(res.status_code, 200)
        dati = res.json()
        self.assertEqual(set(dati), {"version", "updated_at"})
        self.assertEqual(dati["version"], self._version_attesa())
        self.assertEqual(res["ETag"], dati["version"])

    def test_if_none_match_uguale_e_un_304(self):
        version = self.client.get(URL).json()["version"]

        res = self.client.get(URL, headers={"If-None-Match": version})
        self.assertEqual(res.status_code, 304)
        self.assertEqual(res["ETag"], version)
        self.assertEqual(res.content, b"")

        # Anche nella forma HTTP standard fra virgolette.
        res = self.client.get(URL, headers={"If-None-Match": f'"{version}"'})
        self.assertEqual(res.status_code, 304)

    def test_if_none_match_diverso_risponde_200(self):
        res = self.client.get(URL, headers={"If-None-Match": "0000000000000000"})

        self.assertEqual(res.status_code, 200)
        self.assertIn("content", res.json())

    def test_la_sezione_indice_non_viene_mai_servita(self):
        self.percorso.write_text(
            "# Manuale\n\nIntro.\n\n---\n\n<!-- no-index -->\n## Indice\n\n"
            "1. [Prova](#1-prova)\n2. [Altro](#2-altro)\n\n---\n\n"
            "## 1. Prova\n\nTesto.\n\n## 2. Altro\n\nAltro testo.\n",
            encoding="utf-8",
        )

        dati = self.client.get(URL).json()

        self.assertEqual(
            dati["content"],
            "# Manuale\n\nIntro.\n\n---\n\n## 1. Prova\n\nTesto.\n\n## 2. Altro\n\nAltro testo.\n",
        )
        # La versione è l'impronta del testo servito, non del file.
        self.assertEqual(
            dati["version"], hashlib.sha256(dati["content"].encode("utf-8")).hexdigest()[:16]
        )

    def test_file_mancante_e_un_404(self):
        self.percorso.unlink()

        res = self.client.get(URL)

        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"], "Manuale non trovato.")

    def test_senza_autenticazione_401(self):
        self.client.logout()

        res = self.client.get(URL)

        self.assertEqual(res.status_code, 401)

    def test_funziona_col_token(self):
        self.client.logout()
        _, chiave = ApiToken.crea_per_utente(self.user)

        res = self.client.get(URL, headers={"Authorization": f"Token {chiave}"})

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["version"], self._version_attesa())


class SenzaIndiceTests(TestCase):
    """``senza_indice`` toglie la sezione "Indice" in qualunque forma compaia."""

    def test_senza_marcatore_e_con_titolo_di_altro_livello(self):
        testo = "# Manuale\n\n### indice\n\n- a\n- b\n\n## 1. Prova\n\nTesto.\n"

        self.assertEqual(senza_indice(testo), "# Manuale\n\n## 1. Prova\n\nTesto.\n")

    def test_indice_in_coda_al_file(self):
        testo = "# Manuale\n\n## 1. Prova\n\nTesto.\n\n## Indice\n\n- a\n"

        self.assertEqual(senza_indice(testo), "# Manuale\n\n## 1. Prova\n\nTesto.\n\n")

    def test_un_titolo_che_inizia_per_indice_non_viene_toccato(self):
        testo = "# Manuale\n\n## 1. Indice dei documenti\n\nNon è il sommario.\n"

        self.assertEqual(senza_indice(testo), testo)


class ManualeRealeTests(TestCase):
    """Il file della repo esiste e viene servito senza indice."""

    def setUp(self):
        self.client = Client()
        self.client.force_login(
            User.objects.create_user("manuale_w", "manuale-w@b.it", "pw", permesso=Permesso.READING)
        )

    def test_il_manuale_della_repo_viene_servito(self):
        res = self.client.get(URL)

        self.assertEqual(res.status_code, 200)
        content = res.json()["content"]
        self.assertIn("# Manuale utente", content)
        self.assertIn("## 1. Panoramica", content)
        self.assertNotIn("## Indice", content)
        self.assertNotIn("no-index", content)
