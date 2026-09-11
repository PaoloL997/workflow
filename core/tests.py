import io
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import expectedFailure
from unittest.mock import Mock, patch

import pandas as pd
from django.contrib import admin as django_admin
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.models import Count
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.html import escapejs
from django.utils.http import urlsafe_base64_encode
from PIL import Image

from .date_fmt import format_display_date
from .models import (
    FIRMA_MAX_BYTE,
    AggiornamentoBC,
    AttivitaQCP,
    CommessaPin,
    Documento,
    EsecuzioneSchedulata,
    EsitoFirma,
    FirmaNonModificabile,
    IndirSped,
    Notifica,
    Permesso,
    QualityControlPlan,
    QualityControlPlanAgency,
    QualityControlPlanCode,
    QualityControlPlanInterventionPoint,
    QualityControlPlanItem,
    QualityControlPlanSection,
    QualityControlPlanSignature,
    QualityControlPlanSpec,
    QualityControlPlanStep,
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
from .services import scheduler
from .services.bc_sync import (
    BusinessCentralNonDisponibile,
    confronta_commessa,
    list_aggiornamenti,
    sincronizza_commesse,
)
from .services.catalogo_qcp import CAMPI as CAMPI_CATALOGO_QCP
from .services.catalogo_qcp import LIMITE_RISULTATI as LIMITE_CATALOGO_QCP
from .services.catalogo_qcp import capitoli_attivi as capitoli_attivi_qcp
from .services.commesse import (
    MAX_PINNED_COMMESSE,
    fetch_from_bc,
    list_documenti,
    list_home_commesse,
    list_situazione,
    list_stati_esterni,
    pin_commessa,
    revisioni_by_doc_for_job,
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
from .services.quality_control_plan import (
    CODICI_PROPOSTI,
    ENTE_PREDEFINITO,
    LISTE,
    MAX_AGENCIES,
    MAX_CODES,
    MAX_ITEMS,
    MAX_SPECS,
    aggiorna_step,
    aggiungi_step,
    aggiungi_step_multipli,
    annulla_firma,
    avanzamento,
    corpo_per_pagina,
    crea_sezione,
    create_piano,
    data_ora,
    dati_precompilati,
    elimina_sezione,
    elimina_step,
    etichetta_punto,
    extent_in_percentuale,
    firma_punto,
    firma_step,
    get_piano,
    imposta_punto,
    iniziali,
    intestazione_items,
    list_piani,
    mdmt_con_unita,
    mdmt_senza_unita,
    riordina,
    serialize_corpo,
    serialize_firma,
    serialize_piano,
    sincronizza_punti,
    storico_punto,
    titolo_predefinito,
)
from .services.quality_control_plan import VENDOR as QCP_VENDOR
from .services.revisione_anomalie import (
    audit_commessa,
    audit_commessa_summary,
    audit_revisione,
    classifica_revisione,
    ignora_anomalie_revisione,
    serialize_anomalie_gruppi,
)
from .services.revisione_label import (
    format_revisione_label,
    lettera_a_numero,
    numero_a_lettera,
)
from .services.revisione_sblocco import list_revisioni_sbloccabili, sblocca_revisione
from .services.revisioni_cleanup import drop_orphan_revisioni, find_orphan_indices
from .services.seed_corpo_qcp import semina_corpo, valida_corpo
from .services.stato_esterno_codes import DEFAULT_STATUS_COLORS, letter_for_status_name
from .services.stato_esterno_colori import (
    FALLBACK_BG,
    MIN_CONTRAST,
    TEXT_DARK,
    TEXT_LIGHT,
    cell_colors,
    contrast_ratio,
    hex_to_rgb,
    readable_text_color,
    rgb_to_hex,
)
from .services.stato_esterno_legenda import legenda_default, legenda_stati_esterni

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
    def test_import_sets_ricevuto_when_client_answered_without_dates(self, mock_fetch):
        StatoEsterno.objects.create(nome="Approved", colore="#00B050", crea_nuova_rev=False)
        frames = self._frames()
        frames["revisioni"] = pd.DataFrame(
            [
                {
                    "VendorDoc": "99999-01",
                    "RevNo": 0,
                    "RevLet": "A",
                    "DisPlanDate": None,
                    "DisActDate": None,
                    "RecPlanDate": None,
                    "RecActDate": None,
                    "Status": "A",
                }
            ]
        )
        mock_fetch.return_value = frames
        importa_commessa_da_access("99999")
        rev = Revisione.objects.get()
        self.assertEqual(rev.int_status, "ricevuto")
        self.assertIsNotNone(rev.ext_status)

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


class RevisioneEtichettaTests(SimpleTestCase):
    """Lettera e numero sono due scritture dello stesso dato (revisione_label)."""

    def test_numero_convertito_in_lettera(self):
        self.assertEqual(numero_a_lettera(0), "A")
        self.assertEqual(numero_a_lettera(1), "B")
        self.assertEqual(numero_a_lettera(25), "Z")
        self.assertEqual(numero_a_lettera(26), "AA")
        self.assertEqual(numero_a_lettera(27), "AB")
        self.assertEqual(numero_a_lettera("3"), "D")
        self.assertEqual(numero_a_lettera(None), "")
        self.assertEqual(numero_a_lettera(-1), "")

    def test_lettera_convertita_in_numero(self):
        self.assertEqual(lettera_a_numero("A"), 0)
        self.assertEqual(lettera_a_numero("b"), 1)
        self.assertEqual(lettera_a_numero("Z"), 25)
        self.assertEqual(lettera_a_numero("AA"), 26)
        self.assertIsNone(lettera_a_numero(""))
        self.assertIsNone(lettera_a_numero("1"))
        self.assertIsNone(lettera_a_numero(None))

    def test_con_flag_attivo_si_vede_sempre_la_lettera(self):
        self.assertEqual(format_revisione_label(1, "A", True), "A")
        self.assertEqual(format_revisione_label(1, "a", True), "A")
        # Lettera non compilata: si ricava dal numero.
        self.assertEqual(format_revisione_label(0, "", True), "A")
        self.assertEqual(format_revisione_label(2, "", True), "C")
        self.assertEqual(format_revisione_label(26, None, True), "AA")
        # Lettera compilata con un numero: viene comunque convertita.
        self.assertEqual(format_revisione_label(None, "2", True), "C")
        self.assertEqual(format_revisione_label(None, "", True), "")

    def test_con_flag_spento_si_vede_sempre_il_numero(self):
        self.assertEqual(format_revisione_label(1, "A", False), "1")
        self.assertEqual(format_revisione_label(0, "", False), "0")
        # Numero non compilato: si ricava dalla lettera.
        self.assertEqual(format_revisione_label(None, "B", False), "1")
        self.assertEqual(format_revisione_label(None, "AA", False), "26")
        self.assertEqual(format_revisione_label(None, "", False), "")


class RevisioneLabelDisplayTests(TestCase):
    """Revision display depends on Testata.rev_let_flag, not on rev_let alone."""

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

    def test_list_documenti_deriva_la_lettera_quando_manca(self):
        t = Testata.objects.create(job="REVFLG4", rev_let_flag=True)
        doc = Documento.objects.create(testata=t, vendor_doc="REVFLG4-01")
        Revisione.objects.create(documento=doc, rev_no=2, rev_let="")

        self.assertEqual(list_documenti("REVFLG4")[0]["latest_rev_display"], "C")

    def test_list_documenti_deriva_il_numero_quando_manca(self):
        t = Testata.objects.create(job="REVFLG5", rev_let_flag=False)
        doc = Documento.objects.create(testata=t, vendor_doc="REVFLG5-01")
        Revisione.objects.create(documento=doc, rev_no=None, rev_let="C")

        self.assertEqual(list_documenti("REVFLG5")[0]["latest_rev_display"], "2")

    def test_str_della_revisione_segue_il_flag(self):
        con_lettera = Testata.objects.create(job="REVFLG6", rev_let_flag=True)
        senza_lettera = Testata.objects.create(job="REVFLG7", rev_let_flag=False)
        doc_lettera = Documento.objects.create(testata=con_lettera, vendor_doc="REVFLG6-01")
        doc_numero = Documento.objects.create(testata=senza_lettera, vendor_doc="REVFLG7-01")
        rev_lettera = Revisione.objects.create(documento=doc_lettera, rev_no=1, rev_let="")
        rev_numero = Revisione.objects.create(documento=doc_numero, rev_no=1, rev_let="B")

        self.assertEqual(rev_lettera.etichetta(), "B")
        self.assertEqual(str(rev_lettera), "Rev B")
        self.assertEqual(rev_numero.etichetta(), "1")
        self.assertEqual(str(rev_numero), "Rev 1")


class RevisioneLabelExportTests(TestCase):
    """Excel, PDF e trasmittal stampano la revisione come dice l'archivio."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "revexp_user",
            "revexp@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
        )
        self.client.force_login(self.user)
        self.testata = Testata.objects.create(job="REVEXP1", client="ACME", rev_let_flag=True)
        self.doc = Documento.objects.create(
            testata=self.testata,
            item_no="001",
            vendor_doc="REVEXP1-01",
            doc_title="Data book index",
        )
        # Nessuna lettera in archivio: deve comunque uscire "B" (rev_no 1).
        self.rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=1,
            rev_let="",
            dis_plan_date=date(2026, 3, 15),
        )

    def _colonna_rev(self, vista="orizzontale"):
        import openpyxl

        response = self.client.get(
            f"/api/commesse/{self.testata.job}/situazione/export/?format=xlsx&vista={vista}"
        )
        self.assertEqual(response.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(response.content)).active
        # Le colonne fisse hanno l'intestazione in riga 1 (unita con la riga 2).
        intestazioni = [cell.value for cell in ws[1]]
        col = intestazioni.index("Rev.") + 1
        return [ws.cell(row=r, column=col).value for r in range(3, ws.max_row + 1)]

    def test_export_xlsx_usa_la_lettera_col_flag_attivo(self):
        self.assertEqual(self._colonna_rev(), ["B"])
        self.assertEqual(self._colonna_rev(vista="verticale"), ["B"])

    def test_export_xlsx_usa_il_numero_col_flag_spento(self):
        self.testata.rev_let_flag = False
        self.testata.save(update_fields=["rev_let_flag"])
        self.rev.rev_let = "B"
        self.rev.save(update_fields=["rev_let"])

        self.assertEqual(self._colonna_rev(), ["1"])

    def test_intestazione_pdf_situazione_segue_il_flag(self):
        from src.pdf import _rev_group_label

        revs = [[{"rev_no": 0, "rev_let": ""}, {"rev_no": 1, "rev_let": ""}]]
        self.assertEqual(_rev_group_label(revs, 0, True), "Rev. A")
        self.assertEqual(_rev_group_label(revs, 1, True), "Rev. B")
        self.assertEqual(_rev_group_label(revs, 0, False), "Rev. 0")
        # Posizione senza revisioni: l'etichetta resta coerente col flag.
        self.assertEqual(_rev_group_label([[]], 2, True), "Rev. C")
        self.assertEqual(_rev_group_label([[]], 2, False), "Rev. 2")

    def test_righe_pdf_verticale_seguono_il_flag(self):
        from src.pdf import _situazione_verticale_flat_rows

        documenti = list_documenti(self.testata.job)
        rev_map = revisioni_by_doc_for_job(self.testata.job)
        righe = _situazione_verticale_flat_rows(documenti, rev_map, True)
        self.assertEqual([r["rev_label"] for r in righe], ["B"])
        righe_numero = _situazione_verticale_flat_rows(documenti, rev_map, False)
        self.assertEqual([r["rev_label"] for r in righe_numero], ["1"])

    def test_documenti_del_trasmittal_portano_la_revisione_giusta(self):
        from core.views import _trasmittal_documents
        from src.pdf import _cell_value_for_col

        documents = _trasmittal_documents(self.testata, [self.doc.pk])
        self.assertEqual(documents[0]["rev_label"], "B")
        self.assertEqual(_cell_value_for_col(documents[0], "rev_no"), "B")

        self.testata.rev_let_flag = False
        self.testata.save(update_fields=["rev_let_flag"])
        documents = _trasmittal_documents(self.testata, [self.doc.pk])
        self.assertEqual(documents[0]["rev_label"], "1")
        self.assertEqual(_cell_value_for_col(documents[0], "rev_no"), "1")

    def test_le_pagine_ricevono_il_flag_e_l_helper_condiviso(self):
        """Le tabelle costruite in JS formattano la revisione con la regola condivisa."""
        for url in (
            f"/commesse/{self.testata.job}/documenti/",
            f"/commesse/{self.testata.job}/situazione/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "function formatRevLabel(rev, revLetFlag)")
                self.assertContains(response, "REV_LET_FLAG = true")

    def test_export_emissione_xlsx_usa_la_lettera(self):
        import openpyxl

        response = self.client.get(f"/api/commesse/{self.testata.job}/emissione/export/")
        self.assertEqual(response.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(response.content)).active
        col = [cell.value for cell in ws[1]].index("Rev.") + 1
        self.assertEqual(
            [ws.cell(row=r, column=col).value for r in range(2, ws.max_row + 1)], ["B"]
        )


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


class ColoriRisposteClienteTests(SimpleTestCase):
    """Colori delle celle legate alle risposte del cliente (viste situazione)."""

    # ── Conversioni ──────────────────────────────────────────────────────────

    def test_hex_to_rgb_accetta_le_forme_valide(self):
        self.assertEqual(hex_to_rgb("#00B050"), (0, 176, 80))
        self.assertEqual(hex_to_rgb("00b050"), (0, 176, 80))
        self.assertEqual(hex_to_rgb("  #FFC000 "), (255, 192, 0))
        self.assertEqual(hex_to_rgb("#FFF"), (255, 255, 255))

    def test_hex_to_rgb_rifiuta_i_valori_non_validi(self):
        for value in ["", None, "verde", "#12", "#12345", "#GGGGGG"]:
            self.assertIsNone(hex_to_rgb(value), value)

    def test_rgb_to_hex_normalizza_in_maiuscolo(self):
        self.assertEqual(rgb_to_hex((0, 176, 80)), "#00B050")
        self.assertEqual(rgb_to_hex((255.4, -3, 300)), "#FF00FF")

    # ── Scelta del testo ─────────────────────────────────────────────────────

    def test_testo_nero_su_colori_chiari(self):
        # Bianco e quasi bianco: il testo bianco sparirebbe.
        for colore in ["#FFFFFF", "#FEFEFE", "#FFFF00", "#FFC000", "#9E9E9E"]:
            self.assertEqual(readable_text_color(colore), TEXT_DARK, colore)

    def test_testo_bianco_su_colori_scuri(self):
        # Nero e grigi scuri: il testo nero sparirebbe.
        for colore in ["#000000", "#111111", "#404040", "#0070C0", "#D61D09"]:
            self.assertEqual(readable_text_color(colore), TEXT_LIGHT, colore)

    def test_testo_di_default_quando_il_colore_manca(self):
        self.assertEqual(readable_text_color(""), readable_text_color(FALLBACK_BG))

    # ── Colori della cella ───────────────────────────────────────────────────

    def test_fondo_uguale_al_colore_configurato(self):
        # Uniformità con la legenda: il colore inserito non viene sbiadito.
        for colore in ["#00B050", "#FFC000", "#FFFFFF", "#000000", "#D61D09"]:
            self.assertEqual(cell_colors(colore)["bg"], colore, colore)

    def test_bianco_e_nero_restano_leggibili(self):
        self.assertEqual(cell_colors("#FFFFFF"), {"bg": "#FFFFFF", "fg": TEXT_DARK})
        self.assertEqual(cell_colors("#000000"), {"bg": "#000000", "fg": TEXT_LIGHT})

    def test_mezzi_toni_spostati_quel_tanto_che_basta(self):
        # Su #797979 nessuno dei due testi arriva al contrasto minimo: il fondo
        # si sposta di pochi punti, restando lo stesso colore a vista.
        cella = cell_colors("#797979")
        self.assertNotEqual(cella["bg"], "#797979")
        self.assertGreaterEqual(contrast_ratio(cella["bg"], cella["fg"]), MIN_CONTRAST)
        scarto = max(abs(a - b) for a, b in zip(hex_to_rgb("#797979"), hex_to_rgb(cella["bg"])))
        self.assertLessEqual(scarto, 25)

    def test_contrasto_minimo_garantito_su_tutta_la_gamma(self):
        passo = 51  # campiona 6 livelli per canale
        for r in range(0, 256, passo):
            for g in range(0, 256, passo):
                for b in range(0, 256, passo):
                    colore = rgb_to_hex((r, g, b))
                    cella = cell_colors(colore)
                    self.assertGreaterEqual(
                        contrast_ratio(cella["bg"], cella["fg"]),
                        MIN_CONTRAST,
                        colore,
                    )
                    scarto = max(abs(a - b) for a, b in zip((r, g, b), hex_to_rgb(cella["bg"])))
                    self.assertLessEqual(scarto, 25, colore)

    def test_colore_mancante_o_invalido_usa_il_fallback(self):
        atteso = {"bg": FALLBACK_BG, "fg": readable_text_color(FALLBACK_BG)}
        for colore in ["", None, "  ", "non-un-colore"]:
            self.assertEqual(cell_colors(colore), atteso, colore)


class ColoriRisposteClienteApiTests(TestCase):
    """I colori pronti per le celle viaggiano nei payload delle viste."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "colori_user",
            "colori@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
        )
        self.client.force_login(self.user)
        self.testata = Testata.objects.create(job="COL01")
        self.doc = Documento.objects.create(
            testata=self.testata, item_no="001", vendor_doc="COL01-01-0001"
        )
        self.approved = StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        self.final = StatoEsterno.objects.create(
            nome="Final - As Built", lettera="F", colore="#FFFFFF"
        )

    def test_serialize_revisione_include_i_colori_della_cella(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.approved)
        data = serialize_revisione(rev)
        self.assertEqual(data["ext_status_colore"], "#00B050")
        self.assertEqual(data["ext_status_bg"], "#00B050")
        self.assertEqual(data["ext_status_fg"], TEXT_DARK)

    def test_serialize_revisione_su_stato_bianco_usa_testo_nero(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.final)
        data = serialize_revisione(rev)
        self.assertEqual(data["ext_status_bg"], "#FFFFFF")
        self.assertEqual(data["ext_status_fg"], TEXT_DARK)

    def test_serialize_revisione_senza_risposta_non_ha_colori(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0)
        data = serialize_revisione(rev)
        self.assertEqual(data["ext_status_bg"], "")
        self.assertEqual(data["ext_status_fg"], "")

    def test_situazione_api_include_i_colori_della_cella(self):
        Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.approved)
        response = self.client.get(f"/api/commesse/{self.testata.job}/situazione/")
        self.assertEqual(response.status_code, 200)
        revs = response.json()["revisioni_by_doc"][str(self.doc.pk)]
        self.assertEqual(revs[0]["ext_status_bg"], "#00B050")
        self.assertEqual(revs[0]["ext_status_fg"], TEXT_DARK)

    def test_revisioni_sbloccabili_includono_i_colori_della_cella(self):
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            rec_act_date="2025-06-01",
            ext_status=self.final,
            int_status="ricevuto",
        )
        items = list_revisioni_sbloccabili(self.testata.job)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ext_status_bg"], "#FFFFFF")
        self.assertEqual(items[0]["ext_status_fg"], TEXT_DARK)

    def test_pdf_colora_la_cella_vendor_con_il_colore_pieno(self):
        from src.pdf import _status_cell_rgb

        self.assertEqual(_status_cell_rgb("#00B050"), ((0, 176, 80), hex_to_rgb(TEXT_DARK)))
        self.assertEqual(_status_cell_rgb("#D61D09"), ((214, 29, 9), hex_to_rgb(TEXT_LIGHT)))
        self.assertIsNone(_status_cell_rgb(""))


