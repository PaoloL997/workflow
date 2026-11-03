import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase

from ..models import (
    Documento,
    Permesso,
    Reparto,
    Revisione,
    RevisioneFileLink,
    Testata,
    TipoFileLink,
)
from ..services.commesse import (
    risolvi_file_revisione,
    salva_file_link,
)
from ..services.fileserver import estrai_revisione, get_cartella_invio

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _make_fixtures_mock, _make_integration_fixtures


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

    def _jobs_path(self, *parts: str) -> str:
        from ..services.fileserver import get_jobs_root

        return str(get_jobs_root().joinpath(*parts))

    def test_create_link(self):
        path = self._jobs_path("25056", "PROGETTO", "QC", "25056-QMDBI Rev0.pdf")
        link = salva_file_link(self.rev.pk, path)
        self.assertEqual(link.percorso, path)
        self.assertEqual(RevisioneFileLink.objects.count(), 1)

    def test_update_existing_link(self):
        salva_file_link(self.rev.pk, self._jobs_path("25056", "old.pdf"))
        new_path = self._jobs_path("25056", "new.pdf")
        salva_file_link(self.rev.pk, new_path)
        self.assertEqual(RevisioneFileLink.objects.count(), 1)
        self.assertEqual(
            RevisioneFileLink.objects.get(revisione=self.rev).percorso,
            new_path,
        )


class EstraiRevisioneTest(SimpleTestCase):
    """``estrai_revisione`` sui formati trovati davvero nelle cartelle OBSOLETI/SUPERATI."""

    def test_formati_con_numero(self):
        casi = [
            ("26001-01-EBM1 Rev0.pdf", "26001-01-EBM1", "0"),
            ("25013-01-EBM1_Rev_0.pdf", "25013-01-EBM1", "0"),
            ("26001-01-EMC1_REV0.pdf", "26001-01-EMC1", "0"),
            ("25006-01-EBM1_Rev.0.pdf", "25006-01-EBM1", "0"),
            ("24081-03-QCPA Rev,4.pdf", "24081-03-QCPA", "4"),
            ("25032-01-EWM1 Rev-5.pdf", "25032-01-EWM1", "5"),
            ("24053-01-EMC1 Rev 0.pdf", "24053-01-EMC1", "0"),
            ("25067-01-EBM1 Rev1.0.pdf", "25067-01-EBM1", "1"),
            ("25059-01-QBU1 Rev.01a.pdf", "25059-01-QBU1", "1"),
            ("26027-01-EMC1_R0.pdf", "26027-01-EMC1", "0"),
            ("24022-01-EBM1 R00.pdf", "24022-01-EBM1", "0"),
            ("24022-ECS2-R3.pdf", "24022-ECS2", "3"),
            ("25038-01-TWB1 R_0.pdf", "25038-01-TWB1", "0"),
            ("26027-01-EBM1_1.pdf", "26027-01-EBM1", "1"),
            ("24070-01-IOM1-00.pdf", "24070-01-IOM1", "0"),
            ("24018-01-ED04_2.0.pdf", "24018-01-ED04", "2"),
            ("24018-01-EBM1_3RA.pdf", "24018-01-EBM1", "3"),
            ("25029-QTD 1.pdf", "25029-QTD", "1"),
            ("25067-01-TWB1_2 (0).pdf", "25067-01-TWB1", "2"),
            ("24018-01-FM01_0.pdf.pdf", "24018-01-FM01", "0"),
        ]
        for nome, vendor_doc, atteso in casi:
            with self.subTest(nome=nome):
                self.assertEqual(estrai_revisione(nome, vendor_doc).token, atteso)

    def test_formati_con_lettera(self):
        self.assertEqual(estrai_revisione("24096-01-EDS2 Rev A.pdf", "24096-01-EDS2").token, "A")
        self.assertEqual(estrai_revisione("24096-01-EMC1_rev.D.pdf", "24096-01-EMC1").token, "D")
        self.assertEqual(estrai_revisione("24096-01-ED02_Rev_C.pdf", "24096-01-ED02").token, "C")

    def test_senza_suffisso_e_copie(self):
        self.assertEqual(estrai_revisione("26027-01-EBM1.pdf", "26027-01-EBM1").token, "")
        self.assertEqual(estrai_revisione("25005-01-QCPA (2).pdf", "25005-01-QCPA").token, "")

    def test_testo_libero_non_si_capisce(self):
        for nome, vendor_doc in (
            ("25027-01-EBM1_RA.pdf", "25027-01-EBM1"),
            ("25027-01-EE01_PRELIMINARY.pdf", "25027-01-EE01"),
            ("25083-QBDI REJECTED.pdf", "25083-QBDI"),
            ("24037-01-EBM1_Revisione Aperta.pdf", "24037-01-EBM1"),
        ):
            with self.subTest(nome=nome):
                self.assertIsNone(estrai_revisione(nome, vendor_doc).token)

    def test_solo_revisione(self):
        self.assertTrue(estrai_revisione("25006-01-EBM2_Rev.2.pdf", "25006-01-EBM2").solo_revisione)
        self.assertFalse(
            estrai_revisione("25006-01-EBM2_Rev.2A.pdf", "25006-01-EBM2").solo_revisione
        )
        self.assertFalse(estrai_revisione("25027-01-EBM1_2_RA.pdf", "25027-01-EBM1").solo_revisione)

    def test_codice_a_parola_intera(self):
        self.assertIsNone(estrai_revisione("26027-01-ESH10.pdf", "26027-01-ESH1"))
        self.assertIsNone(estrai_revisione("ALTRO-DOC.pdf", "26027-01-ESH1"))
        self.assertEqual(estrai_revisione("26027-01-esh1_1.pdf", "26027-01-ESH1").token, "1")

    def test_codice_vuoto(self):
        self.assertIsNone(estrai_revisione("26027-01-EBM1.pdf", " "))


