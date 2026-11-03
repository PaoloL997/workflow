import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib import admin
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from ..models import (
    DestinatarioTransmittalInterno,
    Documento,
    FirmatarioStabilimento,
    IndirizzoStabilimento,
    IndirizzoTipoDocumento,
    OrigineDestinatarioTransmittalInterno,
    Permesso,
    PersonaCommessa,
    PresaVisioneTransmittalInterno,
    Reparto,
    Revisione,
    RigaTransmittalInterno,
    RuoloFirmatarioStabilimento,
    RuoloPersonaCommessa,
    Stabilimento,
    StatoEsterno,
    Testata,
    TipoDestinatarioTransmittalInterno,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
)
from ..services.fileserver import get_base_path
from ..services.trasmittal_interno import (
    anteprima_destinatari,
    componi_nome,
    crea_trasmittal_interno,
    imposta_destinazioni,
    indirizzi_per_tipi_documento,
    invia_email_emissione,
    mittente_trasmittal,
    prepara_per_dcc,
    prossimo_progressivo,
    registra_presa_visione,
    salva_pdf,
    tipo_documento,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _media_temporanea


class TransmittalInternoAdminTests(TestCase):
    """Admin di TransmittalInterno: sola lettura, ma un superuser può eliminare
    (per pulire dati di test/errore non coperti dal tasto Annulla dell'app)."""

    def setUp(self):
        self.testata = Testata.objects.create(job="99095")
        self.superuser = User.objects.create_superuser(
            "ti_admin_super", "ti_admin_super@example.com", "pw"
        )
        self.staff_normale = User.objects.create_user(
            "ti_admin_staff", "ti_admin_staff@example.com", "pw", permesso=Permesso.ADMIN
        )
        self.trasmittal = TransmittalInterno.objects.create(
            testata=self.testata,
            data=date(2026, 1, 1),
            progressivo=1,
            nome="99095_2026-01-01_E1",
            creato_da=self.superuser,
        )
        self.model_admin = admin.site._registry[TransmittalInterno]
        self.factory = RequestFactory()

    def _request(self, user):
        request = self.factory.get("/admin/core/transmittalinterno/")
        request.user = user
        return request

    def test_superuser_puo_eliminare(self):
        self.assertTrue(
            self.model_admin.has_delete_permission(self._request(self.superuser), self.trasmittal)
        )

    def test_staff_senza_permesso_esplicito_non_puo_eliminare(self):
        self.assertFalse(
            self.model_admin.has_delete_permission(
                self._request(self.staff_normale), self.trasmittal
            )
        )

    def test_aggiunta_e_modifica_restano_bloccate_anche_per_superuser(self):
        request = self._request(self.superuser)
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request, self.trasmittal))


class TrasmittalInternoArchivioTests(TestCase):
    """Archivio del trasmittal interno: progressivo, nome, snapshot dei siti, destinatari."""

    def setUp(self):
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        self.ve = Stabilimento.objects.create(nome="Marghera", sigla="VE", codice_bc=3)

        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=self.pd, email="pd@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        # Stesso indirizzo di BG, ma CC su un altro sito: nei destinatari deve
        # restare solo in TO, senza comparire due volte.
        IndirizzoStabilimento.objects.create(
            stabilimento=self.ve, email="bg@b.it", tipo=TipoIndirizzoStabilimento.CC
        )

        self.testata = Testata.objects.create(job="99010")
        self.altra_testata = Testata.objects.create(job="99011")
        self.doc1 = Documento.objects.create(testata=self.testata, vendor_doc="99010-DOC1")
        self.doc2 = Documento.objects.create(testata=self.testata, vendor_doc="99010-DOC2")

        imposta_destinazioni(self.doc1, [1, 2])
        imposta_destinazioni(self.doc2, [3])

        self.utente = User.objects.create_user("trasmittal_utente", password="pw")

    def _righe(self, *documenti):
        return [{"documento": doc, "revisione": "1"} for doc in documenti]

    # -- prossimo_progressivo --

    def test_prossimo_progressivo_riparte_da_1_il_giorno_dopo(self):
        crea_trasmittal_interno(
            self.testata, self._righe(self.doc1), self.utente, data=date(2026, 9, 14)
        )

        self.assertEqual(prossimo_progressivo(self.testata, date(2026, 9, 14)), 2)
        self.assertEqual(prossimo_progressivo(self.testata, date(2026, 9, 15)), 1)

    def test_prossimo_progressivo_non_collide_fra_commesse(self):
        crea_trasmittal_interno(
            self.testata, self._righe(self.doc1), self.utente, data=date(2026, 9, 14)
        )

        self.assertEqual(prossimo_progressivo(self.altra_testata, date(2026, 9, 14)), 1)

    # -- componi_nome --

    def test_componi_nome_formato_atteso(self):
        self.assertEqual(componi_nome(self.testata, date(2026, 9, 14), 3), "99010_2026-09-14_E3")

    # -- snapshot dei siti --

    def test_i_siti_della_riga_sono_uno_snapshot(self):
        trasmittal = crea_trasmittal_interno(
            self.testata, self._righe(self.doc1), self.utente, data=date(2026, 9, 14)
        )
        riga = trasmittal.righe.get(documento=self.doc1)
        self.assertEqual(sorted(s.codice_bc for s in riga.siti.all()), [1, 2])

        imposta_destinazioni(self.doc1, [3])

        self.assertEqual(sorted(s.codice_bc for s in riga.siti.all()), [1, 2])

    # -- destinatari di stabilimento --

    def test_destinatari_di_stabilimento_dedotti_dall_unione_dei_siti_senza_duplicati(self):
        trasmittal = crea_trasmittal_interno(
            self.testata, self._righe(self.doc1, self.doc2), self.utente, data=date(2026, 9, 14)
        )

        destinatari = list(trasmittal.destinatari.values_list("email", "tipo", "origine"))

        self.assertEqual(
            sorted(destinatari),
            sorted(
                [
                    ("bg@b.it", "to", "stabilimento"),
                    ("pd@b.it", "to", "stabilimento"),
                ]
            ),
        )

    # -- unicità documento nella lettera --

    def test_un_documento_non_puo_comparire_due_volte_nella_stessa_lettera(self):
        trasmittal = TransmittalInterno.objects.create(
            testata=self.testata,
            data=date(2026, 9, 14),
            progressivo=1,
            nome=componi_nome(self.testata, date(2026, 9, 14), 1),
            creato_da=self.utente,
        )
        RigaTransmittalInterno.objects.create(
            trasmittal=trasmittal, documento=self.doc1, revisione="1", posizione=1
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            RigaTransmittalInterno.objects.create(
                trasmittal=trasmittal, documento=self.doc1, revisione="2", posizione=2
            )


class RigaTransmittalInternoTpiTests(TestCase):
    """TPI (b)(c) del modulo: SÌ/NO all'ispettore terzo, e se sì chi.

    ``tpi`` e ``tpi_destinatario`` non possono essere in disaccordo: un
    destinatario ha senso solo se ``tpi`` è attivo, e se è attivo va
    specificato chi.
    """

    def setUp(self):
        self.testata = Testata.objects.create(job="99012")
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="99012-DOC1")
        self.utente = User.objects.create_user("riga_tpi_utente", password="pw")
        self.trasmittal = TransmittalInterno.objects.create(
            testata=self.testata,
            data=date(2026, 9, 14),
            progressivo=1,
            nome=componi_nome(self.testata, date(2026, 9, 14), 1),
            creato_da=self.utente,
        )

    def _riga(self, **overrides):
        base = {
            "trasmittal": self.trasmittal,
            "documento": self.doc,
            "revisione": "1",
            "posizione": 1,
        }
        base.update(overrides)
        return RigaTransmittalInterno(**base)

    def test_tpi_spento_con_destinatario_e_un_errore_di_validazione(self):
        riga = self._riga(tpi=False, tpi_destinatario="AI")

        with self.assertRaises(ValidationError):
            riga.full_clean()

    def test_tpi_acceso_senza_destinatario_e_un_errore_di_validazione(self):
        riga = self._riga(tpi=True, tpi_destinatario="")

        with self.assertRaises(ValidationError):
            riga.full_clean()

    def test_tpi_spento_senza_destinatario_e_valido(self):
        riga = self._riga(tpi=False, tpi_destinatario="")

        riga.full_clean()  # non deve sollevare

    def test_tpi_acceso_con_destinatario_e_valido(self):
        riga = self._riga(tpi=True, tpi_destinatario="No.Bo.")

        riga.full_clean()  # non deve sollevare