class LegendaStatusPdfTests(TestCase):
    """La legenda STATUS dell'header PDF segue le risposte messe a sistema."""

    def _colori_disegnati(self, vista="orizzontale", **kwargs):
        """Colori passati a ``set_fill_color`` generando il PDF situazione."""
        from src.pdf import SituazioneDocumentiPDF, genera_situazione_documenti_pdf

        originale = SituazioneDocumentiPDF.set_fill_color
        chiamate = []

        def spia(pdf, *args):
            chiamate.append(tuple(args))
            return originale(pdf, *args)

        with patch.object(SituazioneDocumentiPDF, "set_fill_color", spia):
            genera_situazione_documenti_pdf(
                {"job": "LEG01", "client": "ACME"},
                documenti=[],
                revisioni_by_doc={},
                vista=vista,
                **kwargs,
            )
        return chiamate

    # ── Voci della legenda ───────────────────────────────────────────────────

    def test_legenda_usa_lettera_nome_e_colore_configurati(self):
        StatoEsterno.objects.create(nome="Rejected", lettera="R", colore="#8B0000")
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#0070C0")
        self.assertEqual(
            legenda_stati_esterni(),
            [
                {"lettera": "A", "nome": "Approved", "colore": "#0070C0"},
                {"lettera": "R", "nome": "Rejected", "colore": "#8B0000"},
            ],
        )

    def test_lettera_dedotta_dal_nome_quando_non_e_configurata(self):
        StatoEsterno.objects.create(nome="Final - As Built", colore="#FFC000")
        self.assertEqual(legenda_stati_esterni()[0]["lettera"], "F")

    def test_colore_mancante_ricade_sul_default_della_lettera(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="")
        self.assertEqual(legenda_stati_esterni()[0]["colore"], DEFAULT_STATUS_COLORS["A"])

    def test_risposta_senza_lettera_riconoscibile_resta_fuori(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        StatoEsterno.objects.create(nome="Stato inventato", colore="#123456")
        self.assertEqual([voce["lettera"] for voce in legenda_stati_esterni()], ["A"])

    def test_senza_risposte_a_sistema_resta_la_legenda_canonica(self):
        self.assertEqual(legenda_stati_esterni(), legenda_default())
        self.assertEqual(
            [voce["lettera"] for voce in legenda_default()],
            ["A", "C", "F", "I", "O", "R", "S", "Z"],
        )

    # ── Righe disegnate nel PDF ──────────────────────────────────────────────

    def test_le_voci_del_pdf_usano_il_fondo_delle_celle(self):
        from src.pdf import _status_legend_entries

        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#FFFFFF")
        self.assertEqual(_status_legend_entries(), [("A", "Approved", (255, 255, 255))])

    def test_voce_con_colore_non_valido_usa_il_fallback(self):
        from src.pdf import _status_legend_entries

        voci = [{"lettera": "A", "nome": "Approved", "colore": "non-un-colore"}]
        self.assertEqual(_status_legend_entries(voci)[0][2], hex_to_rgb(FALLBACK_BG))

    def test_le_voci_si_fermano_alle_righe_disponibili(self):
        from src.pdf import _LEGEND_MAX_ROWS, _status_legend_entries

        voci = [
            {"lettera": chr(ord("A") + i), "nome": f"Stato {i}", "colore": "#00B050"}
            for i in range(_LEGEND_MAX_ROWS + 3)
        ]
        self.assertEqual(len(_status_legend_entries(voci)), _LEGEND_MAX_ROWS)

    def test_le_righe_restano_dentro_il_riquadro_status(self):
        from src.pdf import _HEADER_BOTTOM_PT, _LEGEND_MAX_ROWS, _legend_row_ys

        otto = _legend_row_ys(8)
        # Otto voci = layout storico del foglio di riferimento.
        self.assertEqual(len(otto), 8)
        self.assertAlmostEqual(otto[0], 49.5)
        self.assertAlmostEqual(otto[1] - otto[0], 9.7)
        for count in range(1, _LEGEND_MAX_ROWS + 1):
            ys = _legend_row_ys(count)
            self.assertEqual(len(ys), count)
            self.assertLess(ys[-1], _HEADER_BOTTOM_PT, count)

    # ── PDF generato ─────────────────────────────────────────────────────────

    def test_il_pdf_orizzontale_usa_i_colori_a_sistema(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#0070C0")
        colori = self._colori_disegnati(vista="orizzontale")
        self.assertIn((0, 112, 192), colori)
        # Il vecchio verde fisso non viene più disegnato.
        self.assertNotIn((0, 176, 80), colori)

    def test_il_pdf_verticale_usa_i_colori_a_sistema(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#0070C0")
        colori = self._colori_disegnati(vista="verticale")
        self.assertIn((0, 112, 192), colori)
        self.assertNotIn((0, 176, 80), colori)

    def test_cambiare_colore_a_sistema_cambia_la_legenda(self):
        approved = StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        self.assertIn((0, 176, 80), self._colori_disegnati())
        approved.colore = "#0070C0"
        approved.save(update_fields=["colore"])
        colori = self._colori_disegnati()
        self.assertIn((0, 112, 192), colori)
        self.assertNotIn((0, 176, 80), colori)

    def test_legenda_passata_a_mano_ha_la_precedenza(self):
        StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")
        voci = [{"lettera": "A", "nome": "Approved", "colore": "#0070C0"}]
        colori = self._colori_disegnati(status_legend=voci)
        self.assertIn((0, 112, 192), colori)
        self.assertNotIn((0, 176, 80), colori)


class StatoInternoEffettivoTests(TestCase):
    """Lo stato interno mostrato quando in archivio è rimasto vuoto."""

    def setUp(self):
        self.testata = Testata.objects.create(job="INT01")
        self.doc = Documento.objects.create(
            testata=self.testata, item_no="001", vendor_doc="INT01-01-0001"
        )
        self.approved = StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")

    def test_risposta_cliente_senza_stato_salvato_e_ricevuta(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.approved)
        data = serialize_revisione(rev)
        self.assertEqual(data["int_status"], "")
        self.assertEqual(data["int_status_eff"], "ricevuto")
        self.assertEqual(data["int_status_eff_label"], "Ricevuto")

    def test_data_di_invio_senza_stato_salvato_e_inviata(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0, dis_act_date=date(2025, 1, 1))
        data = serialize_revisione(rev)
        self.assertEqual(data["int_status_eff"], "inviato_al_cliente")

    def test_revisione_senza_nulla_resta_da_inviare(self):
        rev = Revisione.objects.create(documento=self.doc, rev_no=0)
        data = serialize_revisione(rev)
        self.assertEqual(data["int_status_eff"], "")
        self.assertEqual(data["int_status_eff_label"], "Da inviare")

    def test_stato_salvato_ha_la_precedenza(self):
        rev = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            int_status="in_lavorazione",
            ext_status=self.approved,
        )
        data = serialize_revisione(rev)
        self.assertEqual(data["int_status_eff"], "in_lavorazione")

    def test_documento_con_risposta_cliente_non_e_da_emettere(self):
        Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.approved)
        doc = list_documenti(self.testata.job)[0]
        self.assertEqual(doc["latest_int_status"], "ricevuto")
        self.assertEqual(doc["latest_int_status_label"], "Ricevuto")

    def test_etichetta_export_segue_lo_stato_effettivo(self):
        from src.pdf import _int_status_export_label

        rev = Revisione.objects.create(documento=self.doc, rev_no=0, ext_status=self.approved)
        self.assertEqual(_int_status_export_label(serialize_revisione(rev)), "Ricevuto")
        self.assertEqual(_int_status_export_label(None), "Da inviare")
        self.assertEqual(_int_status_export_label({}), "Da inviare")


# ── Update dati da Business Central ───────────────────────────────────────────


class _FakeBusinessCentral:
    """Connettore Business Central finto con dati preparati per commessa.

    Un valore ``Exception`` fra i dati viene sollevato al posto della risposta,
    così da simulare una query fallita su una singola commessa.
    """

    def __init__(self, dati_per_job, conn=True):
        self.dati_per_job = dati_per_job
        self.conn = "connessione-finta" if conn else None
        self.jobs_richiesti = []
        self.chiusa = False

    def dati_commessa(self, job):
        self.jobs_richiesti.append(job)
        dati = self.dati_per_job.get(job, {})
        if isinstance(dati, Exception):
            raise dati
        return dict(dati)

    def close(self):
        self.chiusa = True


class SincronizzazioneBusinessCentralTests(TestCase):
    """Controllo giornaliero di congruenza fra Business Central e le commesse."""

    def setUp(self):
        self.testata = Testata.objects.create(
            job="26010",
            client="Cliente Vecchio",
            po_no="PO-1",
            job_detail="Descrizione vecchia",
            delivery_date=date(2026, 1, 10),
        )

    def _attiva_bc(self, dati_per_job, conn=True):
        """Sostituisce connettore e lettura BC con un doppio di test."""
        fake = _FakeBusinessCentral(dati_per_job, conn=conn)
        connessione = patch("core.services.bc_sync._apri_connessione", return_value=fake)
        lettura = patch(
            "core.services.bc_sync.fetch_from_bc",
            side_effect=lambda job, bc=None: bc.dati_commessa(job),
        )
        connessione.start()
        lettura.start()
        self.addCleanup(connessione.stop)
        self.addCleanup(lettura.stop)
        return fake

    @staticmethod
    def _dati_bc(**overrides):
        dati = {
            "job": "26010",
            "client": "Cliente Nuovo",
            "job_detail": "Descrizione nuova",
            "po_no": "PO-2",
            "delivery_date": "2026-03-01",
        }
        dati.update(overrides)
        return dati

    def test_aggiorna_i_campi_disallineati(self):
        self._attiva_bc({"26010": self._dati_bc()})

        report = sincronizza_commesse()

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Nuovo")
        self.assertEqual(self.testata.po_no, "PO-2")
        self.assertEqual(self.testata.job_detail, "Descrizione nuova")
        self.assertEqual(self.testata.delivery_date, date(2026, 3, 1))
        self.assertEqual(report["controllate"], 1)
        self.assertEqual(report["aggiornate"], 1)
        self.assertEqual(report["non_trovate"], [])
        self.assertEqual(report["errori"], [])
        self.assertEqual(len(report["aggiornamenti"]), 4)

    def test_accetta_una_data_timestamp_da_bc(self):
        self._attiva_bc({"26010": self._dati_bc(delivery_date=pd.Timestamp("2026-03-01"))})

        sincronizza_commesse()

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.delivery_date, date(2026, 3, 1))

    def test_ogni_modifica_viene_registrata(self):
        self._attiva_bc({"26010": self._dati_bc(job_detail="Descrizione vecchia", po_no="PO-1")})

        sincronizza_commesse()

        registrati = {
            (a.campo, a.valore_precedente, a.valore_nuovo)
            for a in AggiornamentoBC.objects.filter(testata=self.testata)
        }
        self.assertEqual(
            registrati,
            {
                ("client", "Cliente Vecchio", "Cliente Nuovo"),
                ("delivery_date", "2026-01-10", "2026-03-01"),
            },
        )

    def test_valori_vuoti_in_bc_non_sovrascrivono(self):
        self._attiva_bc(
            {
                "26010": {
                    "job": "26010",
                    "client": "   ",
                    "po_no": None,
                    "job_detail": float("nan"),
                    "delivery_date": "",
                }
            }
        )

        report = sincronizza_commesse()

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Vecchio")
        self.assertEqual(self.testata.po_no, "PO-1")
        self.assertEqual(self.testata.job_detail, "Descrizione vecchia")
        self.assertEqual(self.testata.delivery_date, date(2026, 1, 10))
        self.assertEqual(report["aggiornate"], 0)
        self.assertFalse(AggiornamentoBC.objects.exists())

    def test_dati_gia_allineati_non_producono_modifiche(self):
        self._attiva_bc(
            {
                "26010": {
                    "job": "26010",
                    "client": "Cliente Vecchio",
                    "po_no": "PO-1",
                    "job_detail": "Descrizione vecchia",
                    "delivery_date": "2026-01-10",
                }
            }
        )

        report = sincronizza_commesse()

        self.assertEqual(report["controllate"], 1)
        self.assertEqual(report["aggiornate"], 0)
        self.assertEqual(report["aggiornamenti"], [])
        self.assertFalse(AggiornamentoBC.objects.exists())

    def test_dry_run_mostra_le_differenze_senza_salvarle(self):
        self._attiva_bc({"26010": self._dati_bc()})

        report = sincronizza_commesse(dry_run=True)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Vecchio")
        self.assertFalse(AggiornamentoBC.objects.exists())
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["aggiornate"], 1)
        self.assertEqual(len(report["aggiornamenti"]), 4)

    def test_le_commesse_chiuse_sono_escluse(self):
        Testata.objects.create(job="25001", actual_delivery_date=date(2025, 12, 31))
        fake = self._attiva_bc({"26010": self._dati_bc()})

        sincronizza_commesse()

        self.assertEqual(fake.jobs_richiesti, ["26010"])

    def test_le_commesse_chiuse_si_possono_includere(self):
        Testata.objects.create(job="25001", actual_delivery_date=date(2025, 12, 31))
        fake = self._attiva_bc({"26010": self._dati_bc()})

        sincronizza_commesse(includi_chiuse=True)

        self.assertEqual(fake.jobs_richiesti, ["25001", "26010"])

    def test_si_puo_controllare_una_sola_commessa(self):
        Testata.objects.create(job="26011")
        fake = self._attiva_bc({"26010": self._dati_bc()})

        sincronizza_commesse(jobs=["26010"])

        self.assertEqual(fake.jobs_richiesti, ["26010"])

    def test_commessa_assente_in_bc_viene_segnalata(self):
        self._attiva_bc({})

        report = sincronizza_commesse()

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Vecchio")
        self.assertEqual(report["non_trovate"], ["26010"])
        self.assertEqual(report["aggiornate"], 0)

    def test_un_errore_non_blocca_le_altre_commesse(self):
        Testata.objects.create(job="26011", client="Altro Cliente")
        self._attiva_bc(
            {
                "26010": RuntimeError("query fallita"),
                "26011": {"job": "26011", "client": "Cliente Nuovo"},
            }
        )

        report = sincronizza_commesse()

        self.assertEqual(report["controllate"], 2)
        self.assertEqual(report["aggiornate"], 1)
        self.assertEqual(report["errori"], [{"job": "26010", "errore": "query fallita"}])
        self.assertEqual(Testata.objects.get(job="26011").client, "Cliente Nuovo")

    def test_connessione_non_disponibile_solleva_errore(self):
        fake = self._attiva_bc({"26010": self._dati_bc()}, conn=False)

        with self.assertRaises(BusinessCentralNonDisponibile):
            sincronizza_commesse()

        self.assertTrue(fake.chiusa)
        self.assertFalse(AggiornamentoBC.objects.exists())

    def test_la_connessione_viene_chiusa_a_fine_controllo(self):
        fake = self._attiva_bc({"26010": self._dati_bc()})

        sincronizza_commesse()

        self.assertTrue(fake.chiusa)

    def test_valore_bc_troppo_lungo_viene_troncato_e_resta_allineato(self):
        descrizione = "X" * 400
        self._attiva_bc({"26010": self._dati_bc(job_detail=descrizione)})

        sincronizza_commesse()
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.job_detail, "X" * 300)

        # Secondo giro: il valore troncato non deve risultare di nuovo diverso.
        report = sincronizza_commesse()
        self.assertEqual(report["aggiornate"], 0)
        self.assertEqual(AggiornamentoBC.objects.filter(campo="job_detail").count(), 1)

    def test_confronta_ignora_i_campi_non_sincronizzati(self):
        differenze = confronta_commessa(self.testata, {"job": "99999", "requisition": "BID-9"})

        self.assertEqual(differenze, [])

    def test_lista_aggiornamenti_per_la_pagina_archivio(self):
        self._attiva_bc({"26010": self._dati_bc()})
        sincronizza_commesse()

        voci = {v["campo"]: v for v in list_aggiornamenti("26010")}

        self.assertEqual(voci["client"]["etichetta"], "Cliente")
        self.assertEqual(voci["client"]["nuovo"], "Cliente Nuovo")
        # Le date sono già pronte per l'interfaccia (10 jan 2026 → 1 mar 2026).
        self.assertEqual(voci["delivery_date"]["precedente"], "10 jan 2026")
        self.assertEqual(voci["delivery_date"]["nuovo"], "1 mar 2026")

    def test_fetch_from_bc_riusa_il_connettore_aperto(self):
        bc = Mock()
        bc.get_commessa_anagrafica.return_value = pd.DataFrame(
            [{"commessa": "26010", "descrizione": "Descrizione BC", "cliente": "Cliente BC"}]
        )
        bc.get_commessa_commerciale.return_value = pd.DataFrame(
            [{"commessa": "26010", "po_cliente": "PO-BC", "data_consegna": "2026-03-01"}]
        )

        dati = fetch_from_bc("26010", bc=bc)

        self.assertEqual(dati["client"], "Cliente BC")
        self.assertEqual(dati["job_detail"], "Descrizione BC")
        self.assertEqual(dati["po_no"], "PO-BC")
        self.assertEqual(dati["delivery_date"], "2026-03-01")
        bc.close.assert_not_called()


class ComandoSyncBusinessCentralTests(TestCase):
    """Il comando ``sync_business_central``, pensato per l'esecuzione giornaliera."""

    def setUp(self):
        self.testata = Testata.objects.create(job="26010", client="Cliente Vecchio")

    def _attiva_bc(self, dati_per_job, conn=True):
        fake = _FakeBusinessCentral(dati_per_job, conn=conn)
        connessione = patch("core.services.bc_sync._apri_connessione", return_value=fake)
        lettura = patch(
            "core.services.bc_sync.fetch_from_bc",
            side_effect=lambda job, bc=None: bc.dati_commessa(job),
        )
        connessione.start()
        lettura.start()
        self.addCleanup(connessione.stop)
        self.addCleanup(lettura.stop)
        return fake

    def test_il_comando_aggiorna_e_riepiloga(self):
        self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})
        out = io.StringIO()

        call_command("sync_business_central", stdout=out)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Nuovo")
        output = out.getvalue()
        self.assertIn("26010: Cliente: Cliente Vecchio → Cliente Nuovo", output)
        self.assertIn("Controllate 1 commesse, aggiornate 1", output)

    def test_il_comando_in_dry_run_non_salva(self):
        self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})
        out = io.StringIO()

        call_command("sync_business_central", "--dry-run", stdout=out)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Vecchio")
        self.assertIn("[dry-run]", out.getvalue())

    def test_il_comando_accetta_una_singola_commessa(self):
        Testata.objects.create(job="26011")
        fake = self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})

        call_command("sync_business_central", "--job", "26010", stdout=io.StringIO())

        self.assertEqual(fake.jobs_richiesti, ["26010"])

    def test_il_comando_segnala_una_commessa_inesistente(self):
        self._attiva_bc({})
        err = io.StringIO()

        call_command("sync_business_central", "--job", "99999", stderr=err)

        self.assertIn("non trovata", err.getvalue())

    def test_il_comando_segnala_business_central_non_raggiungibile(self):
        self._attiva_bc({"26010": {"job": "26010"}}, conn=False)
        err = io.StringIO()

        call_command("sync_business_central", stderr=err)

        self.assertIn("Connessione a Business Central non disponibile", err.getvalue())


class SchedulerBusinessCentralTests(TestCase):
    """Lo scheduler interno che lancia la sincronizzazione BC una volta al giorno."""

    def setUp(self):
        self.oggi = timezone.localtime().date()

    @staticmethod
    def _momento(giorno, ora, minuto):
        """Istante locale, con il fuso della configurazione."""
        return timezone.make_aware(datetime.combine(giorno, time(ora, minuto)))

    def _sync_finta(self, **report):
        """Sostituisce la sincronizzazione vera con un doppio di test."""
        dati = {
            "controllate": 3,
            "aggiornate": 1,
            "non_trovate": [],
            "errori": [],
        }
        dati.update(report)
        finta = patch("core.services.scheduler.sincronizza_commesse", return_value=dati)
        mock = finta.start()
        self.addCleanup(finta.stop)
        return mock

    def _stato(self):
        return EsecuzioneSchedulata.objects.get(nome=scheduler.NOME_JOB)

    def test_non_esegue_prima_dell_orario(self):
        adesso = self._momento(self.oggi, 16, 59)

        self.assertFalse(scheduler._deve_eseguire(None, adesso))

    def test_esegue_dopo_l_orario(self):
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler._deve_eseguire(None, adesso))

    def test_non_riesegue_nello_stesso_giorno(self):
        ultima = self._momento(self.oggi, 17, 2)
        adesso = self._momento(self.oggi, 18, 0)

        self.assertFalse(scheduler._deve_eseguire(ultima, adesso))

    def test_recupera_l_esecuzione_persa(self):
        """Server spento alle 17:00 e riacceso alle 19:00: la sync parte comunque."""
        ultima = self._momento(self.oggi - timedelta(days=1), 17, 0)
        adesso = self._momento(self.oggi, 19, 0)

        self.assertTrue(scheduler._deve_eseguire(ultima, adesso))

    def test_esegue_la_sync_e_registra_l_esito(self):
        sync = self._sync_finta()
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        sync.assert_called_once_with()
        stato = self._stato()
        self.assertEqual(timezone.localtime(stato.ultima_esecuzione), adesso)
        self.assertIn("controllate 3", stato.esito)
        self.assertIn("aggiornate 1", stato.esito)

    def test_un_secondo_giro_non_riesegue(self):
        sync = self._sync_finta()
        adesso = self._momento(self.oggi, 17, 1)

        scheduler.esegui_se_dovuto(adesso=adesso)
        eseguito = scheduler.esegui_se_dovuto(adesso=self._momento(self.oggi, 17, 6))

        self.assertFalse(eseguito)
        self.assertEqual(sync.call_count, 1)

    def test_business_central_non_disponibile_non_propaga(self):
        finta = patch(
            "core.services.scheduler.sincronizza_commesse",
            side_effect=BusinessCentralNonDisponibile("ERP irraggiungibile"),
        )
        sync = finta.start()
        self.addCleanup(finta.stop)
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        self.assertIn("errore", self._stato().esito)
        # Un tentativo al giorno: dopo un errore si ritenta domani, non subito.
        self.assertFalse(scheduler.esegui_se_dovuto(adesso=self._momento(self.oggi, 17, 6)))
        self.assertEqual(sync.call_count, 1)

    def test_un_errore_imprevisto_resta_nel_giro(self):
        finta = patch(
            "core.services.scheduler.sincronizza_commesse",
            side_effect=RuntimeError("driver ODBC assente"),
        )
        finta.start()
        self.addCleanup(finta.stop)

        scheduler.esegui_se_dovuto(adesso=self._momento(self.oggi, 17, 1))

        self.assertIn("driver ODBC assente", self._stato().esito)

    def test_orario_malformato_ricade_sul_predefinito(self):
        with self.settings(BC_SYNC_ORARIO="mezzogiorno"):
            self.assertEqual(scheduler._ora_schedulata(), scheduler.ORARIO_PREDEFINITO)

    def test_lo_scheduler_non_parte_durante_i_test(self):
        with patch.object(sys, "argv", ["manage.py", "test"]):
            self.assertFalse(scheduler._processo_adatto())

    def test_lo_scheduler_parte_sotto_il_server_wsgi(self):
        with patch.object(sys, "argv", ["gunicorn", "config.wsgi:application"]):
            self.assertTrue(scheduler._processo_adatto())


