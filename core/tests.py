import json
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import (
    CommessaPin,
    Documento,
    IndirSped,
    Notifica,
    Permesso,
    Reparto,
    Revisione,
    RevisioneFileLink,
    Segnalazione,
    SegnalazioneCommento,
    SegnalazioneVoto,
    Stabilimento,
    StatoEsterno,
    StatoSegnalazione,
    Testata,
    TipoSegnalazione,
    Transmittal,
)
from .services.commesse import (
    MAX_PINNED_COMMESSE,
    format_revisione_label,
    list_documenti,
    list_home_commesse,
    list_situazione,
    list_stati_esterni,
    pin_commessa,
    risolvi_file_revisione,
    salva_file_link,
    serialize_revisione,
)
from .services.export_grezzo import _cell as _cella_grezza
from .services.export_grezzo import build_workbook as build_dati_grezzi_workbook
from .services.export_grezzo import list_tabelle as list_tabelle_grezze
from .services.export_grezzo import resolve_tabelle as resolve_tabelle_grezze
from .services.import_old import importa_commessa_da_access
from .services.notifiche import count_notifiche, list_notifiche, segna_lette
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
from .services.stato_esterno_codes import letter_for_status_name

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


def _trasmittal_dir(jobs_root, job: str) -> Path:
    folder = Path(jobs_root) / job / "PROGETTO" / "DCC" / "TRANSMITTAL"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _trasmittal_path(jobs_root, job: str, numero: int) -> Path:
    return (
        Path(jobs_root)
        / job
        / "PROGETTO"
        / "DCC"
        / "TRANSMITTAL"
        / f"Transmittal {job}-{numero}.pdf"
    )


