import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from .models import Documento, Reparto, Revisione, RevisioneFileLink, Testata
from .services.commesse import risolvi_file_revisione, salva_file_link

User = get_user_model()


# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────


def _make_fixtures_mock(reparto_acronimo: str = "QC"):
    """Create DB objects for unit tests that mock the filesystem.

    Args:
        reparto_acronimo: Acronimo to assign to the test reparto.

    Returns:
        Dict with created model instances keyed by name.
    """
    reparto = Reparto.objects.create(nome="Qualità e Controllo", acronimo=reparto_acronimo)
    testata = Testata.objects.create(job="25056")

    doc_qmdbi = Documento.objects.create(
        testata=testata,
        vendor_doc="25056-QMDBI",
        reparto=reparto.nome,
    )
    doc_qcpa = Documento.objects.create(
        testata=testata,
        vendor_doc="25056-01-QCPA",
        reparto=reparto.nome,
    )

    rev_qmdbi_0 = Revisione.objects.create(
        documento=doc_qmdbi,
        rev_no=0,
        dis_act_date="2025-09-05",
        rec_act_date="2025-11-17",
    )
    rev_qcpa_0 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=0,
        dis_act_date="2025-09-05",
        rec_act_date="2025-10-14",
    )
    rev_qcpa_1 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=1,
        dis_act_date="2025-11-07",
        rec_act_date="2025-11-10",
    )
    rev_qcpa_2 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=2,
        dis_act_date="2025-11-13",
        rec_act_date="2025-11-16",
    )

    return {
        "reparto": reparto,
        "testata": testata,
        "doc_qmdbi": doc_qmdbi,
        "doc_qcpa": doc_qcpa,
        "rev_qmdbi_0": rev_qmdbi_0,
        "rev_qcpa_0": rev_qcpa_0,
        "rev_qcpa_1": rev_qcpa_1,
        "rev_qcpa_2": rev_qcpa_2,
    }


# ── Unit tests (mock filesystem) ─────────────────────────────────────────────