class ArchivioAggiornamentiBCViewTests(TestCase):
    """La pagina Informazioni archivio mostra le modifiche arrivate da BC."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "bc_user",
            "bc@brembanarolle.com",
            "pw",
            permesso=Permesso.READING,
        )
        self.client.force_login(self.user)
        self.testata = Testata.objects.create(job="26010", client="Cliente Nuovo")

    def test_la_pagina_elenca_gli_aggiornamenti(self):
        AggiornamentoBC.objects.create(
            testata=self.testata,
            campo="client",
            valore_precedente="Cliente Vecchio",
            valore_nuovo="Cliente Nuovo",
        )

        response = self.client.get(f"/commesse/{self.testata.job}/archivio/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aggiornamenti da Business Central")
        self.assertContains(response, "Cliente Vecchio")

    def test_senza_aggiornamenti_mostra_lo_stato_allineato(self):
        response = self.client.get(f"/commesse/{self.testata.job}/archivio/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nessun aggiornamento da Business Central")


class _FakeBCQcp:
    """Connettore Business Central finto per il Quality Control Plan.

    ``conn=False`` simula un ERP irraggiungibile; un'``Exception`` al posto dei
    dati simula una query fallita.
    """

    def __init__(self, testata=None, items=None, conn=True):
        self.conn = "connessione-finta" if conn else None
        self._testata = testata
        self._items = items
        self.chiusa = False

    @staticmethod
    def _df(dati):
        if isinstance(dati, Exception):
            raise dati
        return None if dati is None else pd.DataFrame(dati)

    def get_qcp_testata(self, job):
        return self._df(self._testata)

    def get_qcp_items(self, job):
        return self._df(self._items)

    def close(self):
        self.chiusa = True


QCP_API = "/api/commesse/26010/quality-control-plan/"
QCP_PREFILL = "/api/commesse/26010/quality-control-plan/prefill/"
QCP_PAGE = "/commesse/26010/quality-control-plan/"

_BC_TESTATA = [
    {
        "progetto": "MOPCO UREA REVAMP PROJECT",
        "owner": "MOPCO",
        "purchaser": "THYSSENKRUPP UHDE GmbH",
        "po_cliente": "4000244916",
    }
]
_BC_ITEMS = [
    {"item": "ITEM 2253E001", "descrizione": "COLUMN HEATER", "quantita": 3},
    {"item": "ITEM 2253E003", "descrizione": "PRE-EVAPORATOR", "quantita": 3},
]


class QualityControlPlanTests(TestCase):
    """Sezione Quality Control Plan: pagina, precompilazione, creazione, elenco."""

    def setUp(self):
        self.client = Client()
        self.testata = Testata.objects.create(
            job="26010",
            client="CLIENTE LOCALE",
            po_no="PO-LOCALE",
            time_cli_doc_rev=10,
            time_ven_doc_rev=5,
        )
        self.writer = User.objects.create_user(
            "qcp_writer",
            "qcp-writer@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Paolo",
            last_name="Litta",
        )
        self.reader = User.objects.create_user(
            "qcp_reader", "qcp-reader@brembanarolle.com", "pw", permesso=Permesso.READING
        )
        self.client.force_login(self.writer)

    def _crea(self, **payload):
        payload.setdefault("items", ["ITEM A"])
        return self.client.post(QCP_API, data=json.dumps(payload), content_type="application/json")

    @staticmethod
    def _bc(**kwargs):
        return patch(
            "core.services.quality_control_plan._apri_connessione",
            return_value=_FakeBCQcp(**kwargs),
        )

    # -- Pagina --

    def test_la_pagina_si_apre_e_mostra_il_pulsante_crea(self):
        response = self.client.get(QCP_PAGE)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/quality_control_plan.html")
        self.assertContains(response, "Quality Control Plan")
        self.assertContains(response, 'id="btn-crea"')

    def test_la_pagina_di_una_commessa_inesistente_e_404(self):
        response = self.client.get("/commesse/NOPE/quality-control-plan/")

        self.assertEqual(response.status_code, 404)

    def test_un_utente_in_sola_lettura_non_vede_il_pulsante(self):
        self.client.force_login(self.reader)

        response = self.client.get(QCP_PAGE)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="btn-crea"')

    def test_la_card_compare_nella_pagina_di_commessa(self):
        response = self.client.get("/commesse/26010/")

        self.assertContains(response, "/commesse/26010/quality-control-plan/")
        self.assertContains(response, "Quality Control Plan")

    # -- Precompilazione --

    def test_precompilazione_con_bc_disponibile(self):
        with self._bc(testata=_BC_TESTATA, items=_BC_ITEMS):
            response = self.client.get(QCP_PREFILL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["bc_disponibile"])
        self.assertIsNone(body["warning"])
        dati = body["data"]
        self.assertEqual(dati["project"], "MOPCO UREA REVAMP PROJECT")
        self.assertEqual(dati["owner"], "MOPCO")
        self.assertEqual(dati["purchaser"], "THYSSENKRUPP UHDE GmbH")
        self.assertEqual(dati["po_no"], "4000244916")
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["items"][0]["descrizione"], "COLUMN HEATER")

    def test_precompilazione_con_bc_irraggiungibile_non_fallisce(self):
        with self._bc(conn=False):
            response = self.client.get(QCP_PREFILL)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body["bc_disponibile"])
        self.assertTrue(body["warning"])
        self.assertEqual(body["items"], [])
        # Tutto cio che non dipende da BC resta comunque precompilato.
        dati = body["data"]
        self.assertEqual(dati["job_no"], "26010")
        self.assertEqual(dati["titolo"], "26010-QCPA")
        self.assertEqual(dati["vendor"], QCP_VENDOR)
        self.assertEqual(dati["prepared_by"], "Paolo Litta")
        self.assertEqual(dati["data"], date.today().isoformat())
        self.assertEqual(dati["po_no"], "PO-LOCALE")
        self.assertEqual(dati["purchaser"], "CLIENTE LOCALE")
        self.assertEqual(dati["location"], "")  # l'utente non ha uno stabilimento

    def test_precompilazione_con_query_in_errore_non_da_500(self):
        with self._bc(testata=RuntimeError("boom"), items=None):
            response = self.client.get(QCP_PREFILL)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["bc_disponibile"])

    def test_bc_vuoto_non_sovrascrive_i_dati_del_sistema(self):
        vuoto = [{"progetto": "", "owner": "", "purchaser": "", "po_cliente": ""}]
        with self._bc(testata=vuoto, items=[]):
            dati = self.client.get(QCP_PREFILL).json()["data"]

        self.assertEqual(dati["po_no"], "PO-LOCALE")
        self.assertEqual(dati["purchaser"], "CLIENTE LOCALE")

    def test_gli_item_duplicati_di_bc_compaiono_una_volta_sola(self):
        doppi = _BC_ITEMS + [{"item": "ITEM 2253E001", "descrizione": "ALTRO", "quantita": 1}]
        with self._bc(testata=_BC_TESTATA, items=doppi):
            items = self.client.get(QCP_PREFILL).json()["items"]

        self.assertEqual([i["item_no"] for i in items], ["ITEM 2253E001", "ITEM 2253E003"])

    def test_la_precompilazione_chiude_il_connettore(self):
        fake = _FakeBCQcp(testata=_BC_TESTATA, items=_BC_ITEMS)
        with patch("core.services.quality_control_plan._apri_connessione", return_value=fake):
            dati_precompilati("26010", self.writer)

        self.assertTrue(fake.chiusa)

    def test_precompilazione_su_commessa_inesistente_e_404(self):
        response = self.client.get("/api/commesse/NOPE/quality-control-plan/prefill/")

        self.assertEqual(response.status_code, 404)

    # -- Creazione --

    def test_creazione_salva_testata_e_item(self):
        response = self._crea(
            doc_no="26010-QCP-01",
            project="PROGETTO",
            owner="OWNER",
            data="2026-09-07",
            items=["ITEM A", "ITEM B"],
        )

        self.assertEqual(response.status_code, 201)
        piano = QualityControlPlan.objects.get()
        self.assertEqual(piano.testata_id, "26010")
        self.assertEqual(piano.doc_no, "26010-QCP-01")
        self.assertEqual(piano.prepared_by_user, self.writer)
        self.assertEqual(
            [(i.item_no, i.ordine) for i in piano.items.all()],
            [("ITEM A", 0), ("ITEM B", 1)],
        )

    def test_le_costanti_non_sono_sovrascrivibili_dal_client(self):
        response = self._crea(vendor="ACME", job_no="99999")

        dati = response.json()["data"]
        self.assertEqual(dati["vendor"], QCP_VENDOR)
        self.assertEqual(dati["job_no"], "26010")

    def test_creazione_senza_item_rifiutata(self):
        response = self._crea(items=[])

        self.assertEqual(response.status_code, 400)
        self.assertIn("item", response.json()["error"].lower())
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_item_duplicati_non_generano_errore_di_vincolo(self):
        response = self._crea(items=["A", "A", "B"])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(QualityControlPlanItem.objects.count(), 2)

    def test_troppi_item_rifiutati(self):
        response = self._crea(items=[f"ITEM {n}" for n in range(MAX_ITEMS + 1)])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_prepared_by_vuoto_usa_l_utente_loggato(self):
        self._crea(prepared_by="")

        self.assertEqual(QualityControlPlan.objects.get().prepared_by, "Paolo Litta")

    def test_body_non_json_rifiutato(self):
        response = self.client.post(QCP_API, data=b"{", content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "JSON non valido.")

    def test_creazione_su_commessa_inesistente_e_404(self):
        response = self.client.post(
            "/api/commesse/NOPE/quality-control-plan/",
            data=json.dumps({"items": ["A"]}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 404)

    def test_la_creazione_non_dipende_da_business_central(self):
        with self._bc(conn=False):
            response = self._crea(items=["ITEM A"])

        self.assertEqual(response.status_code, 201)

    # -- Elenco --

    def test_elenco_espone_percentuale_zero_e_item(self):
        self._crea(doc_no="QCP-1", items=["ITEM A", "ITEM B"], data="2026-09-07")

        piani = self.client.get(QCP_API).json()["quality_control_plans"]

        self.assertEqual(len(piani), 1)
        self.assertEqual(piani[0]["percentuale"], 0)
        self.assertEqual(piani[0]["items_label"], "ITEM A / ITEM B")
        self.assertEqual(piani[0]["data_display"], "7 sep 2026")

    def test_elenco_solo_della_commessa_richiesta(self):
        Testata.objects.create(job="26011")
        altro = QualityControlPlan.objects.create(testata_id="26011", doc_no="ALTRO")
        QualityControlPlanItem.objects.create(piano=altro, item_no="X")

        piani = self.client.get(QCP_API).json()["quality_control_plans"]

        self.assertEqual(piani, [])

    def test_elenco_su_commessa_inesistente_e_404(self):
        response = self.client.get("/api/commesse/NOPE/quality-control-plan/")

        self.assertEqual(response.status_code, 404)

    # -- Permessi --

    def test_un_utente_in_sola_lettura_non_puo_creare(self):
        self.client.force_login(self.reader)

        response = self._crea()

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Permesso negato.")
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_un_utente_in_sola_lettura_puo_elencare(self):
        self.client.force_login(self.reader)

        self.assertEqual(self.client.get(QCP_API).status_code, 200)

    def test_le_api_richiedono_autenticazione(self):
        self.client.logout()

        self.assertEqual(self.client.get(QCP_API).status_code, 401)
        self.assertEqual(self.client.get(QCP_PREFILL).status_code, 401)

    # -- Titolo --

    def test_il_titolo_proposto_parte_dalla_lettera_a(self):
        self.assertEqual(titolo_predefinito("26010"), "26010-QCPA")

    def test_il_titolo_proposto_avanza_di_una_lettera_a_ogni_piano(self):
        self._crea(titolo="26010-QCPA")

        self.assertEqual(titolo_predefinito("26010"), "26010-QCPB")

    def test_la_lettera_riparte_dalla_piu_alta_gia_usata(self):
        # Un titolo riscritto a mano non deve far riproporre una lettera già usata.
        self._crea(titolo="26010-QCPC")

        self.assertEqual(titolo_predefinito("26010"), "26010-QCPD")

    def test_i_titoli_fuori_schema_non_spostano_la_lettera(self):
        self._crea(titolo="Piano di prova")

        self.assertEqual(titolo_predefinito("26010"), "26010-QCPA")

    def test_la_lettera_conta_solo_i_piani_della_commessa(self):
        Testata.objects.create(job="26011")
        QualityControlPlan.objects.create(testata_id="26011", titolo="26011-QCPA")

        self.assertEqual(titolo_predefinito("26010"), "26010-QCPA")

    def test_il_titolo_scritto_dall_utente_viene_salvato(self):
        response = self._crea(titolo="Piano collaudi finali")

        self.assertEqual(response.json()["data"]["titolo"], "Piano collaudi finali")
        self.assertEqual(QualityControlPlan.objects.get().titolo, "Piano collaudi finali")

    def test_titolo_vuoto_ricade_su_quello_proposto(self):
        response = self._crea(titolo="   ")

        self.assertEqual(response.json()["data"]["titolo"], "26010-QCPA")

    def test_la_pagina_porta_gia_il_titolo_proposto(self):
        response = self.client.get(QCP_PAGE)

        self.assertContains(response, "26010-QCPA")

    # -- Sede --

    def _sede(self, nome):
        return Stabilimento.objects.create(nome=nome)

    def test_la_precompilazione_propone_la_sede_dell_utente(self):
        self.writer.stabilimento = self._sede("Valbrembo")
        self.writer.save(update_fields=["stabilimento"])

        with self._bc(testata=_BC_TESTATA, items=_BC_ITEMS):
            body = self.client.get(QCP_PREFILL).json()

        self.assertEqual(body["data"]["location"], "Valbrembo")

    def test_la_precompilazione_elenca_le_sedi_in_impostazioni(self):
        self._sede("Valbrembo")
        self._sede("Adro")

        with self._bc(conn=False):
            body = self.client.get(QCP_PREFILL).json()

        self.assertEqual(body["sedi"], ["Adro", "Valbrembo"])

    def test_la_pagina_rende_le_sedi_come_opzioni(self):
        self._sede("Valbrembo")

        response = self.client.get(QCP_PAGE)

        self.assertContains(response, '<option value="Valbrembo"')

    def test_una_sede_dell_elenco_viene_salvata(self):
        self._sede("Valbrembo")

        response = self._crea(location="Valbrembo")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(QualityControlPlan.objects.get().location, "Valbrembo")

    def test_una_sede_fuori_elenco_viene_rifiutata(self):
        self._sede("Valbrembo")

        response = self._crea(location="STABILIMENTO DI VALBREMBO")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Sede non valida", response.json()["error"])
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_la_sede_puo_restare_vuota(self):
        self._sede("Valbrembo")

        response = self._crea(location="")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(QualityControlPlan.objects.get().location, "")

    def test_la_sede_salvata_non_segue_la_rinomina_dello_stabilimento(self):
        # Il piano è un documento: resta com'era anche se l'anagrafica cambia.
        sede = self._sede("Valbrembo")
        self._crea(location="Valbrembo")

        sede.nome = "Valbrembo (BG)"
        sede.save(update_fields=["nome"])

        self.assertEqual(QualityControlPlan.objects.get().location, "Valbrembo")

    # -- Dati tecnici --

    _DATI_TECNICI = {
        "rev_no": 2,
        "mdmt": "-29",
        "asme_stamp": True,
        "national_board": False,
        "lethal_service": True,
        "h2s_service": True,
        "notification_advice_time": "5 working days",
        "dwg_base": "01",
        "serial_base": "A",
        "foglio_dwg": "1",
    }
    _FLAG = ("asme_stamp", "national_board", "lethal_service", "h2s_service")

    def test_creazione_salva_i_dati_tecnici(self):
        response = self._crea(**self._DATI_TECNICI)

        self.assertEqual(response.status_code, 201)
        piano = QualityControlPlan.objects.get()
        for campo, valore in self._DATI_TECNICI.items():
            with self.subTest(campo=campo):
                self.assertEqual(getattr(piano, campo), valore)

    def test_dati_tecnici_assenti_prendono_i_default(self):
        self._crea()

        piano = QualityControlPlan.objects.get()
        self.assertEqual(piano.rev_no, 0)
        for flag in self._FLAG:
            self.assertIs(getattr(piano, flag), False)
        for campo in ("mdmt", "notification_advice_time", "dwg_base", "serial_base", "foglio_dwg"):
            self.assertEqual(getattr(piano, campo), "")

    def test_rev_no_vuoto_vale_zero(self):
        self._crea(rev_no="")

        self.assertEqual(QualityControlPlan.objects.get().rev_no, 0)

    def test_rev_no_non_valido_rifiutato(self):
        for valore in ("uno", "1.5", True, -1):
            with self.subTest(valore=valore):
                self.assertEqual(self._crea(rev_no=valore).status_code, 400)

        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_un_requisito_non_booleano_viene_rifiutato(self):
        response = self._crea(asme_stamp="forse")

        self.assertEqual(response.status_code, 400)
        self.assertIn("ASME stamp", response.json()["error"])
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_la_pagina_mostra_i_dati_tecnici(self):
        response = self.client.get(QCP_PAGE)

        self.assertContains(response, "Technical data")
        self.assertContains(response, "Serial letter")
        for id_campo in (
            "f-dwg-base",
            "f-serial-base",
            "f-foglio-dwg",
            "f-rev-no",
            "f-mdmt",
            "f-h2s-service",
        ):
            self.assertContains(response, f'id="{id_campo}"')
        # Ogni numero compare una volta sola: niente copie "calcolato" in sola lettura.
        self.assertNotContains(response, 'id="f-calc-')

    def test_i_numeri_del_piano_sono_in_sola_lettura_nel_modulo(self):
        # Si calcolano dai dati tecnici: il modulo li mostra ma non li fa scrivere.
        html = self.client.get(QCP_PAGE).content.decode()

        for id_campo in ("f-doc-no", "f-serial-no"):
            with self.subTest(campo=id_campo):
                self.assertRegex(html, rf'<input[^>]*id="{id_campo}"[^>]*readonly')
        # Il Dwg n. non si mostra nel modulo: si calcola e basta.
        self.assertNotIn('id="f-dwg-no"', html)

    # -- Numerazione --

    def test_numerazione_con_tutti_i_componenti(self):
        piano = QualityControlPlan(
            testata_id="26026", dwg_base="01", serial_base="A", foglio_dwg="1"
        )

        self.assertEqual(piano.doc_no_calcolato, "26026-01-QCPA")
        self.assertEqual(piano.dwg_no_calcolato, "26026-01-EGA1")
        self.assertEqual(piano.serial_no_calcolato, "26026-01-SNA")

    def test_numerazione_con_un_componente_mancante_resta_vuota(self):
        # (doc n., dwg n., serial n.) attesi quando manca il componente indicato.
        attesi = {
            "dwg_base": ("", "", ""),
            "serial_base": ("", "26026-01-EGA1", ""),
            "foglio_dwg": ("26026-01-QCPA", "", "26026-01-SNA"),
        }
        for mancante, numeri in attesi.items():
            for vuoto in ("", "   "):
                with self.subTest(mancante=mancante, vuoto=repr(vuoto)):
                    componenti = {"dwg_base": "01", "serial_base": "A", "foglio_dwg": "1"}
                    componenti[mancante] = vuoto
                    piano = QualityControlPlan(testata_id="26026", **componenti)

                    self.assertEqual(
                        (piano.doc_no_calcolato, piano.dwg_no_calcolato, piano.serial_no_calcolato),
                        numeri,
                    )

    def test_un_piano_senza_componenti_non_espone_numeri_malformati(self):
        self._crea()

        piano = self.client.get(QCP_API).json()["quality_control_plans"][0]

        for chiave in ("doc_no", "dwg_no", "serial_no"):
            self.assertEqual(piano[chiave], "")
            self.assertEqual(piano[f"{chiave}_calcolato"], "")

    def test_il_doc_no_scritto_a_mano_vince_sul_calcolo(self):
        response = self._crea(
            doc_no="26010-QCP-SPECIALE", dwg_base="01", serial_base="A", foglio_dwg="1"
        )

        dati = response.json()["data"]
        self.assertEqual(dati["doc_no"], "26010-QCP-SPECIALE")
        self.assertEqual(dati["doc_no_calcolato"], "26010-01-QCPA")
        # Gli altri due sono rimasti vuoti, quindi valgono quelli calcolati.
        self.assertEqual(dati["dwg_no"], "26010-01-EGA1")
        self.assertEqual(dati["serial_no"], "26010-01-SNA")
        piano = QualityControlPlan.objects.get()
        self.assertEqual(piano.doc_no, "26010-QCP-SPECIALE")
        self.assertEqual(piano.dwg_no, "")  # calcolato, non persistito

    def test_l_elenco_espone_dati_tecnici_numeri_e_diciture_dei_requisiti(self):
        self._crea(**self._DATI_TECNICI)

        piano = self.client.get(QCP_API).json()["quality_control_plans"][0]

        for campo, valore in self._DATI_TECNICI.items():
            with self.subTest(campo=campo):
                self.assertEqual(piano[campo], valore)
        self.assertEqual(piano["asme_stamp_label"], "REQUIRED")
        self.assertEqual(piano["national_board_label"], "NOT REQUIRED")
        self.assertEqual(piano["lethal_service_label"], "REQUIRED")
        self.assertEqual(piano["h2s_service_label"], "REQUIRED")
        self.assertEqual(piano["doc_no"], "26010-01-QCPA")
        self.assertEqual(piano["dwg_no_calcolato"], "26010-01-EGA1")
        self.assertEqual(piano["serial_no_calcolato"], "26010-01-SNA")

    def test_precompilazione_senza_bc_propone_i_default_dei_dati_tecnici(self):
        with self._bc(conn=False):
            response = self.client.get(QCP_PREFILL)

        self.assertEqual(response.status_code, 200)
        dati = response.json()["data"]
        self.assertEqual(dati["rev_no"], 0)
        for flag in self._FLAG:
            self.assertIs(dati[flag], False)
        for campo in (
            "dwg_base",
            "serial_base",
            "foglio_dwg",
            "mdmt",
            "notification_advice_time",
            "doc_no",
            "dwg_no",
            "serial_no",
        ):
            self.assertEqual(dati[campo], "")

    # -- Eliminazione --

    def _crea_id(self, **payload):
        return self._crea(**payload).json()["data"]["id"]

    def test_eliminazione_rimuove_piano_e_item(self):
        pk = self._crea_id(items=["ITEM A", "ITEM B"])

        response = self.client.delete(f"{QCP_API}{pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(QualityControlPlan.objects.exists())
        self.assertFalse(QualityControlPlanItem.objects.exists())

    def test_eliminazione_tocca_solo_il_piano_indicato(self):
        pk = self._crea_id(titolo="26010-QCPA")
        self._crea(titolo="26010-QCPB")

        self.client.delete(f"{QCP_API}{pk}/")

        self.assertEqual(
            list(QualityControlPlan.objects.values_list("titolo", flat=True)), ["26010-QCPB"]
        )

    def test_eliminazione_di_un_piano_inesistente_e_404(self):
        response = self.client.delete(f"{QCP_API}999999/")

        self.assertEqual(response.status_code, 404)

    def test_non_si_elimina_un_piano_di_un_altra_commessa(self):
        # L'id arriva dall'URL: non deve bastare a cancellare fuori dalla commessa.
        Testata.objects.create(job="26011")
        altro = QualityControlPlan.objects.create(testata_id="26011", titolo="26011-QCPA")

        response = self.client.delete(f"{QCP_API}{altro.pk}/")

        self.assertEqual(response.status_code, 404)
        self.assertTrue(QualityControlPlan.objects.filter(pk=altro.pk).exists())

    def test_un_utente_in_sola_lettura_non_puo_eliminare(self):
        pk = self._crea_id()
        self.client.force_login(self.reader)

        response = self.client.delete(f"{QCP_API}{pk}/")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Permesso negato.")
        self.assertTrue(QualityControlPlan.objects.filter(pk=pk).exists())

    def test_l_eliminazione_richiede_autenticazione(self):
        pk = self._crea_id()
        self.client.logout()

        self.assertEqual(self.client.delete(f"{QCP_API}{pk}/").status_code, 401)
        self.assertTrue(QualityControlPlan.objects.filter(pk=pk).exists())

    def test_il_dettaglio_accetta_solo_delete(self):
        pk = self._crea_id()

        self.assertEqual(self.client.get(f"{QCP_API}{pk}/").status_code, 405)

    def test_la_pagina_offre_l_eliminazione(self):
        response = self.client.get(QCP_PAGE)

        self.assertContains(response, "doc-row-menu-item--delete")

    # -- Codici, spec ed enti --

    _LISTE = {
        "codes": ["ASME VIII Div.1 Ed 2025", "PED 2014/68/EU", "ASME IX Ed 2021"],
        "specs": ["Req. nr. L001-00000-MS-7303-1002", "and all specs listed in above req."],
        "agencies": ["B&R", "TÜV", "Client"],
    }

    def test_creazione_salva_le_tre_liste_nell_ordine_dato(self):
        response = self._crea(**self._LISTE)

        self.assertEqual(response.status_code, 201)
        piano = QualityControlPlan.objects.get()
        self.assertEqual(
            list(piano.codes.values_list("codice", "ordine")),
            [("ASME VIII Div.1 Ed 2025", 0), ("PED 2014/68/EU", 1), ("ASME IX Ed 2021", 2)],
        )
        self.assertEqual(
            list(piano.specs.values_list("spec", "ordine")),
            [("Req. nr. L001-00000-MS-7303-1002", 0), ("and all specs listed in above req.", 1)],
        )
        self.assertEqual(
            list(piano.agencies.values_list("nome", "ordine")),
            [("B&R", 0), ("TÜV", 1), ("Client", 2)],
        )
        # La risposta di creazione le riporta già come salvate.
        for chiave, valori in self._LISTE.items():
            self.assertEqual(response.json()["data"][chiave], valori)

    def test_un_codice_fuori_elenco_viene_accettato(self):
        # Come nell'Excel: la tendina propone, ma la cella resta libera.
        self.assertNotIn("EN 13445-3", CODICI_PROPOSTI)

        response = self._crea(codes=["EN 13445-3"])

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            list(QualityControlPlanCode.objects.values_list("codice", flat=True)), ["EN 13445-3"]
        )

    def test_un_piano_senza_liste_resta_creabile(self):
        for payload in ({}, {"codes": [], "specs": [], "agencies": []}, {"codes": None}):
            with self.subTest(payload=payload):
                self.assertEqual(self._crea(**payload).status_code, 201)

        self.assertEqual(QualityControlPlan.objects.count(), 3)
        for modello in (QualityControlPlanCode, QualityControlPlanSpec, QualityControlPlanAgency):
            self.assertFalse(modello.objects.exists())

    def test_i_duplicati_nella_stessa_lista_vengono_scartati(self):
        response = self._crea(
            codes=["PED 2014/68/EU", " PED 2014/68/EU ", "", "API 934-C"],
            specs=["SPEC-1", "SPEC-1"],
            agencies=["B&R", "TÜV", "B&R", "   "],
        )

        self.assertEqual(response.status_code, 201)
        piano = QualityControlPlan.objects.get()
        self.assertEqual(
            list(piano.codes.values_list("codice", flat=True)), ["PED 2014/68/EU", "API 934-C"]
        )
        self.assertEqual(list(piano.specs.values_list("spec", flat=True)), ["SPEC-1"])
        self.assertEqual(
            list(piano.agencies.values_list("nome", "ordine")), [("B&R", 0), ("TÜV", 1)]
        )

    def test_i_limiti_sono_quelli_dell_excel(self):
        self.assertEqual((MAX_CODES, MAX_SPECS, MAX_AGENCIES), (12, 12, 6))

    def test_superare_il_massimo_solleva_un_errore_leggibile(self):
        casi = (
            ("codes", MAX_CODES, "Codici applicabili"),
            ("specs", MAX_SPECS, "Spec del cliente"),
            ("agencies", MAX_AGENCIES, "Enti di ispezione"),
        )
        for chiave, massimo, nome in casi:
            with self.subTest(lista=chiave):
                troppi = [f"{chiave} {n}" for n in range(massimo + 1)]
                with self.assertRaisesMessage(ValueError, f"{nome}: al massimo {massimo}."):
                    create_piano("26010", {"items": ["ITEM A"], chiave: troppi}, self.writer)

        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_il_massimo_arriva_all_utente_come_errore_400(self):
        response = self._crea(agencies=[f"Ente {n}" for n in range(MAX_AGENCIES + 1)])

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Enti di ispezione: al massimo 6.")
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_il_massimo_si_conta_dopo_aver_tolto_i_duplicati(self):
        codici = [f"CODE {n}" for n in range(MAX_CODES)] + ["CODE 0", ""]

        response = self._crea(codes=codici)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(QualityControlPlanCode.objects.count(), MAX_CODES)

    def test_una_lista_non_valida_viene_rifiutata(self):
        for valore in ("PED 2014/68/EU", {"codice": "PED"}, [1, 2]):
            with self.subTest(valore=valore):
                response = self._crea(codes=valore)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error"], "Codici applicabili: elenco non valido.")

        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_un_valore_troppo_lungo_viene_rifiutato(self):
        response = self._crea(agencies=["X" * 201])

        self.assertEqual(response.status_code, 400)
        self.assertIn("200 caratteri", response.json()["error"])
        self.assertEqual(QualityControlPlan.objects.count(), 0)

    def test_l_elenco_espone_le_tre_liste_in_ordine(self):
        piano = QualityControlPlan.objects.create(testata=self.testata, titolo="26010-QCPA")
        # Inserite al contrario: conta ``ordine``, non l'ordine di inserimento.
        QualityControlPlanAgency.objects.create(piano=piano, nome="TÜV", ordine=1)
        QualityControlPlanAgency.objects.create(piano=piano, nome="B&R", ordine=0)
        QualityControlPlanCode.objects.create(piano=piano, codice="PED 2014/68/EU", ordine=1)
        QualityControlPlanCode.objects.create(piano=piano, codice="ASME V Ed 2023", ordine=0)
        QualityControlPlanSpec.objects.create(piano=piano, spec="SPEC-2", ordine=1)
        QualityControlPlanSpec.objects.create(piano=piano, spec="SPEC-1", ordine=0)

        dati = self.client.get(QCP_API).json()["quality_control_plans"][0]

        self.assertEqual(dati["agencies"], ["B&R", "TÜV"])
        self.assertEqual(dati["codes"], ["ASME V Ed 2023", "PED 2014/68/EU"])
        self.assertEqual(dati["specs"], ["SPEC-1", "SPEC-2"])

    def test_l_elenco_non_fa_una_query_per_piano(self):
        for lettera in "ABC":
            self._crea(titolo=f"26010-QCP{lettera}", items=["ITEM A", "ITEM B"], **self._LISTE)

        # Commessa, piani, e una query per relazione precaricata (item, codici,
        # spec, enti): lo stesso numero con uno o con cento piani.
        with self.assertNumQueries(6):
            piani = list_piani("26010")

        self.assertEqual(len(piani), 3)
        for piano in piani:
            self.assertEqual(piano["agencies"], self._LISTE["agencies"])

    def test_precompilazione_propone_solo_b_r_come_primo_ente(self):
        with self._bc(conn=False):
            dati = self.client.get(QCP_PREFILL).json()["data"]

        self.assertEqual(ENTE_PREDEFINITO, "B&R")
        self.assertEqual(dati["agencies"], ["B&R"])
        self.assertEqual(dati["codes"], [])
        self.assertEqual(dati["specs"], [])

    def test_la_pagina_propone_i_codici_nella_tendina(self):
        response = self.client.get(QCP_PAGE)

        self.assertEqual(len(CODICI_PROPOSTI), 14)
        self.assertContains(response, 'id="qcp-codici-proposti"')
        self.assertContains(response, '<option value="PED 2014/68/EU">')
        for id_lista in ("f-codes", "f-specs", "f-agencies"):
            self.assertContains(response, f'id="{id_lista}"')

    def test_la_pagina_passa_limiti_ed_ente_predefinito_alle_liste(self):
        # Il componente legge limiti e lunghezze dal markup: senza questi
        # attributi non saprebbe dove fermarsi, né cosa proporre come primo ente.
        html = self.client.get(QCP_PAGE).content.decode()

        for id_lista, massimo, lunghezza in (
            ("f-codes", MAX_CODES, 200),
            ("f-specs", MAX_SPECS, 300),
            ("f-agencies", MAX_AGENCIES, 200),
        ):
            with self.subTest(lista=id_lista):
                self.assertRegex(html, rf'id="{id_lista}"[^>]*data-max="{massimo}"')
                self.assertRegex(html, rf'id="{id_lista}"[^>]*data-maxlength="{lunghezza}"')
        self.assertIn('var ENTE_PREDEFINITO = "B\\u0026R";', html)

    def test_l_eliminazione_rimuove_anche_le_liste(self):
        pk = self._crea_id(**self._LISTE)

        self.client.delete(f"{QCP_API}{pk}/")

        for modello in (QualityControlPlanCode, QualityControlPlanSpec, QualityControlPlanAgency):
            self.assertFalse(modello.objects.exists())

    # -- Modulo a passi --

    @staticmethod
    def _passo(html, n):
        """Markup del passo ``n`` del modal, fino all'inizio del successivo."""
        inizio = html.index(f'data-step="{n}"')
        fine = html.index(f'data-step="{n + 1}"') if n < 5 else html.index('class="modal-footer"')
        return html[inizio:fine]

    def _pagina(self):
        return self.client.get(QCP_PAGE).content.decode()

    def test_il_modulo_e_diviso_in_cinque_passi(self):
        html = self._pagina()

        self.assertRegex(
            html, r'(?s)data-step="1".*data-step="2".*data-step="3".*data-step="4".*data-step="5"'
        )
        self.assertRegex(
            html,
            r'(?s)id="qcp-passo-1">Header<.*id="qcp-passo-2">Item<.*'
            r'id="qcp-passo-3">Technical data<.*id="qcp-passo-4">Codes and agencies<.*'
            r'id="qcp-passo-5">Summary<',
        )
        # Solo i pulsanti dell'indicatore: il CSS usa lo stesso attributo come selettore.
        self.assertEqual(len(re.findall(r'<button[^>]*aria-current="step"', html)), 1)

    def test_all_apertura_si_vede_solo_il_primo_passo(self):
        html = self._pagina()

        self.assertNotRegex(html, r'<section[^>]*data-step="1"[^>]*hidden')
        for n in (2, 3, 4, 5):
            with self.subTest(passo=n):
                self.assertRegex(html, rf'<section[^>]*data-step="{n}"[^>]*hidden')
                self.assertRegex(html, rf'<button[^>]*data-vai="{n}"[^>]*disabled')
        self.assertRegex(html, r'<button[^>]*id="modal-back"[^>]*hidden')
        self.assertRegex(html, r'<button[^>]*id="modal-save"[^>]*hidden')
        self.assertNotRegex(html, r'<button[^>]*id="modal-next"[^>]*hidden')

    def test_ogni_campo_sta_nel_suo_passo(self):
        html = self._pagina()
        passi = {
            1: (
                "f-titolo",
                "f-location",
                "f-sheet",
                "f-project",
                "f-job-no",
                "f-owner",
                "f-po-no",
                "f-data",
                "f-purchaser",
                "f-vendor",
                "f-prepared-by",
            ),
            2: ("f-items-box", "f-descrizione-item"),
            3: (
                "f-dwg-base",
                "f-serial-base",
                "f-foglio-dwg",
                "f-doc-no",
                "f-serial-no",
                "f-rev-no",
                "f-mdmt",
                "f-notification-advice-time",
                "f-asme-stamp",
                "f-national-board",
                "f-lethal-service",
                "f-h2s-service",
            ),
            4: ("f-codes", "f-specs", "f-agencies", "qcp-codici-proposti"),
            5: ("qcp-riepilogo",),
        }
        for n, ids in passi.items():
            markup = self._passo(html, n)
            for id_campo in ids:
                with self.subTest(passo=n, campo=id_campo):
                    self.assertIn(f'id="{id_campo}"', markup)

    def test_doc_n_e_serial_n_seguono_i_dati_tecnici_di_base(self):
        # Si calcolano da quei campi: si vedono subito sotto, non in testata.
        html = self._pagina()
        passo3 = self._passo(html, 3)

        posizioni = [
            passo3.index(f'id="{id_campo}"')
            for id_campo in ("f-foglio-dwg", "f-doc-no", "f-serial-no", "f-rev-no")
        ]
        self.assertEqual(posizioni, sorted(posizioni))
        for id_campo in ("f-doc-no", "f-serial-no"):
            self.assertNotIn(f'id="{id_campo}"', self._passo(html, 1))

    def test_il_piede_ha_annulla_indietro_avanti_e_crea(self):
        html = self._pagina()
        piede = html[html.index('class="modal-footer"') :]

        for id_btn, testo in (
            ("modal-cancel", "Cancel"),
            ("modal-back", "Back"),
            ("modal-next", "Next"),
            ("modal-save", "Create"),
        ):
            with self.subTest(pulsante=id_btn):
                self.assertRegex(piede, rf'id="{id_btn}"[^>]*>{testo}<')

    def test_gli_errori_del_server_portano_al_passo_giusto(self):
        # Il modulo riconosce il passo dall'inizio del messaggio del service: se
        # una frase cambia da una parte sola, questo test lo segnala.
        html = self._pagina()
        attesi = {
            1: ["Sede non valida"],
            2: ["Seleziona almeno un item."],
            3: ["Rev n.", "Valore non valido per"],
            4: [f"{lista.nome}:" for lista in LISTE],
        }

        for n, prefissi in attesi.items():
            dichiarati = [
                prefisso
                for valore in re.findall(r'data-errore="([^"]*)"', self._passo(html, n))
                for prefisso in valore.split("|")
            ]
            for prefisso in prefissi:
                with self.subTest(passo=n, prefisso=prefisso):
                    self.assertIn(prefisso, dichiarati)

    # -- Anteprima della copertina --

    @staticmethod
    def _url_dettaglio(pk, job="26010"):
        return f"/commesse/{job}/quality-control-plan/{pk}/"

    def _piano_completo(self):
        return self._crea_id(
            titolo="26010-QCPA",
            dwg_base="01",
            serial_base="A",
            foglio_dwg="1",
            mdmt="-25",
            asme_stamp=True,
            descrizione_item="GAS COOLER",
            items=[{"item_no": "ITEM 2253E001", "descrizione": "COLUMN HEATER"}],
            **self._LISTE,
        )

    def test_il_dettaglio_mostra_la_copertina_del_piano(self):
        pk = self._piano_completo()

        response = self.client.get(self._url_dettaglio(pk))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/quality_control_plan_detail.html")
        for testo in (
            "26010-01-QCPA",  # doc n. calcolato, come titolo
            "26010-01-EGA1",  # dwg n. calcolato
            "PED 2014/68/EU",
            "Req. nr. L001-00000-MS-7303-1002",
            "TÜV",
            "ITEM 2253E001",
            "COLUMN HEATER",
            "GAS COOLER",  # descrizione item, nel sottotitolo
            "Paolo Litta",
        ):
            with self.subTest(testo=testo):
                self.assertContains(response, testo)
        # Stessa navigazione delle altre pagine; niente più segnaposto "in arrivo"
        # nella panoramica (gli step hanno la loro vista).
        self.assertContains(response, 'class="navbar"')
        self.assertNotContains(response, "in arrivo")
        self.assertContains(response, '<span class="cv-avatar" aria-hidden="true">PL</span>')
        self.assertNotContains(response, "ITEM ITEM")
        # MDMT: il numero, l'unità a parte.
        self.assertContains(response, '-25 <span class="qp-unita">°C</span>')

    def test_il_dettaglio_ha_testata_copertina_e_corpo(self):
        html = self.client.get(self._url_dettaglio(self._piano_completo())).content.decode()

        # Niente più viste Panoramica / Step: la copertina si apre dalla testata,
        # chiusa all'apertura (il JS ricorda l'ultima scelta).
        self.assertNotIn('role="tablist"', html)
        self.assertRegex(
            html, r'id="qp-btn-copertina" aria-expanded="false" aria-controls="qp-copertina"'
        )
        self.assertIn('<div class="qp-copertina" id="qp-copertina" hidden>', html)
        self.assertIn(">Job 26010</a>", html)
        self.assertIn('id="qp-stato-piano">In progress<', html)
        # L'esportazione non c'è ancora: il pulsante c'è, disattivato. Nessun
        # menu ··· nella testata: le azioni sono solo Cover ed Export.
        self.assertRegex(html, r'class="qp-btn" aria-disabled="true"[^>]*>Export</button>')
        testata = html[html.index('<header class="qp-testata"') : html.index("</header>")]
        self.assertNotIn('class="ce-dots"', testata)
        # Il corpo in due colonne: elenco delle sezioni e sezione scelta.
        self.assertIn('id="qp-nav"', html)
        self.assertIn('id="ce-sezioni"', html)
        self.assertNotIn('class="cv-back"', html)

    def test_la_copertina_ha_parti_identificativi_codici_e_spec(self):
        html = self.client.get(self._url_dettaglio(self._piano_completo())).content.decode()

        copertina = html[html.index('id="qp-copertina"') : html.index('<div class="qp-corpo')]
        for testo in (
            "Parties",
            "Identifiers",
            "Applicable codes",
            "Client specs",
            "26010-01-EGA1",
            "PED 2014/68/EU",
            "Req. nr. L001-00000-MS-7303-1002",
        ):
            with self.subTest(testo=testo):
                self.assertIn(testo, copertina)

    def test_il_dettaglio_mostra_gli_enti_con_la_posizione(self):
        # La posizione sarà la colonna nel corpo del piano: si vede sempre.
        html = self.client.get(self._url_dettaglio(self._piano_completo())).content.decode()

        self.assertRegex(
            html,
            r'(?s)cv-ente-n">1</span>B&amp;R.*cv-ente-n">2</span>TÜV'
            r'.*cv-ente-n">3</span>Client',
        )

    def test_solo_i_requisiti_richiesti_compaiono_nella_testata(self):
        html = self.client.get(self._url_dettaglio(self._piano_completo())).content.decode()

        self.assertEqual(re.findall(r'<li class="qp-req">([^<]*)</li>', html), ["ASME stamp"])
        self.assertNotIn('class="qp-req-nessuno"', html)

    def test_il_dettaglio_di_un_piano_di_un_altra_commessa_e_404(self):
        Testata.objects.create(job="26011")
        altro = QualityControlPlan.objects.create(testata_id="26011", titolo="26011-QCPA")
        mio = self._crea_id()

        self.assertEqual(self.client.get(self._url_dettaglio(altro.pk)).status_code, 404)
        self.assertEqual(self.client.get(self._url_dettaglio(mio, job="26011")).status_code, 404)

    def test_il_dettaglio_di_un_piano_inesistente_e_404(self):
        self.assertEqual(self.client.get(self._url_dettaglio(999999)).status_code, 404)
        self.assertEqual(self.client.get("/commesse/NOPE/quality-control-plan/1/").status_code, 404)

    def test_il_dettaglio_di_un_piano_senza_liste(self):
        pk = self._crea_id()

        response = self.client.get(self._url_dettaglio(pk))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<p class="cv-empty">No codes</p>')
        self.assertContains(response, '<p class="cv-empty">No specs</p>')
        self.assertContains(response, '<span class="cv-empty">No agencies</span>')
        # Il nome di classe da solo compare anche nel CSS: si cerca l'attributo.
        self.assertNotContains(response, 'class="cv-codes"')
        self.assertNotContains(response, 'class="cv-ente-n"')

    def test_il_dettaglio_con_campi_vuoti_non_mostra_none(self):
        # Un piano con il solo titolo e un item: data, MDMT, nota e numeri vuoti.
        piano = QualityControlPlan.objects.create(testata=self.testata, titolo="26010-QCPA")
        QualityControlPlanItem.objects.create(piano=piano, item_no="ITEM A")

        response = self.client.get(self._url_dettaglio(piano.pk))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "None")
        self.assertNotContains(response, "°C")
        self.assertNotContains(response, 'class="cv-avatar"')
        self.assertContains(response, '<li class="qp-req-nessuno">No requirements</li>')
        # Senza componenti il doc n. è vuoto: il titolo ne prende il posto.
        self.assertContains(response, '<h1 class="cv-title" id="cover-title">26010-QCPA</h1>')

    def test_il_dettaglio_e_visibile_anche_in_sola_lettura(self):
        pk = self._crea_id()
        self.client.force_login(self.reader)

        self.assertEqual(self.client.get(self._url_dettaglio(pk)).status_code, 200)

    def test_il_dettaglio_richiede_il_login(self):
        pk = self._crea_id()
        self.client.logout()

        response = self.client.get(self._url_dettaglio(pk))

        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)

    def test_il_dettaglio_non_fa_una_query_per_riga(self):
        # Sessione e utente, commessa, piano, una query per relazione (item,
        # codici, spec, enti), il corpo (sezioni, step, punti) e i capitoli del
        # catalogo: lo stesso numero con una riga o con molte.
        pochi = self._crea_id(codes=["C1"], specs=["S1"], agencies=["E1"])
        molti = self._crea_id(
            items=[f"ITEM {n}" for n in range(10)],
            codes=[f"C{n}" for n in range(MAX_CODES)],
            specs=[f"S{n}" for n in range(MAX_SPECS)],
            agencies=[f"E{n}" for n in range(MAX_AGENCIES)],
        )
        for pk, sezioni, steps in ((pochi, 1, 1), (molti, 4, 10)):
            piano = QualityControlPlan.objects.get(pk=pk)
            for indice in range(sezioni):
                sezione = crea_sezione(piano, f"Sezione {indice}")
                for numero in range(steps):
                    aggiungi_step(sezione, dati={"descrizione": f"Step {numero}"})

        # Il corpo legge anche le firme valide dei punti, in una query sola.
        for pk in (pochi, molti):
            with self.subTest(pk=pk), self.assertNumQueries(13):
                self.client.get(self._url_dettaglio(pk))

    def test_le_righe_dell_elenco_portano_al_dettaglio(self):
        # Le righe le disegna il JS: la pagina deve dargli l'indirizzo del dettaglio.
        response = self.client.get(QCP_PAGE)

        url_elenco = escapejs("/commesse/26010/quality-control-plan/")
        self.assertContains(response, f'var PAGINA = "{url_elenco}";')
        self.assertContains(response, "qcp-row-link")

    def test_mdmt_si_mostra_con_l_unita_una_volta_sola(self):
        self.assertEqual(mdmt_con_unita("-25"), "-25 °C")
        self.assertEqual(mdmt_con_unita(" -25 °C "), "-25 °C")
        self.assertEqual(mdmt_con_unita("-25°c"), "-25 °C")
        self.assertEqual(mdmt_senza_unita("-25 °C"), "-25")
        self.assertEqual(mdmt_senza_unita("-25°c"), "-25")
        self.assertEqual(mdmt_senza_unita("-25"), "-25")
        self.assertEqual(mdmt_senza_unita(None), "")
        self.assertEqual(mdmt_con_unita(""), "")
        self.assertEqual(mdmt_con_unita(None), "")

    def test_le_iniziali_sono_di_nome_e_cognome(self):
        self.assertEqual(iniziali("Paolo Litta"), "PL")
        self.assertEqual(iniziali("  maria de rossi "), "MR")
        self.assertEqual(iniziali("admin"), "A")
        self.assertEqual(iniziali(""), "")
        self.assertEqual(iniziali(None), "")

    def test_l_intestazione_non_ripete_item(self):
        # I codici di BC contengono già "ITEM": non va ripetuto.
        self.assertEqual(intestazione_items(["1E/2E-1201"]), "ITEM 1E/2E-1201")
        self.assertEqual(
            intestazione_items(["ITEM 2253E001", "ITEM 2253E003"]),
            "ITEM 2253E001 / ITEM 2253E003",
        )
        self.assertEqual(intestazione_items([]), "")