class RisolviFileInvioTest(TestCase):
    """``risolvi_file_revisione(..., TipoFileLink.INVIATO)``: il file della cella Dispatch."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.pm = Reparto.objects.create(nome="Project Management", acronimo="PM")
        self.testata = Testata.objects.create(job="26027")
        self.doc = Documento.objects.create(
            testata=self.testata, vendor_doc="26027-01-EBM1", reparto=ut.nome
        )
        self.revs = [
            Revisione.objects.create(documento=self.doc, rev_no=n, dis_act_date=f"2026-0{n + 6}-03")
            for n in range(4)
        ]
        # Revisione pianificata e non ancora inviata: non è "l'ultima inviata".
        self.rev_pianificata = Revisione.objects.create(documento=self.doc, rev_no=4)

    def tearDown(self):
        self.patcher.stop()

    def _cartella(self, *parti: str) -> Path:
        d = Path(self.tmp, "26027", "PROGETTO", *parti)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _file(self, *parti: str) -> None:
        (self._cartella(*parti[:-1]) / parti[-1]).touch()

    def _risolvi(self, rev):
        return risolvi_file_revisione(rev.pk, TipoFileLink.INVIATO)

    def _nomi(self, risultato):
        return sorted(f["nome"] for f in risultato["files"])

    def _archivio_ebm1(self):
        """Come 26027 sul fileserver: l'ultima in UT, le precedenti in OBSOLETI."""
        self._file("UT", "26027-01-EBM1.pdf")
        self._file("UT", "26027-01-EBM10.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1_1.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1_2.pdf")

    def test_cartella_invio_ut_o_qc(self):
        self.assertEqual(
            get_cartella_invio("26027", "UT"), Path(self.tmp, "26027", "PROGETTO", "UT")
        )
        for acronimo in ("QC", "WE", "PM", "AM"):
            with self.subTest(acronimo=acronimo):
                self.assertEqual(
                    get_cartella_invio("26027", acronimo), Path(self.tmp, "26027", "PROGETTO", "QC")
                )

    def test_ultima_revisione_inviata_nella_cartella_ut(self):
        self._archivio_ebm1()

        risultato = self._risolvi(self.revs[3])

        self.assertEqual(risultato["status"], "found")
        self.assertEqual(
            risultato["files"][0]["percorso"],
            str(Path(self.tmp, "26027", "PROGETTO", "UT", "26027-01-EBM1.pdf")),
        )

    def test_revisioni_precedenti_per_numero_in_obsoleti(self):
        self._archivio_ebm1()
        for rev, atteso in (
            (self.revs[1], "26027-01-EBM1_1.pdf"),
            (self.revs[2], "26027-01-EBM1_2.pdf"),
        ):
            with self.subTest(rev_no=rev.rev_no):
                risultato = self._risolvi(rev)
                self.assertEqual(risultato["status"], "found")
                self.assertEqual(self._nomi(risultato), [atteso])

    def test_prima_revisione_senza_suffisso_in_archivio(self):
        self._archivio_ebm1()

        risultato = self._risolvi(self.revs[0])

        self.assertEqual(risultato["status"], "found")
        self.assertIn("OBSOLETI", risultato["files"][0]["percorso"])

    def test_numero_nel_nome_vince_anche_per_l_ultima(self):
        """In QC l'ultima revisione sta in cartella col suffisso (``_3``)."""
        self._file("UT", "26027-01-EBM1_3.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1_2.pdf")

        self.assertEqual(self._nomi(self._risolvi(self.revs[3])), ["26027-01-EBM1_3.pdf"])

    def test_preferisce_il_nome_con_la_sola_revisione(self):
        self._file("UT", "OBSOLETI", "26027-01-EBM1_Rev.2.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1_Rev.2A.pdf")

        risultato = self._risolvi(self.revs[2])

        self.assertEqual(risultato["status"], "found")
        self.assertEqual(self._nomi(risultato), ["26027-01-EBM1_Rev.2.pdf"])

    def test_piu_file_con_la_stessa_revisione_fanno_scegliere(self):
        self._file("UT", "OBSOLETI", "26027-01-EBM1_2.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1 Rev2.pdf")

        risultato = self._risolvi(self.revs[2])

        self.assertEqual(risultato["status"], "multiple")
        self.assertEqual(len(risultato["files"]), 2)

    def test_senza_numero_si_sceglie_fra_tutti_i_file_del_documento(self):
        self._file("UT", "26027-01-EBM1.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1_RA.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1 priced.pdf")

        risultato = self._risolvi(self.revs[1])

        self.assertEqual(risultato["status"], "multiple")
        self.assertEqual(len(risultato["files"]), 3)

    def test_revisione_a_lettera(self):
        Revisione.objects.filter(pk=self.revs[1].pk).update(rev_let="B")
        self._file("UT", "OBSOLETI", "26027-01-EBM1 Rev B.pdf")
        self._file("UT", "OBSOLETI", "26027-01-EBM1 Rev C.pdf")

        self.assertEqual(self._nomi(self._risolvi(self.revs[1])), ["26027-01-EBM1 Rev B.pdf"])

    def test_documento_non_ut_cerca_in_qc_e_superati(self):
        doc = Documento.objects.create(
            testata=self.testata, vendor_doc="26027-PPP1", reparto=self.pm.nome
        )
        rev0 = Revisione.objects.create(documento=doc, rev_no=0, dis_act_date="2026-05-20")
        rev1 = Revisione.objects.create(documento=doc, rev_no=1, dis_act_date="2026-09-08")
        self._file("PM", "26027-PPP1.pdf")  # cartella del reparto: non va guardata
        self._file("QC", "26027-PPP1 Rev.1.pdf")
        self._file("QC", "SUPERATI", "26027-PPP1 Rev.0.pdf")

        self.assertEqual(self._nomi(self._risolvi(rev1)), ["26027-PPP1 Rev.1.pdf"])
        risultato = self._risolvi(rev0)
        self.assertEqual(self._nomi(risultato), ["26027-PPP1 Rev.0.pdf"])
        self.assertIn("SUPERATI", risultato["files"][0]["percorso"])

    def test_senza_data_di_invio_not_found(self):
        self._archivio_ebm1()

        self.assertEqual(self._risolvi(self.rev_pianificata)["status"], "not_found")

    def test_nessun_file_not_found(self):
        self._file("UT", "26027-01-EBM10.pdf")

        self.assertEqual(self._risolvi(self.revs[3])["status"], "not_found")

    def test_link_manuale_separato_per_tipo(self):
        self._archivio_ebm1()
        inviato = str(Path(self.tmp, "26027", "PROGETTO", "UT", "scelto-a-mano.pdf"))
        ricevuto = str(Path(self.tmp, "26027", "PROGETTO", "UT", "ricevuto-a-mano.pdf"))

        salva_file_link(self.revs[3].pk, inviato, TipoFileLink.INVIATO)
        self.assertEqual(self._risolvi(self.revs[3])["status"], "manual_linked")
        self.assertEqual(self._risolvi(self.revs[3])["files"][0]["percorso"], inviato)
        # Il link della Dispatch non tocca la Received.
        self.assertNotEqual(risolvi_file_revisione(self.revs[3].pk)["status"], "manual_linked")

        salva_file_link(self.revs[3].pk, ricevuto)
        self.assertEqual(risolvi_file_revisione(self.revs[3].pk)["files"][0]["percorso"], ricevuto)
        self.assertEqual(self._risolvi(self.revs[3])["files"][0]["percorso"], inviato)
        self.assertEqual(RevisioneFileLink.objects.filter(revisione=self.revs[3]).count(), 2)


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

    def test_save_and_resolve_link_inviato(self):
        inviato = str(Path(self.tmp) / "25056" / "inviato.pdf")
        ricevuto = str(Path(self.tmp) / "25056" / "ricevuto.pdf")
        for percorso, corpo in (
            (inviato, {"percorso": inviato, "tipo": "inviato"}),
            (ricevuto, {"percorso": ricevuto}),
        ):
            response = self.client.post(
                f"/api/revisioni/{self.rev.pk}/file/link/",
                data=json.dumps(corpo),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["percorso"], percorso)

        self.assertEqual(RevisioneFileLink.objects.filter(revisione=self.rev).count(), 2)
        dispatch = self.client.get(f"/api/revisioni/{self.rev.pk}/file/", {"tipo": "inviato"})
        self.assertEqual(dispatch.json()["files"][0]["percorso"], inviato)
        received = self.client.get(f"/api/revisioni/{self.rev.pk}/file/")
        self.assertEqual(received.json()["files"][0]["percorso"], ricevuto)

    def test_tipo_non_valido(self):
        response = self.client.get(f"/api/revisioni/{self.rev.pk}/file/", {"tipo": "altro"})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            f"/api/revisioni/{self.rev.pk}/file/link/",
            data=json.dumps({"percorso": str(Path(self.tmp) / "x.pdf"), "tipo": "altro"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(RevisioneFileLink.objects.exists())

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