class DestinatariTrasmittalInternoRuoliTests(TestCase):
    """Risoluzione dei destinatari da PM/PE/QCI e dalla regola export@ per i documenti ESH."""

    def setUp(self):
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )

        self.testata = Testata.objects.create(job="99012")
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="99012-01-QCPA")
        imposta_destinazioni(self.doc, [1])

        self.utente = User.objects.create_user("destinatari_utente", password="pw")
        self.pm = User.objects.create_user("destinatari_pm", "pm@b.it", "pw")
        self.pe = User.objects.create_user("destinatari_pe", "pe@b.it", "pw")
        self.qci = User.objects.create_user("destinatari_qci", "qci@b.it", "pw")

    def _righe(self, *documenti):
        return [{"documento": doc, "revisione": "1"} for doc in documenti]

    def test_pm_in_to_pe_e_qci_in_cc(self):
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, utente=self.pm
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PE, utente=self.pe
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.QCI, utente=self.qci
        )

        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        destinatari = set(trasmittal.destinatari.values_list("email", "tipo", "origine"))
        self.assertEqual(
            destinatari,
            {
                ("bg@b.it", "to", "stabilimento"),
                ("pm@b.it", "to", "pm"),
                ("pe@b.it", "cc", "pe"),
                ("qci@b.it", "cc", "qci"),
            },
        )

    def test_ruolo_non_valorizzato_non_e_un_errore(self):
        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        self.assertEqual(
            set(trasmittal.destinatari.values_list("email", "tipo", "origine")),
            {("bg@b.it", "to", "stabilimento")},
        )

    def test_documento_esh_aggiunge_export_in_cc(self):
        # Regola iniziale della migrazione 0065, senza crearla qui.
        doc_esh = Documento.objects.create(testata=self.testata, vendor_doc="99012-01-ESH1")
        imposta_destinazioni(doc_esh, [1])

        trasmittal = crea_trasmittal_interno(
            self.testata, self._righe(self.doc, doc_esh), self.utente
        )

        self.assertIn(
            ("export@brembanarolle.com", "cc", "tipo_documento"),
            set(trasmittal.destinatari.values_list("email", "tipo", "origine")),
        )

    def test_documento_senza_regola_non_aggiunge_export(self):
        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        self.assertNotIn(
            "export@brembanarolle.com", trasmittal.destinatari.values_list("email", flat=True)
        )

    def test_pm_gia_indirizzo_di_stabilimento_una_sola_occorrenza_in_to(self):
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, utente=self.pm
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="pm@b.it", tipo=TipoIndirizzoStabilimento.CC
        )

        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        destinatari = list(trasmittal.destinatari.values_list("email", "tipo"))
        self.assertEqual(destinatari.count(("pm@b.it", "to")), 1)
        self.assertNotIn(("pm@b.it", "cc"), destinatari)

    def test_stesso_indirizzo_in_to_e_cc_resta_in_to(self):
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.CC
        )

        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        destinatari = list(trasmittal.destinatari.values_list("email", "tipo"))
        self.assertEqual(destinatari.count(("bg@b.it", "to")), 1)
        self.assertNotIn(("bg@b.it", "cc"), destinatari)

    def test_indirizzi_attivi_del_sito_coinvolto_aggiunti_alla_lettera(self):
        altro_sito = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="qualita@b.it", tipo=TipoIndirizzoStabilimento.CC
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg,
            email="disattivato@b.it",
            tipo=TipoIndirizzoStabilimento.CC,
            attivo=False,
        )
        # Indirizzo di un sito non coinvolto nella lettera: non deve comparire.
        IndirizzoStabilimento.objects.create(
            stabilimento=altro_sito,
            email="altro_sito@b.it",
            tipo=TipoIndirizzoStabilimento.CC,
        )

        trasmittal = crea_trasmittal_interno(self.testata, self._righe(self.doc), self.utente)

        destinatari = set(trasmittal.destinatari.values_list("email", "tipo", "origine"))
        email_presenti = trasmittal.destinatari.values_list("email", flat=True)
        self.assertIn(("qualita@b.it", "cc", "stabilimento"), destinatari)
        self.assertNotIn("disattivato@b.it", email_presenti)
        self.assertNotIn("altro_sito@b.it", email_presenti)


class TipoDocumentoTests(SimpleTestCase):
    """tipo_documento: le lettere del B&R Doc dopo il secondo trattino."""

    def test_codici(self):
        casi = {
            "26026-01-EBM1": "EBM",
            "26026-01-esh10": "ESH",
            "26026-03-ED02": "ED",
            "26026-04-QCPA": "QCPA",
            " 26026-01-EGA1 ": "EGA",
            "26026-QWR1": "",
            "26026-01-123": "",
            "": "",
            None: "",
        }
        for vendor_doc, atteso in casi.items():
            with self.subTest(vendor_doc=vendor_doc):
                self.assertEqual(tipo_documento(vendor_doc), atteso)


class IndirizziTipoDocumentoTests(TestCase):
    """Indirizzi del trasmittal interno per tipo di documento (``IndirizzoTipoDocumento``)."""

    def setUp(self):
        # Senza le regole iniziali della migrazione: ogni test crea le sue.
        IndirizzoTipoDocumento.objects.all().delete()
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        self.testata = Testata.objects.create(job="99013")
        self.utente = User.objects.create_user("tipo_doc_utente", password="pw")

    def _documento(self, vendor_doc):
        documento = Documento.objects.create(testata=self.testata, vendor_doc=vendor_doc)
        imposta_destinazioni(documento, [1])
        return documento

    def _destinatari(self, *documenti):
        righe = [{"documento": documento, "revisione": "1"} for documento in documenti]
        trasmittal = crea_trasmittal_interno(self.testata, righe, self.utente)
        return set(trasmittal.destinatari.values_list("email", "tipo", "origine"))

    def _regola(self, codice, email, tipo=TipoDestinatarioTransmittalInterno.CC, attivo=True):
        return IndirizzoTipoDocumento.objects.create(
            codice_tipo=codice, email=email, tipo=tipo, attivo=attivo
        )

    def test_regola_attiva_aggiunge_l_indirizzo_col_suo_tipo(self):
        self._regola("EBM", "qa@b.it", tipo=TipoDestinatarioTransmittalInterno.TO)

        destinatari = self._destinatari(self._documento("99013-01-EBM1"))

        self.assertIn(("qa@b.it", "to", "tipo_documento"), destinatari)

    def test_documento_di_altro_tipo_non_aggiunge_nulla(self):
        self._regola("EBM", "qa@b.it")

        destinatari = self._destinatari(self._documento("99013-01-EGA1"))

        self.assertNotIn("qa@b.it", {email for email, _, _ in destinatari})

    def test_il_confronto_sul_tipo_e_esatto(self):
        self._regola("ED", "ed@b.it")

        destinatari = self._destinatari(self._documento("99013-01-EDV1"))

        self.assertNotIn("ed@b.it", {email for email, _, _ in destinatari})

    def test_regola_disattivata_ignorata(self):
        self._regola("EBM", "qa@b.it", attivo=False)

        destinatari = self._destinatari(self._documento("99013-01-EBM1"))

        self.assertNotIn("qa@b.it", {email for email, _, _ in destinatari})

    def test_un_indirizzo_per_piu_tipi_compare_una_volta_con_tutti_i_tipi(self):
        for codice in ("EBM", "ESH", "EGA"):
            self._regola(codice, "export@b.it")
        documenti = [self._documento("99013-01-EBM1"), self._documento("99013-01-ESH1")]

        self.assertEqual(
            indirizzi_per_tipi_documento(documenti),
            [{"email": "export@b.it", "tipo": "cc", "codici": ["EBM", "ESH"]}],
        )
        self.assertEqual(
            [
                voce
                for voce in anteprima_destinatari(self.testata, documenti)
                if voce["email"] == "export@b.it"
            ],
            [{"email": "export@b.it", "tipo": "cc", "origine": "tipo_documento"}],
        )

    def test_indirizzo_gia_di_stabilimento_resta_in_to(self):
        self._regola("EBM", "bg@b.it")

        destinatari = self._destinatari(self._documento("99013-01-EBM1"))

        self.assertIn(("bg@b.it", "to", "stabilimento"), destinatari)
        self.assertNotIn(("bg@b.it", "cc", "tipo_documento"), destinatari)

    def test_codice_in_maiuscolo_e_validato(self):
        regola = self._regola("ebm", "qa@b.it")
        self.assertEqual(regola.codice_tipo, "EBM")

        doppione = IndirizzoTipoDocumento(codice_tipo="Ebm", email="qa@b.it", tipo="cc")
        with self.assertRaises(ValidationError):
            doppione.full_clean()
        with self.assertRaises(ValidationError):
            IndirizzoTipoDocumento(codice_tipo="EB1", email="x@b.it", tipo="cc").full_clean()


class RegoleExportInizialiTests(TestCase):
    """La migrazione 0065 porta in tabella la regola export@, estesa a EBM ed EGA."""

    def test_export_in_cc_per_ebm_ega_esh(self):
        regole = IndirizzoTipoDocumento.objects.filter(email="export@brembanarolle.com")

        self.assertEqual(
            list(regole.values_list("codice_tipo", "tipo", "attivo")),
            [("EBM", "cc", True), ("EGA", "cc", True), ("ESH", "cc", True)],
        )


class TrasmittalInternoPdfTests(TestCase):
    """Generazione del PDF del trasmittal interno (form MQ 7.5-04)."""

    def setUp(self):
        _media_temporanea(self)

        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)

        self.produzione = User.objects.create_user(
            "pdf_produzione", "pdf-produzione@b.it", "pw", first_name="Mario", last_name="Rossi"
        )
        self.qualita = User.objects.create_user(
            "pdf_qualita", "pdf-qualita@b.it", "pw", first_name="Anna", last_name="Bianchi"
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg,
            ruolo=RuoloFirmatarioStabilimento.PRODUZIONE,
            utente=self.produzione,
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg, ruolo=RuoloFirmatarioStabilimento.QUALITA, utente=self.qualita
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.pd, ruolo=RuoloFirmatarioStabilimento.QUALITA, utente=self.qualita
        )

        self.testata = Testata.objects.create(job="99020", job_detail="Prova PDF interno")
        self.doc1 = Documento.objects.create(testata=self.testata, vendor_doc="99020-DOC1")
        self.doc2 = Documento.objects.create(testata=self.testata, vendor_doc="99020-DOC2")
        imposta_destinazioni(self.doc1, [1, 2])
        imposta_destinazioni(self.doc2, [1])

        self.trasmittal = crea_trasmittal_interno(
            self.testata,
            [
                {
                    "documento": self.doc1,
                    "revisione": "3",
                    "copie": 2,
                    "tpi": True,
                    "tpi_destinatario": "ABC",
                    "note": "x",
                },
                {"documento": self.doc2, "revisione": "B", "cliente": False},
            ],
            self.produzione,
            data=date(2026, 9, 14),
            note="Note libere della lettera.",
        )

    def test_il_pdf_si_genera_e_non_e_vuoto(self):
        from src.pdf import genera_trasmittal_interno_pdf

        contenuto = genera_trasmittal_interno_pdf(self.trasmittal)

        self.assertTrue(contenuto.startswith(b"%PDF"))
        self.assertGreater(len(contenuto), 1000)

    # -- colonna TPI: "NO" se spento, il destinatario se acceso --

    def test_colonna_tpi_mostra_no_se_spento(self):
        from src.pdf import _int_row_value

        riga = self.trasmittal.righe.get(documento=self.doc2)  # tpi=False di default

        self.assertEqual(_int_row_value(riga, "tpi"), "NO")

    def test_colonna_tpi_mostra_il_destinatario_se_acceso(self):
        from src.pdf import _int_row_value

        riga = self.trasmittal.righe.get(documento=self.doc1)  # tpi=True, dest="ABC"

        self.assertEqual(_int_row_value(riga, "tpi"), "ABC")

    def test_tabella_email_mostra_no_e_destinatario_come_il_pdf(self):
        from core.services.trasmittal_interno import _tabella_testo_righe

        tabella = _tabella_testo_righe(self.trasmittal)

        self.assertIn("NO", tabella)
        self.assertIn("ABC", tabella)

    def test_il_pdf_si_genera_anche_con_le_prese_visione(self):
        from src.pdf import genera_trasmittal_interno_pdf

        PresaVisioneTransmittalInterno.objects.create(
            trasmittal=self.trasmittal,
            utente=self.qualita,
            ruolo=RuoloFirmatarioStabilimento.QUALITA,
        )

        contenuto = genera_trasmittal_interno_pdf(self.trasmittal)

        self.assertTrue(contenuto.startswith(b"%PDF"))

    def test_footer_riporta_i_riferimenti_del_modulo_rev01_in_un_solo_riquadro(self):
        from src.pdf import (
            _INT_TABLE_WIDTH_MM,
            TrasmittalInternoPDF,
            _build_footer_riferimenti,
        )

        pdf = TrasmittalInternoPDF()
        pdf.add_page()
        with (
            patch.object(pdf, "cell", wraps=pdf.cell) as cell,
            patch.object(pdf, "rect", wraps=pdf.rect) as rect,
        ):
            _build_footer_riferimenti(pdf)

        testi = [c.args[2] for c in cell.call_args_list]
        self.assertEqual(
            testi, ["B&R Form: MQ 7.5-04 Rev.01 Dated: 23/10/2026  Rif.: PQHSE 7.5-01"]
        )
        rect.assert_called_once()
        self.assertEqual(rect.call_args.args[2], _INT_TABLE_WIDTH_MM)