class BusinessCentralQueryTests(SimpleTestCase):
    """La query commerciale puntava a una tabella inesistente e falliva in silenzio."""

    def test_la_query_commerciale_usa_la_tabella_di_estensione(self):
        from src.erp.queries import COMMESSA_COMMERCIALE

        self.assertIn("BREMBANA$Job$437dbf0e-84ff-417a-965d-ed2bb9650972$ext", COMMESSA_COMMERCIALE)
        # La tabella col GUID dell'app NBT_BRL non esiste: quel GUID sta nel nome
        # della colonna, non in quello della tabella.
        self.assertNotIn(
            "[BREMBANA$Job$d71d761a-a85c-4b10-8459-d30c64b4a709]", COMMESSA_COMMERCIALE
        )


CATALOGO_API = "/api/catalogo-qcp/"

_RIGA_CATALOGO = {
    "riga_excel": 3,
    "ordine": 1,
    "codice": "KOM",
    "divisione": "Gen",
    "capitolo": "KOM",
    "descrizione": "Kick of Meeting",
    "test_inspection": "Kick of Meeting",
    "reference_doc_tipo": "statico",
    "reference_doc_valore": "KOM Agenda",
    "acceptance_criteria": "",
    "documento_richiesto": "MoM of KOM",
    "tecnica": "",
    "tipo": "RIU",
}


class CatalogoAttivitaQCPTests(TestCase):
    """Catalogo attività QCP: import dal JSON, riferimenti documentali, API."""

    def setUp(self):
        self.client = Client()
        self.lettore = User.objects.create_user(
            "catalogo_reader", "catalogo-reader@brembanarolle.com", "pw", permesso=Permesso.READING
        )
        self.client.force_login(self.lettore)
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        self.cartella = Path(cartella.name)

    # -- Aiuti --

    @staticmethod
    def _riga(**campi):
        return {**_RIGA_CATALOGO, **campi}

    def _righe_di_prova(self):
        # Come nel catalogo vero: "Final documentation index" sta in due capitoli.
        return [
            self._riga(),
            self._riga(
                riga_excel=4,
                ordine=2,
                codice="PT-Welds",
                divisione="Div.1",
                capitolo="NDE",
                descrizione="PT on welds",
                reference_doc_tipo="suffisso_job",
                reference_doc_valore="/PT",
                tipo="PT",
            ),
            self._riga(
                riga_excel=15,
                ordine=3,
                codice="Final documentation index",
                capitolo="DOCUMENTAZIONE",
                descrizione="Final documentation index",
                reference_doc_tipo="suffisso_job",
                reference_doc_valore="-01-QBDI",
                tipo="DOC",
            ),
            self._riga(
                riga_excel=286,
                ordine=4,
                codice="Final documentation index",
                divisione="Div.1",
                capitolo="ISPEZIONI FINALI",
                descrizione="Final documentation index",
                reference_doc_tipo="suffisso_job",
                reference_doc_valore="-00-MDBI",
                tipo="FIN",
            ),
        ]

    def _importa(self, righe, *argomenti):
        percorso = self.cartella / f"catalogo_{len(list(self.cartella.iterdir()))}.json"
        percorso.write_text(json.dumps(righe), encoding="utf-8")
        uscita = io.StringIO()
        call_command("importa_catalogo_qcp", str(percorso), *argomenti, stdout=uscita)
        return uscita.getvalue()

    @staticmethod
    def _attivita(**campi):
        valori = {
            "codice": "X",
            "divisione": "Div.1",
            "capitolo": "NDE",
            "descrizione": "X",
            "reference_doc_tipo": "statico",
            "ordine": 1,
            **campi,
        }
        return AttivitaQCP.objects.create(**valori)

    # -- Import --

    def test_import_crea_le_righe_del_json(self):
        uscita = self._importa(self._righe_di_prova())

        self.assertEqual(AttivitaQCP.objects.count(), 4)
        self.assertIn("Creati 4, aggiornati 0, invariati 0.", uscita)
        kom = AttivitaQCP.objects.get(codice="KOM")
        self.assertEqual(kom.reference_doc_valore, "KOM Agenda")
        self.assertTrue(kom.attivo)

    def test_rieseguire_l_import_non_duplica(self):
        righe = self._righe_di_prova()
        self._importa(righe)

        uscita = self._importa(righe)

        self.assertEqual(AttivitaQCP.objects.count(), 4)
        self.assertIn("Creati 0, aggiornati 0, invariati 4.", uscita)

    def test_un_nuovo_import_aggiorna_solo_le_righe_cambiate(self):
        righe = self._righe_di_prova()
        self._importa(righe)
        righe[0]["descrizione"] = "Kick-off meeting"

        uscita = self._importa(righe)

        self.assertIn("Creati 0, aggiornati 1, invariati 3.", uscita)
        self.assertEqual(AttivitaQCP.objects.get(codice="KOM").descrizione, "Kick-off meeting")

    def test_il_reimport_non_riattiva_le_attivita_disattivate(self):
        # Disattivare è una scelta dell'admin: la sorgente non la deve annullare.
        righe = self._righe_di_prova()
        self._importa(righe)
        AttivitaQCP.objects.filter(codice="KOM").update(attivo=False)

        self._importa(righe)

        self.assertFalse(AttivitaQCP.objects.get(codice="KOM").attivo)

    def test_dry_run_non_scrive(self):
        uscita = self._importa(self._righe_di_prova(), "--dry-run")

        self.assertEqual(AttivitaQCP.objects.count(), 0)
        self.assertIn("[dry-run] Creati 4, aggiornati 0, invariati 0.", uscita)

    def test_dry_run_non_aggiorna_le_righe_esistenti(self):
        righe = self._righe_di_prova()
        self._importa(righe)
        righe[0]["descrizione"] = "Kick-off meeting"

        uscita = self._importa(righe, "--dry-run")

        self.assertIn("[dry-run] Creati 0, aggiornati 1, invariati 3.", uscita)
        self.assertEqual(AttivitaQCP.objects.get(codice="KOM").descrizione, "Kick of Meeting")

    def test_una_riga_malformata_interrompe_senza_salvare_nulla(self):
        rotture = (
            ("ordine non numerico", {"ordine": "dodici"}, "ordine"),
            ("formula Excel rimasta", {"tecnica": '=""'}, "formula Excel"),
            (
                "tipo di riferimento sconosciuto",
                {"reference_doc_tipo": "boh"},
                "reference_doc_tipo",
            ),
            ("testo troppo lungo", {"divisione": "X" * 21}, "divisione"),
            ("valore non testuale", {"tipo": 5}, "tipo"),
        )
        for caso, rotto, messaggio in rotture:
            with self.subTest(caso=caso):
                righe = self._righe_di_prova()
                righe[2] = {**righe[2], **rotto}

                with self.assertRaises(CommandError) as errore:
                    self._importa(righe)

                self.assertIn("riga 3 (riga Excel 15)", str(errore.exception))
                self.assertIn(messaggio, str(errore.exception))
                # Nemmeno le righe buone prima di quella rotta.
                self.assertEqual(AttivitaQCP.objects.count(), 0)

    def test_un_campo_mancante_interrompe(self):
        righe = self._righe_di_prova()
        del righe[1]["descrizione"]

        with self.assertRaisesMessage(CommandError, "mancano descrizione"):
            self._importa(righe)
        self.assertEqual(AttivitaQCP.objects.count(), 0)

    def test_codice_e_capitolo_ripetuti_nel_file_interrompono(self):
        righe = self._righe_di_prova() + [self._riga(riga_excel=99, ordine=5)]

        with self.assertRaisesMessage(CommandError, "già usati alla riga 1"):
            self._importa(righe)
        self.assertEqual(AttivitaQCP.objects.count(), 0)

    def test_il_catalogo_del_repository_si_importa_intero(self):
        uscita = io.StringIO()

        call_command("importa_catalogo_qcp", stdout=uscita)

        self.assertEqual(AttivitaQCP.objects.count(), 291)
        self.assertIn("Creati 291, aggiornati 0, invariati 0.", uscita.getvalue())
        tipi = dict(
            AttivitaQCP.objects.order_by().values_list("reference_doc_tipo").annotate(n=Count("id"))
        )
        self.assertEqual(
            tipi,
            {"suffisso_job": 192, "statico": 84, "composito": 7, "campo_piano": 2, "da_proc": 6},
        )
        # I codici ripetuti in capitoli diversi convivono; la riga Fit-up ha il
        # suo codice (nell'Excel era copiato da quella sotto).
        self.assertEqual(AttivitaQCP.objects.filter(codice="Final documentation index").count(), 2)
        self.assertTrue(AttivitaQCP.objects.filter(codice="VT-Fit-up", capitolo="NDE").exists())
        self.assertFalse(AttivitaQCP.objects.filter(tecnica__startswith='="').exists())

    # -- Unicità --

    def test_stesso_codice_in_capitoli_diversi_convive(self):
        self._attivita(codice="Pickling and passivation", capitolo="NDE")
        self._attivita(codice="Pickling and passivation", capitolo="ISPEZIONI FINALI", ordine=2)

        self.assertEqual(AttivitaQCP.objects.filter(codice="Pickling and passivation").count(), 2)

    def test_stesso_codice_nello_stesso_capitolo_no(self):
        self._attivita(codice="Pickling and passivation", capitolo="NDE")

        with self.assertRaises(IntegrityError), transaction.atomic():
            self._attivita(codice="Pickling and passivation", capitolo="NDE", ordine=2)

    def test_l_admin_non_permette_di_cancellare(self):
        admin_catalogo = django_admin.site._registry[AttivitaQCP]

        self.assertFalse(admin_catalogo.has_delete_permission(None))

    # -- Riferimenti documentali --

    @staticmethod
    def _con_riferimento(tipo, valore):
        return AttivitaQCP(codice="X", reference_doc_tipo=tipo, reference_doc_valore=valore)

    @staticmethod
    def _piano(**campi):
        valori = {"testata_id": "26026", "dwg_base": "01", "serial_base": "A", "foglio_dwg": "1"}
        return QualityControlPlan(**{**valori, **campi})

    def test_il_riferimento_si_risolve_per_ogni_tipo(self):
        piano = self._piano()
        casi = (
            ("suffisso_job", "/PT", "26026/PT"),
            ("statico", "ASME IX QW350/360", "ASME IX QW350/360"),
            ("composito", "/VT|/DC", "26026/VT 26026/DC"),
            ("composito", "BCI-006-CWC|-TMRS", "BCI-006-CWC 26026-TMRS"),
            # Come nel catalogo vero, con lo spazio prima della barra.
            ("composito", "/PT |/MT", "26026/PT 26026/MT"),
            ("campo_piano", "dwg_no", "26026-01-EGA1"),
            ("campo_piano", "doc_no", "26026-01-QCPA"),
            ("da_proc", "PROC!H17", ""),
        )
        for tipo, valore, atteso in casi:
            with self.subTest(tipo=tipo, valore=valore):
                attivita = self._con_riferimento(tipo, valore)
                self.assertEqual(attivita.risolvi_reference_doc(piano), atteso)

    def test_campo_piano_usa_il_numero_scritto_a_mano_se_c_e(self):
        piano = self._piano(doc_no="26026-QCP-SPECIALE")

        attivita = self._con_riferimento("campo_piano", "doc_no")

        self.assertEqual(attivita.risolvi_reference_doc(piano), "26026-QCP-SPECIALE")

    def test_il_riferimento_e_vuoto_senza_piano_o_senza_dati(self):
        for tipo in AttivitaQCP.TipoRiferimento.values:
            with self.subTest(tipo=tipo, caso="senza piano"):
                self.assertEqual(self._con_riferimento(tipo, "/PT").risolvi_reference_doc(None), "")

        senza_job = QualityControlPlan(testata_id="")
        senza_numeri = QualityControlPlan(testata_id="26026")
        casi = (
            ("suffisso_job", "/PT", senza_job),
            ("suffisso_job", "", self._piano()),
            ("composito", "/VT|/DC", senza_job),
            ("composito", "", self._piano()),
            ("campo_piano", "dwg_no", senza_numeri),
            ("campo_piano", "serial_no", self._piano()),  # campo non previsto
            ("statico", "", self._piano()),
        )
        for tipo, valore, piano in casi:
            with self.subTest(tipo=tipo, valore=valore):
                attivita = self._con_riferimento(tipo, valore)
                self.assertEqual(attivita.risolvi_reference_doc(piano), "")

    # -- API --

    def _catalogo_api(self):
        self._attivita(
            codice="KOM", divisione="Gen", capitolo="KOM", descrizione="Kick of Meeting", tipo="RIU"
        )
        self._attivita(codice="PT-Welds", descrizione="PT on welds", tipo="PT", ordine=3)
        self._attivita(
            codice="VT-Complete base welding",
            descrizione="Complete base WELDING",
            tipo="VT",
            ordine=2,
        )
        self._attivita(
            codice="UT-Old",
            divisione="Div.2",
            descrizione="UT old welding",
            tipo="UT",
            ordine=4,
            attivo=False,
        )

    def _cerca(self, **parametri):
        response = self.client.get(CATALOGO_API, parametri)
        self.assertEqual(response.status_code, 200)
        return response.json()

    @staticmethod
    def _codici(risposta):
        return [a["codice"] for a in risposta["attivita"]]

    def test_api_filtra_per_capitolo_in_ordine_di_catalogo(self):
        self._catalogo_api()

        risposta = self._cerca(capitolo="NDE")

        self.assertEqual(self._codici(risposta), ["VT-Complete base welding", "PT-Welds"])

    def test_api_filtra_per_tipo_e_per_divisione(self):
        self._catalogo_api()

        self.assertEqual(self._codici(self._cerca(tipo="PT")), ["PT-Welds"])
        self.assertEqual(self._codici(self._cerca(divisione="Gen")), ["KOM"])

    def test_api_cerca_in_codice_e_descrizione_senza_badare_alle_maiuscole(self):
        self._catalogo_api()

        self.assertEqual(self._codici(self._cerca(q="WELDING")), ["VT-Complete base welding"])
        self.assertEqual(self._codici(self._cerca(q="kom")), ["KOM"])
        # Più parole: devono esserci tutte.
        self.assertEqual(self._codici(self._cerca(q="meeting kick")), ["KOM"])
        self.assertEqual(self._codici(self._cerca(q="kick welds")), [])

    def test_api_esclude_le_attivita_non_attive(self):
        self._catalogo_api()

        risposta = self._cerca()

        self.assertNotIn("UT-Old", self._codici(risposta))
        self.assertEqual(risposta["totale"], 3)
        self.assertEqual(self._codici(self._cerca(divisione="Div.2")), [])

    def test_api_espone_i_campi_del_catalogo(self):
        self._catalogo_api()

        attivita = self._cerca(q="kom")["attivita"][0]

        self.assertEqual(set(attivita), {"id", *CAMPI_CATALOGO_QCP})

    def test_api_limita_i_risultati(self):
        AttivitaQCP.objects.bulk_create(
            [
                AttivitaQCP(
                    codice=f"A{n}",
                    divisione="Div.1",
                    capitolo="NDE",
                    descrizione=f"Attività {n}",
                    reference_doc_tipo="statico",
                    ordine=n,
                )
                for n in range(LIMITE_CATALOGO_QCP + 5)
            ]
        )

        risposta = self._cerca()

        self.assertEqual(len(risposta["attivita"]), LIMITE_CATALOGO_QCP)
        self.assertEqual(risposta["totale"], LIMITE_CATALOGO_QCP + 5)
        self.assertTrue(risposta["troncato"])

    def test_api_richiede_autenticazione_e_accetta_solo_get(self):
        self.assertEqual(self.client.post(CATALOGO_API).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.get(CATALOGO_API).status_code, 401)