class RisolviFileRevisioneTest(TestCase):
    """Unit tests for ``risolvi_file_revisione`` using a mocked filesystem."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.objs = _make_fixtures_mock()

    def tearDown(self):
        self.patcher.stop()

    def _ricevuti(self, date_str: str) -> Path:
        d = Path(self.tmp) / "25056" / "PROGETTO" / "QC" / "RICEVUTI" / date_str
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _base(self) -> Path:
        d = Path(self.tmp) / "25056" / "PROGETTO" / "QC"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_found_single_file_in_ricevuti(self):
        d = self._ricevuti("2025-11-17")
        (d / "25056-QMDBI Rev0.pdf").touch()

        result = risolvi_file_revisione(self.objs["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "found")
        self.assertEqual(len(result["files"]), 1)
        self.assertEqual(result["files"][0]["nome"], "25056-QMDBI Rev0.pdf")

    def test_multiple_files_in_ricevuti(self):
        d = self._ricevuti("2025-11-17")
        (d / "25056-QMDBI Rev0.pdf").touch()
        (d / "25056-QMDBI Rev0 Annotated.pdf").touch()

        result = risolvi_file_revisione(self.objs["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "multiple")
        self.assertEqual(len(result["files"]), 2)

    def test_not_found_no_matching_file(self):
        d = self._ricevuti("2025-11-17")
        (d / "OTHER-DOC.pdf").touch()

        result = risolvi_file_revisione(self.objs["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "not_found")

    def test_not_found_missing_directory(self):
        result = risolvi_file_revisione(self.objs["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "not_found")

    def test_found_in_base_path_when_only_sent(self):
        """Revision with dis_act_date only → look in base path."""
        rev_sent = Revisione.objects.create(
            documento=self.objs["doc_qcpa"],
            rev_no=3,
            dis_act_date="2025-12-01",
            rec_act_date=None,
        )
        d = self._base()
        (d / "25056-01-QCPA Rev3.pdf").touch()

        result = risolvi_file_revisione(rev_sent.pk)
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["files"][0]["estensione"], "pdf")

    def test_not_found_no_dates(self):
        """Revision with neither date → not_found."""
        rev_none = Revisione.objects.create(documento=self.objs["doc_qcpa"], rev_no=4)
        result = risolvi_file_revisione(rev_none.pk)
        self.assertEqual(result["status"], "not_found")

    def test_manual_link_takes_priority(self):
        d = self._ricevuti("2025-11-17")
        (d / "25056-QMDBI Rev0.pdf").touch()
        manual_path = str(Path(self.tmp) / "25056" / "PROGETTO" / "QC" / "25056-QMDBI-MANUAL.pdf")
        RevisioneFileLink.objects.create(
            revisione=self.objs["rev_qmdbi_0"],
            percorso=manual_path,
        )

        result = risolvi_file_revisione(self.objs["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "manual_linked")
        self.assertEqual(result["files"][0]["percorso"], manual_path)

    def test_qcpa_each_revision_in_own_date_folder(self):
        """Each QCPA revision must resolve in its own RICEVUTI date folder."""
        cases = [
            ("rev_qcpa_0", "2025-10-14"),
            ("rev_qcpa_1", "2025-11-10"),
            ("rev_qcpa_2", "2025-11-16"),
        ]
        for rev_key, date_str in cases:
            d = self._ricevuti(date_str)
            (d / f"25056-01-QCPA_{date_str}.pdf").touch()
            result = risolvi_file_revisione(self.objs[rev_key].pk)
            self.assertEqual(result["status"], "found", f"Expected found for {rev_key}")


class SalvaFileLinkTest(TestCase):
    """Unit tests for ``salva_file_link``."""

    def setUp(self):
        objs = _make_fixtures_mock()
        self.rev = objs["rev_qmdbi_0"]

    def test_create_link(self):
        path = r"Z:\JOBS\25056\PROGETTO\QC\25056-QMDBI Rev0.pdf"
        link = salva_file_link(self.rev.pk, path)
        self.assertEqual(link.percorso, path)
        self.assertEqual(RevisioneFileLink.objects.count(), 1)

    def test_update_existing_link(self):
        salva_file_link(self.rev.pk, r"Z:\JOBS\25056\old.pdf")
        salva_file_link(self.rev.pk, r"Z:\JOBS\25056\new.pdf")
        self.assertEqual(RevisioneFileLink.objects.count(), 1)
        self.assertEqual(
            RevisioneFileLink.objects.get(revisione=self.rev).percorso,
            r"Z:\JOBS\25056\new.pdf",
        )


class FileBrowserApiTest(TestCase):
    """Unit tests for the fileserver browse API using a mocked filesystem."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.user = User.objects.create_user("testuser_browse", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    def tearDown(self):
        self.patcher.stop()

    def test_browse_root(self):
        (Path(self.tmp) / "25056").mkdir()
        response = self.client.get("/api/fileserver/browse/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("dirs", data)
        self.assertIn("files", data)
        self.assertIsNone(data["parent"])
        self.assertIn("25056", [d["nome"] for d in data["dirs"]])

    def test_browse_subdir(self):
        subdir = Path(self.tmp) / "25056"
        subdir.mkdir()
        (subdir / "test.pdf").touch()
        response = self.client.get("/api/fileserver/browse/", {"path": str(subdir)})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["parent"], self.tmp)
        self.assertIn("test.pdf", [f["nome"] for f in data["files"]])

    def test_browse_outside_root_forbidden(self):
        response = self.client.get("/api/fileserver/browse/", {"path": "C:\\Windows"})
        self.assertEqual(response.status_code, 403)

    def test_browse_nonexistent_path(self):
        response = self.client.get(
            "/api/fileserver/browse/",
            {"path": str(Path(self.tmp) / "doesnotexist")},
        )
        self.assertEqual(response.status_code, 404)

    def test_browse_requires_auth(self):
        response = Client().get("/api/fileserver/browse/")
        self.assertIn(response.status_code, [302, 401, 403])