class SalvaPdfTrasmittalInternoTests(TestCase):
    """salva_pdf: scrittura sul fileserver, sempre dentro la cartella JOBS."""

    def setUp(self):
        _media_temporanea(self)

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        jobs_patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        jobs_patcher.enable()
        self.addCleanup(jobs_patcher.disable)

        self.utente = User.objects.create_user("salva_pdf_utente", "salva-pdf@b.it", "pw")

    def _trasmittal(self, job):
        testata = Testata.objects.create(job=job)
        return TransmittalInterno.objects.create(
            testata=testata,
            data=date(2026, 9, 14),
            progressivo=1,
            nome=componi_nome(testata, date(2026, 9, 14), 1),
            creato_da=self.utente,
        )

    def test_salva_pdf_rifiuta_un_percorso_fuori_dalla_jobs_root(self):
        trasmittal = self._trasmittal("../fuori")

        with self.assertRaises(PermissionError):
            salva_pdf(trasmittal)


class PreparaPerDccTests(TestCase):
    """prepara_per_dcc: copia i PDF dei documenti cliente in una cartella dedicata."""

    def setUp(self):
        from ..services.fileserver import get_base_path

        self.get_base_path = get_base_path

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.reparto = Reparto.objects.create(nome="Qualità e Controllo", acronimo="QMD")
        self.testata = Testata.objects.create(job="99030")
        self.utente = User.objects.create_user("dcc_utente", "dcc@b.it", "pw")

        self.doc_ok = Documento.objects.create(
            testata=self.testata, vendor_doc="99030-QMDBI", reparto=self.reparto.nome
        )
        self.doc_non_cliente = Documento.objects.create(
            testata=self.testata, vendor_doc="99030-QCPA", reparto=self.reparto.nome
        )
        self.doc_missing = Documento.objects.create(
            testata=self.testata, vendor_doc="99030-DWG01", reparto=self.reparto.nome
        )

        base = get_base_path("99030", "QMD")
        base.mkdir(parents=True)
        (base / f"{self.doc_ok.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-doc-ok")
        (base / f"{self.doc_non_cliente.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-doc-non-cliente")
        # doc_missing: nessun file sul finto fileserver.

    def _trasmittal(self, righe, testata=None):
        return crea_trasmittal_interno(
            testata or self.testata, righe, self.utente, data=date(2026, 9, 14)
        )

    def test_copia_solo_i_documenti_con_cliente_true(self):
        trasmittal = self._trasmittal(
            [
                {"documento": self.doc_ok, "revisione": "1", "cliente": True},
                {"documento": self.doc_non_cliente, "revisione": "1", "cliente": False},
            ]
        )

        esito = prepara_per_dcc(trasmittal)

        self.assertEqual([c["vendor_doc"] for c in esito["copiati"]], [self.doc_ok.vendor_doc])
        self.assertEqual(esito["mancanti"], [])
        cartella = Path(esito["cartella"])
        self.assertEqual(
            [p.name for p in cartella.iterdir()], [f"{self.doc_ok.vendor_doc} Rev A.pdf"]
        )

    def test_nessuna_riga_cliente_nessuna_cartella_creata(self):
        trasmittal = self._trasmittal(
            [{"documento": self.doc_non_cliente, "revisione": "1", "cliente": False}]
        )

        esito = prepara_per_dcc(trasmittal)

        self.assertEqual(esito, {"cartella": None, "copiati": [], "mancanti": []})
        cartella_attesa = self.get_base_path("99030", "DCC") / "DA SPEDIRE" / trasmittal.nome
        self.assertFalse(cartella_attesa.exists())

    def test_documento_mancante_gli_altri_vengono_copiati(self):
        trasmittal = self._trasmittal(
            [
                {"documento": self.doc_ok, "revisione": "1", "cliente": True},
                {"documento": self.doc_missing, "revisione": "1", "cliente": True},
            ]
        )

        esito = prepara_per_dcc(trasmittal)

        self.assertEqual([c["vendor_doc"] for c in esito["copiati"]], [self.doc_ok.vendor_doc])
        self.assertEqual(
            [m["vendor_doc"] for m in esito["mancanti"]], [self.doc_missing.vendor_doc]
        )

    def test_codice_prefisso_di_un_altro_documento_copia_il_file_esatto(self):
        doc = Documento.objects.create(
            testata=self.testata, vendor_doc="99030-ESH1", reparto=self.reparto.nome
        )
        base = self.get_base_path("99030", "QMD")
        (base / "99030-ESH1.pdf").write_bytes(b"%PDF-esh1")
        (base / "99030-ESH10.pdf").write_bytes(b"%PDF-esh10")
        trasmittal = self._trasmittal([{"documento": doc, "revisione": "1", "cliente": True}])

        esito = prepara_per_dcc(trasmittal)

        self.assertEqual([c["file"] for c in esito["copiati"]], ["99030-ESH1.pdf"])
        self.assertEqual(esito["mancanti"], [])

    def test_seconda_esecuzione_idempotente(self):
        trasmittal = self._trasmittal(
            [{"documento": self.doc_ok, "revisione": "1", "cliente": True}]
        )

        esito1 = prepara_per_dcc(trasmittal)
        esito2 = prepara_per_dcc(trasmittal)

        self.assertEqual(esito1, esito2)
        cartella = Path(esito1["cartella"])
        self.assertEqual(len(list(cartella.iterdir())), 1)

    def test_percorso_fuori_dalla_jobs_root_rifiutato(self):
        testata_fuori = Testata.objects.create(job="../fuori")
        doc = Documento.objects.create(
            testata=testata_fuori, vendor_doc="X", reparto=self.reparto.nome
        )
        trasmittal = self._trasmittal(
            [{"documento": doc, "revisione": "1", "cliente": True}], testata=testata_fuori
        )

        with self.assertRaises(PermissionError):
            prepara_per_dcc(trasmittal)

    def test_non_interferisce_con_trasmittal_archivio(self):
        # La cartella "DA SPEDIRE/<nome lettera>" è sorella di "DA SPEDIRE/TRANSMITTAL",
        # non ci finisce dentro: trasmittal_archivio non deve accorgersene.
        from ..services.trasmittal_archivio import cartella_trasmittal, lista_trasmittal

        trasmittal = self._trasmittal(
            [{"documento": self.doc_ok, "revisione": "1", "cliente": True}]
        )

        prepara_per_dcc(trasmittal)

        self.assertEqual(lista_trasmittal("99030"), [])
        self.assertEqual(
            cartella_trasmittal("99030"), self.get_base_path("99030", "DCC") / "TRANSMITTAL"
        )