class CorpoQualityControlPlanTests(TestCase):
    """Corpo del piano: sezioni, step, punti d'intervento, numerazione e API."""

    def setUp(self):
        self.client = Client()
        self.writer = _dai_firma(
            User.objects.create_user(
                "corpo_writer", "corpo-writer@brembanarolle.com", "pw", permesso=Permesso.WRITING
            )
        )
        self.reader = User.objects.create_user(
            "corpo_reader", "corpo-reader@brembanarolle.com", "pw", permesso=Permesso.READING
        )
        self.client.force_login(self.writer)
        self.testata = Testata.objects.create(job="26026")
        self.piano = QualityControlPlan.objects.create(
            testata=self.testata,
            titolo="26026-QCPA",
            dwg_base="01",
            serial_base="A",
            foglio_dwg="1",
        )
        self.enti = [
            QualityControlPlanAgency.objects.create(piano=self.piano, nome=nome, ordine=indice)
            for indice, nome in enumerate(("B&R", "TÜV", "Client"))
        ]
        self.pt = self._attivita(
            codice="PT-Welds",
            descrizione="PT on welds",
            test_inspection="PT",
            reference_doc_tipo="suffisso_job",
            reference_doc_valore="/PT",
            acceptance_criteria="ASME VIII/1 App.8",
            documento_richiesto="Test report",
            tecnica="ASME V - Art.6",
            tipo="PT",
            ordine=1,
        )
        self.dwg = self._attivita(
            codice="Drawings",
            capitolo="DOCUMENTAZIONE",
            descrizione="Drawings",
            reference_doc_tipo="campo_piano",
            reference_doc_valore="dwg_no",
            ordine=2,
        )
        self.kom = self._attivita(
            codice="KOM",
            capitolo="KOM",
            descrizione="Kick of Meeting",
            reference_doc_valore="KOM Agenda",
            ordine=3,
        )

    # -- Aiuti --

    @staticmethod
    def _attivita(**campi):
        valori = {
            "codice": "X",
            "divisione": "Div.1",
            "capitolo": "NDE",
            "descrizione": "X",
            "reference_doc_tipo": "statico",
            "ordine": 1,
            **campi,
        }
        return AttivitaQCP.objects.create(**valori)

    def _sezione(self, titolo="Material receiving"):
        return crea_sezione(self.piano, titolo)

    @staticmethod
    def _manuale(sezione, descrizione):
        return aggiungi_step(sezione, dati={"descrizione": descrizione})

    def _numeri(self, piano=None):
        return [
            (
                sezione["titolo"],
                [(step["numero"], step["descrizione"]) for step in sezione["steps"]],
            )
            for sezione in serialize_corpo(piano or self.piano)["sezioni"]
        ]

    def _url(self, suffisso="", pk=None, job="26026"):
        return f"/api/commesse/{job}/quality-control-plan/{pk or self.piano.pk}/corpo/{suffisso}"

    def _invia(self, metodo, suffisso, dati=None, **kwargs):
        url = self._url(suffisso, **kwargs)
        # Per una GET il client di test tratta ``data`` come querystring: niente corpo.
        if metodo == "get":
            return self.client.get(url)
        corpo = json.dumps(dati) if dati is not None else ""
        return getattr(self.client, metodo)(url, data=corpo, content_type="application/json")

    # -- Sezioni --

    def test_le_sezioni_si_aggiungono_in_coda(self):
        prima = self._sezione("Documents approval")
        seconda = self._sezione("Material receiving")

        self.assertEqual((prima.ordine, seconda.ordine), (0, 1))

    def test_una_sezione_si_puo_inserire_in_una_posizione(self):
        self._sezione("A")
        self._sezione("B")

        crea_sezione(self.piano, "C", ordine=0)

        self.assertEqual(
            list(self.piano.sections.values_list("titolo", "ordine")),
            [("C", 0), ("A", 1), ("B", 2)],
        )

    def test_il_titolo_della_sezione_e_obbligatorio(self):
        for titolo in ("", "   ", None, "X" * 201):
            with self.subTest(titolo=titolo), self.assertRaises(ValueError):
                crea_sezione(self.piano, titolo)

        self.assertFalse(QualityControlPlanSection.objects.exists())

    def test_eliminare_una_sezione_ricompatta_le_altre(self):
        self._sezione("A")
        centrale = self._sezione("B")
        self._sezione("C")
        aggiungi_step(centrale, attivita_id=self.pt.pk)

        elimina_sezione(centrale)

        self.assertEqual(
            list(self.piano.sections.values_list("titolo", "ordine")), [("A", 0), ("C", 1)]
        )
        self.assertFalse(QualityControlPlanStep.objects.exists())
        self.assertFalse(QualityControlPlanInterventionPoint.objects.exists())

    # -- Step --

    def test_lo_step_dal_catalogo_copia_lo_snapshot_e_risolve_il_riferimento(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        self.assertEqual(step.attivita, self.pt)
        for campo in (
            "descrizione",
            "test_inspection",
            "acceptance_criteria",
            "documento_richiesto",
            "tecnica",
        ):
            with self.subTest(campo=campo):
                self.assertEqual(getattr(step, campo), getattr(self.pt, campo))
        self.assertEqual(step.reference_doc, "26026/PT")
        self.assertEqual(step.extent, Decimal("1.000"))

    def test_il_riferimento_a_un_campo_del_piano_si_risolve_all_inserimento(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.dwg.pk)

        self.assertEqual(step.reference_doc, "26026-01-EGA1")

    def test_attivita_inesistente_o_disattivata_rifiutata(self):
        self.kom.attivo = False
        self.kom.save(update_fields=["attivo"])
        sezione = self._sezione()

        for attivita_id in (self.kom.pk, 999999, "x", True):
            with self.subTest(attivita_id=attivita_id), self.assertRaises(ValueError):
                aggiungi_step(sezione, attivita_id=attivita_id)

        self.assertFalse(QualityControlPlanStep.objects.exists())

    def test_uno_step_manuale_e_valido_senza_catalogo(self):
        step = aggiungi_step(
            self._sezione(),
            dati={
                "descrizione": "Visual check of nozzles",
                "reference_doc": "26026/VT",
                "extent": "0.5",
            },
        )

        self.assertIsNone(step.attivita)
        self.assertEqual(step.descrizione, "Visual check of nozzles")
        self.assertEqual(step.reference_doc, "26026/VT")
        self.assertEqual(step.extent, Decimal("0.500"))

    def test_uno_step_manuale_senza_descrizione_e_rifiutato(self):
        sezione = self._sezione()

        for dati in ({}, {"descrizione": "   "}, None):
            with self.subTest(dati=dati), self.assertRaises(ValueError):
                aggiungi_step(sezione, dati=dati)

        self.assertFalse(QualityControlPlanStep.objects.exists())

    def test_ogni_step_ha_un_punto_per_ente(self):
        sezione = self._sezione()
        steps = [
            aggiungi_step(sezione, attivita_id=self.pt.pk),
            self._manuale(sezione, "Manual check"),
            *aggiungi_step_multipli(sezione, [self.kom.pk, self.dwg.pk]),
        ]

        for step in steps:
            with self.subTest(step=step.descrizione):
                self.assertEqual(
                    sorted(step.punti.values_list("agency_id", flat=True)),
                    sorted(ente.pk for ente in self.enti),
                )
                self.assertEqual(set(step.punti.values_list("punto", flat=True)), {"-"})

    def test_un_piano_senza_enti_ha_step_senza_punti(self):
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        sezione = crea_sezione(altro, "Documents approval")

        step = aggiungi_step(sezione, attivita_id=self.pt.pk)

        self.assertEqual(step.punti.count(), 0)
        self.assertEqual(serialize_corpo(altro)["sezioni"][0]["steps"][0]["punti"], [])

    def test_l_inserimento_multiplo_preserva_l_ordine(self):
        sezione = self._sezione()
        self._manuale(sezione, "Primo")

        aggiungi_step_multipli(sezione, [self.kom.pk, self.pt.pk, self.kom.pk])

        self.assertEqual(
            list(sezione.steps.values_list("descrizione", "ordine")),
            [("Primo", 0), ("Kick of Meeting", 1), ("PT on welds", 2), ("Kick of Meeting", 3)],
        )
        self.assertEqual(QualityControlPlanInterventionPoint.objects.count(), 4 * len(self.enti))

    def test_l_inserimento_multiplo_e_tutto_o_niente(self):
        sezione = self._sezione()

        with self.assertRaisesMessage(ValueError, "999999"):
            aggiungi_step_multipli(sezione, [self.pt.pk, 999999])

        self.assertFalse(sezione.steps.exists())

    # -- Numerazione --

    def test_la_numerazione_attraversa_le_sezioni(self):
        prima = self._sezione("A")
        seconda = self._sezione("B")
        for descrizione in ("A1", "A2"):
            self._manuale(prima, descrizione)
        for descrizione in ("B1", "B2", "B3"):
            self._manuale(seconda, descrizione)

        self.assertEqual(
            self._numeri(),
            [("A", [(1, "A1"), (2, "A2")]), ("B", [(3, "B1"), (4, "B2"), (5, "B3")])],
        )
        self.assertEqual(serialize_corpo(self.piano)["totale_step"], 5)

    def test_la_numerazione_si_ricalcola_dopo_una_cancellazione(self):
        prima = self._sezione("A")
        seconda = self._sezione("B")
        self._manuale(prima, "A1")
        intermedio = self._manuale(prima, "A2")
        self._manuale(prima, "A3")
        self._manuale(seconda, "B1")

        elimina_step(intermedio)

        self.assertEqual(self._numeri(), [("A", [(1, "A1"), (2, "A3")]), ("B", [(3, "B1")])])
        self.assertEqual(list(prima.steps.values_list("ordine", flat=True)), [0, 1])

    # -- Riordino --

    def test_riordino_di_sezioni_e_step(self):
        a = self._sezione("A")
        b = self._sezione("B")
        c = self._sezione("C")
        x = self._manuale(a, "X")
        y = self._manuale(a, "Y")
        z = self._manuale(a, "Z")

        riordina(self.piano.sections.all(), [c.pk, a.pk, b.pk])
        riordina(a.steps.all(), [z.pk, x.pk, y.pk])

        self.assertEqual(
            self._numeri(), [("C", []), ("A", [(1, "Z"), (2, "X"), (3, "Y")]), ("B", [])]
        )

    def test_il_riordino_vuole_tutti_gli_elementi_una_volta(self):
        a = self._sezione("A")
        b = self._sezione("B")

        for ordine in ([a.pk], [a.pk, a.pk], [a.pk, b.pk, 999999], "x"):
            with self.subTest(ordine=ordine), self.assertRaises(ValueError):
                riordina(self.piano.sections.all(), ordine)

    def test_il_riordino_e_un_solo_update(self):
        sezioni = [self._sezione(titolo) for titolo in ("A", "B", "C")]

        with self.assertNumQueries(1):
            riordina(sezioni, [s.pk for s in reversed(sezioni)])

        self.assertEqual(
            list(self.piano.sections.values_list("titolo", flat=True)), ["C", "B", "A"]
        )

    # -- Punti d'intervento --

    def test_imposta_punto(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        imposta_punto(step, self.enti[1], "h")

        self.assertEqual(step.punti.get(agency=self.enti[1]).punto, "H")
        self.assertEqual(step.punti.count(), len(self.enti))

    def test_imposta_punto_con_ente_di_un_altro_piano_e_un_errore(self):
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        ente_altrui = QualityControlPlanAgency.objects.create(piano=altro, nome="TÜV")
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        with self.assertRaisesMessage(ValueError, "non appartiene al piano"):
            imposta_punto(step, ente_altrui, "W")

        self.assertFalse(
            QualityControlPlanInterventionPoint.objects.filter(agency=ente_altrui).exists()
        )

    def test_imposta_punto_non_valido(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        for punto in ("Z", "", None, "WH"):
            with self.subTest(punto=punto), self.assertRaises(ValueError):
                imposta_punto(step, self.enti[0], punto)

    def test_un_ente_puo_avere_piu_stati_sullo_stesso_step(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        for valore, salvato in (
            ("r/sw", "R/SW"),
            (" F / SW ", "F/SW"),  # l'ordine dato resta
            ("W/W/H", "W/H"),
            ("(*)", "(*)"),
            ("W/H/R/SW/M/A/F/(*)", "W/H/R/SW/M/A/F/(*)"),  # tutti insieme stanno nella colonna
            ("-", "-"),
        ):
            with self.subTest(valore=valore):
                self.assertEqual(imposta_punto(step, self.enti[0], valore).punto, salvato)
        # "-" non si combina con altri stati; parti vuote o sconosciute non valgono.
        for valore in ("-/W", "W/", "W//H", "R/Z", "/"):
            with (
                self.subTest(valore=valore),
                self.assertRaisesMessage(ValueError, "anche più di uno"),
            ):
                imposta_punto(step, self.enti[0], valore)
        self.assertEqual(etichetta_punto("R/SW"), "Review + Spot witness")
        self.assertEqual(etichetta_punto("(*)"), "See dedicated sheet")

    def test_sincronizza_punti_dopo_aggiunta_e_rimozione_di_un_ente(self):
        sezione = self._sezione()
        steps = aggiungi_step_multipli(sezione, [self.pt.pk, self.kom.pk])
        nuovo = QualityControlPlanAgency.objects.create(piano=self.piano, nome="A.I.", ordine=3)

        self.assertEqual(sincronizza_punti(self.piano), {"creati": 2, "rimossi": 0})
        for step in steps:
            self.assertEqual(step.punti.count(), 4)
            self.assertEqual(step.punti.get(agency=nuovo).punto, "-")

        # Togliere un ente cancella in cascata i suoi punti: non resta nulla da fare.
        self.enti[0].delete()
        self.assertEqual(sincronizza_punti(self.piano), {"creati": 0, "rimossi": 0})
        for step in steps:
            self.assertEqual(step.punti.count(), 3)

        # Un punto legato all'ente di un altro piano è orfano e viene tolto.
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        ente_altrui = QualityControlPlanAgency.objects.create(piano=altro, nome="Lloyd")
        QualityControlPlanInterventionPoint.objects.create(step=steps[0], agency=ente_altrui)
        self.assertEqual(sincronizza_punti(self.piano), {"creati": 0, "rimossi": 1})

    def test_il_salvataggio_in_admin_sincronizza_i_punti(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)
        QualityControlPlanAgency.objects.create(piano=self.piano, nome="A.I.", ordine=3)
        admin_piani = django_admin.site._registry[QualityControlPlan]

        admin_piani.save_related(None, Mock(instance=self.piano), [], True)

        self.assertEqual(step.punti.count(), 4)

    # -- Extent e correzioni --

    def test_extent_come_frazione(self):
        step = self._manuale(self._sezione(), "Visual check")

        for valore, atteso in (
            (0.1, "0.100"),
            ("0.125", "0.125"),
            (0, "0.000"),
            (1, "1.000"),
            ("0.5000", "0.500"),
        ):
            with self.subTest(valore=valore):
                aggiorna_step(step, extent=valore)
                step.refresh_from_db()
                self.assertEqual(step.extent, Decimal(atteso))

    def test_extent_fuori_intervallo_o_non_valido(self):
        step = self._manuale(self._sezione(), "Visual check")

        for valore in (1.5, -0.1, 50, "10%", "abc", None, True, "0.1234", "NaN"):
            with self.subTest(valore=valore), self.assertRaises(ValueError):
                aggiorna_step(step, extent=valore)

        step.refresh_from_db()
        self.assertEqual(step.extent, Decimal("1.000"))

    def test_la_correzione_resta_sullo_step(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        aggiorna_step(
            step,
            descrizione="PT on nozzle welds",
            report_no="RPT-12",
            remarks="Solo ugelli",
            id=999,
        )

        step.refresh_from_db()
        self.assertEqual(
            (step.descrizione, step.report_no, step.remarks),
            ("PT on nozzle welds", "RPT-12", "Solo ugelli"),
        )
        self.pt.refresh_from_db()
        self.assertEqual(self.pt.descrizione, "PT on welds")

    def test_correzione_senza_campi_o_senza_descrizione_rifiutata(self):
        step = self._manuale(self._sezione(), "Visual check")

        with self.assertRaisesMessage(ValueError, "Nessun campo"):
            aggiorna_step(step)
        with self.assertRaisesMessage(ValueError, "descrizione"):
            aggiorna_step(step, descrizione="  ")

    def test_cambiare_il_catalogo_non_cambia_gli_step_gia_inseriti(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        self.pt.descrizione = "PT on all welds"
        self.pt.reference_doc_valore = "/QPT"
        self.pt.save()

        step.refresh_from_db()
        self.assertEqual((step.descrizione, step.reference_doc), ("PT on welds", "26026/PT"))
        corpo = serialize_corpo(self.piano)
        self.assertEqual(corpo["sezioni"][0]["steps"][0]["descrizione"], "PT on welds")

    # -- Lettura --

    def test_il_corpo_si_legge_con_un_numero_fisso_di_query(self):
        for indice in range(4):
            sezione = crea_sezione(self.piano, f"Sezione {indice}")
            aggiungi_step_multipli(sezione, [self.pt.pk, self.kom.pk, self.dwg.pk] * 5)
        piano = QualityControlPlan.objects.get(pk=self.piano.pk)

        # Enti, sezioni, step, punti, firme valide: cinque query con 60 step come con uno.
        with self.assertNumQueries(5):
            corpo = serialize_corpo(piano)

        self.assertEqual(corpo["totale_step"], 60)
        self.assertEqual([e["nome"] for e in corpo["enti"]], ["B&R", "TÜV", "Client"])
        for sezione in corpo["sezioni"]:
            for step in sezione["steps"]:
                self.assertEqual([p["agency_id"] for p in step["punti"]], [e.pk for e in self.enti])

    # -- API --

    def test_api_legge_il_corpo(self):
        aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        corpo = response.json()
        self.assertEqual(corpo["sezioni"][0]["steps"][0]["numero"], 1)
        self.assertEqual(corpo["sezioni"][0]["steps"][0]["reference_doc"], "26026/PT")
        self.assertIn("SW", [p["codice"] for p in corpo["punti_disponibili"]])

    def test_api_crea_una_sezione(self):
        response = self._invia("post", "sezioni/", {"titolo": "Documents approval"})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["sezioni"][0]["titolo"], "Documents approval")

    def test_api_rinomina_e_sposta_una_sezione(self):
        self._sezione("A")
        seconda = self._sezione("B")

        response = self._invia("patch", f"sezioni/{seconda.pk}/", {"titolo": "B2", "ordine": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual([s["titolo"] for s in response.json()["data"]["sezioni"]], ["B2", "A"])

    def test_api_elimina_una_sezione(self):
        sezione = self._sezione("A")

        response = self._invia("delete", f"sezioni/{sezione.pk}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["sezioni"], [])

    def test_api_aggiunge_step_dal_catalogo_e_a_mano(self):
        sezione = self._sezione()
        url = f"sezioni/{sezione.pk}/steps/"

        self.assertEqual(
            self._invia("post", url, {"attivita_ids": [self.kom.pk, self.pt.pk]}).status_code, 201
        )
        self.assertEqual(self._invia("post", url, {"attivita_id": self.dwg.pk}).status_code, 201)
        response = self._invia("post", url, {"dati": {"descrizione": "Manual check"}})

        self.assertEqual(response.status_code, 201)
        steps = response.json()["data"]["sezioni"][0]["steps"]
        self.assertEqual(
            [(s["numero"], s["descrizione"]) for s in steps],
            [(1, "Kick of Meeting"), (2, "PT on welds"), (3, "Drawings"), (4, "Manual check")],
        )

    def test_api_aggiunta_step_non_valida_e_400(self):
        sezione = self._sezione()
        url = f"sezioni/{sezione.pk}/steps/"

        for dati in ({}, {"dati": {}}, {"attivita_ids": [999999]}, {"attivita_ids": "x"}):
            with self.subTest(dati=dati):
                self.assertEqual(self._invia("post", url, dati).status_code, 400)
        self.assertFalse(QualityControlPlanStep.objects.exists())

    def test_api_modifica_e_sposta_uno_step(self):
        sezione = self._sezione()
        self._manuale(sezione, "Primo")
        secondo = self._manuale(sezione, "Secondo")

        response = self._invia(
            "patch", f"steps/{secondo.pk}/", {"extent": 0.1, "remarks": "Solo ugelli", "ordine": 0}
        )

        self.assertEqual(response.status_code, 200)
        steps = response.json()["data"]["sezioni"][0]["steps"]
        self.assertEqual([s["descrizione"] for s in steps], ["Secondo", "Primo"])
        self.assertEqual((steps[0]["extent"], steps[0]["remarks"]), (0.1, "Solo ugelli"))
        self.assertEqual(
            self._invia("patch", f"steps/{secondo.pk}/", {"extent": 5}).status_code, 400
        )

    def test_api_elimina_uno_step(self):
        sezione = self._sezione()
        primo = self._manuale(sezione, "Primo")
        self._manuale(sezione, "Secondo")

        response = self._invia("delete", f"steps/{primo.pk}/")

        self.assertEqual(response.status_code, 200)
        steps = response.json()["data"]["sezioni"][0]["steps"]
        self.assertEqual([(s["numero"], s["descrizione"]) for s in steps], [(1, "Secondo")])

    def test_api_imposta_i_punti_tutti_o_nessuno(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)
        url = f"steps/{step.pk}/punti/"

        response = self._invia(
            "patch",
            url,
            {
                "punti": [
                    {"agency": self.enti[0].pk, "punto": "H"},
                    {"agency": self.enti[1].pk, "punto": "W"},
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        punti = response.json()["data"]["sezioni"][0]["steps"][0]["punti"]
        self.assertEqual([p["punto"] for p in punti], ["H", "W", "-"])

        # Un punto non valido annulla anche quello valido nella stessa richiesta.
        response = self._invia(
            "patch",
            url,
            {
                "punti": [
                    {"agency": self.enti[0].pk, "punto": "A"},
                    {"agency": self.enti[1].pk, "punto": "Z"},
                ]
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(step.punti.get(agency=self.enti[0]).punto, "H")

    def test_api_ente_di_un_altro_piano_e_400(self):
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        ente_altrui = QualityControlPlanAgency.objects.create(piano=altro, nome="TÜV")
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)

        response = self._invia(
            "patch",
            f"steps/{step.pk}/punti/",
            {"punti": [{"agency": ente_altrui.pk, "punto": "W"}]},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("non appartiene al piano", response.json()["error"])

    def test_api_oggetti_di_un_altro_piano_o_commessa_sono_404(self):
        Testata.objects.create(job="99999")
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        sezione_altrui = crea_sezione(altro, "Altro")
        step_altrui = aggiungi_step(sezione_altrui, attivita_id=self.pt.pk)

        casi = (
            ("get", "", {"job": "99999"}),
            ("get", "", {"pk": 999999}),
            ("patch", f"sezioni/{sezione_altrui.pk}/", {}),
            ("delete", f"sezioni/{sezione_altrui.pk}/", {}),
            ("post", f"sezioni/{sezione_altrui.pk}/steps/", {}),
            ("patch", f"steps/{step_altrui.pk}/", {}),
            ("delete", f"steps/{step_altrui.pk}/", {}),
            ("patch", f"steps/{step_altrui.pk}/punti/", {}),
        )
        for metodo, suffisso, kwargs in casi:
            with self.subTest(metodo=metodo, suffisso=suffisso, **kwargs):
                response = self._invia(metodo, suffisso, {"titolo": "X", "punti": []}, **kwargs)
                self.assertEqual(response.status_code, 404)

        self.assertTrue(QualityControlPlanStep.objects.filter(pk=step_altrui.pk).exists())
        self.assertTrue(QualityControlPlanSection.objects.filter(pk=sezione_altrui.pk).exists())

    def test_api_permessi_e_autenticazione(self):
        self.client.force_login(self.reader)

        self.assertEqual(self.client.get(self._url()).status_code, 200)
        self.assertEqual(self._invia("post", "sezioni/", {"titolo": "X"}).status_code, 403)

        self.client.logout()
        self.assertEqual(self.client.get(self._url()).status_code, 401)

    def test_api_json_che_non_e_un_oggetto_e_400(self):
        response = self._invia("post", "sezioni/", ["Documents approval"])

        self.assertEqual(response.status_code, 400)
        self.assertFalse(QualityControlPlanSection.objects.exists())

    # -- Spostamento fra sezioni --

    def test_api_sposta_uno_step_in_un_altra_sezione(self):
        prima = self._sezione("A")
        seconda = self._sezione("B")
        self._manuale(prima, "A1")
        a2 = self._manuale(prima, "A2")
        self._manuale(prima, "A3")
        self._manuale(seconda, "B1")

        response = self._invia("patch", f"steps/{a2.pk}/", {"sezione": seconda.pk, "ordine": 0})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._numeri(), [("A", [(1, "A1"), (2, "A3")]), ("B", [(3, "A2"), (4, "B1")])]
        )
        # Tutte e due le sezioni restano numerate senza buchi.
        for sezione in (prima, seconda):
            with self.subTest(sezione=sezione.titolo):
                self.assertEqual(
                    list(sezione.steps.order_by("ordine").values_list("ordine", flat=True)), [0, 1]
                )
        # I punti d'intervento seguono lo step: gli enti sono dello stesso piano.
        self.assertEqual(QualityControlPlanStep.objects.get(pk=a2.pk).punti.count(), 3)

    def test_api_senza_ordine_lo_step_va_in_coda_con_le_correzioni(self):
        prima = self._sezione("A")
        seconda = self._sezione("B")
        a1 = self._manuale(prima, "A1")
        self._manuale(seconda, "B1")

        response = self._invia(
            "patch", f"steps/{a1.pk}/", {"sezione": seconda.pk, "remarks": "Qui"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._numeri(), [("A", []), ("B", [(1, "B1"), (2, "A1")])])
        self.assertEqual(QualityControlPlanStep.objects.get(pk=a1.pk).remarks, "Qui")

    def test_api_sezione_di_destinazione_non_valida_non_cambia_nulla(self):
        altro = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        sezione_altrui = crea_sezione(altro, "Altro")
        sezione = self._sezione("A")
        seconda = self._sezione("B")
        step = self._manuale(sezione, "A1")

        casi = (
            {"sezione": sezione_altrui.pk},
            {"sezione": 999999},
            {"sezione": "x"},
            {"sezione": True},
            {"sezione": sezione.pk, "ordine": 5},
            {"sezione": seconda.pk, "ordine": 9},
        )
        for dati in casi:
            with self.subTest(dati=dati):
                response = self._invia("patch", f"steps/{step.pk}/", {**dati, "remarks": "No"})
                self.assertEqual(response.status_code, 400)

        # Né lo spostamento né la correzione nella stessa richiesta.
        step.refresh_from_db()
        self.assertEqual((step.sezione_id, step.ordine, step.remarks), (sezione.pk, 0, ""))

    # -- Catalogo per il modale "Aggiungi step da catalogo" --

    def test_api_catalogo_col_piano_risolve_il_riferimento(self):
        response = self.client.get(CATALOGO_API, {"piano": self.piano.pk})

        self.assertEqual(response.status_code, 200)
        riferimenti = {a["codice"]: a["reference_doc_risolto"] for a in response.json()["attivita"]}
        self.assertEqual(
            riferimenti,
            {"PT-Welds": "26026/PT", "Drawings": "26026-01-EGA1", "KOM": "KOM Agenda"},
        )

    def test_api_catalogo_col_piano_cerca_filtra_ed_esclude_le_non_attive(self):
        self._attivita(codice="PT-Old", descrizione="PT on old welds", attivo=False)

        def codici(**parametri):
            response = self.client.get(CATALOGO_API, {"piano": self.piano.pk, **parametri})
            self.assertEqual(response.status_code, 200)
            return [a["codice"] for a in response.json()["attivita"]]

        self.assertEqual(codici(q="welds"), ["PT-Welds"])
        self.assertEqual(codici(capitolo="DOCUMENTAZIONE"), ["Drawings"])
        self.assertEqual(codici(capitolo="NDE", q="kick"), [])
        self.assertNotIn("PT-Old", codici())

    def test_api_catalogo_senza_piano_o_con_piano_non_valido(self):
        attivita = self.client.get(CATALOGO_API).json()["attivita"]
        self.assertNotIn("reference_doc_risolto", attivita[0])

        self.assertEqual(self.client.get(CATALOGO_API, {"piano": "abc"}).status_code, 400)
        self.assertEqual(self.client.get(CATALOGO_API, {"piano": 999999}).status_code, 404)

    def test_i_capitoli_del_catalogo_sono_quelli_con_attivita_attive(self):
        self._attivita(codice="OLD", capitolo="VECCHIO", attivo=False, ordine=0)

        self.assertEqual(capitoli_attivi_qcp(), ["NDE", "DOCUMENTAZIONE", "KOM"])

    # -- Editor nella pagina del piano --

    def _pagina(self):
        response = self.client.get(f"/commesse/26026/quality-control-plan/{self.piano.pk}/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    @staticmethod
    def _html_step(html, step):
        """Il markup di uno step: dal suo <li> alla sua chiusura (non ha <li> dentro)."""
        inizio = html.index(f'<li class="ce-step" data-id="{step.pk}" ')
        return html[inizio : html.index("</li>", inizio) + len("</li>")]

    def test_la_pagina_mostra_sezioni_step_e_una_colonna_di_punti_per_ente(self):
        prima = self._sezione("Documents approval")
        seconda = self._sezione("Material receiving")
        aggiungi_step(prima, attivita_id=self.kom.pk)
        pt = aggiungi_step(seconda, attivita_id=self.pt.pk)
        imposta_punto(pt, self.enti[1], "H")

        html = self._pagina()

        # Le sezioni sono voci dell'elenco laterale e pannelli, nello stesso ordine.
        self.assertRegex(
            html,
            r'(?s)qp-voce-titolo">Documents approval<.*qp-voce-titolo">Material receiving<',
        )
        self.assertRegex(
            html,
            r'(?s)ce-sez-titolo">Documents approval<.*ce-sez-titolo">Material receiving<',
        )
        self.assertIn("Kick of Meeting", html)
        self.assertIn("PT on welds", html)
        # Si vede una sezione alla volta: all'apertura la prima.
        self.assertIn(f'<li class="ce-sezione" data-id="{prima.pk}" id="ce-sez-{prima.pk}">', html)
        self.assertIn(
            f'<li class="ce-sezione" data-id="{seconda.pk}" id="ce-sez-{seconda.pk}" hidden>', html
        )
        self.assertRegex(
            html,
            rf'<li class="qp-voce is-attiva" data-id="{prima.pk}">\s*<button[^>]*'
            rf'aria-controls="ce-sez-{prima.pk}" aria-current="true">',
        )
        self.assertRegex(
            html,
            rf'<li class="qp-voce" data-id="{seconda.pk}">\s*<button[^>]*'
            rf'aria-current="false" tabindex="-1">',
        )
        # Una colonna per ente, nell'ordine della copertina: intestazione e celle.
        self.assertEqual(
            re.findall(r'class="ce-ente-nome">([^<]*)<', html)[:3], ["B&amp;R", "TÜV", "Client"]
        )
        self.assertEqual(
            re.findall(r'class="ce-intesta-(?:n|step|extent)">([^<]*)<', html)[:3],
            ["No.", "Step", "Extent"],
        )
        riga = self._html_step(html, pt)
        self.assertEqual(
            re.findall(r'class="ce-punto[^"]*"\s+data-ente="(\d+)"', riga),
            [str(ente.pk) for ente in self.enti],
        )
        self.assertEqual(re.findall(r'data-punto="([^"]*)"', riga), ["-", "H", "-"])
        # Numerazione continua fra le sezioni, extent in percentuale.
        self.assertIn('<span class="ce-step-n">2</span>', riga)
        self.assertIn('value="100"', riga)
        self.assertIn('<span class="qp-sez-conta" id="ce-conteggio">2 · 2 steps</span>', html)
        # Due livelli: sul primo descrizione, extent, punti e menu; sul secondo
        # gli altri testi, con la loro sigla. Niente più riga che scorre.
        self.assertRegex(
            riga,
            r"(?s)ce-testo-descrizione.*ce-extent.*ce-punto.*ce-dettagli"
            r".*ce-testo-test_inspection.*ce-testo-reference_doc.*ce-testo-acceptance_criteria"
            r".*ce-testo-documento_richiesto.*ce-testo-tecnica.*ce-testo-report_no"
            r".*ce-testo-remarks.*ce-azioni-step",
        )
        self.assertIn(
            '<span class="ce-coppia-sigla" title="Reference doc." aria-hidden="true">ref</span>'
            '<span class="ce-sr">Reference doc.: </span><span class="ce-testo-val">26026/PT</span>',
            riga,
        )
        self.assertIn('<span class="ce-testo-val">ASME VIII/1 App.8</span>', riga)
        # I testi vuoti non si vedono, ma restano per poterli riempire da "Modifica".
        self.assertIn('class="ce-testo ce-coppia ce-testo-report_no is-vuota"', riga)
        self.assertNotIn('class="ce-testo ce-coppia ce-testo-tecnica is-vuota"', riga)
        # Si modifica cliccando lo step (o con Invio): niente menu ··· sulla riga,
        # le azioni stanno sotto i testi e compaiono in modifica.
        self.assertRegex(
            riga, r'^<li class="ce-step"[^>]* tabindex="0" aria-describedby="ce-aiuto-step">'
        )
        self.assertNotIn('class="ce-dots"', riga)
        self.assertEqual(re.findall(r'data-step-azione="([^"]*)"', riga), ["elimina"])
        self.assertNotIn("ce-intesta-testo", html)
        # Le colonne degli enti si allargano fino al nome più lungo ("Client").
        self.assertIn('style="--ce-ente-car: 6"', html)

    def test_la_pagina_mostra_i_punti_con_piu_stati(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)
        imposta_punto(step, self.enti[1], "R/SW")

        html = self._pagina()

        riga = self._html_step(html, step)
        self.assertIn('data-punto="R/SW"', riga)
        self.assertIn("TÜV, intervention point: Review + Spot witness", riga)
        # Il menu dei punti offre anche "(*)".
        self.assertIn('data-punto="(*)" data-etichetta="See dedicated sheet"', html)

    def test_la_pagina_senza_enti_non_ha_colonne_di_punti_e_lo_dice(self):
        QualityControlPlanAgency.objects.filter(piano=self.piano).delete()
        self._manuale(self._sezione(), "Manual check")

        html = self._pagina()

        self.assertIn("Manual check", html)
        self.assertNotIn('class="ce-punto', html)
        self.assertNotIn('class="ce-ente-nome"', html)
        self.assertIn('class="ce-avviso"', html)
        self.assertIn("ce-senza-enti", html)

    def test_la_pagina_senza_sezioni_spiega_come_cominciare(self):
        html = self._pagina()

        self.assertNotRegex(html, r'id="ce-vuoto"[^>]*hidden')
        self.assertIn("Add the first section", html)
        self.assertIn('<span class="qp-sez-conta" id="ce-conteggio">0 · 0 steps</span>', html)
        # Un piano senza punti da firmare è a 0%, senza divisioni per zero.
        self.assertIn('<span class="qp-pct" id="qp-pct">0%</span>', html)
        self.assertNotRegex(html, r'id="qp-barra"[^>]*hidden>')
        self.assertIn('<span id="qp-completi">0 points signed</span>', html)

    def test_la_pagina_offre_i_capitoli_del_catalogo(self):
        self._attivita(codice="OLD", capitolo="VECCHIO", attivo=False)

        html = self._pagina()

        self.assertIn('<option value="NDE">NDE</option>', html)
        self.assertNotIn('<option value="VECCHIO">', html)

    def _punti_step(self, step):
        return list(step.punti.order_by("agency__ordine"))

    def test_l_avanzamento_per_sezione_e_per_piano(self):
        documenti = self._sezione("Documents approval")
        materiali = self._sezione("Material receiving")
        self._sezione("Vuota")
        pt, kom = aggiungi_step_multipli(documenti, [self.pt.pk, self.kom.pk])
        dwg = aggiungi_step(materiali, attivita_id=self.dwg.pk)
        # Da firmare: PT su B&R e TÜV, KOM su B&R; Drawings solo "-".
        imposta_punto(pt, self.enti[0], "H")
        imposta_punto(pt, self.enti[1], "W")
        imposta_punto(kom, self.enti[0], "R")
        firma_punto(self._punti_step(pt)[0], self.writer, EsitoFirma.CONFORME)

        corpo = corpo_per_pagina(self.piano)

        prima, seconda, vuota = corpo["sezioni"]
        chiavi = ("punti_da_firmare", "punti_firmati", "percentuale")
        self.assertEqual({k: prima[k] for k in chiavi}, dict(zip(chiavi, (3, 1, 33))))
        # Senza punti da firmare (solo "-", o nessuno step) niente percentuale.
        self.assertEqual({k: seconda[k] for k in chiavi}, dict(zip(chiavi, (0, 0, None))))
        self.assertEqual({k: vuota[k] for k in chiavi}, dict(zip(chiavi, (0, 0, None))))
        self.assertEqual(
            {
                k: corpo["avanzamento"][k]
                for k in ("totale", "firmati", "da_firmare", "percentuale")
            },
            {"totale": 3, "firmati": 1, "da_firmare": 2, "percentuale": 33},
        )
        # Gli stessi numeri che dà avanzamento(piano), contato dal database.
        conti = avanzamento(self.piano)
        self.assertEqual((conti["totale"], conti["firmati"]), (3, 1))
        self.assertFalse(dwg.punti.exclude(punto="-").exists())

    def test_la_pagina_mostra_l_avanzamento_nella_barra_laterale(self):
        documenti = self._sezione("Documents approval")
        vuota = self._sezione("Material receiving")
        pt, kom = aggiungi_step_multipli(documenti, [self.pt.pk, self.kom.pk])
        imposta_punto(pt, self.enti[0], "H")
        imposta_punto(kom, self.enti[0], "R")
        firma_punto(self._punti_step(pt)[0], self.writer, EsitoFirma.CONFORME)

        html = self._pagina()

        self.assertIn('<span class="qp-pct" id="qp-pct">50%</span>', html)
        self.assertIn('<span id="qp-completi">1 point signed</span>', html)
        self.assertIn('<span id="qp-da-completare">1 to sign</span>', html)
        self.assertIn('id="qp-stato-piano">In progress<', html)
        self.assertRegex(
            html,
            rf'(?s)<li class="qp-voce is-attiva" data-id="{documenti.pk}">.*?'
            r'qp-voce-meta">2 steps · 50%<',
        )
        # La sezione vuota è "da compilare", senza barra.
        self.assertRegex(
            html,
            rf'(?s)<li class="qp-voce" data-id="{vuota.pk}">.*?qp-voce-meta">No steps yet<'
            r'.*?class="qp-barra qp-barra-mini" aria-hidden="true" hidden>',
        )
        self.assertIn('<span class="ce-sez-conta">2 steps · 50% complete</span>', html)

    def test_un_piano_con_tutti_i_punti_firmati_e_completo(self):
        step = aggiungi_step(self._sezione(), attivita_id=self.pt.pk)
        imposta_punto(step, self.enti[0], "H")
        firma_step(step, self.writer, EsitoFirma.CONFORME)

        html = self._pagina()

        self.assertIn('id="qp-stato-piano">Complete<', html)
        self.assertIn('<span class="qp-pct" id="qp-pct">100%</span>', html)

    def test_in_sola_lettura_la_pagina_non_ha_controlli_di_modifica(self):
        aggiungi_step(self._sezione(), attivita_id=self.pt.pk)
        self.client.force_login(self.reader)

        html = self._pagina()

        self.assertIn("PT on welds", html)
        for marcatore in (
            'id="ce-add-sezione"',
            'id="ce-catalogo"',
            'id="ce-tpl-step"',
            'id="ce-tpl-voce"',
            'aria-label="Azioni sullo step"',
            'aria-label="Azioni sulla sezione"',
            'class="ce-extent-input"',
            'title="Trascina per spostare',
            'class="ce-dots"',
            'class="ce-azioni-step"',
            'tabindex="0" aria-describedby="ce-aiuto-step"',
        ):
            with self.subTest(marcatore=marcatore):
                self.assertNotIn(marcatore, html)
        # Le celle dei punti non sono pulsanti: si leggono, col tooltip dello
        # stato di firma (su un pulsante disattivato il tooltip non compare).
        self.assertNotIn('<button type="button" class="ce-punto', html)
        self.assertRegex(html, r'<span role="img" class="ce-punto[^"]*"[^>]*title="B&amp;R: ')
        # I valori si leggono sulla riga come per chi scrive.
        self.assertIn('<span class="ce-testo-val">ASME VIII/1 App.8</span>', html)

    def test_l_extent_si_mostra_in_percentuale(self):
        self.assertEqual(extent_in_percentuale(1), "100")
        self.assertEqual(extent_in_percentuale(0.125), "12,5")
        self.assertEqual(extent_in_percentuale(0.1), "10")
        self.assertEqual(extent_in_percentuale(0), "0")


CORPO_26026 = Path(__file__).resolve().parent / "data" / "corpo_26026.json"


class SeedCorpoQCPTests(TestCase):
    """Comando seed_corpo_qcp: il corpo del piano della commessa 26026 da file."""

    @classmethod
    def setUpTestData(cls):
        # Il catalogo vero: il file usa i suoi codici.
        call_command("importa_catalogo_qcp", stdout=io.StringIO())

    def setUp(self):
        self.testata = Testata.objects.create(job="26026")
        self.piano = QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPA")
        for indice, nome in enumerate(("B&R", "LNG CANADA", "A.I.")):
            QualityControlPlanAgency.objects.create(piano=self.piano, nome=nome, ordine=indice)
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        self.cartella = Path(cartella.name)

    # -- Aiuti --

    def _seed(self, sezioni=None, *argomenti, percorso=None, job="26026"):
        if percorso is None:
            percorso = self.cartella / f"corpo_{len(list(self.cartella.iterdir()))}.json"
            percorso.write_text(json.dumps(sezioni), encoding="utf-8")
        uscita = io.StringIO()
        call_command(
            "seed_corpo_qcp", "--job", job, "--file", str(percorso), *argomenti, stdout=uscita
        )
        return uscita.getvalue()

    @staticmethod
    def _file_vero():
        return json.loads(CORPO_26026.read_text(encoding="utf-8"))

    @staticmethod
    def _sezione(*steps, titolo="Documents Approval"):
        return {"titolo": titolo, "steps": list(steps)}

    @staticmethod
    def _step(codice="KOM", punti=None, extent=1.0, remarks=None):
        if punti is None:
            punti = {"B&R": "H", "LNG CANADA": "R", "A.I.": "-"}
        return {"codice": codice, "extent": extent, "punti": punti, "remarks": remarks}

    def _steps(self):
        return QualityControlPlanStep.objects.filter(sezione__piano=self.piano).order_by(
            "sezione__ordine", "ordine"
        )

    def _codici(self):
        """Per sezione, il codice di ogni step (la descrizione se è scritto a mano)."""
        return [
            (
                sezione.titolo,
                [
                    step.attivita.codice if step.attivita else step.descrizione
                    for step in sezione.steps.select_related("attivita").order_by("ordine")
                ],
            )
            for sezione in self.piano.sections.order_by("ordine")
        ]

    # -- File vero --

    def test_punti_che_il_modello_non_rappresenta_fermano_il_seed(self):
        sezioni = [
            self._sezione(self._step(punti={"B&R": "H/Q", "LNG CANADA": "-/W", "A.I.": "-"})),
            self._sezione(self._step(punti={"B&R": "H/Q", "LNG CANADA": "R"}), titolo="B"),
        ]

        with self.assertRaises(CommandError) as errore:
            self._seed(sezioni)

        messaggio = str(errore.exception)
        self.assertIn(
            '"H/Q" (2 volte, la prima in sezione 1 "Documents Approval", step 1, ente "B&R")',
            messaggio,
        )
        self.assertIn('"-/W" (1 volta', messaggio)
        self.assertIn("nessuna modifica salvata", messaggio)
        self.assertFalse(self.piano.sections.exists())

    def test_il_seed_crea_34_sezioni_e_224_step_nell_ordine_del_file(self):
        sezioni = self._file_vero()

        uscita = self._seed(sezioni)

        attesi = [(s["titolo"], [st["codice"].strip() for st in s["steps"]]) for s in sezioni]
        self.assertEqual(len(attesi), 34)
        self.assertEqual(self._codici(), attesi)
        corpo = serialize_corpo(self.piano)
        self.assertEqual(corpo["totale_step"], 224)
        self.assertEqual(
            [step["numero"] for s in corpo["sezioni"] for step in s["steps"]], list(range(1, 225))
        )
        self.assertIn("sezioni create 34, step creati 224 (di cui 1 scritto a mano)", uscita)
        # Extent e remarks come nel file, remarks testuali comprese; snapshot e
        # riferimento come li inserirebbe l'interfaccia.
        dal_file = [step for s in sezioni for step in s["steps"]]
        steps = list(self._steps().select_related("attivita"))
        self.assertEqual([s.remarks for s in steps], [d["remarks"] or "" for d in dal_file])
        self.assertEqual([float(s.extent) for s in steps], [d["extent"] for d in dal_file])
        for step in steps:
            if step.attivita:
                self.assertEqual(step.descrizione, step.attivita.descrizione)
                self.assertEqual(
                    step.reference_doc, step.attivita.risolvi_reference_doc(self.piano)
                )

    def test_ogni_step_ha_un_punto_per_ogni_ente_del_piano(self):
        sezioni = self._file_vero()

        self._seed(sezioni)

        dal_file = [step for s in sezioni for step in s["steps"]]
        trovati = [
            {punto.agency.nome: punto.punto for punto in step.punti.all()}
            for step in self._steps().prefetch_related("punti__agency")
        ]
        # Come nel file, stati multipli e "(*)" compresi; i null restano "-".
        attesi = [{ente: v or "-" for ente, v in d["punti"].items()} for d in dal_file]
        self.assertEqual(trovati, attesi)
        self.assertLessEqual({"R/SW", "F/SW", "(*)"}, {v for p in trovati for v in p.values()})
        self.assertEqual(self.piano.agencies.count(), 3)

    # -- Casi dei dati reali --

    def test_codice_assente_dal_catalogo_diventa_step_manuale_segnalato(self):
        uscita = self._seed([self._sezione(self._step("Preservation  procedure"), self._step())])

        manuale, kom = self.piano.sections.get().steps.order_by("ordine")
        self.assertIsNone(manuale.attivita_id)
        self.assertEqual(manuale.descrizione, "Preservation  procedure")
        self.assertEqual(manuale.punti.count(), 3)
        self.assertEqual(kom.attivita.codice, "KOM")
        self.assertIn(
            '"Preservation  procedure" non è nel catalogo (nel catalogo c\'è '
            '"Preservation procedure", con spazi diversi); creato come step manuale',
            uscita,
        )
        self.assertIn("step creati 2 (di cui 1 scritto a mano)", uscita)

    def test_ente_non_presente_sul_piano_si_salta_senza_crearlo(self):
        punti = {"B&R": "H", "TÜV": "W", "Lng Canada": "R"}

        uscita = self._seed([self._sezione(self._step(punti=punti))])

        step = self._steps().get()
        self.assertEqual(
            {p.agency.nome: p.punto for p in step.punti.select_related("agency")},
            {"B&R": "H", "LNG CANADA": "-", "A.I.": "-"},
        )
        self.assertEqual(
            list(self.piano.agencies.order_by("ordine").values_list("nome", flat=True)),
            ["B&R", "LNG CANADA", "A.I."],
        )
        self.assertIn('Ente "TÜV" non presente sul piano, punti saltati: 1', uscita)
        self.assertIn(
            'Ente "Lng Canada" non presente sul piano (sul piano c\'è "LNG CANADA")', uscita
        )
        self.assertIn("punti d'intervento impostati 1.", uscita)

    def test_codice_in_piu_capitoli_usa_il_primo_e_lo_segnala(self):
        uscita = self._seed([self._sezione(self._step("Pickling and passivation"))])

        self.assertEqual(self._steps().select_related("attivita").get().attivita.capitolo, "NDE")
        self.assertIn(
            '"Pickling and passivation" è nel catalogo in 2 capitoli (NDE, ISPEZIONI FINALI)',
            uscita,
        )

    def test_punto_non_indicato_resta_trattino_e_si_segnala(self):
        punti = {"B&R": "H", "LNG CANADA": "H", "A.I.": None}

        uscita = self._seed([self._sezione(self._step(punti=punti))])

        self.assertEqual(self._steps().get().punti.get(agency__nome="A.I.").punto, "-")
        self.assertIn('ente "A.I.": punto non indicato nel file (null), resta "-"', uscita)

    # -- Dry-run, idempotenza, reset --

    def test_dry_run_non_scrive_niente(self):
        sezioni = [self._sezione(self._step(), self._step("Preservation  procedure"))]

        uscita = self._seed(sezioni, "--dry-run")

        self.assertIn("[dry-run]", uscita)
        self.assertIn("sezioni create 1, step creati 2", uscita)
        self.assertIn("non è nel catalogo", uscita)  # le anomalie sono quelle vere
        self.assertFalse(QualityControlPlanSection.objects.exists())
        self.assertFalse(QualityControlPlanStep.objects.exists())

    def test_seconda_esecuzione_senza_reset_si_ferma_e_non_cambia_nulla(self):
        sezioni = [self._sezione(self._step(), self._step("PIM"))]
        self._seed(sezioni)
        prima = list(QualityControlPlanStep.objects.order_by("pk").values_list("pk", "ordine"))

        with self.assertRaisesMessage(CommandError, "Usa --reset"):
            self._seed(sezioni)

        self.assertEqual(
            list(QualityControlPlanStep.objects.order_by("pk").values_list("pk", "ordine")), prima
        )
        self.assertEqual(self.piano.sections.count(), 1)

    def test_il_reset_chiede_conferma_e_senza_un_si_non_tocca_nulla(self):
        sezioni = [self._sezione(self._step())]
        self._seed(sezioni)
        vecchio = QualityControlPlanStep.objects.get().pk

        with (
            patch("builtins.input", return_value="no") as domanda,
            self.assertRaisesMessage(CommandError, "Reset annullato"),
        ):
            self._seed(sezioni, "--reset")
        self.assertIn("(sezioni: 1, step: 1)", domanda.call_args.args[0])
        self.assertEqual(QualityControlPlanStep.objects.get().pk, vecchio)

        with patch("builtins.input", return_value="si"):
            uscita = self._seed(sezioni, "--reset")
        self.assertNotEqual(QualityControlPlanStep.objects.get().pk, vecchio)
        self.assertIn("Eliminati prima: sezioni 1, step 1.", uscita)

    def test_reset_con_no_input_non_chiede(self):
        self._seed([self._sezione(self._step())])

        with patch("builtins.input") as domanda:
            self._seed([self._sezione(self._step("PIM"), titolo="Nuova")], "--reset", "--no-input")

        domanda.assert_not_called()
        self.assertEqual(self._codici(), [("Nuova", ["PIM"])])

    # -- Piano e file non adatti --

    def test_commessa_senza_piano_o_con_piu_piani_si_ferma(self):
        sezioni = [self._sezione(self._step())]
        Testata.objects.create(job="26027")

        with self.assertRaisesMessage(CommandError, "non ha un Quality Control Plan"):
            self._seed(sezioni, job="26027")
        QualityControlPlan.objects.create(testata=self.testata, titolo="26026-QCPB")
        with self.assertRaisesMessage(CommandError, "ha 2 piani"):
            self._seed(sezioni)

        self.assertEqual(QualityControlPlan.objects.count(), 2)
        self.assertFalse(QualityControlPlanSection.objects.exists())

    def test_un_errore_a_meta_annulla_tutto(self):
        sezioni = [self._sezione(self._step()), self._sezione(self._step(extent=5), titolo="B")]

        with self.assertRaisesMessage(CommandError, 'sezione 2 "B", step 1: Extent non valido'):
            self._seed(sezioni)

        self.assertFalse(QualityControlPlanSection.objects.exists())


# ─────────────────────────────────────────────
# AUDIT QCP: coerenza con il documento originale (commesse 26026 e 26004)
# ─────────────────────────────────────────────
# I numeri dei test sono quelli dei punti dell'audit (vedi AUDIT-QCP.md). I test
# marcati ``expectedFailure`` descrivono il comportamento atteso dove oggi il
# sistema diverge dal documento: passano finché la difformità resta, e il giorno
# in cui viene corretta falliscono come "unexpected success", per ricordare di
# togliere il decoratore.

_SEDE_26026 = "Valbrembo - Bergamo (Italy)"
_ENTI_26026 = ["B&R", "LNG CANADA", "A.I."]
_COPERTINA_26026 = {
    "titolo": "26026-QCPA",
    "project": "LNG CANADA Project",
    "owner": "LNG CANADA DEVELOPMENT INC.",
    "purchaser": "LNG CANADA DEVELOPMENT INC.",
    "po_no": "4514428987",
    "items": [{"item_no": "1E-1201", "descrizione": "GAS COOLER"}],
    "descrizione_item": "GAS COOLER",
    "location": _SEDE_26026,
    # Il modulo manda la data in ISO; "25/08/2026" del documento: vedi test dedicato.
    "data": "2026-08-25",
    "prepared_by": "Federico Baldin",
    "sheet": "1",
    "rev_no": 0,
    "dwg_base": "01",
    "serial_base": "A",
    "foglio_dwg": "1",
    "mdmt": "-25",
    "asme_stamp": True,
    "national_board": True,
    "lethal_service": False,
    "h2s_service": False,
    "notification_advice_time": "15 CALENDAR DAYS FOR W, H & F POINTS",
    "codes": ["ASME VIII Div.1 Ed 2025", 'TEMA "R" 11th Edition', "API 660 9TH Ed.2015"],
    "specs": ["Req. nr. L001-00000-MS-7303-1002", "and all specs listed in above req."],
    # Non alfabetico di proposito: "A.I." in ordine alfabetico verrebbe primo.
    "agencies": _ENTI_26026,
}


def _piano_26026(user, **modifiche):
    """Il piano della commessa 26026 con la copertina del documento originale."""
    Testata.objects.get_or_create(job="26026")
    Stabilimento.objects.get_or_create(nome=_SEDE_26026)
    return create_piano("26026", {**_COPERTINA_26026, **modifiche}, user)


def _url_pagina_piano(piano):
    return f"/commesse/{piano.testata_id}/quality-control-plan/{piano.pk}/"


def _copertina(html):
    """Solo la testata della pagina, copertina compresa: senza corpo né script."""
    return html[html.index('<header class="qp-testata"') : html.index('<div class="qp-corpo')]


class AuditCopertinaQCPTests(TestCase):
    """Audit, parti 1 e 4: la copertina delle commesse 26026 e 26004."""

    def setUp(self):
        self.writer = User.objects.create_user(
            "audit_copertina", "audit-copertina@brembanarolle.com", "pw", permesso=Permesso.WRITING
        )
        self.client = Client()
        self.client.force_login(self.writer)

    @staticmethod
    def _ricarica(piano):
        """Il piano come lo restituisce il sistema, riletto dal database."""
        return serialize_piano(get_piano(piano.testata_id, piano.pk))

    def _pagina(self, piano):
        risposta = self.client.get(_url_pagina_piano(piano))
        self.assertEqual(risposta.status_code, 200)
        return risposta.content.decode()

    # -- Parte 1: commessa 26026 --

    def test_1_copertina_26026_persistita_e_restituita_dall_api(self):
        Testata.objects.create(job="26026")
        Stabilimento.objects.create(nome=_SEDE_26026)
        url = "/api/commesse/26026/quality-control-plan/"

        creato = self.client.post(
            url, json.dumps(_COPERTINA_26026), content_type="application/json"
        )

        self.assertEqual(creato.status_code, 201)
        (riletto,) = self.client.get(url).json()["quality_control_plans"]
        self.assertEqual(riletto, creato.json()["data"])
        attesi = {
            "job_no": "26026",
            "project": "LNG CANADA Project",
            "owner": "LNG CANADA DEVELOPMENT INC.",
            "purchaser": "LNG CANADA DEVELOPMENT INC.",
            "po_no": "4514428987",
            "items": [{"item_no": "1E-1201", "descrizione": "GAS COOLER"}],
            "descrizione_item": "GAS COOLER",
            "location": _SEDE_26026,
            "data": "2026-08-25",
            "prepared_by": "Federico Baldin",
            "sheet": "1",
            "rev_no": 0,
            "dwg_base": "01",
            "serial_base": "A",
            "foglio_dwg": "1",
            "mdmt": "-25",
            "mdmt_display": "-25 °C",
            "asme_stamp_label": "REQUIRED",
            "national_board_label": "REQUIRED",
            "lethal_service_label": "NOT REQUIRED",
            "h2s_service_label": "NOT REQUIRED",
            "notification_advice_time": "15 CALENDAR DAYS FOR W, H & F POINTS",
            "codes": ["ASME VIII Div.1 Ed 2025", 'TEMA "R" 11th Edition', "API 660 9TH Ed.2015"],
            "specs": ["Req. nr. L001-00000-MS-7303-1002", "and all specs listed in above req."],
            "agencies": ["B&R", "LNG CANADA", "A.I."],
        }
        for campo, valore in attesi.items():
            with self.subTest(campo=campo):
                self.assertEqual(riletto[campo], valore)

    @expectedFailure
    def test_1_il_vendor_e_quello_del_documento(self):
        # Difformità: il vendor è la costante VENDOR ("Brembana & Rolle"), non una
        # colonna; il valore mandato dal client si ignora. Il documento dice "B&R".
        piano = _piano_26026(self.writer, vendor="B&R")

        self.assertEqual(self._ricarica(piano)["vendor"], "B&R")

    @expectedFailure
    def test_1_la_data_nel_formato_del_documento_non_si_perde_in_silenzio(self):
        # Difformità: _parse_date accetta solo ISO e trasforma "25/08/2026" in None
        # senza errore, così il piano nasce senza data. Andrebbe letta o rifiutata.
        try:
            piano = _piano_26026(self.writer, data="25/08/2026")
        except ValueError:
            return
        piano.refresh_from_db()
        self.assertEqual(piano.data, date(2026, 8, 25))

    def test_1_1_numerazione_calcolata(self):
        dati = self._ricarica(_piano_26026(self.writer))

        self.assertEqual(
            (dati["doc_no"], dati["dwg_no"], dati["serial_no"]),
            ("26026-01-QCPA", "26026-01-EGA1", "26026-01-SNA"),
        )

    def test_1_2_il_serial_base_cambia_doc_e_serial_ma_non_il_dwg(self):
        piano = _piano_26026(self.writer)
        piano.serial_base = "B"
        piano.save()

        dati = self._ricarica(piano)

        self.assertEqual(
            (dati["doc_no"], dati["dwg_no"], dati["serial_no"]),
            ("26026-01-QCPB", "26026-01-EGA1", "26026-01-SNB"),
        )

    def test_1_3_componente_mancante_numero_vuoto_mai_malformato(self):
        piano = _piano_26026(self.writer, serial_base="")

        dati = self._ricarica(piano)
        self.assertEqual((dati["doc_no"], dati["serial_no"]), ("", ""))
        self.assertEqual(dati["dwg_no"], "26026-01-EGA1")  # dipende dal foglio, non dal serial
        html = self._pagina(piano)
        # Il titolo della copertina ripiega sul titolo del piano.
        self.assertIn('id="cover-title">26026-QCPA</h1>', html)
        for malformato in ("26026--", "26026-01-QCP<", "26026-01-SN<"):
            with self.subTest(malformato=malformato):
                self.assertNotIn(malformato, html)

        piano.dwg_base = "  "
        piano.save()

        dati = self._ricarica(piano)
        self.assertEqual((dati["doc_no"], dati["dwg_no"], dati["serial_no"]), ("", "", ""))

    def test_1_4_doc_no_scritto_a_mano_vince_sul_calcolato(self):
        piano = _piano_26026(self.writer, doc_no="26026-QCP-SPECIALE")

        dati = self._ricarica(piano)

        self.assertEqual(dati["doc_no"], "26026-QCP-SPECIALE")
        self.assertEqual(dati["doc_no_calcolato"], "26026-01-QCPA")
        self.assertIn('id="cover-title">26026-QCP-SPECIALE</h1>', self._pagina(piano))
        # Vince anche nel riferimento documentale "campo_piano" di "Inspections & tests plan".
        itp = AttivitaQCP(reference_doc_tipo="campo_piano", reference_doc_valore="doc_no")
        self.assertEqual(itp.risolvi_reference_doc(piano), "26026-QCP-SPECIALE")

    def test_1_5_ordine_degli_enti_stabile_dopo_salvataggio_e_ricarica(self):
        piano = _piano_26026(self.writer)
        piano.save()

        for _ in range(2):
            self.assertEqual(self._ricarica(piano)["agencies"], _ENTI_26026)
        self.assertEqual(
            list(piano.agencies.values_list("nome", "ordine")),
            [("B&R", 0), ("LNG CANADA", 1), ("A.I.", 2)],
        )
        self.assertEqual([e["nome"] for e in serialize_corpo(piano)["enti"]], _ENTI_26026)
        self.assertRegex(
            self._pagina(piano),
            r'(?s)cv-ente-n">1</span>B&amp;R</li>.*cv-ente-n">2</span>LNG CANADA</li>'
            r'.*cv-ente-n">3</span>A\.I\.</li>',
        )

    def test_1_6_la_copertina_rende_tutti_i_campi_senza_none_ne_vuoti(self):
        piano = _piano_26026(self.writer)

        copertina = _copertina(self._pagina(piano))

        for testo in (
            "LNG CANADA Project",
            "4514428987",
            '<span class="cv-mono qp-item">1E-1201</span>',
            '<span class="cv-mono qp-item-no">1E-1201</span>',
            '<span class="cv-mono qp-item-desc">GAS COOLER</span>',
            _SEDE_26026,
            format_display_date(date(2026, 8, 25)),
            "Federico Baldin",
            "Sheet 1",
            '<span class="cv-rev">Rev 0</span>',
            "26026-01-QCPA",
            "26026-01-EGA1",
            "26026-01-SNA",
            '-25 <span class="qp-unita">°C</span>',
            "15 CALENDAR DAYS FOR W, H &amp; F POINTS",
            "ASME VIII Div.1 Ed 2025",
            "TEMA &quot;R&quot; 11th Edition",
            "API 660 9TH Ed.2015",
            "Req. nr. L001-00000-MS-7303-1002",
            "and all specs listed in above req.",
        ):
            with self.subTest(testo=testo):
                self.assertIn(testo, copertina)
        self.assertEqual(copertina.count("LNG CANADA DEVELOPMENT INC."), 2)  # owner e purchaser
        # ASME stamp e National board richiesti, Lethal e H2S no.
        self.assertEqual(
            re.findall(r'<li class="qp-req">([^<]*)</li>', copertina),
            ["ASME stamp", "National board"],
        )
        self.assertNotIn("None", copertina)
        # Nessun campo vuoto (il trattino grigio) e nessun "Nessun … inserito".
        self.assertEqual(re.findall(r'class="[^"]*\bcv-val\b[^"]*">\s*</', copertina), [])
        self.assertNotIn("cv-empty", copertina)

    # -- Parte 4: commessa 26004, configurazione diversa --

    _ENTI_26004 = ["B&R", "PHILLIPS 66", "A.I. (LRQA)"]

    def _piano_26004(self, **modifiche):
        Testata.objects.get_or_create(job="26004")
        dati = {
            "titolo": "26004-QCPA",
            "items": ["ITEM 1"],
            "owner": "",
            "dwg_base": "01",
            "serial_base": "A",
            "foglio_dwg": "1",
            "codes": [
                "ASME VIII Div.1 Ed 2025",
                "ASME II/A Ed 2021",
                "ASME IX Ed 2021",
                'TEMA "R" 11th Edition',
            ],
            "agencies": self._ENTI_26004,
            **modifiche,
        }
        return create_piano("26004", dati, self.writer)

    def test_4_1_quattro_codici_applicabili_e_tre_enti(self):
        dati = self._ricarica(self._piano_26004())

        self.assertEqual(len(dati["codes"]), 4)
        self.assertEqual(dati["codes"][3], 'TEMA "R" 11th Edition')
        self.assertEqual(dati["agencies"], self._ENTI_26004)

    def test_4_2_ente_con_parentesi_e_punti(self):
        piano = self._piano_26004()
        lrqa = piano.agencies.get(nome="A.I. (LRQA)")
        # Il seed abbina gli enti per nome: anche questo nome deve tornare.
        semina_corpo(
            piano,
            valida_corpo(
                [
                    {
                        "titolo": "Documents Approval",
                        "steps": [
                            {
                                "codice": "Drawings",
                                "extent": 1.0,
                                "punti": {"B&R": "H", "PHILLIPS 66": "A", "A.I. (LRQA)": "R/SW"},
                                "remarks": None,
                            }
                        ],
                    }
                ]
            ),
        )

        self.assertEqual(self._ricarica(piano)["agencies"], self._ENTI_26004)
        corpo = serialize_corpo(piano)
        self.assertEqual([e["nome"] for e in corpo["enti"]], self._ENTI_26004)
        punto = corpo["sezioni"][0]["steps"][0]["punti"][2]
        self.assertEqual(
            (punto["agency_id"], punto["punto"], punto["firma"]), (lrqa.pk, "R/SW", None)
        )
        html = self._pagina(piano)
        self.assertIn('cv-ente-n">3</span>A.I. (LRQA)</li>', html)
        self.assertIn('<span class="ce-ente-nome">A.I. (LRQA)</span>', html)
        self.assertIn('data-ente-nome="A.I. (LRQA)" data-punto="R/SW"', html)

    def test_4_3_owner_vuoto_o_trattino_non_stampa_none(self):
        for owner in ("", None, "-"):
            with self.subTest(owner=owner):
                piano = self._piano_26004(owner=owner)

                self.assertEqual(self._ricarica(piano)["owner"], owner or "")
                copertina = _copertina(self._pagina(piano))
                self.assertNotIn("None", copertina)
                # Vuoto: elemento vuoto, che la pagina mostra come trattino grigio.
                self.assertIn(f'<dt>Owner</dt><dd class="cv-val">{owner or ""}</dd>', copertina)

    @expectedFailure
    def test_4_4_tre_revisioni_con_firme_prepared_checked_approved(self):
        # Difformità: Rev 0 F. Baldin / P. Facheris / F. Baldin, Rev 1 e 2 con
        # F. Crotta come checked. Il piano ha un solo rev_no e un solo prepared_by:
        # nessuno storico delle revisioni, nessuna firma checked / approved.
        modelli = [QualityControlPlan] + [
            relazione.related_model for relazione in QualityControlPlan._meta.related_objects
        ]
        con_firme = [
            modello
            for modello in modelli
            if {"checked_by", "approved_by"} <= {campo.name for campo in modello._meta.get_fields()}
        ]
        self.assertTrue(con_firme, "Nessun modello rappresenta le firme di una revisione.")


class AuditCatalogoQCPTests(TestCase):
    """Audit, parte 2: il catalogo vero, importato dal file del repository."""

    @classmethod
    def setUpTestData(cls):
        call_command("importa_catalogo_qcp", stdout=io.StringIO())
        testata = Testata.objects.create(job="26026")
        cls.piano = QualityControlPlan.objects.create(
            testata=testata, titolo="26026-QCPA", dwg_base="01", serial_base="A", foglio_dwg="1"
        )

    @staticmethod
    def _conta(campo):
        return dict(AttivitaQCP.objects.order_by().values_list(campo).annotate(n=Count("id")))

    def test_2_1_2_2_2_3_attivita_divisioni_e_capitoli(self):
        self.assertEqual(AttivitaQCP.objects.count(), 291)
        self.assertEqual(self._conta("divisione"), {"Gen": 88, "Div.1": 197, "Div.2": 6})
        self.assertEqual(len(self._conta("capitolo")), 10)
        self.assertEqual(len(capitoli_attivi_qcp()), 10)

    def test_2_4_codici_ripetuti_in_capitoli_diversi_convivono(self):
        ripetuti = {codice: n for codice, n in self._conta("codice").items() if n > 1}

        self.assertEqual(ripetuti, {"Final documentation index": 2, "Pickling and passivation": 2})
        self.assertEqual(
            set(
                AttivitaQCP.objects.filter(codice="Pickling and passivation").values_list(
                    "capitolo", flat=True
                )
            ),
            {"NDE", "ISPEZIONI FINALI"},
        )
        # Il brief cita anche "VT-Complete base welding" fra i ripetuti: nel file
        # è una riga sola (la riga fit-up ha ora il suo codice).
        self.assertEqual(AttivitaQCP.objects.filter(codice="VT-Complete base welding").count(), 1)

    def test_2_5_riferimenti_documentali_risolti_sul_job(self):
        casi = (
            ("PT-Complete base welding", "suffisso_job", "/PT", "26026/PT"),
            ("Complete equipment in pressure test", "suffisso_job", "-QHT1", "26026-QHT1"),
            ("Welders & welding operators", "statico", "ASME IX QW350/360", "ASME IX QW350/360"),
            ("VT & DC-Complete bundle", "composito", "/VT |/DC", "26026/VT 26026/DC"),
            (
                "Welding Consumables 3.1/2.2-VT,DC & marking check",
                "composito",
                "BCI-006-CWC |-TMRS",
                "BCI-006-CWC 26026-TMRS",
            ),
            ("Drawings", "campo_piano", "dwg_no", "26026-01-EGA1"),
            ("Inspections & tests plan", "campo_piano", "doc_no", "26026-01-QCPA"),
            ("Calculations", "da_proc", "PROC!H17", ""),
        )
        for codice, tipo, valore, atteso in casi:
            with self.subTest(codice=codice):
                attivita = AttivitaQCP.objects.get(codice=codice)
                self.assertEqual(
                    (attivita.reference_doc_tipo, attivita.reference_doc_valore), (tipo, valore)
                )
                self.assertEqual(attivita.risolvi_reference_doc(self.piano), atteso)

    def test_2_5_conteggio_per_tipo_e_nessun_riferimento_malformato(self):
        self.assertEqual(
            self._conta("reference_doc_tipo"),
            {"suffisso_job": 192, "statico": 84, "composito": 7, "da_proc": 6, "campo_piano": 2},
        )
        for attivita in AttivitaQCP.objects.all():
            risolto = attivita.risolvi_reference_doc(self.piano)
            with self.subTest(attivita=str(attivita)):
                self.assertNotIn("|", risolto)
                self.assertNotIn("None", risolto)
                if attivita.reference_doc_tipo == "da_proc":
                    self.assertEqual(risolto, "")
                elif attivita.reference_doc_tipo in ("suffisso_job", "campo_piano"):
                    self.assertTrue(risolto.startswith("26026"), risolto)

    def test_2_5_il_riferimento_campo_piano_resta_quello_dell_inserimento(self):
        # Comportamento attuale, da decidere: il riferimento si risolve quando lo
        # step entra (snapshot). Un Dwg n. completato dopo non arriva agli step.
        piano = QualityControlPlan.objects.create(testata_id="26026", titolo="26026-QCPB")
        step = aggiungi_step(
            crea_sezione(piano, "Documents Approval"),
            attivita_id=AttivitaQCP.objects.get(codice="Drawings").pk,
        )
        self.assertEqual(step.reference_doc, "")

        piano.dwg_base, piano.foglio_dwg = "01", "1"
        piano.save()

        step.refresh_from_db()
        self.assertEqual(step.reference_doc, "")
        self.assertEqual(step.attivita.risolvi_reference_doc(piano), "26026-01-EGA1")

    def test_2_6_reimportare_non_duplica(self):
        uscita = io.StringIO()

        call_command("importa_catalogo_qcp", stdout=uscita)

        self.assertEqual(AttivitaQCP.objects.count(), 291)
        self.assertIn("Creati 0, aggiornati 0, invariati 291.", uscita.getvalue())


# Query della pagina di un piano, qualunque sia il numero di sezioni, di step e
# di firme: sessione e utente (2), commessa (1), piano con item, codici, spec ed
# enti (5), sezioni, step, punti e firme valide (4), capitoli del catalogo (1).
_QUERY_PAGINA_PIANO = 13


class AuditCorpo26026Tests(TestCase):
    """Audit, parti 3 e 5: il corpo reale della 26026 (34 sezioni, 224 step)."""

    @classmethod
    def setUpTestData(cls):
        call_command("importa_catalogo_qcp", stdout=io.StringIO())
        cls.writer = _dai_firma(
            User.objects.create_user(
                "audit_corpo", "audit-corpo@brembanarolle.com", "pw", permesso=Permesso.WRITING
            )
        )
        cls.piano = _piano_26026(cls.writer)
        cls.file = json.loads(CORPO_26026.read_text(encoding="utf-8"))
        cls.report = semina_corpo(cls.piano, valida_corpo(cls.file))

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.writer)
        self.dal_file = [step for sezione in self.file for step in sezione["steps"]]

    # -- Aiuti --

    def _corpo(self):
        return serialize_corpo(QualityControlPlan.objects.get(pk=self.piano.pk))

    def _steps(self):
        """Gli step nell'ordine del documento."""
        return list(
            QualityControlPlanStep.objects.filter(sezione__piano=self.piano)
            .order_by("sezione__ordine", "ordine")
            .select_related("attivita")
        )

    def _punti(self):
        return QualityControlPlanInterventionPoint.objects.filter(step__sezione__piano=self.piano)

    def _distribuzione(self):
        return Counter(self._punti().values_list("punto", flat=True))

    def _pagina(self, piano=None):
        risposta = self.client.get(_url_pagina_piano(piano or self.piano))
        self.assertEqual(risposta.status_code, 200)
        return risposta.content.decode()

    def _url_api(self, suffisso, piano=None):
        return f"/api/commesse/26026/quality-control-plan/{(piano or self.piano).pk}/{suffisso}"

    # -- Parte 3 --

    def test_3_1_34_sezioni_nell_ordine_del_file(self):
        self.assertEqual(
            list(self.piano.sections.order_by("ordine").values_list("titolo", flat=True)),
            [sezione["titolo"] for sezione in self.file],
        )
        self.assertEqual(len(self.file), 34)

    def test_3_2_224_step_con_i_conteggi_per_sezione_del_file(self):
        corpo = self._corpo()

        self.assertEqual(corpo["totale_step"], 224)
        self.assertEqual(
            [len(sezione["steps"]) for sezione in corpo["sezioni"]],
            [len(sezione["steps"]) for sezione in self.file],
        )
        # Un codice del file non è nel catalogo ("Preservation  procedure", con due
        # spazi): lo step nasce scritto a mano, con la sola descrizione.
        self.assertEqual(self.report["manuali"], 1)
        manuale = QualityControlPlanStep.objects.get(
            sezione__piano=self.piano, attivita__isnull=True
        )
        self.assertEqual(
            (manuale.descrizione, manuale.test_inspection, manuale.reference_doc),
            ("Preservation  procedure", "", ""),
        )

    def test_3_3_numerazione_continua_e_ricalcolata_dopo_una_cancellazione(self):
        corpo = self._corpo()
        prima = [step for sezione in corpo["sezioni"] for step in sezione["steps"]]
        self.assertEqual([step["numero"] for step in prima], list(range(1, 225)))
        self.assertEqual(corpo["sezioni"][1]["steps"][0]["numero"], 18)  # non riparte da 1

        # Via lo step 20, a metà della seconda sezione.
        eliminato, successivo = prima[19], prima[20]
        elimina_step(QualityControlPlanStep.objects.get(pk=eliminato["id"]))

        dopo = [step for sezione in self._corpo()["sezioni"] for step in sezione["steps"]]
        self.assertEqual([step["numero"] for step in dopo], list(range(1, 224)))
        self.assertEqual(next(s["numero"] for s in dopo if s["id"] == successivo["id"]), 20)
        sezione = QualityControlPlanStep.objects.get(pk=successivo["id"]).sezione
        self.assertEqual(list(sezione.steps.values_list("ordine", flat=True)), list(range(8)))

    def test_3_4_snapshot_dal_catalogo_e_riferimento_risolto(self):
        def steps_di(codice):
            return QualityControlPlanStep.objects.filter(
                sezione__piano=self.piano, attivita__codice=codice
            )

        calcoli = steps_di("Calculations").get()
        self.assertEqual(
            (
                calcoli.descrizione,
                calcoli.test_inspection,
                calcoli.acceptance_criteria,
                calcoli.documento_richiesto,
            ),
            ("Calculations", "Approval", "Contractual doc.s & code", "Approval stamp"),
        )
        # "Calculations" è da_proc: il riferimento resta vuoto (non implementato).
        self.assertEqual(calcoli.reference_doc, "")
        for codice, atteso in (
            ("Manufacturing & NDE procedures", "26026-QNDE"),
            ("Drawings", "26026-01-EGA1"),
        ):
            with self.subTest(codice=codice):
                self.assertEqual(
                    set(steps_di(codice).values_list("reference_doc", flat=True)), {atteso}
                )
        # Impatto sul documento reale: 8 step su 224 escono con Reference doc. vuoto.
        da_proc = QualityControlPlanStep.objects.filter(
            sezione__piano=self.piano, attivita__reference_doc_tipo="da_proc"
        )
        self.assertEqual(da_proc.count(), 8)
        self.assertEqual(set(da_proc.values_list("reference_doc", flat=True)), {""})
        # Tutti gli altri: snapshot uguale al catalogo, riferimento risolto sul piano.
        for step in self._steps():
            if step.attivita is None:
                continue
            with self.subTest(step=step.descrizione):
                for campo in (
                    "descrizione",
                    "test_inspection",
                    "acceptance_criteria",
                    "documento_richiesto",
                    "tecnica",
                ):
                    self.assertEqual(getattr(step, campo), getattr(step.attivita, campo))
                self.assertEqual(
                    step.reference_doc, step.attivita.risolvi_reference_doc(self.piano)
                )

    def test_3_5_un_punto_per_ciascuno_dei_3_enti_su_ogni_step(self):
        per_step = (
            self._punti()
            .order_by()
            .values("step")
            .annotate(n=Count("id"), enti=Count("agency", distinct=True))
        )

        self.assertEqual(len(per_step), 224)
        self.assertEqual({(riga["n"], riga["enti"]) for riga in per_step}, {(3, 3)})
        self.assertFalse(
            self._punti().exclude(agency__piano=self.piano).exists(),
            "Un punto riferito a un ente di un altro piano.",
        )

    def test_3_6_punti_composti_salvati_come_nel_file(self):
        attesa = {
            "H": 301,
            "-": 138,
            "W": 77,
            "R": 70,
            "R/SW": 41,
            "A": 17,
            "F/SW": 16,
            "(*)": 6,
            "SW": 4,
        }
        self.assertEqual(
            Counter(v for step in self.dal_file for v in step["punti"].values()),
            Counter({**attesa, None: 2}),
        )

        distribuzione = self._distribuzione()

        composti = {punto: distribuzione[punto] for punto in ("R/SW", "F/SW", "(*)")}
        self.assertEqual(composti, {"R/SW": 41, "F/SW": 16, "(*)": 6})
        self.assertEqual(sum(composti.values()), 63)
        # Uno per uno, sullo step e sull'ente giusti; i due null diventano "-".
        trovati = [
            {punto.agency.nome: punto.punto for punto in step.punti.all()}
            for step in QualityControlPlanStep.objects.filter(sezione__piano=self.piano)
            .order_by("sezione__ordine", "ordine")
            .prefetch_related("punti__agency")
        ]
        self.assertEqual(
            trovati,
            [{ente: v or "-" for ente, v in step["punti"].items()} for step in self.dal_file],
        )
        # La pagina li disegna così come sono (solo le celle, non il menu dei punti).
        html = self._pagina()
        for punto, volte in attesa.items():
            if punto != "-":
                with self.subTest(punto=punto):
                    celle = re.findall(
                        rf'data-ente-nome="[^"]*" data-punto="{re.escape(punto)}"', html
                    )
                    self.assertEqual(len(celle), volte)

    @expectedFailure
    def test_3_6_le_celle_vuote_del_file_restano_distinte_da_non_coinvolto(self):
        # Difformità: le 2 celle vuote del documento (step 80 e 106, "DC-Complete
        # equipment", ente A.I.) diventano "-" (non coinvolto): 140 trattini invece
        # di 138 più 2 vuoti. Il modello non ha un valore per "non indicato".
        self.assertEqual(self._distribuzione()["-"], 138)

    def test_3_7_extent_223_al_100_e_uno_al_5_per_cento(self):
        steps = self._steps()

        self.assertEqual(
            Counter(step.extent for step in steps),
            Counter({Decimal("1.000"): 223, Decimal("0.050"): 1}),
        )
        gaskets = steps[24]  # step 25, "Material identification & Receivment inspection"
        self.assertEqual(self.dal_file[24]["extent"], 0.05)
        self.assertEqual(gaskets.extent, Decimal("0.050"))
        serializzato = [s for sez in self._corpo()["sezioni"] for s in sez["steps"]][24]
        self.assertEqual((serializzato["numero"], serializzato["extent"]), (25, 0.05))
        self.assertEqual(extent_in_percentuale(serializzato["extent"]), "5")
        self.assertRegex(
            self._pagina(), rf'(?s)data-id="{gaskets.pk}".*?class="ce-extent-input" value="5"'
        )

    def test_3_8_remarks_numerici_e_testuali_senza_alterazioni(self):
        steps = self._steps()

        self.assertEqual(
            [step.remarks for step in steps], [step["remarks"] or "" for step in self.dal_file]
        )
        self.assertLessEqual(
            {"4", "6", "IF ANY", "* SEE DEDICATED SHEET"}, {step.remarks for step in steps}
        )
        html = self._pagina()
        self.assertEqual(html.count('<span class="ce-testo-val">* SEE DEDICATED SHEET</span>'), 12)
        self.assertEqual(html.count('<span class="ce-testo-val">IF ANY</span>'), 1)

    def test_3_9_modificare_il_catalogo_dopo_non_cambia_gli_step(self):
        campi = (
            "descrizione",
            "test_inspection",
            "reference_doc",
            "acceptance_criteria",
            "documento_richiesto",
            "tecnica",
        )
        steps = QualityControlPlanStep.objects.filter(sezione__piano=self.piano).order_by("pk")
        prima = list(steps.values_list(*campi))

        AttivitaQCP.objects.update(
            descrizione="CAMBIATA",
            test_inspection="CAMBIATO",
            acceptance_criteria="CAMBIATO",
            documento_richiesto="CAMBIATO",
            tecnica="CAMBIATA",
            reference_doc_tipo="statico",
            reference_doc_valore="NUOVO",
        )
        AttivitaQCP.objects.filter(codice="Calculations").update(attivo=False)

        self.assertEqual(list(steps.values_list(*campi)), prima)
        self.assertEqual(steps.count(), 224)

    def test_3_10_un_quarto_ente_aggiunto_e_poi_tolto(self):
        prima = self._distribuzione()
        quarto = QualityControlPlanAgency.objects.create(piano=self.piano, nome="TÜV", ordine=3)

        # Creare l'ente da solo non basta (nessun segnale): i punti arrivano con
        # sincronizza_punti, che l'admin chiama al salvataggio. Nel frattempo la
        # pagina mostra comunque una cella "-" per l'ente.
        self.assertFalse(self._punti().filter(agency=quarto).exists())
        celle = [
            len(step["celle"])
            for sezione in corpo_per_pagina(QualityControlPlan.objects.get(pk=self.piano.pk))[
                "sezioni"
            ]
            for step in sezione["steps"]
        ]
        self.assertEqual(set(celle), {4})

        self.assertEqual(sincronizza_punti(self.piano), {"creati": 224, "rimossi": 0})

        self.assertEqual(self._punti().count(), 224 * 4)
        self.assertEqual(set(self._punti().filter(agency=quarto).values_list("punto")), {("-",)})
        self.assertEqual(
            {
                tuple(p["agency_id"] for p in s["punti"])
                for z in self._corpo()["sezioni"]
                for s in z["steps"]
            },
            {tuple(self.piano.agencies.values_list("pk", flat=True))},
        )

        quarto.delete()

        self.assertEqual(self._punti().count(), 224 * 3)
        self.assertEqual(self._distribuzione(), prima)
        self.assertEqual(sincronizza_punti(self.piano), {"creati": 0, "rimossi": 0})

    # -- Parte 5 --

    def test_5_1_la_pagina_del_piano_non_ha_n_piu_1(self):
        piccolo = _piano_26026(self.writer, titolo="26026-QCPB")
        aggiungi_step(
            crea_sezione(piccolo, "Documents Approval"),
            attivita_id=AttivitaQCP.objects.get(codice="PIM").pk,
        )

        with CaptureQueriesContext(connection) as con_uno_step:
            self._pagina(piccolo)
        with CaptureQueriesContext(connection) as con_224_step:
            html = self._pagina()

        self.assertIn('<span class="qp-sez-conta" id="ce-conteggio">34 · 224 steps</span>', html)
        self.assertEqual(len(con_224_step), len(con_uno_step))
        with self.assertNumQueries(_QUERY_PAGINA_PIANO):
            self._pagina()

    def test_5_3_uno_step_spostato_in_un_altra_sezione(self):
        sezioni = self._corpo()["sezioni"]
        spostato, seguente = sezioni[0]["steps"][4], sezioni[0]["steps"][5]  # step 5 e 6

        risposta = self.client.patch(
            self._url_api(f"corpo/steps/{spostato['id']}/"),
            json.dumps({"sezione": sezioni[2]["id"], "ordine": 0}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        dopo = risposta.json()["data"]["sezioni"]
        self.assertEqual(
            [step["numero"] for sezione in dopo for step in sezione["steps"]], list(range(1, 225))
        )
        self.assertEqual([len(sezione["steps"]) for sezione in dopo[:3]], [16, 9, 8])
        arrivato = dopo[2]["steps"][0]
        self.assertEqual((arrivato["id"], arrivato["numero"]), (spostato["id"], 26))
        self.assertEqual(arrivato["punti"], spostato["punti"])
        self.assertEqual(
            (dopo[0]["steps"][4]["id"], dopo[0]["steps"][4]["numero"]), (seguente["id"], 5)
        )
        for indice in (0, 2):
            self.assertEqual(
                [step["ordine"] for step in dopo[indice]["steps"]],
                list(range(len(dopo[indice]["steps"]))),
            )

    def test_5_4_piano_senza_enti_sezione_senza_step_catalogo_senza_risultati(self):
        piano = QualityControlPlan.objects.create(testata_id="26026", titolo="26026-QCPZ")
        vuota = crea_sezione(piano, "Senza step")
        step = aggiungi_step(
            crea_sezione(piano, "Con uno step"),
            attivita_id=AttivitaQCP.objects.get(codice="PIM").pk,
        )

        self.assertFalse(step.punti.exists())
        self.assertEqual(sincronizza_punti(piano), {"creati": 0, "rimossi": 0})
        html = self._pagina(piano)
        self.assertIn("The plan has no inspection agencies", html)
        self.assertIn('<span class="cv-empty">No agencies</span>', html)
        self.assertRegex(
            html,
            rf'(?s)<li class="ce-sezione" data-id="{vuota.pk}" id="ce-sez-{vuota.pk}">.*?'
            r'<div class="ce-sez-vuota">\s*<p class="ce-sez-vuota-titolo">'
            r"No steps in this section</p>",
        )
        corpo = self.client.get(self._url_api("corpo/", piano))
        self.assertEqual(corpo.status_code, 200)
        self.assertEqual(corpo.json()["enti"], [])
        punti = self.client.patch(
            self._url_api(f"corpo/steps/{step.pk}/punti/", piano),
            json.dumps({"punti": []}),
            content_type="application/json",
        )
        self.assertEqual(punti.status_code, 400)

        for query in ("q=nessuna-attivita-cosi", f"q=zzz&piano={piano.pk}", "capitolo=NESSUNO"):
            with self.subTest(query=query):
                risposta = self.client.get(f"/api/catalogo-qcp/?{query}")
                self.assertEqual(risposta.status_code, 200)
                self.assertEqual(
                    {k: risposta.json()[k] for k in ("attivita", "totale", "troncato")},
                    {"attivita": [], "totale": 0, "troncato": False},
                )

    # -- Firme sul piano reale --

    def test_firme_e_avanzamento_sul_piano_reale(self):
        # Il brief si aspetta 534 punti da firmare su 672 (672 - 138 "-"). Il
        # sistema ne conta 532: le 2 celle vuote del file (step 80 e 106, A.I.)
        # sono salvate come "-" (difformità D3 dell'audit) e restano fuori.
        punti = self._punti()
        self.assertEqual(punti.count(), 672)
        conti = avanzamento(self.piano)
        self.assertEqual((conti["totale"], conti["firmati"], conti["percentuale"]), (532, 0, 0))
        attesi = Counter(
            ente
            for step in self.dal_file
            for ente, v in step["punti"].items()
            if v not in (None, "-")
        )
        self.assertEqual({e["nome"]: e["totale"] for e in conti["enti"]}, dict(attesi))
        self.assertEqual(sum(attesi.values()) + 138 + 2, 672)

        # Firmati i primi 20 step che hanno qualcosa da firmare, un controllo per step.
        steps = [s for s in self._steps() if s.punti.exclude(punto="-").exists()][:20]
        for step in steps:
            firma_step(step, self.writer, EsitoFirma.CONFORME)
        firmati = punti.exclude(punto="-").filter(step__in=steps).count()

        conti = avanzamento(self.piano)
        self.assertEqual((conti["totale"], conti["firmati"]), (532, firmati))
        self.assertEqual(conti["percentuale"], firmati * 100 // 532)
        self.assertEqual(sum(e["firmati"] for e in conti["enti"]), firmati)
        # La pagina e l'elenco piani dicono gli stessi numeri.
        pagina = corpo_per_pagina(QualityControlPlan.objects.get(pk=self.piano.pk))["avanzamento"]
        self.assertEqual((pagina["totale"], pagina["firmati"]), (532, firmati))
        (in_elenco,) = [p for p in list_piani("26026") if p["id"] == self.piano.pk]
        self.assertEqual(
            (in_elenco["punti_da_firmare"], in_elenco["punti_firmati"], in_elenco["percentuale"]),
            (532, firmati, conti["percentuale"]),
        )
        # E le firme non aggiungono query alla pagina.
        with self.assertNumQueries(_QUERY_PAGINA_PIANO):
            self._pagina()


def _dai_firma(utente, nome="firme/prova.png"):
    """L'utente con un'immagine di firma, che serve per firmare.

    Basta il nome del file: firmare non lo legge. I test che servono o
    caricano davvero l'immagine usano ``_png`` e una cartella media temporanea.
    """
    utente.firma = nome
    utente.save(update_fields=["firma"])
    return utente


def _png(dimensione=(160, 48), modo="RGBA", formato="PNG"):
    """Un'immagine vera, come la carica un utente."""
    buffer = io.BytesIO()
    Image.new(modo, dimensione, (20, 40, 90, 0) if modo == "RGBA" else (255, 255, 255)).save(
        buffer, format=formato
    )
    return buffer.getvalue()


class FirmeQCPTests(TestCase):
    """Firme di esecuzione dei punti d'intervento, immagine di firma e avanzamento."""

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        impostazioni = override_settings(MEDIA_ROOT=media.name)
        impostazioni.enable()
        self.addCleanup(impostazioni.disable)

        self.client = Client()
        self.writer = User.objects.create_user(
            "firme_writer",
            "firme-writer@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Mario",
            last_name="Rossi",
        )
        self.altro = User.objects.create_user(
            "firme_altro",
            "firme-altro@brembanarolle.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Anna",
            last_name="Bianchi",
        )
        self.reader = User.objects.create_user(
            "firme_reader", "firme-reader@brembanarolle.com", "pw", permesso=Permesso.READING
        )
        # Per firmare serve l'immagine di firma: ce l'hanno i due che firmano.
        _dai_firma(self.writer)
        _dai_firma(self.altro, "firme/altro.png")
        self.client.force_login(self.writer)
        self.testata = Testata.objects.create(job="26031")
        self.piano = QualityControlPlan.objects.create(testata=self.testata, titolo="26031-QCPA")
        self.enti = [
            QualityControlPlanAgency.objects.create(piano=self.piano, nome=nome, ordine=indice)
            for indice, nome in enumerate(("B&R", "CLIENT", "A.I."))
        ]
        self.sezione = crea_sezione(self.piano, "Documents approval")
        # Primo step: H, W, "-". Secondo: R/SW, "-", "-". Terzo: solo "-".
        self.steps = [
            aggiungi_step(self.sezione, dati={"descrizione": descrizione})
            for descrizione in ("Drawings", "Calculations", "Nothing to sign")
        ]
        for step, valori in zip(self.steps, (("H", "W", "-"), ("R/SW", "-", "-"), ("-",) * 3)):
            for ente, valore in zip(self.enti, valori):
                imposta_punto(step, ente, valore)

    # -- Aiuti --

    def _punto(self, step_indice, ente_indice):
        return QualityControlPlanInterventionPoint.objects.get(
            step=self.steps[step_indice], agency=self.enti[ente_indice]
        )

    def _url(self, suffisso, pk=None, job="26031"):
        return f"/api/commesse/{job}/quality-control-plan/{pk or self.piano.pk}/{suffisso}"

    def _post(self, suffisso, dati, **kwargs):
        return self.client.post(
            self._url(suffisso, **kwargs), json.dumps(dati), content_type="application/json"
        )

    def _profilo(self, **campi):
        # Il modulo del profilo manda tutti i campi: uno che manca si svuota.
        dati = {
            "action": "update_profile",
            "first_name": "Mario",
            "last_name": "Rossi",
            "email": self.writer.email,
        }
        return self.client.post("/profilo/", {**dati, **campi})

    def _pagina(self):
        risposta = self.client.get(f"/commesse/26031/quality-control-plan/{self.piano.pk}/")
        self.assertEqual(risposta.status_code, 200)
        return risposta.content.decode()

    # -- Immagine di firma sul profilo --

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

    def test_upload_rifiuta_un_file_oltre_il_limite(self):
        pesante = _png() + b"\0" * FIRMA_MAX_BYTE

        risposta = self._profilo(firma=SimpleUploadedFile("firma.png", pesante, "image/png"))

        self.assertContains(risposta, "al massimo 1 MB")
        self.writer.refresh_from_db()
        self.assertEqual(self.writer.firma.name, "firme/prova.png")

    def test_l_immagine_di_firma_si_toglie_dal_profilo(self):
        self._profilo(firma=SimpleUploadedFile("firma.png", _png(), "image/png"))

        self._profilo(rimuovi_firma="1")

        self.writer.refresh_from_db()
        self.assertFalse(self.writer.firma)
        pagina = self.client.get("/profilo/").content.decode()
        self.assertIn("per firmare gli step del Quality Control Plan devi caricarne una", pagina)
        self.assertNotIn("firma digitale", pagina.lower())

    # -- Firma, annullamento, storico --

    def test_la_firma_di_un_punto_e_valida_e_aggiorna_l_avanzamento(self):
        self.assertEqual(
            {k: avanzamento(self.piano)[k] for k in ("totale", "firmati", "percentuale")},
            {"totale": 3, "firmati": 0, "percentuale": 0},
        )

        firma = firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME, " ok ")

        self.assertTrue(firma.valida)
        self.assertEqual((firma.utente, firma.esito, firma.note), (self.writer, "conforme", "ok"))
        conti = avanzamento(self.piano)
        self.assertEqual((conti["totale"], conti["firmati"], conti["percentuale"]), (3, 1, 33))
        self.assertEqual(
            [(e["nome"], e["totale"], e["firmati"], e["percentuale"]) for e in conti["enti"]],
            [("B&R", 2, 1, 50), ("CLIENT", 1, 0, 0), ("A.I.", 0, 0, 0)],
        )

    def test_la_firma_su_un_punto_trattino_si_rifiuta(self):
        with self.assertRaisesMessage(ValueError, "non c'è niente da firmare"):
            firma_punto(self._punto(0, 2), self.writer, EsitoFirma.CONFORME)

        self.assertFalse(QualityControlPlanSignature.objects.exists())

    def test_esito_non_valido_si_rifiuta(self):
        with self.assertRaisesMessage(ValueError, "Esito della firma non valido"):
            firma_punto(self._punto(0, 0), self.writer, "ok")

    def test_la_doppia_firma_la_respinge_il_database(self):
        punto = self._punto(0, 0)
        firma_punto(punto, self.writer, EsitoFirma.CONFORME)

        # Dal service: messaggio chiaro.
        with self.assertRaisesMessage(ValueError, "ha già una firma valida"):
            firma_punto(punto, self.altro, EsitoFirma.CONFORME)
        # Scavalcando il service (due richieste in parallelo): il vincolo del database.
        with self.assertRaises(IntegrityError), transaction.atomic():
            QualityControlPlanSignature.objects.create(
                punto=punto, utente=self.altro, esito=EsitoFirma.CONFORME
            )

        self.assertEqual(punto.firme.filter(annullata_il__isnull=True).count(), 1)

    def test_l_annullamento_toglie_la_firma_valida_e_lo_storico_resta(self):
        punto = self._punto(0, 0)
        firma = firma_punto(punto, self.writer, EsitoFirma.CONFORME, "prima")

        annulla_firma(firma, self.altro, "Firmato sullo step sbagliato")

        firma.refresh_from_db()
        self.assertFalse(firma.valida)
        self.assertEqual(
            (firma.annullata_da, firma.motivo_annullo), (self.altro, "Firmato sullo step sbagliato")
        )
        # Esito e note restano quelli registrati.
        self.assertEqual((firma.esito, firma.note), ("conforme", "prima"))
        self.assertEqual(avanzamento(self.piano)["firmati"], 0)
        (voce,) = storico_punto(punto)
        self.assertEqual(
            (voce["valida"], voce["annullata_da"], voce["motivo_annullo"]),
            (False, "Anna Bianchi", "Firmato sullo step sbagliato"),
        )
        with self.assertRaisesMessage(ValueError, "già stata annullata"):
            annulla_firma(firma, self.writer, "ancora")

    def test_l_annullamento_senza_motivo_si_rifiuta(self):
        firma = firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME)

        for motivo in ("", "   ", None):
            with self.subTest(motivo=motivo), self.assertRaisesMessage(ValueError, "motivo"):
                annulla_firma(firma, self.writer, motivo)

        firma.refresh_from_db()
        self.assertTrue(firma.valida)

    def test_dopo_l_annullamento_si_firma_di_nuovo(self):
        punto = self._punto(0, 0)
        annulla_firma(
            firma_punto(punto, self.writer, EsitoFirma.NON_CONFORME), self.writer, "Rifatto"
        )

        nuova = firma_punto(punto, self.writer, EsitoFirma.CONFORME)

        self.assertTrue(nuova.valida)
        storico = storico_punto(punto)
        self.assertEqual(
            [(f["esito"], f["valida"]) for f in storico],
            [("conforme", True), ("non_conforme", False)],
        )
        self.assertEqual(avanzamento(self.piano)["firmati"], 1)

    def test_firma_step_firma_tutti_e_soli_i_punti_diversi_da_trattino(self):
        firme = firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME, "controllo unico")

        self.assertEqual(
            sorted((f.punto.agency.nome, f.punto.punto) for f in firme),
            [("B&R", "H"), ("CLIENT", "W")],
        )
        self.assertFalse(self._punto(0, 2).firme.exists())
        # Già tutti firmati, o solo "-": niente da firmare.
        with self.assertRaisesMessage(ValueError, "già firmati"):
            firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME)
        with self.assertRaisesMessage(ValueError, "non ha punti da firmare"):
            firma_step(self.steps[2], self.writer, EsitoFirma.CONFORME)

    def test_firma_step_lascia_come_sono_i_punti_gia_firmati(self):
        prima = firma_punto(self._punto(0, 0), self.altro, EsitoFirma.NON_CONFORME)

        (nuova,) = firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME)

        self.assertEqual(nuova.punto, self._punto(0, 1))
        prima.refresh_from_db()
        self.assertEqual(
            (prima.utente, prima.esito, prima.valida), (self.altro, "non_conforme", True)
        )

    def test_la_firma_non_si_modifica_ne_si_cancella(self):
        firma = firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME, "originale")

        with self.assertRaises(FirmaNonModificabile):
            firma.delete()
        with self.assertRaises(FirmaNonModificabile):
            QualityControlPlanSignature.objects.all().delete()
        firma.esito, firma.note = EsitoFirma.NON_CONFORME, "cambiata"
        with self.assertRaises(FirmaNonModificabile):
            firma.save()

        firma.refresh_from_db()
        self.assertEqual((firma.esito, firma.note), ("conforme", "originale"))
        # Neanche indirettamente: step, sezione, piano e il valore del punto firmato.
        with self.assertRaisesMessage(ValueError, "firme registrate"):
            elimina_step(self.steps[0])
        with self.assertRaisesMessage(ValueError, "firme registrate"):
            elimina_sezione(self.sezione)
        risposta = self.client.delete(self._url(""))
        self.assertEqual(risposta.status_code, 400)
        with self.assertRaisesMessage(ValueError, "annulla prima la firma"):
            imposta_punto(self.steps[0], self.enti[0], "W")
        self.assertTrue(QualityControlPlan.objects.filter(pk=self.piano.pk).exists())
        # Annullata la firma il punto si può cambiare; la riga resta.
        annulla_firma(firma, self.writer, "Punto sbagliato: era W")
        imposta_punto(self.steps[0], self.enti[0], "W")
        self.assertEqual(QualityControlPlanSignature.objects.count(), 1)

    def test_un_piano_senza_punti_e_a_zero(self):
        vuoto = QualityControlPlan.objects.create(testata=self.testata, titolo="26031-QCPB")
        crea_sezione(vuoto, "Senza step")

        self.assertEqual(
            {k: avanzamento(vuoto)[k] for k in ("totale", "firmati", "percentuale", "completo")},
            {"totale": 0, "firmati": 0, "percentuale": 0, "completo": False},
        )
        (in_elenco,) = [p for p in list_piani("26031") if p["id"] == vuoto.pk]
        self.assertEqual(in_elenco["percentuale"], 0)

    def test_la_percentuale_e_per_difetto(self):
        firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME)

        # 2 su 3: 66%, non 67%; e 100% solo quando è firmato tutto.
        self.assertEqual(avanzamento(self.piano)["percentuale"], 66)
        firma_step(self.steps[1], self.writer, EsitoFirma.NON_APPLICABILE)
        self.assertEqual(
            {k: avanzamento(self.piano)[k] for k in ("percentuale", "completo")},
            {"percentuale": 100, "completo": True},
        )

    # -- Resa: utente con e senza immagine, stato in riga --

    def test_senza_immagine_di_firma_non_si_firma(self):
        senza = User.objects.create_user(
            "firme_senza", "firme-senza@brembanarolle.com", "pw", permesso=Permesso.WRITING
        )

        for firma in (
            lambda: firma_punto(self._punto(0, 0), senza, EsitoFirma.CONFORME),
            lambda: firma_step(self.steps[0], senza, EsitoFirma.CONFORME),
        ):
            with self.assertRaisesMessage(ValueError, "serve la tua immagine di firma"):
                firma()
        self.client.force_login(senza)
        risposta = self._post(f"corpo/punti/{self._punto(0, 0).pk}/firma/", {"esito": "conforme"})
        self.assertEqual(risposta.status_code, 400)
        self.assertIn("caricala nel profilo", risposta.json()["error"])
        self.assertFalse(QualityControlPlanSignature.objects.exists())
        # La pagina lo sa: al posto dei pulsanti "Firma" mostra l'avviso col profilo.
        html = self._pagina()
        self.assertIn('data-ha-firma="" data-url-profilo="/profilo/"', html)
        self.client.force_login(self.writer)
        self.assertIn('data-ha-firma="1"', self._pagina())

    def test_se_l_immagine_si_toglie_le_firme_mostrano_nome_e_data(self):
        firma = firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME)
        self._profilo(rimuovi_firma="1")

        html = self._pagina()

        dati = serialize_firma(QualityControlPlanSignature.objects.get(pk=firma.pk))
        self.assertEqual((dati["immagine"], dati["utente"]), ("", "Mario Rossi"))
        quando = data_ora(firma.firmato_il)
        self.assertIn('data-firma-utente="Mario Rossi"', html)
        self.assertIn(f'data-firma-quando="{quando}"', html)
        self.assertIn('data-firma-immagine=""', html)
        self.assertIn(f"B&amp;R: Hold point — conforming, signed by Mario Rossi on {quando}", html)

    def test_la_firma_mostra_l_immagine_servita_a_chi_e_autenticato(self):
        self.client.force_login(self.altro)
        self.client.post(
            "/profilo/",
            {
                "action": "update_profile",
                "email": self.altro.email,
                "firma": SimpleUploadedFile("firma.png", _png(), "image/png"),
            },
        )
        self.altro.refresh_from_db()
        firma_punto(self._punto(0, 0), self.altro, EsitoFirma.CONFORME)

        html = self._pagina()

        # Non l'URL dei file caricati (servito solo in sviluppo), ma una vista.
        url = f"/utenti/{self.altro.pk}/firma/?v={self.altro.firma.name}"
        self.assertIn(f'data-firma-immagine="{url}"', html)
        self.assertNotIn(self.altro.firma.url, html)
        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "image/png")
        # Letta per intero, la risposta la chiude il client di test (col file):
        # chiuderla di nuovo a mano chiuderebbe la connessione al database.
        contenuto = b"".join(risposta.streaming_content)
        self.assertTrue(contenuto.startswith(b"\x89PNG"))
        # Serve l'accesso; e chi non ha un'immagine risponde 404.
        self.assertEqual(self.client.get(f"/utenti/{self.reader.pk}/firma/").status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_la_riga_mostra_lo_stato_di_firma_di_ogni_punto(self):
        firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME)
        firma_punto(self._punto(0, 1), self.writer, EsitoFirma.NON_CONFORME, "Cricca al piede")

        html = self._pagina()

        riga = html[html.index(f'<li class="ce-step" data-id="{self.steps[0].pk}" ') :]
        riga = riga[: riga.index("</li>")]
        self.assertEqual(
            re.findall(r'data-punto="([^"]*)"[^>]*data-firma-esito="([^"]*)"', riga),
            [("H", "conforme"), ("W", "non_conforme"), ("-", "")],
        )
        self.assertEqual(riga.count('<span class="ce-firma-segno" aria-hidden="true"></span>'), 3)
        self.assertIn("CLIENT: Witness point — non-conforming, signed by Mario Rossi on ", riga)
        self.assertIn('title="B&amp;R: Review + Spot witness — to be signed"', html)
        # Nell'avanzamento: 2 punti firmati su 3, e mai la dicitura "firma
        # digitale", neanche in inglese.
        self.assertIn('<span id="qp-completi">2 points signed</span>', html)
        self.assertIn('<span class="qp-pct" id="qp-pct">66%</span>', html)
        self.assertIn('id="ce-esiti-firma"', html)
        self.assertIn("Simple electronic signature", html)
        self.assertNotIn("firma digitale", html.lower())
        self.assertNotIn("digital signature", html.lower())

    # -- Elenco piani e numero di query --

    def test_l_elenco_piani_mostra_la_percentuale_reale_senza_query_in_piu(self):
        firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME)
        for lettera in "BC":
            altro = QualityControlPlan.objects.create(
                testata=self.testata, titolo=f"26031-QCP{lettera}"
            )
            QualityControlPlanAgency.objects.create(piano=altro, nome="B&R")
            step = aggiungi_step(crea_sezione(altro, "S"), dati={"descrizione": "X"})
            imposta_punto(step, altro.agencies.get(), "H")
            firma_step(step, self.writer, EsitoFirma.CONFORME)

        # Commessa, piani con i conteggi, item, codici, spec ed enti: sei query.
        with self.assertNumQueries(6):
            piani = list_piani("26031")

        self.assertEqual(
            {p["titolo"]: p["percentuale"] for p in piani},
            {"26031-QCPA": 66, "26031-QCPB": 100, "26031-QCPC": 100},
        )
        self.assertEqual(
            self.client.get("/api/commesse/26031/quality-control-plan/").json()[
                "quality_control_plans"
            ][-1]["percentuale"],
            66,
        )

    def test_le_firme_non_aggiungono_query_al_dettaglio(self):
        with CaptureQueriesContext(connection) as senza:
            self._pagina()
        firma_step(self.steps[0], self.writer, EsitoFirma.CONFORME)
        firma_step(self.steps[1], self.altro, EsitoFirma.NON_CONFORME)
        annulla_firma(self._punto(1, 0).firme.get(), self.writer, "Da rifare")

        with self.assertNumQueries(len(senza)):
            self._pagina()

    # -- API --

    def test_api_firma_un_punto(self):
        punto = self._punto(0, 0)

        risposta = self._post(f"corpo/punti/{punto.pk}/firma/", {"esito": "conforme", "note": "ok"})

        self.assertEqual(risposta.status_code, 201)
        dati = risposta.json()["data"]
        (servito,) = dati["punti"]
        self.assertEqual(
            (servito["id"], servito["firma"]["esito"], servito["firma"]["utente"]),
            (punto.pk, "conforme", "Mario Rossi"),
        )
        self.assertEqual((dati["avanzamento"]["totale"], dati["avanzamento"]["firmati"]), (3, 1))
        # Di nuovo sullo stesso punto: 400 col messaggio, non 500.
        doppia = self._post(f"corpo/punti/{punto.pk}/firma/", {"esito": "conforme"})
        self.assertEqual(doppia.status_code, 400)
        self.assertIn("già una firma valida", doppia.json()["error"])
        self.assertEqual(
            self._post(f"corpo/punti/{punto.pk}/firma/", {"esito": "boh"}).status_code, 400
        )

    def test_api_firma_uno_step(self):
        risposta = self._post(
            f"corpo/steps/{self.steps[0].pk}/firma/", {"esito": "non_applicabile"}
        )

        self.assertEqual(risposta.status_code, 201)
        self.assertEqual(
            sorted(p["firma"]["esito"] for p in risposta.json()["data"]["punti"]),
            ["non_applicabile", "non_applicabile"],
        )
        vuoto = self._post(f"corpo/steps/{self.steps[2].pk}/firma/", {"esito": "conforme"})
        self.assertEqual(vuoto.status_code, 400)

    def test_api_annulla_storico_e_avanzamento(self):
        punto = self._punto(0, 0)
        firma = firma_punto(punto, self.writer, EsitoFirma.CONFORME)

        senza_motivo = self._post(f"firme/{firma.pk}/annulla/", {"motivo": " "})
        annullata = self._post(f"firme/{firma.pk}/annulla/", {"motivo": "Errore di punto"})

        self.assertEqual(senza_motivo.status_code, 400)
        self.assertEqual(annullata.status_code, 200)
        self.assertIsNone(annullata.json()["data"]["punti"][0]["firma"])
        self.assertEqual(annullata.json()["data"]["punti"][0]["firme_registrate"], 1)
        # Storico e avanzamento li legge anche chi è in sola lettura.
        self.client.force_login(self.reader)
        storico = self.client.get(self._url(f"corpo/punti/{punto.pk}/firme/"))
        self.assertEqual(storico.status_code, 200)
        self.assertEqual(
            [f["motivo_annullo"] for f in storico.json()["firme"]], ["Errore di punto"]
        )
        conti = self.client.get(self._url("avanzamento/"))
        self.assertEqual(conti.status_code, 200)
        self.assertEqual(
            {k: conti.json()[k] for k in ("totale", "firmati", "percentuale")},
            {"totale": 3, "firmati": 0, "percentuale": 0},
        )

    def test_api_verifica_appartenenza_e_permessi(self):
        punto = self._punto(0, 0)
        firma = firma_punto(punto, self.writer, EsitoFirma.CONFORME)
        Testata.objects.create(job="26032")
        altro = QualityControlPlan.objects.create(testata_id="26032", titolo="26032-QCPA")

        for risposta in (
            # Punto e firma di questo piano, ma chiesti sotto un altro piano o un'altra commessa.
            self._post(
                f"corpo/punti/{punto.pk}/firma/", {"esito": "conforme"}, pk=altro.pk, job="26032"
            ),
            self._post(f"corpo/punti/{punto.pk}/firma/", {"esito": "conforme"}, job="26032"),
            self._post(f"firme/{firma.pk}/annulla/", {"motivo": "x"}, pk=altro.pk, job="26032"),
            self.client.get(self._url(f"corpo/punti/{punto.pk}/firme/", pk=altro.pk, job="26032")),
            self._post("corpo/punti/999999/firma/", {"esito": "conforme"}),
            self._post("firme/999999/annulla/", {"motivo": "x"}),
        ):
            with self.subTest(url=risposta.request["PATH_INFO"]):
                self.assertEqual(risposta.status_code, 404)

        self.client.force_login(self.reader)
        self.assertEqual(
            self._post(
                f"corpo/punti/{self._punto(0, 1).pk}/firma/", {"esito": "conforme"}
            ).status_code,
            403,
        )
        self.assertEqual(self._post(f"firme/{firma.pk}/annulla/", {"motivo": "x"}).status_code, 403)
        firma.refresh_from_db()
        self.assertTrue(firma.valida)

    def test_il_seed_non_cancella_un_corpo_firmato(self):
        firma_punto(self._punto(0, 0), self.writer, EsitoFirma.CONFORME)
        cartella = tempfile.TemporaryDirectory()
        self.addCleanup(cartella.cleanup)
        percorso = Path(cartella.name) / "corpo.json"
        percorso.write_text(
            json.dumps(
                [
                    {
                        "titolo": "Nuova",
                        "steps": [{"codice": "X", "extent": 1.0, "punti": {}, "remarks": None}],
                    }
                ]
            ),
            encoding="utf-8",
        )

        with self.assertRaisesMessage(CommandError, "Reset impossibile"):
            call_command(
                "seed_corpo_qcp",
                "--job",
                "26031",
                "--file",
                str(percorso),
                "--reset",
                "--no-input",
                stdout=io.StringIO(),
            )

        self.assertTrue(QualityControlPlanSignature.objects.exists())
        self.assertEqual(self.piano.sections.get().titolo, "Documents approval")
