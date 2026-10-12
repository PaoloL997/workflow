import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import Client, TestCase

from ..models import (
    Documento,
    Permesso,
    Revisione,
    Testata,
    Transmittal,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _trasmittal_dir, _trasmittal_path, _write_trasmittal


class ListaTrasmittalTest(TestCase):
    """Unit tests for transmittal archive listing against a temp folder."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_lists_matching_job_sorted_desc(self):
        folder = _trasmittal_dir(self.tmp, "25089")
        (folder / "Transmittal 25089-3.pdf").write_bytes(b"%PDF")
        (folder / "Transmittal 25089-21.pdf").write_bytes(b"%PDF")
        (folder / "Transmittal 25056-1.pdf").write_bytes(b"%PDF")
        (folder / "readme.txt").write_text("x")
        _write_trasmittal(self.tmp, "25056", 9)
        from core.services.trasmittal_archivio import lista_trasmittal

        items = lista_trasmittal("25089")
        self.assertEqual([i["id"] for i in items], [21, 3])
        self.assertEqual(items[0]["nome"], "Transmittal 25089-21.pdf")

    def test_case_insensitive_filename(self):
        _write_trasmittal(self.tmp, "25089", 2, filename="TRANSMITTAL 25089-2.PDF")
        from core.services.trasmittal_archivio import lista_trasmittal

        items = lista_trasmittal("25089")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 2)

    def test_italian_spelling_trasmittal(self):
        _write_trasmittal(self.tmp, "25089", 2, filename="Trasmittal 25089-2.pdf")
        from core.services.trasmittal_archivio import lista_trasmittal

        items = lista_trasmittal("25089")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 2)
        self.assertEqual(items[0]["nome"], "Trasmittal 25089-2.pdf")

    def test_leading_zeros_in_number(self):
        _write_trasmittal(self.tmp, "25089", 1, filename="Transmittal 25089-01.pdf")
        from core.services.trasmittal_archivio import lista_trasmittal

        items = lista_trasmittal("25089")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], 1)
        self.assertEqual(items[0]["nome"], "Transmittal 25089-01.pdf")

    def test_missing_folder_returns_empty(self):
        from core.services.trasmittal_archivio import lista_trasmittal

        self.assertEqual(lista_trasmittal("25089"), [])

    def test_percorso_found(self):
        _write_trasmittal(self.tmp, "25089", 7, content=b"%PDF-1.4")
        from core.services.trasmittal_archivio import percorso_trasmittal

        path = percorso_trasmittal("25089", 7)
        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "Transmittal 25089-7.pdf")
        self.assertEqual(path, _trasmittal_path(self.tmp, "25089", 7))

    def test_percorso_resolves_padded_filename(self):
        written = _write_trasmittal(self.tmp, "25089", 1, filename="Transmittal 25089-01.pdf")
        from core.services.trasmittal_archivio import percorso_trasmittal

        path = percorso_trasmittal("25089", 1)
        self.assertEqual(path, written)
        self.assertEqual(path.name, "Transmittal 25089-01.pdf")

    def test_sync_imports_italian_padded_filename(self):
        Testata.objects.create(job="25089")
        _write_trasmittal(self.tmp, "25089", 1, filename="Trasmittal 25089-01.pdf")
        from core.services.trasmittal_archivio import sync_trasmittal_da_cartella

        created = sync_trasmittal_da_cartella("25089")
        self.assertEqual(created, 1)
        row = Transmittal.objects.get(testata_id="25089", numero=1)
        self.assertIsNotNone(row.data_emissione)

    def test_percorso_wrong_job_not_found(self):
        _write_trasmittal(self.tmp, "25089", 7)
        from core.services.trasmittal_archivio import percorso_trasmittal

        with self.assertRaises(FileNotFoundError):
            percorso_trasmittal("25056", 7)

    def test_lists_from_da_spedire_when_dcc_missing(self):
        folder = Path(self.tmp) / "25089" / "PROGETTO" / "DCC" / "DA SPEDIRE" / "TRANSMITTAL"
        folder.mkdir(parents=True)
        (folder / "Transmittal 25089-5.pdf").write_bytes(b"%PDF")
        from core.services.trasmittal_archivio import (
            cartella_trasmittal,
            lista_trasmittal,
            trasmittal_in_da_spedire,
        )

        items = lista_trasmittal("25089")
        self.assertEqual([i["id"] for i in items], [5])
        self.assertTrue(trasmittal_in_da_spedire("25089"))
        self.assertEqual(cartella_trasmittal("25089"), folder)

    def test_prefers_dcc_over_da_spedire(self):
        _write_trasmittal(self.tmp, "25089", 1)
        fallback = Path(self.tmp) / "25089" / "PROGETTO" / "DCC" / "DA SPEDIRE" / "TRANSMITTAL"
        fallback.mkdir(parents=True)
        (fallback / "Transmittal 25089-9.pdf").write_bytes(b"%PDF")
        from core.services.trasmittal_archivio import lista_trasmittal, trasmittal_in_da_spedire

        items = lista_trasmittal("25089")
        self.assertEqual([i["id"] for i in items], [1])
        self.assertFalse(trasmittal_in_da_spedire("25089"))


class TrasmittalStoricoApiTest(TestCase):
    """API tests for transmittal history and file serve."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.user = User.objects.create_user(
            "testuser_trasmittal", password="pw", permesso=Permesso.READING
        )
        self.client = Client()
        self.client.force_login(self.user)
        Testata.objects.create(job="25089")

    def tearDown(self):
        self.patcher.stop()

    def test_storico_lists_files(self):
        _write_trasmittal(self.tmp, "25089", 1)
        _write_trasmittal(self.tmp, "25089", 4)
        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([i["id"] for i in items], [4, 1])
        self.assertTrue(all(i.get("data") for i in items))
        self.assertEqual(Transmittal.objects.filter(testata_id="25089").count(), 2)

    def test_storico_lists_db_rows_without_file(self):
        Transmittal.objects.create(
            testata_id="25089",
            numero=8,
            data_emissione="2026-09-02",
        )
        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual(items[0]["id"], 8)
        self.assertEqual(items[0]["codice"], "25089-8")
        self.assertEqual(items[0]["data"], "2026-09-02")

    def test_storico_does_not_overwrite_existing_row(self):
        Transmittal.objects.create(
            testata_id="25089",
            numero=1,
            data_emissione="2020-01-01",
        )
        _write_trasmittal(self.tmp, "25089", 1)
        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        row = Transmittal.objects.get(testata_id="25089", numero=1)
        self.assertEqual(str(row.data_emissione), "2020-01-01")

    def test_storico_skips_sync_when_job_already_has_rows(self):
        Transmittal.objects.create(
            testata_id="25089",
            numero=1,
            data_emissione="2020-01-01",
        )
        _write_trasmittal(self.tmp, "25089", 9)
        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["id"] for i in response.json()["items"]], [1])
        self.assertFalse(Transmittal.objects.filter(testata_id="25089", numero=9).exists())

    def test_storico_empty_includes_cartella_and_formato(self):
        from core.services.trasmittal_archivio import (
            cartella_trasmittal_canonica,
            formato_nome_file,
        )

        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["items"], [])
        self.assertEqual(body["cartella"], str(cartella_trasmittal_canonica("25089")))
        self.assertEqual(body["formato"], formato_nome_file("25089"))
        self.assertEqual(body["formato"], "Transmittal 25089-{n}.pdf")
        self.assertFalse(body["in_da_spedire"])

    def test_storico_reads_from_da_spedire_and_flags(self):
        folder = Path(self.tmp) / "25089" / "PROGETTO" / "DCC" / "DA SPEDIRE" / "TRANSMITTAL"
        folder.mkdir(parents=True)
        (folder / "Transmittal 25089-4.pdf").write_bytes(b"%PDF")
        # Tabella vuota: la lettura in GET la popola dalla cartella.
        response = self.client.get("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["in_da_spedire"])
        self.assertEqual([i["id"] for i in body["items"]], [4])
        self.assertTrue(Transmittal.objects.filter(testata_id="25089", numero=4).exists())

    def test_storico_force_sync_imports_new_files(self):
        Transmittal.objects.create(
            testata_id="25089",
            numero=1,
            data_emissione="2020-01-01",
        )
        _write_trasmittal(self.tmp, "25089", 9)
        # La risincronizzazione forzata scrive: è un POST riservato a chi scrive.
        writer = User.objects.create_user(
            "storico_writer", "storico-writer@b.it", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(writer)
        response = self.client.post("/api/commesse/25089/trasmittal/storico/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["id"] for i in response.json()["items"]], [9, 1])
        self.assertTrue(Transmittal.objects.filter(testata_id="25089", numero=9).exists())

    def test_storico_force_sync_negata_a_chi_legge_soltanto(self):
        _write_trasmittal(self.tmp, "25089", 9)
        Transmittal.objects.create(testata_id="25089", numero=1, data_emissione="2020-01-01")

        response = self.client.post("/api/commesse/25089/trasmittal/storico/")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Transmittal.objects.filter(testata_id="25089", numero=9).exists())
        # In GET un lettore vede comunque l'elenco (senza risincronizzare).
        self.assertEqual(
            [
                i["id"]
                for i in self.client.get("/api/commesse/25089/trasmittal/storico/").json()["items"]
            ],
            [1],
        )

    def test_storico_unknown_job(self):
        response = self.client.get("/api/commesse/NOPE/trasmittal/storico/")
        self.assertEqual(response.status_code, 404)

    def test_storico_requires_auth(self):
        response = Client().get("/api/commesse/25089/trasmittal/storico/")
        self.assertIn(response.status_code, [302, 401, 403])

    def test_serve_pdf_inline(self):
        _write_trasmittal(self.tmp, "25089", 12, content=b"%PDF-fake")
        response = self.client.get("/api/commesse/25089/trasmittal/12/file/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(b"%PDF-fake", b"".join(response.streaming_content))

    def test_serve_missing_id(self):
        response = self.client.get("/api/commesse/25089/trasmittal/99/file/")
        self.assertEqual(response.status_code, 404)

    def test_serve_other_job_file_hidden(self):
        _write_trasmittal(self.tmp, "11111", 1)
        response = self.client.get("/api/commesse/25089/trasmittal/1/file/")
        self.assertEqual(response.status_code, 404)

    def test_prossimo_api(self):
        from core.services.trasmittal_archivio import percorso_previsto

        _write_trasmittal(self.tmp, "25089", 3)
        Transmittal.objects.create(testata_id="25089", numero=5, data_emissione="2026-01-01")
        response = self.client.get("/api/commesse/25089/trasmittal/prossimo/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "numero": 6,
                "codice": "25089-6",
                "percorso": str(percorso_previsto("25089", 6)),
            },
        )


class TransmittalArchivioServiceTest(TestCase):
    """DB + filesystem tests for transmittal numbering and emission archive."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.testata = Testata.objects.create(job="25089")
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="25089-A")
        self.rev = Revisione.objects.create(documento=self.doc, rev_no=0)

    def tearDown(self):
        self.patcher.stop()

    def test_prossimo_numero_from_files_and_db(self):
        from core.services.trasmittal_archivio import prossimo_numero

        _write_trasmittal(self.tmp, "25089", 3)
        Transmittal.objects.create(testata=self.testata, numero=5, data_emissione="2026-01-01")
        self.assertEqual(prossimo_numero("25089"), 6)

    def test_emetti_e_archivia_writes_file_and_links_revs(self):
        from core.services.trasmittal_archivio import emetti_e_archivia

        result = emetti_e_archivia("25089", [self.doc.pk], "2026-09-02", b"%PDF-emit")
        self.assertEqual(result["trasmittal"]["id"], 1)
        self.assertEqual(result["trasmittal"]["codice"], "25089-1")
        dest = _trasmittal_path(self.tmp, "25089", 1)
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), b"%PDF-emit")
        row = Transmittal.objects.get(testata=self.testata, numero=1)
        self.assertEqual(str(row.data_emissione), "2026-09-02")
        self.assertEqual(list(row.revisioni.values_list("pk", flat=True)), [self.rev.pk])
        self.rev.refresh_from_db()
        self.assertEqual(self.rev.int_status, "inviato_al_cliente")

    def test_annulla_restores_and_reuses_numero(self):
        from core.services.trasmittal_archivio import (
            annulla_trasmittal,
            emetti_e_archivia,
            lista_storico,
            prossimo_numero,
        )

        emetti_e_archivia("25089", [self.doc.pk], "2026-09-02", b"%PDF-emit")
        dest = _trasmittal_path(self.tmp, "25089", 1)
        self.assertTrue(dest.is_file())
        items = lista_storico("25089")
        self.assertTrue(items[0]["annullabile"])

        annulla_trasmittal("25089", 1)
        self.rev.refresh_from_db()
        self.assertEqual(self.rev.int_status, "")
        self.assertIsNone(self.rev.dis_act_date)
        self.assertIsNone(self.rev.rec_plan_date)
        self.assertFalse(Transmittal.objects.filter(testata=self.testata, numero=1).exists())
        self.assertFalse(dest.is_file())
        self.assertEqual(prossimo_numero("25089"), 1)

    def test_annulla_rejects_not_latest(self):
        from core.services.trasmittal_archivio import TrasmittalAnnullaError, emetti_e_archivia

        emetti_e_archivia("25089", [self.doc.pk], "2026-09-02", b"%PDF-1")
        doc2 = Documento.objects.create(testata=self.testata, vendor_doc="25089-B")
        Revisione.objects.create(documento=doc2, rev_no=0)
        emetti_e_archivia("25089", [doc2.pk], "2026-09-03", b"%PDF-2")
        from core.services.trasmittal_archivio import annulla_trasmittal

        with self.assertRaises(TrasmittalAnnullaError):
            annulla_trasmittal("25089", 1)

    def test_annulla_rejects_legacy_without_revs(self):
        from core.services.trasmittal_archivio import TrasmittalAnnullaError, annulla_trasmittal

        Transmittal.objects.create(testata=self.testata, numero=1, data_emissione="2026-01-01")
        with self.assertRaises(TrasmittalAnnullaError):
            annulla_trasmittal("25089", 1)

    def test_annulla_rejects_already_received(self):
        from core.services.trasmittal_archivio import (
            TrasmittalAnnullaError,
            annulla_trasmittal,
            emetti_e_archivia,
        )

        emetti_e_archivia("25089", [self.doc.pk], "2026-09-02", b"%PDF-emit")
        self.rev.refresh_from_db()
        self.rev.int_status = "ricevuto"
        self.rev.rec_act_date = "2026-09-10"
        self.rev.save(update_fields=["int_status", "rec_act_date"])
        with self.assertRaises(TrasmittalAnnullaError):
            annulla_trasmittal("25089", 1)


class EmissioneArchiviaApiTest(TestCase):
    """POST /api/emissione/ archives the PDF and returns transmittal id."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.pdf_patcher = patch("core.views.genera_trasmittal_pdf", return_value=b"%PDF-api")
        self.pdf_patcher.start()
        self.user = User.objects.create_user(
            "testuser_emit_tr", password="pw", permesso=Permesso.WRITING
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.testata = Testata.objects.create(job="25089")
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="25089-A")
        Revisione.objects.create(documento=self.doc, rev_no=0)

    def tearDown(self):
        self.pdf_patcher.stop()
        self.patcher.stop()

    def test_emissione_saves_pdf_and_row(self):
        response = self.client.post(
            "/api/emissione/",
            data=json.dumps(
                {
                    "doc_ids": [self.doc.pk],
                    "dis_act_date": "2026-09-02",
                    "job": "25089",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["trasmittal"]["id"], 1)
        self.assertTrue(_trasmittal_path(self.tmp, "25089", 1).is_file())
        self.assertTrue(Transmittal.objects.filter(testata_id="25089", numero=1).exists())

    def test_annulla_api(self):
        emit = self.client.post(
            "/api/emissione/",
            data=json.dumps(
                {"doc_ids": [self.doc.pk], "dis_act_date": "2026-09-02", "job": "25089"}
            ),
            content_type="application/json",
        )
        self.assertEqual(emit.status_code, 200)
        response = self.client.post("/api/commesse/25089/trasmittal/1/annulla/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(Transmittal.objects.filter(testata_id="25089", numero=1).exists())
        self.assertFalse(_trasmittal_path(self.tmp, "25089", 1).is_file())

    def test_annulla_api_requires_write(self):
        User.objects.create_user(
            "reader_tr",
            email="reader_tr@example.com",
            password="pw",
            permesso=Permesso.READING,
        )
        reader = Client()
        reader.force_login(User.objects.get(username="reader_tr"))
        Transmittal.objects.create(testata=self.testata, numero=1, data_emissione="2026-09-02")
        response = reader.post("/api/commesse/25089/trasmittal/1/annulla/")
        self.assertEqual(response.status_code, 403)

    def test_emissione_rifiuta_documenti_di_un_altra_commessa(self):
        """Il trasmittal nasce sulla commessa indicata: un documento di un'altra
        commessa non va emesso (né la sua revisione marcata "inviata") sotto
        il numero di trasmittal sbagliato."""
        altra = Testata.objects.create(job="25090")
        doc_altra = Documento.objects.create(testata=altra, vendor_doc="25090-A")
        rev_altra = Revisione.objects.create(documento=doc_altra, rev_no=0)

        response = self.client.post(
            "/api/emissione/",
            data=json.dumps(
                {
                    "doc_ids": [self.doc.pk, doc_altra.pk],
                    "dis_act_date": "2026-09-02",
                    "job": "25089",
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("non appartengono alla commessa", response.json()["error"])
        self.assertFalse(Transmittal.objects.exists())
        rev_altra.refresh_from_db()
        self.assertEqual(rev_altra.int_status, "")
        self.assertIsNone(rev_altra.dis_act_date)

    def test_emissione_rifiuta_doc_ids_non_numerici(self):
        response = self.client.post(
            "/api/emissione/",
            data=json.dumps({"doc_ids": ["abc"], "dis_act_date": "2026-09-02", "job": "25089"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "doc_ids non validi.")