class RevisioneFileMockApiTest(TestCase):
    """Unit tests for the revision file API endpoints using a mocked filesystem."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.user = User.objects.create_user("testuser_api", password="pw")
        self.client = Client()
        self.client.force_login(self.user)
        objs = _make_fixtures_mock()
        self.rev = objs["rev_qmdbi_0"]

    def tearDown(self):
        self.patcher.stop()

    def test_resolve_found(self):
        d = Path(self.tmp) / "25056" / "PROGETTO" / "QC" / "RICEVUTI" / "2025-11-17"
        d.mkdir(parents=True)
        (d / "25056-QMDBI Rev0.pdf").touch()

        response = self.client.get(f"/api/revisioni/{self.rev.pk}/file/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "found")
        self.assertEqual(len(data["files"]), 1)

    def test_resolve_not_found(self):
        response = self.client.get(f"/api/revisioni/{self.rev.pk}/file/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "not_found")

    def test_resolve_nonexistent_revision(self):
        response = self.client.get("/api/revisioni/999999/file/")
        self.assertEqual(response.status_code, 404)

    def test_save_link(self):
        path = str(Path(self.tmp) / "25056" / "test.pdf")
        response = self.client.post(
            f"/api/revisioni/{self.rev.pk}/file/link/",
            data=json.dumps({"percorso": path}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["percorso"], path)
        self.assertTrue(RevisioneFileLink.objects.filter(revisione=self.rev).exists())

    def test_save_link_missing_percorso(self):
        response = self.client.post(
            f"/api/revisioni/{self.rev.pk}/file/link/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)

    def test_save_link_requires_auth(self):
        response = Client().post(
            f"/api/revisioni/{self.rev.pk}/file/link/",
            data=json.dumps({"percorso": "Z:\\x.pdf"}),
            content_type="application/json",
        )
        self.assertIn(response.status_code, [302, 401, 403])


# ── Integration tests (real fileserver Z:\JOBS) ───────────────────────────────


def _make_integration_fixtures():
    """Create DB fixtures pointing to the real fileserver structure.

    Both documents are under Z:\\JOBS\\25056\\PROGETTO\\QC\\ as observed on the
    real fileserver. This creates fresh records in the test DB.

    Returns:
        Dict with Revisione instances keyed by name.
    """
    import datetime

    reparto, _ = Reparto.objects.get_or_create(
        acronimo="QC",
        defaults={"nome": "Qualità e Controllo"},
    )
    testata, _ = Testata.objects.get_or_create(
        job="25056",
        defaults={"client": "Test", "job_detail": "Integration test"},
    )
    doc_qmdbi, _ = Documento.objects.get_or_create(
        testata=testata,
        vendor_doc="25056-QMDBI",
        defaults={"reparto": reparto.nome, "doc_title": "QMDBI"},
    )
    doc_qcpa, _ = Documento.objects.get_or_create(
        testata=testata,
        vendor_doc="25056-01-QCPA",
        defaults={"reparto": reparto.nome, "doc_title": "QCPA"},
    )

    rev_qmdbi_0, _ = Revisione.objects.get_or_create(
        documento=doc_qmdbi,
        rev_no=0,
        defaults={
            "dis_act_date": datetime.date(2025, 9, 5),
            "rec_act_date": datetime.date(2025, 11, 17),
        },
    )
    rev_qcpa_0, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=0,
        defaults={
            "dis_act_date": datetime.date(2025, 9, 5),
            "rec_act_date": datetime.date(2025, 10, 14),
        },
    )
    rev_qcpa_1, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=1,
        defaults={
            "dis_act_date": datetime.date(2025, 11, 7),
            "rec_act_date": datetime.date(2025, 11, 10),
        },
    )
    rev_qcpa_2, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=2,
        defaults={
            "dis_act_date": datetime.date(2025, 11, 13),
            "rec_act_date": datetime.date(2025, 11, 16),
        },
    )

    return {
        "rev_qmdbi_0": rev_qmdbi_0,
        "rev_qcpa_0": rev_qcpa_0,
        "rev_qcpa_1": rev_qcpa_1,
        "rev_qcpa_2": rev_qcpa_2,
    }


class FileserverIntegrationTest(TestCase):
    """Integration tests against the real fileserver at Z:\\JOBS.

    These tests create their own DB fixtures in the test database and access
    the real fileserver at Z:\\JOBS (no mocking). The test is skipped
    automatically if the fileserver is not reachable.

    Expected results based on real fileserver content at Z:\\JOBS\\25056\\PROGETTO\\QC\\:
        - QMDBI Rev.0  (rec=2025-11-17): 1 file  → found
        - QCPA  Rev.0  (rec=2025-10-14): 1 file  → found
        - QCPA  Rev.1  (rec=2025-11-10): 3 files → multiple
        - QCPA  Rev.2  (rec=2025-11-16): 1 file  → found
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.conf import settings

        cls.jobs_root = Path(settings.FILESERVER_JOBS_PATH)
        cls.fileserver_available = cls.jobs_root.exists()

    def setUp(self):
        if not self.fileserver_available:
            self.skipTest(f"Fileserver non raggiungibile: {self.jobs_root}")
        self.fixtures = _make_integration_fixtures()
        self.user = User.objects.create_user("integration_user", password="pw")
        self.client = Client()
        self.client.force_login(self.user)

    def tearDown(self):
        RevisioneFileLink.objects.filter(revisione__in=self.fixtures.values()).delete()

    # ── risolvi_file_revisione ────────────────────────────────────────────────

    def test_qmdbi_rev0_found(self):
        """QMDBI Rev.0 ricevuta 17/11/25 → deve trovare 1 file."""
        result = risolvi_file_revisione(self.fixtures["rev_qmdbi_0"].pk)
        self.assertIn(
            result["status"],
            ("found", "multiple"),
            f"Atteso found/multiple, ottenuto {result['status']}.\n"
            f"Cerca in: Z:\\JOBS\\25056\\PROGETTO\\QC\\RICEVUTI\\2025-11-17\\",
        )
        if result["status"] == "found":
            self.assertEqual(len(result["files"]), 1)
            nome = result["files"][0]["nome"]
            self.assertTrue(
                nome.lower().startswith("25056-qmdbi"),
                f"Nome file inatteso: {nome!r}",
            )

    def test_qcpa_rev0_found(self):
        """QCPA Rev.0 ricevuta 14/10/25 → deve trovare 1 file."""
        result = risolvi_file_revisione(self.fixtures["rev_qcpa_0"].pk)
        self.assertIn(
            result["status"],
            ("found", "multiple"),
            f"Atteso found/multiple, ottenuto {result['status']}.\n"
            f"Cerca in: Z:\\JOBS\\25056\\PROGETTO\\QC\\RICEVUTI\\2025-10-14\\",
        )

    def test_qcpa_rev1_multiple(self):
        """QCPA Rev.1 ricevuta 10/11/25 → più file presenti → multiple."""
        result = risolvi_file_revisione(self.fixtures["rev_qcpa_1"].pk)
        self.assertEqual(
            result["status"],
            "multiple",
            f"Atteso multiple (3 file noti), ottenuto {result['status']}.\n"
            f"File trovati: {[f['nome'] for f in result['files']]}",
        )
        self.assertEqual(
            len(result["files"]),
            3,
            f"Attesi 3 file, trovati {len(result['files'])}: "
            f"{[f['nome'] for f in result['files']]}",
        )

    def test_qcpa_rev2_found(self):
        """QCPA Rev.2 ricevuta 16/11/25 → deve trovare 1 file."""
        result = risolvi_file_revisione(self.fixtures["rev_qcpa_2"].pk)
        self.assertIn(
            result["status"],
            ("found", "multiple"),
            f"Atteso found/multiple, ottenuto {result['status']}.\n"
            f"Cerca in: Z:\\JOBS\\25056\\PROGETTO\\QC\\RICEVUTI\\2025-11-16\\",
        )

    def test_manual_link_overrides_filesystem(self):
        """Se salvo un link manuale, risolvi deve restituire quello, non il file FS."""
        real_file = str(
            self.jobs_root
            / "25056"
            / "PROGETTO"
            / "QC"
            / "RICEVUTI"
            / "2025-11-17"
            / "25056-QMDBI rev.0 - commented.pdf"
        )
        salva_file_link(self.fixtures["rev_qmdbi_0"].pk, real_file)
        result = risolvi_file_revisione(self.fixtures["rev_qmdbi_0"].pk)
        self.assertEqual(result["status"], "manual_linked")
        self.assertEqual(result["files"][0]["percorso"], real_file)

    # ── API endpoint ─────────────────────────────────────────────────────────

    def test_api_resolve_qmdbi_rev0(self):
        """GET /api/revisioni/{pk}/file/ deve restituire found o multiple."""
        pk = self.fixtures["rev_qmdbi_0"].pk
        response = self.client.get(f"/api/revisioni/{pk}/file/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn(
            data["status"],
            ("found", "multiple"),
            f"Ottenuto {data['status']}; files={data.get('files')}",
        )

    def test_api_resolve_qcpa_rev1_multiple(self):
        """GET /api/revisioni/{pk}/file/ per Rev.1 QCPA deve restituire multiple."""
        pk = self.fixtures["rev_qcpa_1"].pk
        response = self.client.get(f"/api/revisioni/{pk}/file/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["status"],
            "multiple",
            f"Atteso multiple, ottenuto {data['status']}; "
            f"files={[f['nome'] for f in data.get('files', [])]}",
        )

    def test_api_save_and_resolve_manual_link(self):
        """POST link → GET risolve manual_linked."""
        pk = self.fixtures["rev_qmdbi_0"].pk
        real_file = str(
            self.jobs_root
            / "25056"
            / "PROGETTO"
            / "QC"
            / "RICEVUTI"
            / "2025-11-17"
            / "25056-QMDBI rev.0 - commented.pdf"
        )
        resp = self.client.post(
            f"/api/revisioni/{pk}/file/link/",
            data=json.dumps({"percorso": real_file}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)

        resp2 = self.client.get(f"/api/revisioni/{pk}/file/")
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "manual_linked")