def _write_trasmittal(jobs_root, job, numero, content=b"%PDF", filename=None):
    folder = _trasmittal_dir(jobs_root, job)
    name = filename or f"Transmittal {job}-{numero}.pdf"
    path = folder / name
    path.write_bytes(content)
    return path


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
        response = self.client.get("/api/commesse/25089/trasmittal/storico/?sync=1")
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
        response = self.client.get("/api/commesse/25089/trasmittal/storico/?sync=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i["id"] for i in response.json()["items"]], [9, 1])
        self.assertTrue(Transmittal.objects.filter(testata_id="25089", numero=9).exists())

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


class UserStabilimentoTest(TestCase):
    def test_stabilimento_optional(self):
        user = User.objects.create_user("stab_none", password="pw")
        self.assertIsNone(user.stabilimento_id)

    def test_stabilimento_assign(self):
        stab = Stabilimento.objects.create(nome="Bergamo")
        user = User.objects.create_user("stab_yes", password="pw", stabilimento=stab)
        self.assertEqual(user.stabilimento.nome, "Bergamo")


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


class RevisioniCleanupTests(TestCase):
    def test_single_orphan_after_approved_with_only_dis_plan(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisPlanDate": "2025-01-01",
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": "2025-01-10",
                    "RecActDate": "2025-01-10",
                    "Status": "C",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisPlanDate": "2025-02-01",
                    "DisActDate": "2025-02-01",
                    "RecPlanDate": "2025-02-10",
                    "RecActDate": "2025-02-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 2,
                    "DisPlanDate": "2025-03-01",
                    "DisActDate": None,
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        orphans = find_orphan_indices(df)
        self.assertEqual(orphans, {2})
        cleaned = drop_orphan_revisioni(df)
        self.assertEqual(len(cleaned), 2)

    def test_not_orphan_when_previous_status_needs_new_rev(self):
        # Status C has crea_nuova_rev=True by default → keep last placeholder.
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisPlanDate": "2025-01-01",
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": "2025-01-10",
                    "RecActDate": "2025-01-10",
                    "Status": "C",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisPlanDate": "2025-02-01",
                    "DisActDate": None,
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        self.assertEqual(find_orphan_indices(df), set())

    def test_not_orphan_when_dis_act_date_present(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisPlanDate": "2025-01-01",
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": "2025-01-10",
                    "RecActDate": "2025-01-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisPlanDate": "2025-02-01",
                    "DisActDate": "2025-02-01",
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        self.assertEqual(find_orphan_indices(df), set())

    def test_not_orphan_without_dis_plan_date(self):
        df = pd.DataFrame(
            [
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 0,
                    "DisPlanDate": "2025-01-01",
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": "2025-01-10",
                    "RecActDate": "2025-01-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "JOB-01",
                    "RevNo": 1,
                    "DisPlanDate": None,
                    "DisActDate": None,
                    "RecPlanDate": None,
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
                        "ContractorDocNo": "CTR-99",
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
        self.assertEqual(result["revisioni_orfane_escluse"], 0)
        self.assertEqual(Revisione.objects.count(), 2)
        self.assertIn("anomalie", result)
        # Rev 0 has DisActDate + RecActDate → ricevuto; rev 1 has no dates → Da inviare
        self.assertEqual(Revisione.objects.filter(rev_no=0).get().int_status, "ricevuto")
        self.assertEqual(Revisione.objects.filter(rev_no=1).get().int_status, "")
        doc = Documento.objects.get(vendor_doc="99999-01")
        self.assertEqual(doc.contractor_doc_no, "CTR-99")

    @patch("core.services.import_old.fetch_commessa_frames")
    def test_import_excludes_orphan_after_approved(self, mock_fetch):
        StatoEsterno.objects.create(nome="Approved", colore="#00B050", crea_nuova_rev=False)
        frames = self._frames()
        frames["revisioni"] = pd.DataFrame(
            [
                {
                    "VendorDoc": "99999-01",
                    "RevNo": 0,
                    "RevLet": "",
                    "DisPlanDate": "2025-01-01",
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": "2025-01-10",
                    "RecActDate": "2025-01-10",
                    "Status": "A",
                },
                {
                    "VendorDoc": "99999-01",
                    "RevNo": 1,
                    "RevLet": "",
                    "DisPlanDate": "2025-02-01",
                    "DisActDate": None,
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": None,
                },
            ]
        )
        mock_fetch.return_value = frames
        result = importa_commessa_da_access("99999")
        self.assertEqual(result["revisioni_orfane_escluse"], 1)
        self.assertEqual(result["revisioni"], 1)
        self.assertEqual(Revisione.objects.count(), 1)
        self.assertEqual(Revisione.objects.get().rev_no, 0)

    @patch("core.services.import_old.fetch_commessa_frames")
    def test_import_sets_inviato_when_only_dis_act_date(self, mock_fetch):
        frames = self._frames()
        frames["revisioni"] = pd.DataFrame(
            [
                {
                    "VendorDoc": "99999-01",
                    "RevNo": 0,
                    "RevLet": "A",
                    "DisPlanDate": None,
                    "DisActDate": "2025-01-01",
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": None,
                }
            ]
        )
        mock_fetch.return_value = frames
        importa_commessa_da_access("99999")
        rev = Revisione.objects.get()
        self.assertEqual(rev.int_status, "inviato_al_cliente")
        self.assertEqual(rev.dis_act_date.isoformat(), "2025-01-01")
        self.assertIsNone(rev.rec_act_date)

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

    def test_export_situazione_pdf(self):
        from datetime import date

        import fitz

        today = date.today()
        date_part = f"{today.day:02d}_{today.month:02d}_{today.year}"

        response = self.client.get(f"/api/commesse/{self.job}/situazione/export/?vista=orizzontale")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(
            f'filename="situazione_documenti_orizzontale_{date_part}.pdf"',
            response["Content-Disposition"],
        )
        self.assertTrue(response.content.startswith(b"%PDF"))

        text = fitz.open(stream=response.content, filetype="pdf")[0].get_text()
        self.assertIn("Vendor Document", text)
        self.assertIn("Planning", text)
        self.assertIn("Dispatch", text)
        self.assertIn("25056-QMDBI", text)
        self.assertNotIn("Client Doc No", text)
        self.assertNotIn("Penalty", text)

        response_v = self.client.get(f"/api/commesse/{self.job}/situazione/export/?vista=verticale")
        self.assertEqual(response_v.status_code, 200)
        self.assertIn(
            f'filename="situazione_documenti_verticale_{date_part}.pdf"',
            response_v["Content-Disposition"],
        )
        text_v = fitz.open(stream=response_v.content, filetype="pdf")[0].get_text()
        self.assertIn("Vendor Document", text_v)

    def test_export_situazione_pdf_hides_empty_fixed_columns(self):
        from src.pdf import _active_fixed_doc_columns

        documenti = [
            {"vendor_doc": "DOC-1", "doc_title": "", "client_doc_no": ""},
            {"vendor_doc": "DOC-2", "doc_penalty": True, "item_no": "42"},
        ]
        active = _active_fixed_doc_columns(documenti)
        labels = [col["label"] for col in active]
        self.assertEqual(labels, ["Vendor Document", "Item", "Penalty"])

    def test_export_situazione_not_found(self):
        response = self.client.get("/api/commesse/INEXISTENT/situazione/export/")
        self.assertEqual(response.status_code, 404)

    def test_situazione_api_includes_ext_status_lettera(self):
        approved = StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        doc = self.fixtures["doc_qmdbi"]
        rev = doc.revisioni.order_by("rev_no").first()
        rev.ext_status = approved
        rev.save(update_fields=["ext_status"])

        response = self.client.get(f"/api/commesse/{self.job}/situazione/")
        self.assertEqual(response.status_code, 200)
        revs = response.json()["revisioni_by_doc"][str(doc.pk)]
        self.assertEqual(revs[0]["ext_status_lettera"], "A")
        self.assertEqual(revs[0]["ext_status_label"], "Approved")


class StatoEsternoLetteraTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "stato_lettera_user",
            "stato_lettera@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
        )
        self.client.force_login(self.user)

    def test_letter_for_status_name_aliases(self):
        self.assertEqual(letter_for_status_name("Approved"), "A")
        self.assertEqual(
            letter_for_status_name("Commented-To be resubmitted-Work can proceed"),
            "C",
        )
        self.assertEqual(
            letter_for_status_name("Commented - To be resubmitted - Work can proceed"),
            "C",
        )
        self.assertEqual(letter_for_status_name("Unknown Status"), "")

    def test_serialize_revisione_includes_lettera(self):
        testata = Testata.objects.create(job="LET01")
        doc = Documento.objects.create(testata=testata, item_no="001", vendor_doc="VD")
        stato = StatoEsterno.objects.create(nome="Final - As Built", lettera="F", colore="#FFC000")
        rev = Revisione.objects.create(documento=doc, rev_no=0, ext_status=stato)
        data = serialize_revisione(rev)
        self.assertEqual(data["ext_status_lettera"], "F")
        self.assertEqual(data["ext_status_label"], "Final - As Built")

    def test_list_stati_esterni_includes_lettera(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        items = list_stati_esterni()
        self.assertEqual(items[0]["lettera"], "A")

    def test_stati_esterni_api_create_and_patch_lettera(self):
        create = self.client.post(
            "/api/stati-esterni/",
            data=json.dumps({"nome": "For Information", "lettera": "z", "colore": "#FFC000"}),
            content_type="application/json",
        )
        self.assertEqual(create.status_code, 201)
        payload = create.json()["data"]
        self.assertEqual(payload["lettera"], "Z")
        pk = payload["id"]

        patch = self.client.patch(
            f"/api/stati-esterni/{pk}/",
            data=json.dumps({"lettera": "Z"}),
            content_type="application/json",
        )
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.json()["data"]["lettera"], "Z")


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
            ["Item", "Document title", "Planned send date (Rev. 0)"],
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
            ["Item", "Document title"],
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
            ["Item", "Planned send date (Rev. 0)"],
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
            ["Item", "Planned send date (Rev. 0)"],
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

    def test_import_with_contractor_doc_no(self):
        self.client.force_login(self.writing_user)
        xlsx = self._make_xlsx(
            ["Item", "Document title", "Contractor Doc N°"],
            [["005", "Doc contractor", "CTR-001"]],
        )
        resp = self.client.post(
            "/api/commesse/IMP01/import-excel/",
            data={"file": xlsx},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["created"], 1)
        doc = Documento.objects.get(testata_id="IMP01", item_no="005")
        self.assertEqual(doc.contractor_doc_no, "CTR-001")

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
        self.assertIn("Planned send date (Rev. 0)", headers)
        # All expected columns must be present
        for col in ["Item", "B&R Doc", "Contractor Doc N°", "Document title", "Notes"]:
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
        reparto_col = get_column_letter([cell.value for cell in ws[1]].index("Department") + 1)
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


class DateDisplayFormatTests(SimpleTestCase):
    """Dates are shown as ``10 jan 2026`` across the app."""

    def test_format_display_date(self):
        import datetime

        from .date_fmt import format_display_date

        self.assertEqual(format_display_date(datetime.date(2026, 1, 10)), "10 jan 2026")
        self.assertEqual(format_display_date("2026-03-05"), "5 mar 2026")
        self.assertEqual(format_display_date(None), "")
        self.assertEqual(format_display_date(""), "")

    def test_pdf_date_line(self):
        from src.pdf import _fmt_date

        self.assertEqual(_fmt_date("2026-01-10", "Milano"), "Milano, 10 jan 2026")
        self.assertEqual(_fmt_date("2026-01-10", ""), "10 jan 2026")


class RevisioneLabelDisplayTests(TestCase):
    """Revision display depends on Testata.rev_let_flag, not on rev_let alone."""

    def test_format_revisione_label_uses_flag(self):
        self.assertEqual(format_revisione_label(1, "A", True), "A")
        self.assertEqual(format_revisione_label(1, "A", False), "1")
        self.assertEqual(format_revisione_label(1, "", True), "1")
        self.assertEqual(format_revisione_label(None, "B", True), "B")
        self.assertEqual(format_revisione_label(None, "B", False), "")

    def test_list_documenti_ignores_rev_let_when_flag_false(self):
        t = Testata.objects.create(job="REVFLG1", rev_let_flag=False)
        doc = Documento.objects.create(testata=t, vendor_doc="REVFLG1-01")
        Revisione.objects.create(documento=doc, rev_no=2, rev_let="C")

        payload = list_documenti("REVFLG1")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["latest_rev_display"], "2")
        self.assertEqual(payload[0]["latest_rev_let"], "C")
        self.assertEqual(payload[0]["latest_rev_no"], 2)

    def test_list_documenti_shows_letter_when_flag_true(self):
        t = Testata.objects.create(job="REVFLG2", rev_let_flag=True)
        doc = Documento.objects.create(testata=t, vendor_doc="REVFLG2-01")
        Revisione.objects.create(documento=doc, rev_no=2, rev_let="C")

        payload = list_documenti("REVFLG2")
        self.assertEqual(payload[0]["latest_rev_display"], "C")

    def test_list_situazione_includes_rev_let_flag(self):
        Testata.objects.create(job="REVFLG3", rev_let_flag=True)
        data = list_situazione("REVFLG3")
        self.assertTrue(data["rev_let_flag"])


class CommessaPinTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "pin_user", "pin@example.com", "pw", permesso=Permesso.READING
        )
        self.other = User.objects.create_user(
            "pin_other", "pinother@example.com", "pw", permesso=Permesso.WRITING
        )
        self.jobs = []
        for i in range(10):
            self.jobs.append(Testata.objects.create(job=f"PIN-{i:02d}", client=f"C{i}"))

    def test_reading_user_can_pin_and_unpin(self):
        self.client.force_login(self.user)
        job = self.jobs[0].job
        pin_res = self.client.post(f"/api/commesse/{job}/pin/")
        self.assertEqual(pin_res.status_code, 200)
        self.assertTrue(pin_res.json()["data"]["pinned"])
        self.assertTrue(CommessaPin.objects.filter(user=self.user, testata_id=job).exists())

        list_res = self.client.get("/api/commesse/")
        self.assertEqual(list_res.status_code, 200)
        by_job = {c["job"]: c for c in list_res.json()["commesse"]}
        self.assertTrue(by_job[job]["pinned"])

        unpin_res = self.client.delete(f"/api/commesse/{job}/pin/")
        self.assertEqual(unpin_res.status_code, 200)
        self.assertFalse(unpin_res.json()["data"]["pinned"])
        self.assertFalse(CommessaPin.objects.filter(user=self.user, testata_id=job).exists())

    def test_pin_limit_is_eight(self):
        self.client.force_login(self.user)
        for t in self.jobs[:MAX_PINNED_COMMESSE]:
            res = self.client.post(f"/api/commesse/{t.job}/pin/")
            self.assertEqual(res.status_code, 200)
        overflow = self.client.post(f"/api/commesse/{self.jobs[8].job}/pin/")
        self.assertEqual(overflow.status_code, 400)
        self.assertIn("massimo", overflow.json()["error"].lower())
        self.assertEqual(CommessaPin.objects.filter(user=self.user).count(), 8)

    def test_home_fills_with_recent_when_fewer_than_eight_pinned(self):
        self.client.force_login(self.user)
        pinned_jobs = [self.jobs[0].job, self.jobs[1].job]
        for job in pinned_jobs:
            self.client.post(f"/api/commesse/{job}/pin/")

        res = self.client.get("/api/commesse/?home=1")
        self.assertEqual(res.status_code, 200)
        home = res.json()["commesse"]
        self.assertEqual(len(home), 8)
        self.assertEqual([c["job"] for c in home[:2]], pinned_jobs)
        self.assertTrue(all(c["pinned"] for c in home[:2]))
        self.assertTrue(all(not c["pinned"] for c in home[2:]))
        self.assertNotIn(self.jobs[0].job, [c["job"] for c in home[2:]])

    def test_home_shows_only_eight_when_eight_pinned(self):
        self.client.force_login(self.user)
        pinned = [t.job for t in self.jobs[:8]]
        for job in pinned:
            self.client.post(f"/api/commesse/{job}/pin/")

        res = self.client.get("/api/commesse/?home=1")
        home = res.json()["commesse"]
        self.assertEqual(len(home), 8)
        self.assertEqual([c["job"] for c in home], pinned)
        self.assertTrue(all(c["pinned"] for c in home))
        self.assertNotIn(self.jobs[8].job, [c["job"] for c in home])

    def test_pins_are_per_user(self):
        pin_commessa(self.user, self.jobs[0].job)
        self.client.force_login(self.other)
        res = self.client.get("/api/commesse/?home=1")
        home = res.json()["commesse"]
        by_job = {c["job"]: c for c in home}
        self.assertFalse(by_job.get(self.jobs[0].job, {}).get("pinned", False))
        self.assertEqual(len(list_home_commesse(self.other)), 8)


class SegnalazioniTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.reader = User.objects.create_user(
            "seg_reader",
            "seg-reader@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Luca",
            last_name="Rossi",
        )
        self.writer = User.objects.create_user(
            "seg_writer",
            "seg-writer@example.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Anna",
            last_name="Bianchi",
        )
        self.admin = User.objects.create_user(
            "seg_admin",
            "seg-admin@example.com",
            "pw",
            permesso=Permesso.ADMIN,
            first_name="Mario",
            last_name="Verdi",
        )
        self.voter = User.objects.create_user(
            "seg_voter",
            "seg-voter@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Piero",
            last_name="Neri",
        )

    def _post(self, url, payload, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")

    def _create(self, user, tipo="feature", titolo="Titolo", testo="Descrizione"):
        return self._post(
            "/api/segnalazioni/",
            {"tipo": tipo, "titolo": titolo, "testo": testo},
            user=user,
        )

    def test_page_requires_login(self):
        res = self.client.get("/segnalazioni/")
        self.assertEqual(res.status_code, 302)

    def test_page_ok_for_authenticated(self):
        self.client.force_login(self.reader)
        res = self.client.get("/segnalazioni/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Nuova proposta")
        self.assertContains(res, "Tutti i post")
        self.assertContains(res, "I miei post")
        self.assertContains(res, "Top 10 per voti")
        self.assertContains(res, "Nuove funzionalità")
        self.assertContains(res, "Segnalazioni")
        self.assertContains(res, "Solo aperti")
        self.assertContains(res, "Post chiusi")

    def test_home_contains_prompt_link(self):
        self.client.force_login(self.reader)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Qualcosa da segnalare?")
        self.assertContains(res, 'href="/segnalazioni/"')

    def test_reading_user_can_create(self):
        res = self._create(self.reader, titolo="Nuova export", testo="Vorrei un export CSV.")
        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertEqual(data["titolo"], "Nuova export")
        self.assertEqual(data["tipo"], TipoSegnalazione.FEATURE)
        self.assertEqual(data["autore_nome"], "Luca Rossi")
        self.assertEqual(data["autore_iniziale"], "L")
        self.assertIsNone(data["autore_avatar"])
        self.assertEqual(data["stato"], StatoSegnalazione.APERTO)
        self.assertEqual(data["score"], 0)
        self.assertEqual(data["mio_voto"], 0)
        self.assertNotIn("voti", data)
        self.assertNotIn("utente", data)

    def test_vote_unique_and_score(self):
        created = self._create(self.reader)
        pk = created.json()["data"]["id"]

        up = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.writer)
        self.assertEqual(up.status_code, 200)
        self.assertEqual(up.json()["data"]["score"], 1)
        self.assertEqual(up.json()["data"]["up"], 1)
        self.assertEqual(up.json()["data"]["mio_voto"], 1)

        again = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.writer)
        self.assertEqual(again.json()["data"]["score"], 1)
        self.assertEqual(SegnalazioneVoto.objects.filter(segnalazione_id=pk).count(), 1)

        down = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": -1}, user=self.voter)
        self.assertEqual(down.json()["data"]["score"], 0)
        self.assertEqual(down.json()["data"]["down"], 1)

        switch = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": -1}, user=self.writer)
        self.assertEqual(switch.json()["data"]["score"], -2)

        clear = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 0}, user=self.writer)
        self.assertEqual(clear.json()["data"]["mio_voto"], 0)
        self.assertEqual(clear.json()["data"]["score"], -1)

    def test_votes_are_anonymous_in_list(self):
        created = self._create(self.reader, titolo="Voto anonimo")
        pk = created.json()["data"]["id"]
        self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.voter)

        self.client.force_login(self.reader)
        res = self.client.get("/api/segnalazioni/")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode()
        self.assertNotIn("seg_voter", blob)
        self.assertNotIn("Piero Neri", blob)
        item = res.json()["segnalazioni"][0]
        self.assertEqual(item["up"], 1)
        self.assertEqual(item["mio_voto"], 0)
        self.assertNotIn("voti", item)
        for key in item:
            self.assertNotIn("utente", key)

    def test_comment_on_open_and_closed(self):
        pk = self._create(self.reader).json()["data"]["id"]
        comment = self._post(
            f"/api/segnalazioni/{pk}/commenti/",
            {"testo": "Concordo."},
            user=self.writer,
        )
        self.assertEqual(comment.status_code, 201)
        self.assertEqual(comment.json()["data"]["commenti"][0]["autore_nome"], "Anna Bianchi")
        self.assertEqual(SegnalazioneCommento.objects.filter(segnalazione_id=pk).count(), 1)

        close = self._post(f"/api/segnalazioni/{pk}/chiudi/", {}, user=self.admin)
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.json()["data"]["stato"], StatoSegnalazione.CHIUSO)

        blocked = self._post(
            f"/api/segnalazioni/{pk}/commenti/",
            {"testo": "Troppo tardi."},
            user=self.writer,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("chiuso", blocked.json()["error"].lower())

    def test_non_admin_cannot_close(self):
        pk = self._create(self.reader).json()["data"]["id"]
        res = self._post(f"/api/segnalazioni/{pk}/chiudi/", {}, user=self.writer)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"], "Permesso negato.")
        self.assertEqual(Segnalazione.objects.get(pk=pk).stato, StatoSegnalazione.APERTO)

        res2 = self._post(f"/api/segnalazioni/{pk}/riapri/", {}, user=self.reader)
        self.assertEqual(res2.status_code, 403)

    def test_list_orders_open_before_closed_by_score(self):
        low = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Basso",
            testo="x",
        )
        high = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Alto",
            testo="x",
        )
        closed = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiuso alto",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        SegnalazioneVoto.objects.create(segnalazione=low, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.admin, valore=1)

        self.client.force_login(self.reader)
        titles = [s["titolo"] for s in self.client.get("/api/segnalazioni/").json()["segnalazioni"]]
        self.assertEqual(titles, ["Alto", "Basso", "Chiuso alto"])

    def test_filter_by_tipo(self):
        self._create(self.reader, tipo="feature", titolo="Feat")
        self._create(self.reader, tipo="problema", titolo="Bug")
        self.client.force_login(self.reader)
        feats = self.client.get("/api/segnalazioni/?tipo=feature").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in feats], ["Feat"])
        bugs = self.client.get("/api/segnalazioni/?tipo=problema").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in bugs], ["Bug"])

    def test_filter_by_stato(self):
        self._create(self.reader, titolo="Aperto")
        closed_pk = self._create(self.reader, titolo="Chiuso").json()["data"]["id"]
        self._post(f"/api/segnalazioni/{closed_pk}/chiudi/", {}, user=self.admin)
        self.client.force_login(self.reader)
        aperti = self.client.get("/api/segnalazioni/?stato=aperto").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in aperti], ["Aperto"])
        chiusi = self.client.get("/api/segnalazioni/?stato=chiuso").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in chiusi], ["Chiuso"])

    def test_filter_mine(self):
        self._create(self.reader, titolo="Del reader")
        self._create(self.writer, titolo="Del writer")
        self.client.force_login(self.reader)
        mine = self.client.get("/api/segnalazioni/?mine=1").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in mine], ["Del reader"])
        self.client.force_login(self.writer)
        mine_w = self.client.get("/api/segnalazioni/?mine=1").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in mine_w], ["Del writer"])

    def test_top_by_score(self):
        closed = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiuso top",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        mid = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Medio",
            testo="x",
        )
        high = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Alto",
            testo="x",
        )
        Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Zero",
            testo="x",
        )
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.admin, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=mid, utente=self.writer, valore=1)

        for i in range(8):
            Segnalazione.objects.create(
                autore=self.reader,
                tipo=TipoSegnalazione.FEATURE,
                titolo=f"Extra {i}",
                testo="x",
            )
        self.client.force_login(self.reader)
        top = self.client.get("/api/segnalazioni/?top=10").json()["segnalazioni"]
        self.assertEqual(len(top), 10)
        self.assertEqual([s["titolo"] for s in top[:3]], ["Chiuso top", "Alto", "Medio"])
        self.assertNotIn("Zero", [s["titolo"] for s in top])

    def test_list_ordered_by_created_at_desc(self):
        """L'elenco è cronologico (le più recenti in cima), i voti non contano."""
        votata = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Vecchia ma votata",
            testo="x",
        )
        recente = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Recente senza voti",
            testo="x",
        )
        chiusa = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiusa recentissima",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        base = timezone.now()
        for s, delta in ((votata, -3), (recente, -1), (chiusa, 0)):
            Segnalazione.objects.filter(pk=s.pk).update(created_at=base + timedelta(hours=delta))
        SegnalazioneVoto.objects.create(segnalazione=votata, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=votata, utente=self.voter, valore=1)

        self.client.force_login(self.reader)
        titoli = [s["titolo"] for s in self.client.get("/api/segnalazioni/").json()["segnalazioni"]]
        self.assertEqual(
            titoli,
            ["Recente senza voti", "Vecchia ma votata", "Chiusa recentissima"],
        )

    def test_invalid_list_params(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get("/api/segnalazioni/?tipo=nope").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?stato=nope").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?top=abc").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?top=0").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?mine=yes").status_code, 400)


class NotificheTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.autore = User.objects.create_user(
            "notif_autore",
            "notif-autore@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Luca",
            last_name="Rossi",
        )
        self.altro = User.objects.create_user(
            "notif_altro",
            "notif-altro@example.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Anna",
            last_name="Bianchi",
        )
        self.terzo = User.objects.create_user(
            "notif_terzo",
            "notif-terzo@example.com",
            "pw",
            permesso=Permesso.ADMIN,
            first_name="Mario",
            last_name="Verdi",
        )

    def _crea_segnalazione(self, user, tipo="feature", titolo="Titolo", testo="Descrizione"):
        self.client.force_login(user)
        res = self.client.post(
            "/api/segnalazioni/",
            data=json.dumps({"tipo": tipo, "titolo": titolo, "testo": testo}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        return res.json()["data"]["id"]

    def test_nuova_feature_notifica_tutti_tranne_autore(self):
        self._crea_segnalazione(self.autore, tipo="feature")
        self.assertEqual(Notifica.objects.filter(destinatario=self.autore).count(), 0)
        testi = set(
            Notifica.objects.exclude(destinatario=self.autore).values_list("testo", flat=True)
        )
        self.assertEqual(testi, {"Luca Rossi ha proposto una nuova feature"})
        self.assertEqual(
            set(
                Notifica.objects.values_list("destinatario__username", flat=True),
            ),
            {"notif_altro", "notif_terzo"},
        )

    def test_nuovo_problema_ha_testo_dedicato(self):
        self._crea_segnalazione(self.autore, tipo="problema")
        testi = set(Notifica.objects.values_list("testo", flat=True))
        self.assertEqual(testi, {"Luca Rossi ha evidenziato un problema"})

    def test_utenti_disattivati_non_ricevono_notifiche(self):
        self.terzo.is_active = False
        self.terzo.save(update_fields=["is_active"])
        self._crea_segnalazione(self.autore)
        self.assertEqual(
            list(Notifica.objects.values_list("destinatario__username", flat=True)),
            ["notif_altro"],
        )

    def test_api_elenca_solo_le_proprie_notifiche(self):
        pk = self._crea_segnalazione(self.autore)
        self.client.force_login(self.altro)
        res = self.client.get("/api/notifiche/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 1)
        item = body["notifiche"][0]
        self.assertEqual(item["testo"], "Luca Rossi ha proposto una nuova feature")
        self.assertEqual(item["segnalazione_id"], pk)
        self.assertEqual(item["tipo"], TipoSegnalazione.FEATURE)
        self.assertIsNotNone(item["created_at"])

        self.client.force_login(self.autore)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 0)

    def test_api_richiede_autenticazione(self):
        self.assertEqual(self.client.get("/api/notifiche/").status_code, 401)
        self.assertEqual(self.client.post("/api/notifiche/lette/").status_code, 401)

    def test_notifica_sparisce_dopo_la_visualizzazione(self):
        self._crea_segnalazione(self.autore)
        self.client.force_login(self.altro)
        ids = [n["id"] for n in self.client.get("/api/notifiche/").json()["notifiche"]]

        lette = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": ids}),
            content_type="application/json",
        )
        self.assertEqual(lette.status_code, 200)
        self.assertEqual(lette.json()["lette"], 1)
        self.assertEqual(lette.json()["count"], 0)
        self.assertEqual(self.client.get("/api/notifiche/").json()["notifiche"], [])
        self.assertIsNotNone(Notifica.objects.get(pk=ids[0]).letta_il)

        # Le notifiche degli altri utenti restano da leggere
        self.client.force_login(self.terzo)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 1)

    def test_lette_senza_ids_marca_tutte(self):
        self._crea_segnalazione(self.autore, titolo="Prima")
        self._crea_segnalazione(self.terzo, titolo="Seconda")
        self.client.force_login(self.altro)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 2)

        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["lette"], 2)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 0)

    def test_lette_marca_solo_gli_id_richiesti(self):
        self._crea_segnalazione(self.autore, titolo="Prima")
        self._crea_segnalazione(self.terzo, titolo="Seconda")
        self.client.force_login(self.altro)
        notifiche = self.client.get("/api/notifiche/").json()["notifiche"]
        self.assertEqual(len(notifiche), 2)

        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": [notifiche[0]["id"]]}),
            content_type="application/json",
        )
        self.assertEqual(res.json()["lette"], 1)
        rimaste = self.client.get("/api/notifiche/").json()["notifiche"]
        self.assertEqual([n["id"] for n in rimaste], [notifiche[1]["id"]])

    def test_lette_rifiuta_payload_non_valido(self):
        self.client.force_login(self.altro)
        bad_type = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": "1"}),
            content_type="application/json",
        )
        self.assertEqual(bad_type.status_code, 400)
        bad_item = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": ["abc"]}),
            content_type="application/json",
        )
        self.assertEqual(bad_item.status_code, 400)
        bad_json = self.client.post(
            "/api/notifiche/lette/",
            data="non-json",
            content_type="application/json",
        )
        self.assertEqual(bad_json.status_code, 400)

    def test_lette_ignora_notifiche_di_altri_utenti(self):
        self._crea_segnalazione(self.autore)
        altrui = Notifica.objects.get(destinatario=self.terzo)
        self.client.force_login(self.altro)
        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": [altrui.pk]}),
            content_type="application/json",
        )
        self.assertEqual(res.json()["lette"], 0)
        self.assertIsNone(Notifica.objects.get(pk=altrui.pk).letta_il)

    def test_notifiche_rimosse_con_la_segnalazione(self):
        pk = self._crea_segnalazione(self.autore)
        Segnalazione.objects.filter(pk=pk).delete()
        self.assertEqual(Notifica.objects.count(), 0)

    def test_service_helpers(self):
        self._crea_segnalazione(self.autore)
        self.assertEqual(count_notifiche(self.altro), 1)
        self.assertEqual(len(list_notifiche(self.altro)), 1)
        self.assertEqual(segna_lette(self.altro), 1)
        self.assertEqual(count_notifiche(self.altro), 0)
        self.assertEqual(list_notifiche(self.altro), [])
        with self.assertRaises(ValueError):
            segna_lette(self.terzo, ["x"])

    def test_campanella_visibile_nelle_pagine_autenticate(self):
        self.client.force_login(self.altro)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="notif-btn"')
        self.assertContains(res, 'id="notif-panel"')
        self.assertContains(res, 'aria-label="Notifiche"')

    def test_campanella_assente_per_anonimi(self):
        res = self.client.get("/login/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'id="notif-btn"')


class ScaricaDatiGrezziTestCase(TestCase):
    """Pagina "Scarica" ed export Excel dei dati grezzi di una commessa."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "grezzi_reader",
            "grezzi-reader@example.com",
            "pw",
            permesso=Permesso.READING,
        )
        self.testata = Testata.objects.create(job="GR01", client="ACME Spa")
        self.altra = Testata.objects.create(job="GR02", client="Altro Cliente")

        self.indirizzo = IndirSped.objects.create(
            testata=self.testata,
            consignee="ACME Spa",
            city="Bergamo",
            country="IT",
        )
        self.doc = Documento.objects.create(
            testata=self.testata,
            item_no="001",
            vendor_doc="GR01-QMDBI",
            client_doc_no="CL-001",
            client_doc_class="CLASSE-A",
            contractor_doc_no="CTR-001",
            doc_title="Data book index",
        )
        self.stato = StatoEsterno.objects.create(nome="Approved", lettera="A")
        self.rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_plan_date=date(2026, 3, 15),
            int_status="da_emettere",
            ext_status=self.stato,
        )

        # Dati della seconda commessa: non devono finire nell'export di GR01.
        self.doc_altra = Documento.objects.create(
            testata=self.altra,
            item_no="999",
            doc_title="Documento di un'altra commessa",
        )

    def _scarica(self, job="GR01", tabelle="documenti"):
        return self.client.get(f"/api/commesse/{job}/dati-grezzi/?tabelle={tabelle}")

    def _workbook(self, response):
        import io

        import openpyxl

        return openpyxl.load_workbook(io.BytesIO(response.content))

    def _righe(self, ws):
        return [list(row) for row in ws.iter_rows(values_only=True)]

    # ── Pagina HTML ──────────────────────────────────────────────────────────

    def test_pagina_richiede_autenticazione(self):
        res = self.client.get("/scarica/")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/login/", res["Location"])

    def test_pagina_elenca_tutte_le_tabelle_e_il_seleziona_tutte(self):
        self.client.force_login(self.user)
        res = self.client.get("/scarica/")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "core/scarica.html")
        self.assertContains(res, 'id="tabelle-all"')
        self.assertContains(res, "Seleziona tutte")
        self.assertContains(res, 'id="commessa-search"')
        for tabella in list_tabelle_grezze():
            self.assertContains(res, f'value="{tabella["key"]}"')
            self.assertContains(res, tabella["label"])

    def test_navbar_mostra_scarica_tra_cerca_e_impostazioni(self):
        self.client.force_login(self.user)
        for url in ("/", "/commesse/", "/segnalazioni/", "/scarica/"):
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200)
                html = res.content.decode()
                self.assertIn('href="/scarica/"', html)
                self.assertIn("Scarica", html)
                # La voce sta fra il pulsante "Cerca" e il link "Impostazioni".
                self.assertLess(html.index("openSpotlight()"), html.index('href="/scarica/"'))
                self.assertLess(html.index('href="/scarica/"'), html.index('href="/admin/"'))

    # ── Export ───────────────────────────────────────────────────────────────

    def test_export_richiede_autenticazione(self):
        self.assertEqual(self._scarica().status_code, 401)

    def test_export_restituisce_un_xlsx_con_nome_file_dedicato(self):
        self.client.force_login(self.user)
        res = self._scarica()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(
            res["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertIn("attachment;", res["Content-Disposition"])
        self.assertIn("GR01_dati_grezzi_", res["Content-Disposition"])
        self.assertIn(".xlsx", res["Content-Disposition"])

    def test_un_foglio_per_ogni_tabella_richiesta(self):
        self.client.force_login(self.user)
        res = self._scarica(tabelle="documenti,revisioni")
        wb = self._workbook(res)
        self.assertEqual(wb.sheetnames, ["Documenti", "Revisioni"])

    def test_i_fogli_seguono_lordine_canonico_non_quello_richiesto(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="revisioni,testate,documenti"))
        self.assertEqual(wb.sheetnames, ["Commessa", "Documenti", "Revisioni"])

    def test_seleziona_tutte_scarica_ogni_tabella(self):
        self.client.force_login(self.user)
        keys = ",".join(t["key"] for t in list_tabelle_grezze())
        wb = self._workbook(self._scarica(tabelle=keys))
        self.assertEqual(wb.sheetnames, [t["label"] for t in list_tabelle_grezze()])

    def test_header_con_i_nomi_colonna_e_dato_grezzo(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="documenti"))
        righe = self._righe(wb["Documenti"])
        headers = righe[0]
        self.assertEqual(headers[0], "id")
        self.assertIn("testata_id", headers)
        self.assertIn("doc_title", headers)
        self.assertEqual(len(righe), 2)
        riga = dict(zip(headers, righe[1]))
        self.assertEqual(riga["id"], self.doc.pk)
        self.assertEqual(riga["testata_id"], "GR01")
        self.assertEqual(riga["item_no"], "001")
        self.assertEqual(riga["doc_title"], "Data book index")
        self.assertFalse(riga["doc_penalty"])

    def test_solo_header_in_grassetto_e_nessuna_colorazione(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="documenti"))
        ws = wb["Documenti"]
        for cell in ws[1]:
            self.assertTrue(cell.font.bold)
        for cell in ws[2]:
            self.assertFalse(cell.font.bold)
            self.assertEqual(cell.fill.fill_type, None)

    def test_export_contiene_solo_i_dati_della_commessa_scelta(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="documenti"))
        ids = [r[0] for r in self._righe(wb["Documenti"])]
        self.assertNotIn(self.doc_altra.pk, ids)

        wb_altra = self._workbook(self._scarica(job="GR02", tabelle="documenti"))
        righe = self._righe(wb_altra["Documenti"])
        self.assertEqual(len(righe), 2)
        self.assertEqual(dict(zip(righe[0], righe[1]))["id"], self.doc_altra.pk)

    def test_revisioni_e_indirizzi_esportano_le_righe_collegate(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="testate,indirizzi_spedizione,revisioni"))

        commessa = self._righe(wb["Commessa"])
        self.assertEqual(dict(zip(commessa[0], commessa[1]))["job"], "GR01")

        indirizzi = self._righe(wb["Indirizzi spedizione"])
        self.assertEqual(dict(zip(indirizzi[0], indirizzi[1]))["city"], "Bergamo")

        revisioni = self._righe(wb["Revisioni"])
        riga_rev = dict(zip(revisioni[0], revisioni[1]))
        self.assertEqual(riga_rev["rev_no"], 0)
        self.assertEqual(riga_rev["int_status"], "da_emettere")

    def test_revisioni_portano_i_dati_del_documento_e_la_lettera_dello_stato(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="revisioni"))
        righe = self._righe(wb["Revisioni"])
        headers = righe[0]
        self.assertEqual(
            headers,
            [
                "client_doc_no",
                "client_doc_class",
                "contractor_doc_no",
                "vendor_doc",
                "item_no",
                "rev_no",
                "rev_let",
                "dis_plan_date",
                "dis_act_date",
                "rec_plan_date",
                "rec_act_date",
                "int_status",
                "ext_status",
                "crea_nuova_rev",
            ],
        )
        riga = dict(zip(headers, righe[1]))
        self.assertEqual(riga["client_doc_no"], "CL-001")
        self.assertEqual(riga["client_doc_class"], "CLASSE-A")
        self.assertEqual(riga["contractor_doc_no"], "CTR-001")
        self.assertEqual(riga["vendor_doc"], "GR01-QMDBI")
        self.assertEqual(riga["item_no"], "001")
        self.assertEqual(riga["ext_status"], "A")

    def test_revisione_senza_risposta_cliente_ha_la_lettera_vuota(self):
        Revisione.objects.filter(pk=self.rev.pk).update(ext_status=None)
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="revisioni"))
        righe = self._righe(wb["Revisioni"])
        # openpyxl rilegge una cella vuota come None.
        self.assertIn(dict(zip(righe[0], righe[1]))["ext_status"], ("", None))

    def test_le_tabelle_esportabili_sono_solo_le_quattro_utili(self):
        self.assertEqual(
            [t["key"] for t in list_tabelle_grezze()],
            ["testate", "indirizzi_spedizione", "documenti", "revisioni"],
        )
        for key in ("revisioni_file_link", "trasmittal", "trasmittal_revisioni"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                resolve_tabelle_grezze([key])

    def test_tabella_vuota_esporta_il_solo_header(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(job="GR02", tabelle="indirizzi_spedizione"))
        righe = self._righe(wb["Indirizzi spedizione"])
        self.assertEqual(len(righe), 1)
        self.assertIn("consignee", righe[0])

    def test_le_date_restano_date_e_i_timestamp_perdono_il_fuso(self):
        self.client.force_login(self.user)
        wb = self._workbook(self._scarica(tabelle="revisioni"))
        revisioni = self._righe(wb["Revisioni"])
        self.assertEqual(
            dict(zip(revisioni[0], revisioni[1]))["dis_plan_date"],
            datetime(2026, 3, 15),
        )
        aware = timezone.make_aware(datetime(2026, 3, 15, 8, 30))
        self.assertEqual(_cella_grezza(aware), timezone.localtime(aware).replace(tzinfo=None))
        self.assertIsNone(_cella_grezza(aware).tzinfo)

    # ── Errori ───────────────────────────────────────────────────────────────

    def test_senza_tabelle_selezionate_400(self):
        self.client.force_login(self.user)
        res = self._scarica(tabelle="")
        self.assertEqual(res.status_code, 400)
        self.assertIn("almeno una tabella", res.json()["error"])

    def test_tabella_sconosciuta_400(self):
        self.client.force_login(self.user)
        res = self._scarica(tabelle="documenti,pippo")
        self.assertEqual(res.status_code, 400)
        self.assertIn("pippo", res.json()["error"])

    def test_commessa_inesistente_404(self):
        self.client.force_login(self.user)
        res = self._scarica(job="NOPE")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"], "Commessa non trovata.")

    # ── Service ──────────────────────────────────────────────────────────────

    def test_resolve_tabelle_deduplica_e_ordina(self):
        tabelle = resolve_tabelle_grezze(["revisioni", "documenti", "revisioni"])
        self.assertEqual([t.key for t in tabelle], ["documenti", "revisioni"])

    def test_resolve_tabelle_rifiuta_selezioni_non_valide(self):
        with self.assertRaises(ValueError):
            resolve_tabelle_grezze([])
        with self.assertRaises(ValueError):
            resolve_tabelle_grezze(["   "])
        with self.assertRaises(ValueError):
            resolve_tabelle_grezze(["documenti", "sconosciuta"])

    def test_build_workbook_su_commessa_inesistente(self):
        with self.assertRaises(Testata.DoesNotExist):
            build_dati_grezzi_workbook("NOPE", ["documenti"])