class TrasmittalInternoDestinazioniViewTests(TestCase):
    """Pagina e API della griglia destinazioni cartacee del trasmittal interno."""

    def setUp(self):
        self.client = Client()
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        Stabilimento.objects.create(nome="Milano")  # non è un sito costruttivo

        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.reparto_qc = Reparto.objects.create(nome="Qualità e Controllo", acronimo="QMD")

        self.testata = Testata.objects.create(job="99040", sito_costruttivo=self.bg)
        self.doc_alfa = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99040-ALFA",
            doc_title="Documento Alfa",
            reparto=self.reparto_ut.nome,
        )
        self.doc_beta = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99040-BETA",
            doc_title="Documento Beta",
            reparto=self.reparto_ut.nome,
        )
        # Un reparto con un acronimo fuori da UT/QC/WE: i suoi documenti restano fuori.
        self.doc_non_ut = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99040-QMD",
            reparto=self.reparto_qc.nome,
        )
        self.reparto_qc_vero = Reparto.objects.create(nome="Quality Control", acronimo="QC")
        self.doc_qc = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99040-QC",
            doc_title="Documento QC",
            reparto=self.reparto_qc_vero.nome,
        )

        self.writer = User.objects.create_user(
            "tidv_writer",
            "tidv-writer@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.reader = User.objects.create_user(
            "tidv_reader", "tidv-reader@b.it", "pw", permesso=Permesso.READING
        )

    def _pagina_url(self, job=None):
        return f"/commesse/{job or self.testata.job}/trasmittal-interno/"

    def _api_destinazioni_url(self, job=None):
        return f"/api/commesse/{job or self.testata.job}/trasmittal-interno/destinazioni/"

    def _api_documento_url(self, documento_id, job=None):
        return (
            f"/api/commesse/{job or self.testata.job}/trasmittal-interno/"
            f"documenti/{documento_id}/destinazioni/"
        )

    def _api_bulk_url(self, codice_bc, job=None):
        return (
            f"/api/commesse/{job or self.testata.job}/trasmittal-interno/"
            f"stabilimenti/{codice_bc}/destinazioni/"
        )

    # -- pagina --

    def test_pagina_richiede_login(self):
        risposta = self.client.get(self._pagina_url())
        self.assertNotEqual(risposta.status_code, 200)

    def test_pagina_risponde_e_mostra_i_documenti_della_commessa(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._pagina_url())

        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Trasmittal interno")

    # -- prerequisito: sito costruttivo --

    def test_commessa_senza_sito_costruttivo_accesso_diretto_rifiutato(self):
        Testata.objects.create(job="99041")  # niente sito_costruttivo
        self.client.force_login(self.reader)

        risposta = self.client.get(self._pagina_url(job="99041"))

        self.assertEqual(risposta.status_code, 403)

    def test_card_bloccata_in_pagina_commessa_senza_sito_costruttivo(self):
        Testata.objects.create(job="99042")
        self.client.force_login(self.reader)

        risposta = self.client.get("/commesse/99042/")

        # Il nome della classe compare anche nel <style> (regole CSS), quindi
        # va cercato sull'attributo class della card, non come sottostringa
        # libera nell'intera risposta.
        self.assertContains(risposta, 'class="section-card section-card-locked"')
        self.assertContains(risposta, "Completa prima il sito costruttivo della commessa")

    def test_card_non_bloccata_in_pagina_commessa_con_sito_costruttivo(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(f"/commesse/{self.testata.job}/")

        self.assertNotContains(risposta, 'class="section-card section-card-locked"')

    # -- API: lettura griglia --

    def test_api_destinazioni_richiede_login(self):
        risposta = self.client.get(self._api_destinazioni_url())
        self.assertNotEqual(risposta.status_code, 200)

    def test_api_destinazioni_elenca_i_documenti_ut_qc_e_we(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._api_destinazioni_url())

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertEqual(
            {d["vendor_doc"] for d in dati["documenti"]},
            {self.doc_alfa.vendor_doc, self.doc_beta.vendor_doc, self.doc_qc.vendor_doc},
        )
        self.assertEqual(
            [s["sigla"] for s in dati["stabilimenti"]], ["BG", "PD"]
        )  # niente Milano (senza codice_bc)

    # -- API: salvataggio per documento --

    def test_salvataggio_persiste_e_la_rilettura_mostra_le_destinazioni_spuntate(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._api_documento_url(self.doc_alfa.pk),
            data=json.dumps({"codici_bc": [1, 2]}),
            content_type="application/json",
        )
        self.assertEqual(risposta.status_code, 200)

        rilettura = self.client.get(self._api_destinazioni_url()).json()
        alfa = next(d for d in rilettura["documenti"] if d["id"] == self.doc_alfa.pk)
        self.assertEqual(sorted(alfa["codici_bc"]), [1, 2])
        beta = next(d for d in rilettura["documenti"] if d["id"] == self.doc_beta.pk)
        self.assertEqual(beta["codici_bc"], [])

    def test_salvataggio_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._api_documento_url(self.doc_alfa.pk),
            data=json.dumps({"codici_bc": [1]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(list(self.doc_alfa.destinazioni.all()), [])

    def test_salvataggio_su_documento_di_un_altro_reparto_rifiutato(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._api_documento_url(self.doc_non_ut.pk),
            data=json.dumps({"codici_bc": [1]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 404)

    # -- API: selezione in blocco --

    def test_selezione_in_blocco_agisce_solo_sui_documenti_filtrati(self):
        self.client.force_login(self.writer)
        imposta_destinazioni(self.doc_beta, [2])  # beta è già su PD, fuori dal filtro

        risposta = self.client.post(
            self._api_bulk_url(codice_bc=1),
            data=json.dumps({"documento_ids": [self.doc_alfa.pk], "attiva": True}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            sorted(self.doc_alfa.destinazioni.values_list("stabilimento__codice_bc", flat=True)),
            [1],
        )
        # doc_beta non era nel filtro (documento_ids): resta invariato.
        self.assertEqual(
            list(self.doc_beta.destinazioni.values_list("stabilimento__codice_bc", flat=True)),
            [2],
        )

    def test_selezione_in_blocco_puo_disattivare(self):
        self.client.force_login(self.writer)
        imposta_destinazioni(self.doc_alfa, [1, 2])
        imposta_destinazioni(self.doc_beta, [1])

        risposta = self.client.post(
            self._api_bulk_url(codice_bc=1),
            data=json.dumps(
                {"documento_ids": [self.doc_alfa.pk, self.doc_beta.pk], "attiva": False}
            ),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            sorted(self.doc_alfa.destinazioni.values_list("stabilimento__codice_bc", flat=True)),
            [2],
        )
        self.assertEqual(
            list(self.doc_beta.destinazioni.values_list("stabilimento__codice_bc", flat=True)), []
        )

    def test_selezione_in_blocco_ignora_id_estranei_a_questa_commessa(self):
        altra_testata = Testata.objects.create(job="99043", sito_costruttivo=self.bg)
        doc_altra = Documento.objects.create(
            testata=altra_testata,
            vendor_doc="99043-ALFA",
            reparto=self.reparto_ut.nome,
        )
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._api_bulk_url(codice_bc=1),
            data=json.dumps({"documento_ids": [self.doc_alfa.pk, doc_altra.pk], "attiva": True}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(list(doc_altra.destinazioni.all()), [])
        self.assertEqual(
            list(self.doc_alfa.destinazioni.values_list("stabilimento__codice_bc", flat=True)),
            [1],
        )

    def test_selezione_in_blocco_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._api_bulk_url(codice_bc=1),
            data=json.dumps({"documento_ids": [self.doc_alfa.pk], "attiva": True}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(list(self.doc_alfa.destinazioni.all()), [])


class TrasmittalInternoLetteraTests(TestCase):
    """Creazione della lettera: selezione, anteprima, conferma, elenco emesse."""

    def setUp(self):
        self.client = Client()

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99070", sito_costruttivo=self.bg)

        self.doc_ok = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99070-ALFA",
            doc_title="Documento Alfa",
            reparto=self.reparto_ut.nome,
        )
        Revisione.objects.create(documento=self.doc_ok, rev_no=0)
        imposta_destinazioni(self.doc_ok, [self.bg.codice_bc])
        from core.services.fileserver import get_base_path

        base = get_base_path(self.testata.job, "UT")
        base.mkdir(parents=True)
        (base / f"{self.doc_ok.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-fake")

        self.doc_senza_revisione = Documento.objects.create(
            testata=self.testata, vendor_doc="99070-BETA", reparto=self.reparto_ut.nome
        )
        self.doc_senza_file = Documento.objects.create(
            testata=self.testata, vendor_doc="99070-GAMMA", reparto=self.reparto_ut.nome
        )
        Revisione.objects.create(documento=self.doc_senza_file, rev_no=0)

        self.pm_utente = User.objects.create_user(
            "til_pm", "til-pm@b.it", "pw", first_name="Mario", last_name="PM"
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, utente=self.pm_utente
        )

        self.writer = User.objects.create_user(
            "til_writer",
            "til-writer@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.reader = User.objects.create_user(
            "til_reader", "til-reader@b.it", "pw", permesso=Permesso.READING
        )

    def _url(self, path):
        return f"/api/commesse/{self.testata.job}/trasmittal-interno/{path}"

    def _riga(self, documento, **overrides):
        base = {
            "documento_id": documento.pk,
            "revisione": "0",
            "copie": 2,
            "tpi": False,
            "note": "",
            "cliente": True,
        }
        base.update(overrides)
        return base

    # -- selezione --

    def test_documento_senza_revisione_non_selezionabile(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(
            d for d in risposta.json()["documenti"] if d["id"] == self.doc_senza_revisione.pk
        )
        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Nessuna revisione registrata.")

    def test_documento_senza_file_non_selezionabile(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_senza_file.pk)
        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Nessun file trovato sul fileserver.")

    def test_codice_prefisso_di_un_altro_documento_sceglie_il_file_esatto(self):
        # ESH1 e ESH10 sono documenti diversi: il file di ESH10 contiene "ESH1" ma
        # non deve rendere ambiguo il file di ESH1.
        doc = Documento.objects.create(
            testata=self.testata, vendor_doc="99070-01-ESH1", reparto=self.reparto_ut.nome
        )
        Revisione.objects.create(documento=doc, rev_no=0)
        base = get_base_path(self.testata.job, "UT")
        (base / "99070-01-ESH1.pdf").write_bytes(b"%PDF-esh1")
        (base / "99070-01-ESH10.pdf").write_bytes(b"%PDF-esh10")
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(d for d in risposta.json()["documenti"] if d["id"] == doc.pk)
        self.assertTrue(voce["selezionabile"])

    def test_piu_file_esatti_non_selezionabile_con_motivo_dedicato(self):
        base = get_base_path(self.testata.job, "UT")
        (base / f"{self.doc_ok.vendor_doc} Rev B.pdf").write_bytes(b"%PDF-fake-b")
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_ok.pk)
        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Più file corrispondenti sul fileserver.")

    def test_documento_valido_selezionabile(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_ok.pk)
        self.assertTrue(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "")

    # -- regola: solo la revisione da emettere (come in «Gestisci emissione») --

    def _voce_doc_ok(self):
        self.client.force_login(self.reader)
        risposta = self.client.get(self._url("selezione/"))
        return next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_ok.pk)

    def test_revisione_da_emettere_e_selezionabile(self):
        voce = self._voce_doc_ok()

        self.assertTrue(voce["selezionabile"])
        self.assertEqual(voce["revisioni_ammissibili"], [{"etichetta": "0", "numero": 0}])

    def test_revisione_in_lavorazione_e_selezionabile(self):
        Revisione.objects.filter(documento=self.doc_ok).update(int_status="in_lavorazione")

        voce = self._voce_doc_ok()

        self.assertTrue(voce["selezionabile"])

    def test_revisione_inviata_al_cliente_non_selezionabile(self):
        Revisione.objects.filter(documento=self.doc_ok).update(
            dis_act_date=date(2026, 1, 5), int_status="inviato_al_cliente"
        )

        voce = self._voce_doc_ok()

        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Rev 0 già inviata al cliente.")
        self.assertEqual(voce["revisioni_ammissibili"], [])

    def test_revisione_ricevuta_non_selezionabile(self):
        Revisione.objects.filter(documento=self.doc_ok).update(rec_act_date=date(2026, 1, 10))

        voce = self._voce_doc_ok()

        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Rev 0 già ricevuta dal cliente.")

    def test_revisione_con_risposta_del_cliente_non_selezionabile(self):
        # Basta la risposta registrata, anche senza data di rientro.
        risposta_cliente = StatoEsterno.objects.create(nome="Approved", lettera="A")
        Revisione.objects.filter(documento=self.doc_ok).update(ext_status=risposta_cliente)

        voce = self._voce_doc_ok()

        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Rev 0 già ricevuta dal cliente.")

    def test_nuova_revisione_dopo_la_risposta_e_selezionabile(self):
        # Rev 0 rientrata, Rev 1 appena creata: la lettera accompagna solo la Rev 1.
        Revisione.objects.filter(documento=self.doc_ok).update(rec_act_date=date(2026, 1, 10))
        Revisione.objects.create(documento=self.doc_ok, rev_no=1)

        voce = self._voce_doc_ok()

        self.assertTrue(voce["selezionabile"])
        self.assertEqual(voce["revisione_corrente"], "1")
        self.assertEqual(voce["revisioni_ammissibili"], [{"etichetta": "1", "numero": 1}])

    def test_anteprima_rifiuta_revisione_non_ammissibile(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, revisione="1")]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("non è ammessa", risposta.json()["error"])

    def test_selezione_revisione_corrente_con_sequenza_personalizzata(self):
        self.testata.rev_sequenza = ["P", "Q"]
        self.testata.save(update_fields=["rev_sequenza"])
        Revisione.objects.filter(documento=self.doc_ok).update(rec_act_date=date(2026, 1, 10))
        Revisione.objects.create(documento=self.doc_ok, rev_no=1)
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        voce = next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_ok.pk)
        self.assertEqual(voce["revisione_corrente"], "Q")
        # Lo stepper usa l'etichetta già formattata dal server.
        self.assertEqual(voce["revisioni_ammissibili"], [{"etichetta": "Q", "numero": 1}])

    def test_selezione_riporta_i_siti_costruttivi(self):
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url("selezione/"))

        self.assertEqual(
            risposta.json()["stabilimenti"],
            [{"codice_bc": 1, "sigla": "BG", "nome": "Valbrembo"}],
        )

    def test_selezione_e_destinazioni_riportano_l_ultima_modifica_del_file(self):
        percorso = get_base_path(self.testata.job, "UT") / f"{self.doc_ok.vendor_doc} Rev A.pdf"
        istante = timezone.make_aware(datetime(2026, 3, 2, 9, 30)).timestamp()
        os.utime(percorso, (istante, istante))
        self.client.force_login(self.reader)

        for path in ("selezione/", "destinazioni/"):
            with self.subTest(path=path):
                risposta = self.client.get(self._url(path))

                documenti = {d["id"]: d for d in risposta.json()["documenti"]}
                self.assertEqual(
                    documenti[self.doc_ok.pk]["file_modificato_il"], "2026-03-02T09:30:00+01:00"
                )
                self.assertIsNone(documenti[self.doc_senza_file.pk]["file_modificato_il"])

    # -- anteprima --

    def test_anteprima_mostra_destinatari_risolti_con_origine(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        destinatari = risposta.json()["destinatari"]
        self.assertIn({"email": "bg@b.it", "tipo": "to", "origine": "stabilimento"}, destinatari)
        self.assertIn({"email": "til-pm@b.it", "tipo": "to", "origine": "pm"}, destinatari)
        self.assertEqual(sorted(risposta.json()["ruoli_mancanti"]), ["PE", "QCI"])

    def test_anteprima_include_nome_e_percorso_pdf_previsti(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, cliente=False)]}),
            content_type="application/json",
        )

        corpo = risposta.json()
        self.assertTrue(corpo["nome_preview"].startswith(f"{self.testata.job}_"))
        self.assertTrue(corpo["percorso_pdf_preview"].endswith(f"{corpo['nome_preview']}.pdf"))
        self.assertIsNone(corpo["percorso_dcc_preview"])

    def test_anteprima_percorso_dcc_previsto_solo_con_un_documento_cliente(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, cliente=True)]}),
            content_type="application/json",
        )

        corpo = risposta.json()
        self.assertIsNotNone(corpo["percorso_dcc_preview"])
        self.assertIn(corpo["nome_preview"], corpo["percorso_dcc_preview"])

    def test_anteprima_rifiuta_documento_non_selezionabile(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_senza_revisione)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("revisione", risposta.json()["error"].lower())

    # -- conferma --

    def test_conferma_crea_trasmittal_e_invia_l_email_senza_pdf_ne_dcc(self):
        from core.services.trasmittal_interno import _percorso_dcc_da, percorso_pdf

        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)], "note": "riga 1\nriga 2"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        self.assertTrue(corpo["ok"])
        self.assertTrue(corpo["email"]["ok"])
        self.assertEqual(corpo["stato"], "in_attesa")
        self.assertEqual(corpo["ruoli_mancanti"], ["QC", "PROD"])
        # PDF e cartella DCC arrivano solo dopo le due prese visione.
        self.assertNotIn("pdf", corpo)
        self.assertNotIn("dcc", corpo)
        lettera = TransmittalInterno.objects.get(pk=corpo["trasmittal_id"])
        self.assertFalse(percorso_pdf(lettera).exists())
        self.assertFalse(_percorso_dcc_da(self.testata.job, lettera.nome).exists())

        self.assertEqual(TransmittalInterno.objects.filter(testata=self.testata).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["bg@b.it", "til-pm@b.it"])
        self.assertEqual(len(mail.outbox[0].attachments), 0)

    def test_destinatari_modificati_in_anteprima_sono_quelli_usati_e_registrati(self):
        self.client.force_login(self.writer)
        destinatari_modificati = [
            {"email": "extra@b.it", "tipo": "to", "origine": "manuale"},
        ]

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps(
                {"righe": [self._riga(self.doc_ok)], "destinatari": destinatari_modificati}
            ),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        trasmittal = TransmittalInterno.objects.get(pk=risposta.json()["trasmittal_id"])
        registrati = list(trasmittal.destinatari.values_list("email", "tipo", "origine"))
        self.assertEqual(registrati, [("extra@b.it", "to", "manuale")])
        self.assertEqual(mail.outbox[0].to, ["extra@b.it"])
        # I destinatari auto-risolti (stabilimento, PM) non compaiono più:
        # quelli confermati in anteprima sono gli unici usati.
        self.assertNotIn("bg@b.it", mail.outbox[0].to)

    def test_conferma_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(TransmittalInterno.objects.count(), 0)

    def test_invio_email_fallito_la_lettera_resta_in_archivio_e_l_errore_e_visibile(self):
        self.client.force_login(self.writer)

        with patch(
            "django.core.mail.EmailMessage.send", side_effect=Exception("SMTP non raggiungibile")
        ):
            risposta = self.client.post(
                self._url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            )

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        self.assertTrue(corpo["ok"])
        self.assertFalse(corpo["email"]["ok"])
        self.assertIn("SMTP non raggiungibile", corpo["email"]["errore"])
        # La lettera resta in archivio nonostante l'invio email fallito.
        self.assertTrue(TransmittalInterno.objects.filter(pk=corpo["trasmittal_id"]).exists())
        self.assertEqual(corpo["stato"], "in_attesa")
        self.assertEqual(len(mail.outbox), 0)

    # -- mittente: chi ha compilato ed emesso la lettera --

    def _pdf_finto(self):
        """Sostituisce la generazione del PDF nel completamento della lettera.

        Il rendering vero non c'entra con l'elenco e le email e dipende dai
        font di sistema (``src.pdf._register_unicode_font``): sostituirlo tiene
        questi test sui passi che verificano.
        """
        return patch("src.pdf.genera_trasmittal_interno_pdf", return_value=b"%PDF-1.4 finto")

    # Il server di posta accetta solo la casella dell'app come mittente: l'email
    # parte da lì, chi ha emesso la lettera è nel testo e riceve risposte e copia.
    MITTENTE_WRITER = "workflow@b.it"

    @override_settings(DEFAULT_FROM_EMAIL="Workflow <workflow@b.it>")
    def test_email_parte_dalla_casella_dell_app_e_dice_chi_ha_emesso_la_lettera(self):
        self.client.force_login(self.writer)

        with self._pdf_finto():
            risposta = self.client.post(
                self._url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        inviata = mail.outbox[0]
        self.assertEqual(inviata.from_email, self.MITTENTE_WRITER)
        # Le risposte e una copia vanno a chi ha emesso la lettera.
        self.assertEqual(inviata.reply_to, [f"til_writer <{self.writer.email}>"])
        self.assertIn(self.writer.email, inviata.cc)
        self.assertIn(f"— emesso da til_writer ({self.writer.email}).", inviata.body)
        self.assertEqual(risposta.json()["email"]["mittente"], self.MITTENTE_WRITER)
        self.assertIn(self.writer.email, risposta.json()["email"]["cc"])

    def test_messaggio_scritto_prima_dell_invio_finisce_nell_email_e_resta_per_riprova(self):
        self.client.force_login(self.writer)
        with self._pdf_finto():
            risposta = self.client.post(
                self._url("emetti/"),
                data=json.dumps(
                    {"righe": [self._riga(self.doc_ok)], "messaggio": "  Ritirare in reception.  "}
                ),
                content_type="application/json",
            )

        self.assertEqual(risposta.status_code, 200)
        lettera = TransmittalInterno.objects.get(pk=risposta.json()["trasmittal_id"])
        self.assertEqual(lettera.messaggio_email, "Ritirare in reception.")
        self.assertIn("Ritirare in reception.", mail.outbox[0].body)

        with self._pdf_finto():
            self.client.post(
                self._url(f"lettere/{lettera.pk}/retry/"),
                data=json.dumps({"step": "email"}),
                content_type="application/json",
            )
        self.assertIn("Ritirare in reception.", mail.outbox[1].body)

    def test_messaggio_troppo_lungo_non_crea_la_lettera(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)], "messaggio": "x" * 2001}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("2000 caratteri", risposta.json()["error"])
        self.assertFalse(TransmittalInterno.objects.filter(testata=self.testata).exists())

    def test_destinatario_non_valido_non_lascia_una_lettera_orfana(self):
        """La lettera si crea prima della validazione dei destinatari confermati:
        se questa fallisce, lettera e progressivo del giorno non devono restare
        nel database (senza PDF, cartella DCC né email), altrimenti il
        tentativo successivo produce una seconda lettera."""
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps(
                {
                    "righe": [self._riga(self.doc_ok)],
                    "destinatari": [{"email": "non-una-email", "tipo": "to", "origine": "manuale"}],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("non valido", risposta.json()["error"])
        self.assertFalse(TransmittalInterno.objects.filter(testata=self.testata).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_etichetta_di_revisione_troppo_lunga_e_un_400_non_un_500(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, revisione="A" * 11)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("10 caratteri", risposta.json()["error"])
        self.assertFalse(TransmittalInterno.objects.filter(testata=self.testata).exists())

    def test_il_pannello_di_conferma_ha_il_campo_messaggio(self):
        self.client.force_login(self.writer)

        pagina = self.client.get(f"/commesse/{self.testata.job}/trasmittal-interno/")

        self.assertContains(pagina, "Messaggio nell")
        self.assertContains(pagina, "messaggio: _messaggioEmail.trim()")

    @override_settings(DEFAULT_FROM_EMAIL="Workflow <workflow@b.it>")
    def test_anteprima_riporta_il_mittente_di_chi_sta_compilando(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["mittente"], self.MITTENTE_WRITER)

    @override_settings(DEFAULT_FROM_EMAIL="Workflow <workflow@b.it>")
    def test_retry_email_parte_dal_mittente_di_chi_ha_emesso_non_di_chi_riprova(self):
        self.client.force_login(self.writer)
        with (
            self._pdf_finto(),
            patch(
                "django.core.mail.EmailMessage.send",
                side_effect=Exception("SMTP non raggiungibile"),
            ),
        ):
            esito = self.client.post(
                self._url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            ).json()
        self.assertFalse(esito["email"]["ok"])

        altro_writer = User.objects.create_user(
            "til_writer2",
            "til-writer2@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.client.force_login(altro_writer)
        with self._pdf_finto():
            risposta = self.client.post(
                self._url(f"lettere/{esito['trasmittal_id']}/retry/"),
                data=json.dumps({"step": "email"}),
                content_type="application/json",
            )

        self.assertEqual(risposta.status_code, 200)
        self.assertTrue(risposta.json()["esito"]["ok"])
        self.assertEqual(risposta.json()["esito"]["mittente"], self.MITTENTE_WRITER)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, self.MITTENTE_WRITER)
        self.assertIn(self.writer.email, mail.outbox[0].cc)
        self.assertNotIn(altro_writer.email, mail.outbox[0].cc)

    @override_settings(DEFAULT_FROM_EMAIL="Workflow <workflow@b.it>")
    def test_esito_email_fallita_riporta_comunque_il_mittente(self):
        self.client.force_login(self.writer)

        with (
            self._pdf_finto(),
            patch(
                "django.core.mail.EmailMessage.send",
                side_effect=Exception("SMTP non raggiungibile"),
            ),
        ):
            esito = self.client.post(
                self._url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            ).json()

        self.assertFalse(esito["email"]["ok"])
        self.assertEqual(esito["email"]["mittente"], self.MITTENTE_WRITER)

    # -- elenco lettere emesse --

    def test_elenco_segnala_le_lettere_senza_pdf_sul_fileserver(self):
        from core.services.trasmittal_interno import percorso_pdf

        qc = User.objects.create_user("til_qc", "til-qc@b.it", "pw")
        prod = User.objects.create_user("til_prod", "til-prod@b.it", "pw")
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg, ruolo=RuoloFirmatarioStabilimento.QUALITA, utente=qc
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg, ruolo=RuoloFirmatarioStabilimento.PRODUZIONE, utente=prod
        )
        self.client.force_login(self.writer)
        emessa = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        ).json()
        lettera = TransmittalInterno.objects.get(pk=emessa["trasmittal_id"])
        with self._pdf_finto():
            registra_presa_visione(lettera, qc)
            registra_presa_visione(lettera, prod)

        voce = self.client.get(self._url("lettere/")).json()["lettere"][0]
        self.assertTrue(voce["pdf_presente"])

        percorso_pdf(lettera).unlink()
        voce = self.client.get(self._url("lettere/")).json()["lettere"][0]
        self.assertFalse(voce["pdf_presente"])

        pagina = self.client.get(f"/commesse/{self.testata.job}/trasmittal-interno/")
        self.assertContains(pagina, "l.pdf_presente === false")

    def test_elenco_lettere_emesse_in_ordine(self):
        self.client.force_login(self.writer)
        for _ in range(2):
            self.client.post(
                self._url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            )

        risposta = self.client.get(self._url("lettere/"))

        lettere = risposta.json()["lettere"]
        self.assertEqual(len(lettere), 2)
        self.assertEqual(lettere[0]["nome"], "99070_" + timezone.localdate().isoformat() + "_E2")
        self.assertEqual(lettere[1]["nome"], "99070_" + timezone.localdate().isoformat() + "_E1")
        self.assertEqual(lettere[0]["n_documenti"], 1)
        self.assertEqual(lettere[0]["creato_da"], self.writer.nome_completo)


@override_settings(DEFAULT_FROM_EMAIL="Workflow <noreply@b.it>")
class MittenteEmailTrasmittalInternoTests(TestCase):
    """L'email parte dalla casella dell'app; chi ha emesso la lettera è nel testo.

    Il server di posta rifiuta un mittente diverso dalla casella con cui l'app
    si autentica (550 5.7.0 Authentication rejected).
    """

    def setUp(self):
        _media_temporanea(self)

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        jobs_patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        jobs_patcher.enable()
        self.addCleanup(jobs_patcher.disable)

        self.emittente = User.objects.create_user(
            "mittente_ti", "anna.bianchi@b.it", "pw", first_name="Anna", last_name="Bianchi"
        )

    def _trasmittal(self, utente):
        testata = Testata.objects.create(job="99095")
        documento = Documento.objects.create(testata=testata, vendor_doc="99095-ALFA")
        data = date(2026, 9, 14)
        trasmittal = TransmittalInterno.objects.create(
            testata=testata,
            data=data,
            progressivo=1,
            nome=componi_nome(testata, data, 1),
            creato_da=utente,
        )
        RigaTransmittalInterno.objects.create(
            trasmittal=trasmittal, documento=documento, revisione="0", posizione=1
        )
        trasmittal.destinatari.create(email="dest@b.it", tipo="to", origine="manuale")
        return trasmittal

    MITTENTE = "noreply@b.it"

    def test_mittente_e_solo_l_indirizzo_della_casella_dell_app(self):
        # Il nome di DEFAULT_FROM_EMAIL ("Workflow") non compare.
        self.assertEqual(mittente_trasmittal(self.emittente), self.MITTENTE)

    @override_settings(DEFAULT_FROM_EMAIL="workflow@b.it")
    def test_mittente_senza_nome_nel_env(self):
        self.assertEqual(mittente_trasmittal(self.emittente), "workflow@b.it")

    def test_invio_dalla_casella_dell_app_con_risposte_e_copia_a_chi_ha_emesso(self):
        trasmittal = self._trasmittal(self.emittente)

        esito = invia_email_emissione(trasmittal)

        self.assertEqual(esito["mittente"], self.MITTENTE)
        self.assertEqual(esito["cc"], ["anna.bianchi@b.it"])
        self.assertEqual(len(mail.outbox), 1)
        inviata = mail.outbox[0]
        self.assertEqual(inviata.from_email, self.MITTENTE)
        self.assertEqual(inviata.reply_to, ["Anna Bianchi <anna.bianchi@b.it>"])
        self.assertEqual(inviata.to, ["dest@b.it"])
        self.assertEqual(inviata.cc, ["anna.bianchi@b.it"])
        self.assertTrue(
            inviata.body.startswith(
                "Trasmittal interno 99095_2026-09-14_E1 — commessa 99095 "
                "— emesso da Anna Bianchi (anna.bianchi@b.it)."
            )
        )
        self.assertNotIn("Inviata da", inviata.body)

    def test_chi_ha_emesso_non_va_in_copia_due_volte(self):
        trasmittal = self._trasmittal(self.emittente)
        trasmittal.destinatari.create(email="Anna.Bianchi@b.it", tipo="cc", origine="manuale")

        invia_email_emissione(trasmittal)

        self.assertEqual(mail.outbox[0].cc, ["Anna.Bianchi@b.it"])

    def test_utente_senza_email_niente_risposte_ne_copia(self):
        senza_email = User.objects.create_user("senza_email", "", "pw")
        trasmittal = self._trasmittal(senza_email)

        invia_email_emissione(trasmittal)

        self.assertEqual(mail.outbox[0].from_email, "noreply@b.it")
        self.assertEqual(mail.outbox[0].reply_to, [])
        self.assertEqual(mail.outbox[0].cc, [])
        self.assertIn("— emesso da senza_email.", mail.outbox[0].body)

    def test_il_messaggio_e_sopra_la_tabella_le_note_nel_riquadro_notes(self):
        trasmittal = self._trasmittal(self.emittente)
        trasmittal.messaggio_email = "Consegnare entro venerdì.\nCopia per l'ufficio <qualità>."
        trasmittal.note = "Nota del modulo"
        trasmittal.save(update_fields=["messaggio_email", "note"])

        invia_email_emissione(trasmittal)

        inviata = mail.outbox[0]
        self.assertIn(
            "anna.bianchi@b.it).\n\nConsegnare entro venerdì.\nCopia per l'ufficio <qualità>.\n\nB&R",
            inviata.body,
        )
        # Le note della lettera sono nel riquadro NOTES, numerate come nel PDF.
        self.assertIn("NOTES\n1) Nota del modulo\n2)\n3)\n\n", inviata.body)
        html = inviata.alternatives[0][0]
        self.assertIn(
            "<p>Consegnare entro venerdì.<br>Copia per l&#x27;ufficio &lt;qualità&gt;.</p>", html
        )
        self.assertIn("— emesso da Anna Bianchi (anna.bianchi@b.it).", html)

    def test_senza_messaggio_nessun_paragrafo_vuoto(self):
        trasmittal = self._trasmittal(self.emittente)

        invia_email_emissione(trasmittal)

        self.assertIn("(anna.bianchi@b.it).\n\nB&R DOC. No.", mail.outbox[0].body)

    @override_settings(TRASMITTAL_INTERNO_EMAIL_TEST_REDIRECT="prove@b.it")
    def test_redirect_di_test_cambia_i_destinatari_ma_non_il_mittente(self):
        trasmittal = self._trasmittal(self.emittente)

        esito = invia_email_emissione(trasmittal)

        self.assertEqual(esito["to"], ["dest@b.it"])  # gli indirizzi reali, nell'esito
        self.assertEqual(mail.outbox[0].to, ["prove@b.it"])  # il reindirizzamento di test
        self.assertEqual(mail.outbox[0].cc, [])
        self.assertEqual(mail.outbox[0].from_email, self.MITTENTE)


class TrasmittalInternoEmissioneApiTests(TestCase):
    """Anteprima, emissione e retry per-passo (API): il flusso "Nuova lettera"

    gira interamente in modal nella pagina ``trasmittal-interno/``, quindi
    ``self.client`` (che non esegue JavaScript) non può esercitarlo dal vivo.
    L'evidenziazione dello stepper, "Emetti non invia finché il pannello non
    è confermato" (oltre alla garanzia di non-scrittura testata qui) e
    "l'assegnazione siti inline non perde lo stato delle altre righe" restano
    verifiche manuali/di browser — le garanzie server-side sottostanti sono
    invece testate qui, direttamente sulle API, e in
    ``TrasmittalInternoDestinazioniViewTests``.
    """

    def setUp(self):
        self.client = Client()

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99075", sito_costruttivo=self.bg)

        self.doc_ok = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99075-ALFA",
            doc_title="Documento Alfa",
            reparto=self.reparto_ut.nome,
        )
        Revisione.objects.create(documento=self.doc_ok, rev_no=0)
        imposta_destinazioni(self.doc_ok, [self.bg.codice_bc])
        from core.services.fileserver import get_base_path

        base = get_base_path(self.testata.job, "UT")
        base.mkdir(parents=True)
        (base / f"{self.doc_ok.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-fake")

        self.writer = User.objects.create_user(
            "tinp_writer",
            "tinp-writer@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.reader = User.objects.create_user(
            "tinp_reader", "tinp-reader@b.it", "pw", permesso=Permesso.READING
        )

    def _url_detail(self):
        return f"/commesse/{self.testata.job}/trasmittal-interno/"

    def _api_url(self, path):
        return f"/api/commesse/{self.testata.job}/trasmittal-interno/{path}"

    def _riga(self, documento, **overrides):
        base = {
            "documento_id": documento.pk,
            "revisione": "0",
            "copie": 1,
            "tpi": False,
            "note": "",
            "cliente": True,
        }
        base.update(overrides)
        return base

    def test_pagina_trasmittal_interno_richiede_sito_costruttivo(self):
        self.testata.sito_costruttivo = None
        self.testata.save(update_fields=["sito_costruttivo"])
        self.client.force_login(self.reader)

        risposta = self.client.get(self._url_detail())

        self.assertEqual(risposta.status_code, 403)

    # -- revisione modificata --

    def test_revisione_da_emettere_viene_usata_nella_lettera(self):
        # Rev 0 rientrata, Rev 1 da emettere: la lettera porta la "1".
        Revisione.objects.filter(documento=self.doc_ok).update(rec_act_date=date(2026, 1, 10))
        Revisione.objects.create(documento=self.doc_ok, rev_no=1)
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._api_url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, revisione="1")]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        trasmittal_id = risposta.json()["trasmittal_id"]
        riga = RigaTransmittalInterno.objects.get(
            trasmittal_id=trasmittal_id, documento=self.doc_ok
        )
        self.assertEqual(riga.revisione, "1")

    def test_revisione_non_ammissibile_e_un_400(self):
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._api_url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok, revisione="C")]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("non è ammessa", risposta.json()["error"])
        self.assertFalse(RigaTransmittalInterno.objects.filter(documento=self.doc_ok).exists())

    # -- "Emetti" non invia finché il pannello non è confermato --

    def test_anteprima_non_scrive_nulla(self):
        self.client.force_login(self.reader)

        self.client.post(
            self._api_url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        )

        self.assertEqual(TransmittalInterno.objects.count(), 0)

    def test_anteprima_include_sigle_stabilimento(self):
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._api_url("anteprima/"),
            data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
            content_type="application/json",
        )

        sigle = risposta.json()["sigle_stabilimento"]
        self.assertEqual(sigle.get("bg@b.it"), ["BG"])

    # -- esito con un passo fallito: retry per-passo --

    def _emetti_con_email_fallita(self):
        with patch(
            "django.core.mail.EmailMessage.send", side_effect=Exception("SMTP non raggiungibile")
        ):
            risposta = self.client.post(
                self._api_url("emetti/"),
                data=json.dumps({"righe": [self._riga(self.doc_ok)]}),
                content_type="application/json",
            )
        return risposta.json()

    def test_retry_email_riesce_dopo_un_fallimento(self):
        self.client.force_login(self.writer)
        corpo = self._emetti_con_email_fallita()
        self.assertFalse(corpo["email"]["ok"])
        self.assertEqual(len(mail.outbox), 0)

        risposta = self.client.post(
            self._api_url(f"lettere/{corpo['trasmittal_id']}/retry/"),
            data=json.dumps({"step": "email"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        corpo_retry = risposta.json()
        self.assertTrue(corpo_retry["ok"])
        self.assertTrue(corpo_retry["esito"]["ok"])
        self.assertEqual(len(mail.outbox), 1)

    def test_retry_richiede_login(self):
        risposta = self.client.post(
            self._api_url("lettere/1/retry/"),
            data=json.dumps({"step": "email"}),
            content_type="application/json",
        )
        self.assertEqual(risposta.status_code, 401)

    def test_retry_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.writer)
        corpo = self._emetti_con_email_fallita()
        self.client.force_login(self.reader)

        risposta = self.client.post(
            self._api_url(f"lettere/{corpo['trasmittal_id']}/retry/"),
            data=json.dumps({"step": "email"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)

    def test_retry_lettera_di_un_altra_commessa_404(self):
        self.client.force_login(self.writer)
        corpo = self._emetti_con_email_fallita()

        altra = Testata.objects.create(job="99076", sito_costruttivo=self.bg)
        risposta = self.client.post(
            f"/api/commesse/{altra.job}/trasmittal-interno/lettere/{corpo['trasmittal_id']}/retry/",
            data=json.dumps({"step": "email"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 404)

    def test_retry_step_non_valido_400(self):
        self.client.force_login(self.writer)
        corpo = self._emetti_con_email_fallita()

        risposta = self.client.post(
            self._api_url(f"lettere/{corpo['trasmittal_id']}/retry/"),
            data=json.dumps({"step": "qualcosa"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)


class AnnullaTrasmittalInternoTests(TestCase):
    """Annullamento di una lettera emessa per errore."""

    def setUp(self):
        self.client = Client()
        _media_temporanea(self)

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99080", sito_costruttivo=self.bg)

        from core.services.fileserver import get_base_path

        self.get_base_path = get_base_path
        base = get_base_path(self.testata.job, "UT")
        base.mkdir(parents=True)

        self.doc1 = Documento.objects.create(
            testata=self.testata, vendor_doc="99080-ALFA", reparto=self.reparto_ut.nome
        )
        Revisione.objects.create(documento=self.doc1, rev_no=0)
        imposta_destinazioni(self.doc1, [self.bg.codice_bc])
        (base / f"{self.doc1.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-1")

        self.doc2 = Documento.objects.create(
            testata=self.testata, vendor_doc="99080-BETA", reparto=self.reparto_ut.nome
        )
        Revisione.objects.create(documento=self.doc2, rev_no=0)
        imposta_destinazioni(self.doc2, [self.bg.codice_bc])
        (base / f"{self.doc2.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-2")

        self.writer = User.objects.create_user(
            "ann_writer",
            "ann-writer@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.reader = User.objects.create_user(
            "ann_reader", "ann-reader@b.it", "pw", permesso=Permesso.READING
        )
        self.qc = User.objects.create_user("ann_qc", "ann-qc@b.it", "pw")
        self.prod = User.objects.create_user("ann_prod", "ann-prod@b.it", "pw")
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg, ruolo=RuoloFirmatarioStabilimento.QUALITA, utente=self.qc
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.bg, ruolo=RuoloFirmatarioStabilimento.PRODUZIONE, utente=self.prod
        )

    def _url(self, path):
        return f"/api/commesse/{self.testata.job}/trasmittal-interno/{path}"

    def _emetti(self, documento, completa=True):
        """Emette la lettera e, con ``completa``, registra le prese visione QC e PROD:
        il risultato porta anche gli esiti ``pdf`` e ``dcc`` del completamento."""
        emesso = self.client.post(
            self._url("emetti/"),
            data=json.dumps(
                {"righe": [{"documento_id": documento.pk, "revisione": "0", "cliente": True}]}
            ),
            content_type="application/json",
        ).json()
        if not completa:
            return emesso
        lettera = TransmittalInterno.objects.get(pk=emesso["trasmittal_id"])
        registra_presa_visione(lettera, self.qc)
        completata = registra_presa_visione(lettera, self.prod)
        return {**emesso, **completata["completamento"]}

    def test_annullamento_dell_ultimo_riesce_e_rimuove_record_pdf_e_cartella_dcc(self):
        self.client.force_login(self.writer)
        emesso = self._emetti(self.doc1)
        pdf_path = Path(emesso["pdf"]["percorso"])
        cartella_dcc = Path(emesso["dcc"]["cartella"])
        self.assertTrue(pdf_path.is_file())
        self.assertTrue(cartella_dcc.is_dir())

        risposta = self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        self.assertTrue(corpo["ok"])
        self.assertTrue(corpo["pdf_rimosso"])
        self.assertTrue(corpo["cartella_dcc_rimossa"])
        self.assertIn("email", corpo["email_avviso"].lower())
        self.assertFalse(TransmittalInterno.objects.filter(pk=emesso["trasmittal_id"]).exists())
        self.assertFalse(pdf_path.exists())
        self.assertFalse(cartella_dcc.exists())
        # Le prese visione se ne vanno con la lettera (CASCADE).
        self.assertFalse(
            PresaVisioneTransmittalInterno.objects.filter(
                trasmittal_id=emesso["trasmittal_id"]
            ).exists()
        )

    def test_annullamento_di_una_lettera_in_attesa_con_una_presa_visione(self):
        self.client.force_login(self.writer)
        emesso = self._emetti(self.doc1, completa=False)
        lettera = TransmittalInterno.objects.get(pk=emesso["trasmittal_id"])
        registra_presa_visione(lettera, self.qc)

        risposta = self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        # Nessun PDF né cartella DCC da togliere: la lettera non era completata.
        self.assertFalse(corpo["pdf_rimosso"])
        self.assertFalse(corpo["cartella_dcc_rimossa"])
        self.assertFalse(TransmittalInterno.objects.filter(pk=lettera.pk).exists())
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())

    def test_annullamento_di_uno_non_ultimo_rifiutato(self):
        self.client.force_login(self.writer)
        primo = self._emetti(self.doc1)
        self._emetti(self.doc2)  # secondo, ora è lui l'ultimo

        risposta = self.client.post(self._url(f"lettere/{primo['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 409)
        self.assertIn("ultimo", risposta.json()["error"].lower())
        self.assertTrue(TransmittalInterno.objects.filter(pk=primo["trasmittal_id"]).exists())
        self.assertTrue(Path(primo["pdf"]["percorso"]).is_file())

    def test_progressivo_successivo_riparte_dal_numero_liberato(self):
        self.client.force_login(self.writer)
        emesso = self._emetti(self.doc1)
        self.assertTrue(emesso["nome"].endswith("_E1"))
        self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        rifatto = self._emetti(self.doc2)

        self.assertTrue(rifatto["nome"].endswith("_E1"))

    def test_cartella_dcc_con_contenuto_estraneo_non_viene_rimossa(self):
        self.client.force_login(self.writer)
        emesso = self._emetti(self.doc1)
        cartella_dcc = Path(emesso["dcc"]["cartella"])
        estraneo = cartella_dcc / "documento_non_nostro.pdf"
        estraneo.write_bytes(b"%PDF-estraneo")

        risposta = self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        self.assertFalse(corpo["cartella_dcc_rimossa"])
        # Il file di questo trasmittal è stato rimosso, quello estraneo no.
        self.assertTrue(cartella_dcc.is_dir())
        self.assertEqual([p.name for p in cartella_dcc.iterdir()], ["documento_non_nostro.pdf"])
        self.assertTrue(estraneo.exists())

    def test_annullamento_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.writer)
        emesso = self._emetti(self.doc1)
        self.client.logout()
        self.client.force_login(self.reader)

        risposta = self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 403)
        self.assertTrue(TransmittalInterno.objects.filter(pk=emesso["trasmittal_id"]).exists())

    def test_annullamento_richiede_login(self):
        emesso_writer = Client()
        emesso_writer.force_login(self.writer)
        emesso = emesso_writer.post(
            self._url("emetti/"),
            data=json.dumps(
                {"righe": [{"documento_id": self.doc1.pk, "revisione": "0", "cliente": True}]}
            ),
            content_type="application/json",
        ).json()

        risposta = self.client.post(self._url(f"lettere/{emesso['trasmittal_id']}/annulla/"))

        self.assertNotEqual(risposta.status_code, 200)

    def test_annullabile_solo_sull_ultimo_nella_lista_lettere(self):
        self.client.force_login(self.writer)
        primo = self._emetti(self.doc1)
        secondo = self._emetti(self.doc2)

        lettere = {
            voce["id"]: voce for voce in self.client.get(self._url("lettere/")).json()["lettere"]
        }

        self.assertFalse(lettere[primo["trasmittal_id"]]["annullabile"])
        self.assertTrue(lettere[secondo["trasmittal_id"]]["annullabile"])


class TrasmittalInternoPermessoRistrettoTests(TestCase):
    """La scrittura del trasmittal interno è riservata a chi ha il flag

    ``User.trasmittal_interno_writer`` (impostabile da admin), indipendentemente
    dal permesso generale (ADMIN/WRITING/READING): un admin "qualunque" senza
    il flag non può scrivere, un utente con il flag può anche se il suo
    permesso generale è solo READING. La pagina resta visibile a tutti.
    """

    def setUp(self):
        self.client = Client()
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99090", sito_costruttivo=self.bg)
        self.doc = Documento.objects.create(
            testata=self.testata, vendor_doc="99090-ALFA", reparto=self.reparto_ut.nome
        )

        # Permesso generale ADMIN, ma senza il flag: deve essere bloccato.
        self.admin_non_autorizzato = User.objects.create_user(
            "trp_admin", "trp-admin@b.it", "pw", permesso=Permesso.ADMIN
        )
        # Permesso generale READING, ma con il flag: deve poter scrivere.
        self.autorizzato_reading = User.objects.create_user(
            "trp_autorizzato",
            "trp-autorizzato@b.it",
            "pw",
            permesso=Permesso.READING,
            trasmittal_interno_writer=True,
        )

    def _url(self, path):
        return f"/api/commesse/{self.testata.job}/trasmittal-interno/{path}"

    def test_admin_generico_non_autorizzato_riceve_403_su_destinazioni_documento(self):
        self.client.force_login(self.admin_non_autorizzato)

        risposta = self.client.post(
            self._url(f"documenti/{self.doc.pk}/destinazioni/"),
            data=json.dumps({"codici_bc": [1]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(list(self.doc.destinazioni.all()), [])

    def test_admin_generico_non_autorizzato_riceve_403_su_destinazioni_bulk(self):
        self.client.force_login(self.admin_non_autorizzato)

        risposta = self.client.post(
            self._url("stabilimenti/1/destinazioni/"),
            data=json.dumps({"documento_ids": [self.doc.pk], "attiva": True}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(list(self.doc.destinazioni.all()), [])

    def test_utente_autorizzato_con_solo_permesso_reading_puo_scrivere(self):
        self.client.force_login(self.autorizzato_reading)

        risposta = self.client.post(
            self._url(f"documenti/{self.doc.pk}/destinazioni/"),
            data=json.dumps({"codici_bc": [1]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertEqual(
            list(self.doc.destinazioni.values_list("stabilimento__codice_bc", flat=True)), [1]
        )

    def test_pagina_trasmittal_interno_resta_visibile_a_chi_non_puo_scrivere(self):
        self.client.force_login(self.admin_non_autorizzato)

        risposta = self.client.get(f"/commesse/{self.testata.job}/trasmittal-interno/")

        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "Trasmittal interno")


class IndirizziEmailNotiApiTests(TestCase):
    """Suggerimenti per i destinatari TO/CC del pannello di conferma."""

    URL = "/api/trasmittal-interno/indirizzi-email/"

    def setUp(self):
        self.client = Client()
        self.utente = User.objects.create_user(
            "tie_utente", "mario.rossi@b.it", "pw", first_name="Mario", last_name="Rossi"
        )
        User.objects.create_user("tie_inattivo", "inattivo@b.it", "pw", is_active=False)

        bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        IndirizzoStabilimento.objects.create(
            stabilimento=bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=bg, email="spento@b.it", tipo=TipoIndirizzoStabilimento.CC, attivo=False
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=bg, email="qualita@b.it", tipo=TipoIndirizzoStabilimento.CC
        )

        trasmittal = TransmittalInterno.objects.create(
            testata=Testata.objects.create(job="99096"),
            data=date(2026, 1, 1),
            progressivo=1,
            nome="99096_2026-01-01_E1",
            creato_da=self.utente,
        )
        for email in ("esterno@x.it", "Mario.Rossi@B.it"):
            DestinatarioTransmittalInterno.objects.create(
                trasmittal=trasmittal,
                email=email,
                tipo=TipoDestinatarioTransmittalInterno.TO,
                origine=OrigineDestinatarioTransmittalInterno.MANUALE,
            )

    def _indirizzi(self):
        self.client.force_login(self.utente)
        risposta = self.client.get(self.URL)
        self.assertEqual(risposta.status_code, 200)
        return risposta.json()["indirizzi"]

    def test_richiede_login(self):
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_unisce_utenti_stabilimenti_e_destinatari_gia_usati(self):
        self.assertEqual(
            self._indirizzi(),
            [
                {"email": "bg@b.it", "nome": "Stabilimento BG"},
                {"email": "esterno@x.it", "nome": ""},
                {"email": "mario.rossi@b.it", "nome": "Mario Rossi"},
                {"email": "qualita@b.it", "nome": "Stabilimento BG"},
            ],
        )

    def test_esclude_utenti_e_indirizzi_non_attivi(self):
        email = {voce["email"] for voce in self._indirizzi()}

        self.assertNotIn("inattivo@b.it", email)
        self.assertNotIn("spento@b.it", email)

    def test_deduplica_senza_distinguere_maiuscole_e_tiene_il_nome_dell_utente(self):
        voci = [v for v in self._indirizzi() if v["email"].lower() == "mario.rossi@b.it"]

        self.assertEqual(voci, [{"email": "mario.rossi@b.it", "nome": "Mario Rossi"}])
