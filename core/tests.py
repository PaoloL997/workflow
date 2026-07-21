import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, TestCase
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import (
    Documento,
    Permesso,
    Reparto,
    Revisione,
    RevisioneFileLink,
    StatoEsterno,
    Testata,
)
from .services.commesse import risolvi_file_revisione, salva_file_link
from .services.import_old import importa_commessa_da_access
from .services.revisione_anomalie import (
    audit_commessa,
    audit_commessa_summary,
    audit_revisione,
    classifica_revisione,
    ignora_anomalie_revisione,
    serialize_anomalie_gruppi,
)
from .services.revisione_sblocco import list_revisioni_sbloccabili, sblocca_revisione
from .services.revisioni_cleanup import drop_orphan_revisioni, find_orphan_indices

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
        self.user = User.objects.create_user(
            "testuser_browse", password="pw", permesso=Permesso.WRITING
        )
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
        self.user = User.objects.create_user(
            "testuser_api", password="pw", permesso=Permesso.WRITING
        )
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
        self.user = User.objects.create_user(
            "integration_user", password="pw", permesso=Permesso.WRITING
        )
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
        self.assertFalse(self.writing_user.is_staff)
        self.assertFalse(self.reading_user.is_staff)


class RevisioniCleanupTests(TestCase):
    def test_single_orphan_after_approved(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisActDate": "2025-01-01",
                    "RecActDate": "2025-01-10",
                    "Status": "C",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisActDate": "2025-02-01",
                    "RecActDate": "2025-02-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 2,
                    "DisActDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        orphans = find_orphan_indices(df)
        self.assertEqual(orphans, {2})
        cleaned = drop_orphan_revisioni(df)
        self.assertEqual(len(cleaned), 2)

    def test_consecutive_orphans_removed(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisActDate": "2025-01-01",
                    "RecActDate": "2025-01-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisActDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 2,
                    "DisActDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        orphans = find_orphan_indices(df)
        self.assertEqual(orphans, {1, 2})

    def test_not_orphan_when_dis_act_date_present(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisActDate": "2025-01-01",
                    "RecActDate": "2025-01-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisActDate": "2025-02-01",
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        self.assertEqual(find_orphan_indices(df), set())


class RevisioneAnomalieTests(TestCase):
    def setUp(self):
        self.approved = StatoEsterno.objects.create(nome="Approved", colore="#00B050")
        self.rejected = StatoEsterno.objects.create(
            nome="Rejected - Work can not proceed", colore="#D61D09"
        )
        self.testata = Testata.objects.create(job="25012", time_cli_doc_rev=21)
        self.doc = Documento.objects.create(
            testata=self.testata,
            vendor_doc="25012-01-4005",
            doc_title="Test doc",
        )

    def test_empty_revision_not_anomalous(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=1, dis_plan_date="2026-03-01")
        self.assertEqual(audit_revisione(rev), [])

    def test_risposta_senza_ricezione(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            dis_act_date="2026-02-26",
            ext_status=self.approved,
        )
        codes = [a.codice for a in audit_revisione(rev, time_cli=21)]
        self.assertIn("RISPOSTA_SENZA_RICEZIONE", codes)
        self.assertIn("DISPATCH_SENZA_RIENTRO_PREV", codes)

    def test_inviato_senza_dispatch(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=4,
            int_status="inviato_al_cliente",
        )
        codes = [a.codice for a in audit_revisione(rev)]
        self.assertEqual(codes, ["INVIATO_SENZA_DISPATCH"])

    def test_empty_after_approved_not_anomalous(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_act_date="2025-01-01",
            rec_act_date="2025-01-10",
            ext_status=self.approved,
            int_status="ricevuto",
        )
        rev1 = Revisione.objects.create(documento=self.doc, rev_no=1)
        self.assertEqual(audit_revisione(rev1), [])
        self.assertEqual(audit_commessa("25012"), [])

    def test_post_ricezione_pending_emission_not_anomalous(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_act_date="2025-01-01",
            rec_act_date="2025-01-10",
            ext_status=self.rejected,
            int_status="ricevuto",
        )
        rev1 = Revisione.objects.create(
            documento=self.doc,
            rev_no=1,
            dis_plan_date="2025-01-24",
        )
        self.assertEqual(audit_revisione(rev1), [])
        self.assertEqual(audit_commessa("25012"), [])

    def test_int_status_incongruente_ricevuto_senza_data(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            int_status="ricevuto",
        )
        codes = [a.codice for a in audit_revisione(rev)]
        self.assertIn("INT_STATUS_INCONGRUENTE", codes)

    def test_classifica_conclusi_fixes_risposta_senza_ricezione(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            dis_act_date="2026-02-26",
            ext_status=self.approved,
        )
        result = classifica_revisione(
            "25012",
            rev.pk,
            "conclusi",
            {"rec_act_date": "2026-03-10"},
        )
        self.assertEqual(result["revisione"]["int_status"], "ricevuto")
        self.assertEqual(result["revisione"]["rec_act_date"], "2026-03-10")
        rev.refresh_from_db()
        self.assertEqual(audit_revisione(rev, time_cli=21), [])

    def test_classifica_da_emettere_clears_inviato_senza_dispatch(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=4,
            int_status="inviato_al_cliente",
        )
        classifica_revisione("25012", rev.pk, "da_emettere")
        rev.refresh_from_db()
        self.assertEqual(rev.int_status, "")
        self.assertEqual(audit_revisione(rev), [])

    def test_gruppi_marks_latest_revision(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            int_status="ricevuto",
            rec_act_date="2025-01-10",
            dis_act_date="2025-01-01",
            ext_status=self.approved,
        )
        rev1 = Revisione.objects.create(
            documento=self.doc,
            rev_no=1,
            int_status="inviato_al_cliente",
        )
        gruppi = serialize_anomalie_gruppi("25012", audit_commessa("25012"))
        self.assertEqual(len(gruppi), 1)
        self.assertEqual(gruppi[0]["revisione_id"], rev1.pk)
        self.assertTrue(gruppi[0]["is_latest"])
        self.assertEqual(gruppi[0]["suggest_bucket"], "da_ricevere")
        self.assertEqual(gruppi[0]["situazione_attuale"]["label"], "Da ricevere")

    def test_ignora_anomalie_esclude_revisione(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            dis_act_date="2026-02-26",
            ext_status=self.approved,
        )
        self.assertEqual(len(audit_commessa("25012")), 2)
        ignora_anomalie_revisione("25012", rev.pk)
        rev.refresh_from_db()
        self.assertTrue(rev.ignora_anomalie)
        self.assertEqual(audit_commessa("25012"), [])
        self.assertEqual(audit_commessa_summary("25012")["count"], 0)


class ImportOldTests(TestCase):
    def _frames(self):
        return {
            "testata": pd.DataFrame(
                [
                    {
                        "Job": "99999",
                        "Client": "Cliente Test",
                        "POno": "PO-1",
                        "JobDetail": "Dettaglio",
                        "DeliveryDate": None,
                        "DeliveryTerm": "",
                        "Requisition": "",
                        "TimeCliDocRev": None,
                        "TimeVenDocRev": None,
                        "RevLetFlag": False,
                    }
                ]
            ),
            "indirsped": pd.DataFrame(),
            "dettaglio": pd.DataFrame(
                [
                    {
                        "ItemNo": "1",
                        "VendorDoc": "99999-01",
                        "ClientDocNo": "",
                        "ClientDocClass": "",
                        "DocTitle": "Titolo",
                        "DocPenalty": False,
                        "DocPayment": False,
                        "RevGen": False,
                        "Reparto": 4,
                        "Remarks": "",
                    }
                ]
            ),
            "revisioni": pd.DataFrame(
                [
                    {
                        "VendorDoc": "99999-01",
                        "RevNo": 0,
                        "RevLet": "",
                        "DisPlanDate": None,
                        "DisActDate": "2025-01-01",
                        "RecPlanDate": None,
                        "RecActDate": "2025-01-10",
                        "Status": "A",
                    },
                    {
                        "VendorDoc": "99999-01",
                        "RevNo": 1,
                        "RevLet": "",
                        "DisPlanDate": None,
                        "DisActDate": None,
                        "RecPlanDate": None,
                        "RecActDate": None,
                        "Status": None,
                    },
                ]
            ),
        }

    @patch("core.services.import_old.fetch_commessa_frames")
    def test_import_includes_all_revisioni_and_reports_orphans(self, mock_fetch):
        mock_fetch.return_value = self._frames()
        result = importa_commessa_da_access("99999")
        self.assertEqual(result["documenti"], 1)
        self.assertEqual(result["revisioni"], 2)
        self.assertEqual(Revisione.objects.count(), 2)
        self.assertIn("anomalie", result)
        self.assertEqual(Revisione.objects.filter(rev_no=1).get().int_status, "")

    @patch("core.services.import_old.fetch_commessa_frames")
    def test_import_rejects_existing_job(self, mock_fetch):
        Testata.objects.create(job="99999")
        with self.assertRaises(ValueError):
            importa_commessa_da_access("99999")
        mock_fetch.assert_not_called()


class SituazioneApiTestCase(TestCase):
    """Tests for batch situazione/documenti API endpoints."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "situazione_user",
            "situazione@brembanarolle.com",
            "pw",
            permesso=Permesso.READING,
        )
        self.client.force_login(self.user)
        self.fixtures = _make_fixtures_mock()
        self.job = self.fixtures["testata"].job

    def test_situazione_api_returns_documenti_and_revisioni(self):
        response = self.client.get(f"/api/commesse/{self.job}/situazione/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["documenti"]), 2)
        revs_by_doc = data["revisioni_by_doc"]
        doc_qmdbi_id = str(self.fixtures["doc_qmdbi"].pk)
        doc_qcpa_id = str(self.fixtures["doc_qcpa"].pk)
        self.assertEqual(len(revs_by_doc[doc_qmdbi_id]), 1)
        self.assertEqual(len(revs_by_doc[doc_qcpa_id]), 3)

    def test_documenti_api_include_revisioni(self):
        response = self.client.get(f"/api/commesse/{self.job}/documenti/?include_revisioni=1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["documenti"]), 2)
        doc_qcpa_id = str(self.fixtures["doc_qcpa"].pk)
        self.assertEqual(len(data["revisioni_by_doc"][doc_qcpa_id]), 3)

    def test_situazione_api_requires_auth(self):
        self.client.logout()
        response = self.client.get(f"/api/commesse/{self.job}/situazione/")
        self.assertEqual(response.status_code, 401)

    def test_situazione_api_not_found(self):
        response = self.client.get("/api/commesse/INEXISTENT/situazione/")
        self.assertEqual(response.status_code, 404)


class RevisioneSbloccoTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.approved = StatoEsterno.objects.create(nome="Approved", colore="#00B050")
        self.rejected = StatoEsterno.objects.create(
            nome="Rejected - Work can not proceed", colore="#D61D09"
        )
        self.testata = Testata.objects.create(job="25012")
        self.doc = Documento.objects.create(
            testata=self.testata,
            vendor_doc="25012-01-4005",
            doc_title="Test doc",
        )
        self.writing_user = User.objects.create_user(
            "sbloc_user", "sbloc@example.com", "pw", permesso=Permesso.WRITING
        )
        self.reading_user = User.objects.create_user(
            "sbloc_read", "sbloc-read@example.com", "pw", permesso=Permesso.READING
        )

    def test_list_includes_latest_with_ext_status(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            rec_act_date="2025-06-01",
            ext_status=self.approved,
            int_status="ricevuto",
        )
        items = list_revisioni_sbloccabili("25012")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["revisione_id"], rev.pk)

    def test_list_excludes_when_successor_exists(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            rec_act_date="2025-01-10",
            ext_status=self.approved,
            int_status="ricevuto",
        )
        Revisione.objects.create(documento=self.doc, rev_no=1)
        self.assertEqual(list_revisioni_sbloccabili("25012"), [])

    def test_list_excludes_latest_without_ext_status(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            rec_act_date="2025-01-10",
            ext_status=self.approved,
            int_status="ricevuto",
        )
        Revisione.objects.create(documento=self.doc, rev_no=1, dis_plan_date="2025-02-01")
        self.assertEqual(list_revisioni_sbloccabili("25012"), [])

    def test_list_includes_any_ext_status(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=1,
            rec_act_date="2025-06-01",
            ext_status=self.rejected,
            int_status="ricevuto",
        )
        items = list_revisioni_sbloccabili("25012")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["revisione_id"], rev.pk)

    def test_sblocca_creates_next_revision(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            rec_act_date="2025-06-01",
            ext_status=self.approved,
            int_status="ricevuto",
        )
        result = sblocca_revisione("25012", rev.pk, "2025-07-15")
        new_rev = Revisione.objects.get(pk=result["revisione"]["id"])
        self.assertEqual(new_rev.rev_no, 3)
        self.assertEqual(new_rev.dis_plan_date.isoformat(), "2025-07-15")
        self.assertTrue(new_rev.crea_nuova_rev)
        self.assertEqual(new_rev.ext_status_id, None)

    def test_sblocca_without_date(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            ext_status=self.approved,
            int_status="ricevuto",
        )
        result = sblocca_revisione("25012", rev.pk)
        new_rev = Revisione.objects.get(pk=result["revisione"]["id"])
        self.assertIsNone(new_rev.dis_plan_date)

    def test_sblocca_rejects_non_latest(self):
        rev0 = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            ext_status=self.approved,
            int_status="ricevuto",
        )
        Revisione.objects.create(documento=self.doc, rev_no=1)
        with self.assertRaises(ValueError):
            sblocca_revisione("25012", rev0.pk)

    def test_api_list_and_sblocca(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=1,
            ext_status=self.approved,
            int_status="ricevuto",
        )
        self.client.force_login(self.reading_user)
        list_res = self.client.get("/api/commesse/25012/revisioni/sbloccabili/")
        self.assertEqual(list_res.status_code, 200)
        self.assertEqual(list_res.json()["count"], 1)

        self.client.force_login(self.reading_user)
        post_res = self.client.post(
            "/api/commesse/25012/revisioni/sblocca/",
            data=json.dumps({"revisione_id": rev.pk}),
            content_type="application/json",
        )
        self.assertEqual(post_res.status_code, 403)

        self.client.force_login(self.writing_user)
        post_res = self.client.post(
            "/api/commesse/25012/revisioni/sblocca/",
            data=json.dumps({"revisione_id": rev.pk, "dis_plan_date": "2025-08-01"}),
            content_type="application/json",
        )
        self.assertEqual(post_res.status_code, 200)
        data = post_res.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 0)
        self.assertEqual(Revisione.objects.filter(documento=self.doc, rev_no=2).count(), 1)


class ImportDocumentiExcelTests(TestCase):
    """Tests for the Excel import endpoint and the import template download."""

    def setUp(self):
        self.client = Client()
        User = get_user_model()
        self.writing_user = User.objects.create_user(
            "imp_writer", "w@example.com", "pw", permesso=Permesso.WRITING
        )
        self.reading_user = User.objects.create_user(
            "imp_reader", "r@example.com", "pw", permesso=Permesso.READING
        )
        Testata.objects.create(job="IMP01")

    def _make_xlsx(self, headers, rows):
        """Build an in-memory xlsx file and return it as bytes."""
        import io

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(headers)
        for row in rows:
            ws.append(row)
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return buf

    # ── import with date column ──────────────────────────────────────────────

    def test_import_with_date_sets_dis_plan_date(self):
        self.client.force_login(self.writing_user)
        xlsx = self._make_xlsx(
            ["Item", "Titolo documento", "Data invio prevista (Rev. 0)"],
            [["001", "Doc test", "2026-03-15"]],
        )
        resp = self.client.post(
            "/api/commesse/IMP01/import-excel/",
            data={"file": xlsx},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["created"], 1)
        self.assertEqual(body["errors"], [])
        rev0 = Revisione.objects.filter(documento__testata_id="IMP01", rev_no=0).first()
        self.assertIsNotNone(rev0)
        self.assertIsNotNone(rev0.dis_plan_date)
        self.assertEqual(rev0.dis_plan_date.isoformat(), "2026-03-15")

    def test_import_without_date_column_leaves_dis_plan_date_null(self):
        self.client.force_login(self.writing_user)
        xlsx = self._make_xlsx(
            ["Item", "Titolo documento"],
            [["002", "Doc senza data"]],
        )
        resp = self.client.post(
            "/api/commesse/IMP01/import-excel/",
            data={"file": xlsx},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created"], 1)
        rev0 = Revisione.objects.filter(documento__testata_id="IMP01", rev_no=0).first()
        self.assertIsNone(rev0.dis_plan_date)

    def test_import_with_italian_date_format(self):
        self.client.force_login(self.writing_user)
        xlsx = self._make_xlsx(
            ["Item", "Data invio prevista (Rev. 0)"],
            [["003", "20/07/2026"]],
        )
        resp = self.client.post(
            "/api/commesse/IMP01/import-excel/",
            data={"file": xlsx},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["created"], 1)
        rev0 = Revisione.objects.filter(documento__testata_id="IMP01", rev_no=0).first()
        self.assertEqual(rev0.dis_plan_date.isoformat(), "2026-07-20")

    def test_import_with_invalid_date_creates_doc_and_reports_warning(self):
        self.client.force_login(self.writing_user)
        xlsx = self._make_xlsx(
            ["Item", "Data invio prevista (Rev. 0)"],
            [["004", "not-a-date"]],
        )
        resp = self.client.post(
            "/api/commesse/IMP01/import-excel/",
            data={"file": xlsx},
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        # Document is still created despite the invalid date
        self.assertEqual(body["created"], 1)
        self.assertEqual(len(body["errors"]), 1)
        self.assertIn("data non riconosciuta", body["errors"][0])
        rev0 = Revisione.objects.filter(documento__testata_id="IMP01", rev_no=0).first()
        self.assertIsNone(rev0.dis_plan_date)

    # ── template download ────────────────────────────────────────────────────

    def test_template_download_returns_xlsx(self):
        self.client.force_login(self.reading_user)
        resp = self.client.get("/api/import-documenti-template/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(
            "spreadsheetml",
            resp.get("Content-Type", ""),
        )

    def test_template_download_contains_date_column(self):
        import io

        import openpyxl

        self.client.force_login(self.reading_user)
        resp = self.client.get("/api/import-documenti-template/")
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        self.assertIn("Data invio prevista (Rev. 0)", headers)
        # All expected columns must be present
        for col in ["Item", "B&R Doc", "Titolo documento", "Note"]:
            self.assertIn(col, headers)

    def test_template_download_reparto_has_dropdown_validation(self):
        import io

        import openpyxl
        from openpyxl.utils import get_column_letter

        from core.models import Reparto

        Reparto.objects.create(nome="Qualità e Controllo", acronimo="QC")
        Reparto.objects.create(nome="Project Management", acronimo="PM")

        self.client.force_login(self.reading_user)
        resp = self.client.get("/api/import-documenti-template/")
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))

        self.assertIn("_Reparti", wb.sheetnames)
        ws_reparti = wb["_Reparti"]
        reparti_in_sheet = [ws_reparti.cell(row=r, column=1).value for r in range(1, 3)]
        self.assertEqual(
            sorted(reparti_in_sheet),
            ["Project Management", "Qualità e Controllo"],
        )

        ws = wb.active
        reparto_col = get_column_letter([cell.value for cell in ws[1]].index("Reparto") + 1)
        validations = [
            dv
            for dv in ws.data_validations.dataValidation
            if any(reparto_col in str(r) for r in dv.sqref.ranges)
        ]
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0].type, "list")
        self.assertIn("_Reparti", validations[0].formula1)


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
