"""Trasmittal interno: selezione UT/QC/WE, email di emissione, presa visione QC e
PROD, completamento (PDF, DCC, email di completamento) e blocco del download."""

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth.models import Group
from django.core import mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from ..models import (
    Documento,
    FirmatarioStabilimento,
    IndirizzoStabilimento,
    Permesso,
    PresaVisioneTransmittalInterno,
    Reparto,
    Revisione,
    RuoloFirmatarioStabilimento,
    Stabilimento,
    Testata,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
)
from ..permissions import GRUPPO_SERVIZIO
from ..services.fileserver import get_base_path
from ..services.trasmittal_interno import (
    _percorso_dcc_da,
    imposta_destinazioni,
    percorso_pdf,
)
from ._fixtures import User

QC = RuoloFirmatarioStabilimento.QUALITA
PROD = RuoloFirmatarioStabilimento.PRODUZIONE


@override_settings(
    DEFAULT_FROM_EMAIL="Workflow <workflow@b.it>",
    WORKFLOW_BASE_URL="",
    TRASMITTAL_INTERNO_EMAIL_TEST_REDIRECT="",
)
class _LetteraTestCase(TestCase):
    """Commessa con un documento UT e uno QC destinati a Valbrembo, i firmatari
    QC e PROD di Valbrembo e un firmatario QC di Albignasego (sito non coinvolto)."""

    def setUp(self):
        self.client = Client()

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        patcher = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg-cc@b.it", tipo=TipoIndirizzoStabilimento.CC
        )

        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.reparto_qc = Reparto.objects.create(nome="Quality Control", acronimo="QC")
        self.testata = Testata.objects.create(job="99100", sito_costruttivo=self.bg)
        self.doc_ut = self._documento("99100-01-UT1", self.reparto_ut, "Disegno UT")
        self.doc_qc = self._documento("99100-01-QC1", self.reparto_qc, "Piano QC")

        self.writer = User.objects.create_user(
            "pv_writer",
            "writer@b.it",
            "pw",
            first_name="Wanda",
            last_name="Writer",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.qc_bg = self._firmatario("pv_qc", "Quinto", "Qualita", (self.bg, QC))
        self.prod_bg = self._firmatario("pv_prod", "Paola", "Produzione", (self.bg, PROD))
        self.qc_pd = self._firmatario("pv_qc_pd", "Pietro", "Padova", (self.pd, QC))
        self.estraneo = User.objects.create_user("pv_estraneo", "estraneo@b.it", "pw")

    # ── helper ──

    def _documento(self, vendor_doc, reparto, titolo, siti=(1,), file=True):
        documento = Documento.objects.create(
            testata=self.testata, vendor_doc=vendor_doc, doc_title=titolo, reparto=reparto.nome
        )
        Revisione.objects.create(documento=documento, rev_no=0)
        imposta_destinazioni(documento, list(siti))
        if file:
            cartella = get_base_path(self.testata.job, reparto.acronimo)
            cartella.mkdir(parents=True, exist_ok=True)
            (cartella / f"{vendor_doc} Rev 0.pdf").write_bytes(b"%PDF-fake")
        return documento

    def _firmatario(self, username, nome, cognome, *ruoli):
        utente = User.objects.create_user(
            username, f"{username}@b.it", "pw", first_name=nome, last_name=cognome
        )
        for stabilimento, ruolo in ruoli:
            FirmatarioStabilimento.objects.create(
                stabilimento=stabilimento, ruolo=ruolo, utente=utente
            )
        return utente

    def _url(self, path, job=None):
        return f"/api/commesse/{job or self.testata.job}/trasmittal-interno/{path}"

    def _riga(self, documento, **overrides):
        riga = {"documento_id": documento.pk, "revisione": "0", "copie": 1, "cliente": True}
        riga.update(overrides)
        return riga

    def _emetti(self, righe=None, **extra):
        self.client.force_login(self.writer)
        righe = righe or [self._riga(self.doc_ut), self._riga(self.doc_qc)]
        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": righe, **extra}),
            content_type="application/json",
        )
        self.assertEqual(risposta.status_code, 200, risposta.content)
        return risposta.json()

    def _prendi_visione(self, utente, lettera_id, ruolo=None):
        self.client.force_login(utente)
        return self.client.post(
            self._url(f"lettere/{lettera_id}/presa-visione/"),
            data=json.dumps({"ruolo": ruolo} if ruolo else {}),
            content_type="application/json",
        )

    def _completa(self, lettera_id):
        self.assertEqual(self._prendi_visione(self.qc_bg, lettera_id).status_code, 200)
        risposta = self._prendi_visione(self.prod_bg, lettera_id)
        self.assertEqual(risposta.status_code, 200, risposta.content)
        return risposta.json()


class SelezioneMultiRepartoTests(_LetteraTestCase):
    """I documenti selezionabili sono quelli di UT, QC e WE, col file nella cartella del loro reparto."""

    def _selezione(self):
        self.client.force_login(self.writer)
        return {
            d["vendor_doc"]: d for d in self.client.get(self._url("selezione/")).json()["documenti"]
        }

    def test_documenti_ut_e_qc_selezionabili(self):
        selezione = self._selezione()

        self.assertTrue(selezione["99100-01-UT1"]["selezionabile"])
        self.assertTrue(selezione["99100-01-QC1"]["selezionabile"])

    def test_il_file_si_cerca_solo_nella_cartella_del_reparto_del_documento(self):
        doc = self._documento("99100-01-QC2", self.reparto_qc, "QC senza file", file=False)
        cartella_ut = get_base_path(self.testata.job, "UT")
        (cartella_ut / f"{doc.vendor_doc} Rev 0.pdf").write_bytes(b"%PDF-fake")

        voce = self._selezione()["99100-01-QC2"]

        self.assertFalse(voce["selezionabile"])
        self.assertEqual(voce["motivo"], "Nessun file trovato sul fileserver.")

    def test_documenti_di_altri_reparti_esclusi(self):
        reparto_pm = Reparto.objects.create(nome="Project Management", acronimo="PM")
        self._documento("99100-01-PM1", reparto_pm, "Documento PM")

        self.assertNotIn("99100-01-PM1", self._selezione())

    def test_il_reparto_we_entra_quando_esiste_in_anagrafica(self):
        Documento.objects.create(
            testata=self.testata, vendor_doc="99100-01-WE1", reparto="Welding Engineering"
        )
        self.assertNotIn("99100-01-WE1", self._selezione())

        reparto_we = Reparto.objects.create(nome="Welding Engineering", acronimo="WE")
        Documento.objects.filter(vendor_doc="99100-01-WE1").delete()
        self._documento("99100-01-WE1", reparto_we, "Documento WE")

        self.assertTrue(self._selezione()["99100-01-WE1"]["selezionabile"])

    def test_la_lettera_si_emette_con_documenti_ut_e_qc(self):
        esito = self._emetti()

        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        self.assertEqual(
            sorted(lettera.righe.values_list("documento__vendor_doc", flat=True)),
            ["99100-01-QC1", "99100-01-UT1"],
        )


class LetteraSenzaSitiTests(_LetteraTestCase):
    """Una lettera senza siti coinvolti non si emette: nessuno potrebbe prenderne visione."""

    def test_anteprima_ed_emissione_rifiutano_una_lettera_senza_siti(self):
        imposta_destinazioni(self.doc_ut, [])
        self.client.force_login(self.writer)
        payload = json.dumps({"righe": [self._riga(self.doc_ut)]})

        for percorso in ("anteprima/", "emetti/"):
            risposta = self.client.post(
                self._url(percorso), data=payload, content_type="application/json"
            )
            self.assertEqual(risposta.status_code, 400, percorso)
            self.assertIn("sito coinvolto", risposta.json()["error"])

        self.assertFalse(TransmittalInterno.objects.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_basta_un_documento_con_un_sito(self):
        imposta_destinazioni(self.doc_ut, [])

        esito = self._emetti()

        self.assertTrue(esito["ok"])


class EmailEmissioneTests(_LetteraTestCase):
    """Email di emissione: righe, NOTES, stato con il link, nessun percorso, Message-ID salvato."""

    @override_settings(WORKFLOW_BASE_URL="https://workflow.example/")
    def test_note_numerate_stato_e_link_senza_percorso(self):
        esito = self._emetti(note="prima nota\nseconda nota", messaggio="Ciao a tutti")

        inviata = mail.outbox[0]
        link = (
            f"https://workflow.example/commesse/99100/trasmittal-interno/"
            f"?lettera={esito['trasmittal_id']}"
        )
        self.assertIn("Ciao a tutti", inviata.body)
        self.assertIn("NOTES\n1) prima nota\n2) seconda nota\n3)\n\n", inviata.body)
        self.assertTrue(inviata.body.endswith(f"In attesa di presa visione QC e PROD: {link}"))
        self.assertNotIn("Salvato in", inviata.body)
        self.assertNotIn(str(Path("Progetto") / "UT" / "Transmittal"), inviata.body)
        self.assertEqual(inviata.attachments, [])
        html = inviata.alternatives[0][0]
        self.assertIn(">NOTES</th>", html)
        self.assertIn("1) prima nota<br>2) seconda nota<br>3)", html)
        self.assertIn(f'<a href="{link}">', html)

    def test_senza_indirizzo_configurato_il_link_usa_quello_della_richiesta(self):
        esito = self._emetti()

        self.assertIn(
            f"http://testserver/commesse/99100/trasmittal-interno/?lettera={esito['trasmittal_id']}",
            mail.outbox[0].body,
        )

    def test_message_id_salvato_sulla_lettera_e_usato_nell_email(self):
        esito = self._emetti()

        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        self.assertRegex(lettera.message_id, r"^<.+@b\.it>$")
        self.assertEqual(esito["email"]["message_id"], lettera.message_id)
        self.assertEqual(mail.outbox[0].message()["Message-ID"], lettera.message_id)

    def test_riprova_email_salva_un_nuovo_message_id(self):
        esito = self._emetti()
        primo = TransmittalInterno.objects.get(pk=esito["trasmittal_id"]).message_id

        risposta = self.client.post(
            self._url(f"lettere/{esito['trasmittal_id']}/retry/"),
            data=json.dumps({"step": "email"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        secondo = TransmittalInterno.objects.get(pk=esito["trasmittal_id"]).message_id
        self.assertNotEqual(primo, secondo)
        self.assertEqual(mail.outbox[1].message()["Message-ID"], secondo)


class PresaVisioneTests(_LetteraTestCase):
    """Chi può prendere visione, per quale ruolo, e una sola volta per ruolo."""

    def setUp(self):
        super().setUp()
        self.lettera_id = self._emetti()["trasmittal_id"]

    def test_richiede_login(self):
        self.client.logout()

        risposta = self.client.post(self._url(f"lettere/{self.lettera_id}/presa-visione/"))

        self.assertNotEqual(risposta.status_code, 200)
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())

    def test_chi_non_e_firmatario_riceve_403(self):
        risposta = self._prendi_visione(self.estraneo, self.lettera_id)

        self.assertEqual(risposta.status_code, 403)
        self.assertIn("non sei firmatario", risposta.json()["error"])

    def test_firmatario_di_un_sito_non_coinvolto_riceve_403(self):
        risposta = self._prendi_visione(self.qc_pd, self.lettera_id)

        self.assertEqual(risposta.status_code, 403)
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())

    def test_utente_di_servizio_riceve_403(self):
        self.qc_bg.groups.add(Group.objects.get(name=GRUPPO_SERVIZIO))

        risposta = self._prendi_visione(self.qc_bg, self.lettera_id)

        self.assertEqual(risposta.status_code, 403)
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())

    def test_il_ruolo_si_deduce_dal_firmatario(self):
        risposta = self._prendi_visione(self.qc_bg, self.lettera_id)

        self.assertEqual(risposta.status_code, 200)
        corpo = risposta.json()
        self.assertEqual(corpo["presa_visione"]["ruolo"], QC)
        self.assertEqual(corpo["presa_visione"]["utente"], "Quinto Qualita")
        self.assertEqual(corpo["stato"], "parziale")
        self.assertEqual(corpo["ruoli_mancanti"], ["PROD"])
        self.assertIsNone(corpo["completamento"])
        presa = PresaVisioneTransmittalInterno.objects.get()
        self.assertEqual((presa.utente, presa.ruolo), (self.qc_bg, QC))
        self.assertEqual(len(mail.outbox), 1)  # solo l'email di emissione

    def test_non_serve_il_permesso_di_scrittura(self):
        self.assertEqual(self.qc_bg.permesso, Permesso.READING)
        self.assertFalse(self.qc_bg.trasmittal_interno_writer)

        self.assertEqual(self._prendi_visione(self.qc_bg, self.lettera_id).status_code, 200)

    def test_ruolo_chiesto_che_l_utente_non_ha_riceve_403(self):
        risposta = self._prendi_visione(self.qc_bg, self.lettera_id, ruolo=PROD)

        self.assertEqual(risposta.status_code, 403)
        self.assertIn("PROD", risposta.json()["error"])

    def test_ruolo_non_valido_riceve_400(self):
        risposta = self._prendi_visione(self.qc_bg, self.lettera_id, ruolo="direzione")

        self.assertEqual(risposta.status_code, 400)

    def test_una_sola_presa_visione_per_ruolo(self):
        altro_qc = self._firmatario("pv_qc2", "Quarta", "Qualita", (self.bg, QC))
        self.assertEqual(self._prendi_visione(self.qc_bg, self.lettera_id).status_code, 200)

        risposta = self._prendi_visione(altro_qc, self.lettera_id)

        self.assertEqual(risposta.status_code, 409)
        self.assertIn("già stata registrata da Quinto Qualita", risposta.json()["error"])
        self.assertEqual(PresaVisioneTransmittalInterno.objects.count(), 1)

    def test_piu_firmatari_dello_stesso_ruolo_e_sito_possono_prendere_visione(self):
        altro_qc = self._firmatario("pv_qc2", "Quarta", "Qualita", (self.bg, QC))

        risposta = self._prendi_visione(altro_qc, self.lettera_id)

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["presa_visione"]["utente"], "Quarta Qualita")

    def test_firmatario_di_entrambi_i_ruoli_indica_il_ruolo(self):
        doppio = self._firmatario("pv_doppio", "Dario", "Doppio", (self.bg, QC), (self.bg, PROD))

        senza_ruolo = self._prendi_visione(doppio, self.lettera_id)
        self.assertEqual(senza_ruolo.status_code, 400)
        self.assertIn("indica per quale ruolo", senza_ruolo.json()["error"])

        prod = self._prendi_visione(doppio, self.lettera_id, ruolo=PROD)
        self.assertEqual(prod.status_code, 200)
        self.assertEqual(prod.json()["presa_visione"]["ruolo"], PROD)

        # Ne manca uno solo dei suoi: il ruolo si deduce.
        qc = self._prendi_visione(doppio, self.lettera_id)
        self.assertEqual(qc.status_code, 200)
        self.assertEqual(qc.json()["presa_visione"]["ruolo"], QC)
        self.assertEqual(qc.json()["stato"], "completato")

    def test_lettera_di_un_altra_commessa_404(self):
        altra = Testata.objects.create(job="99101", sito_costruttivo=self.bg)
        self.client.force_login(self.qc_bg)

        risposta = self.client.post(
            self._url(f"lettere/{self.lettera_id}/presa-visione/", job=altra.job),
            data="{}",
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 404)


class CompletamentoTests(_LetteraTestCase):
    """Con QC e PROD: PDF sul fileserver, cartella DCC, email di completamento nello stesso thread."""

    def test_salva_il_pdf_prepara_il_dcc_e_invia_la_seconda_email(self):
        esito = self._emetti()
        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        self.assertFalse(percorso_pdf(lettera).exists())

        corpo = self._completa(lettera.pk)

        self.assertEqual(corpo["stato"], "completato")
        completamento = corpo["completamento"]
        self.assertTrue(completamento["pdf"]["ok"])
        self.assertTrue(percorso_pdf(lettera).is_file())
        self.assertTrue(completamento["dcc"]["ok"])
        self.assertEqual(
            sorted(c["vendor_doc"] for c in completamento["dcc"]["copiati"]),
            ["99100-01-QC1", "99100-01-UT1"],
        )
        self.assertTrue(_percorso_dcc_da(self.testata.job, lettera.nome).is_dir())
        self.assertTrue(completamento["email"]["ok"])
        self.assertEqual(len(mail.outbox), 2)

    def test_seconda_email_stesso_oggetto_e_destinatari_nello_stesso_thread(self):
        esito = self._emetti()
        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])

        self._completa(lettera.pk)

        prima, seconda = mail.outbox
        self.assertEqual(seconda.subject, prima.subject)
        self.assertEqual(seconda.to, prima.to)
        self.assertEqual(seconda.cc, prima.cc)
        self.assertIn("writer@b.it", seconda.cc)
        self.assertEqual(seconda.reply_to, prima.reply_to)
        self.assertEqual(seconda.from_email, prima.from_email)
        self.assertEqual(seconda.extra_headers["In-Reply-To"], lettera.message_id)
        self.assertEqual(seconda.extra_headers["References"], lettera.message_id)
        self.assertEqual(seconda.attachments, [])

        riga_qc = re.search(
            r"Visionato da Quinto Qualita \(QC\) il \d{2}/\d{2}/\d{4} \d{2}:\d{2}", seconda.body
        )
        riga_prod = re.search(
            r"Visionato da Paola Produzione \(PROD\) il \d{2}/\d{2}/\d{4} \d{2}:\d{2}",
            seconda.body,
        )
        self.assertIsNotNone(riga_qc)
        self.assertIsNotNone(riga_prod)
        self.assertLess(riga_qc.start(), riga_prod.start())
        self.assertIn(f"Salvato in: {percorso_pdf(lettera)}", seconda.body)
        self.assertIn("Visionato da Quinto Qualita (QC)", seconda.alternatives[0][0])

    def test_un_passo_fallito_non_ferma_gli_altri_e_l_email_lo_dice(self):
        esito = self._emetti()
        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        self._prendi_visione(self.qc_bg, lettera.pk)

        with patch("core.services.trasmittal_interno.salva_pdf", side_effect=OSError("share giù")):
            corpo = self._prendi_visione(self.prod_bg, lettera.pk).json()

        completamento = corpo["completamento"]
        self.assertFalse(completamento["pdf"]["ok"])
        self.assertIn("share giù", completamento["pdf"]["errore"])
        self.assertTrue(completamento["dcc"]["ok"])
        self.assertTrue(completamento["email"]["ok"])
        self.assertIn("PDF non ancora salvato", mail.outbox[1].body)
        self.assertNotIn("Salvato in", mail.outbox[1].body)

    def test_senza_message_id_la_seconda_email_parte_senza_header_di_thread(self):
        with patch("django.core.mail.EmailMessage.send", side_effect=Exception("SMTP giù")):
            esito = self._emetti()
        self.assertFalse(esito["email"]["ok"])
        self.assertEqual(TransmittalInterno.objects.get(pk=esito["trasmittal_id"]).message_id, "")

        self._completa(esito["trasmittal_id"])

        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn("In-Reply-To", mail.outbox[0].extra_headers)

    def test_il_completamento_avviene_una_volta_sola(self):
        esito = self._emetti()
        self._completa(esito["trasmittal_id"])

        risposta = self._prendi_visione(self.prod_bg, esito["trasmittal_id"])

        self.assertEqual(risposta.status_code, 409)
        self.assertEqual(len(mail.outbox), 2)


class RiprovaCompletamentoTests(_LetteraTestCase):
    """Riprova dei passi di completamento: solo a lettera completata."""

    def _riprova(self, lettera_id, step):
        self.client.force_login(self.writer)
        return self.client.post(
            self._url(f"lettere/{lettera_id}/retry/"),
            data=json.dumps({"step": step}),
            content_type="application/json",
        )

    def test_rifiutati_finche_manca_una_presa_visione(self):
        lettera_id = self._emetti()["trasmittal_id"]
        self._prendi_visione(self.qc_bg, lettera_id)

        for step in ("pdf", "dcc", "email_completamento"):
            risposta = self._riprova(lettera_id, step)
            self.assertEqual(risposta.status_code, 409, step)
            self.assertIn("PROD", risposta.json()["error"])

    def test_riprova_pdf_dopo_il_completamento(self):
        lettera_id = self._emetti()["trasmittal_id"]
        self._completa(lettera_id)
        lettera = TransmittalInterno.objects.get(pk=lettera_id)
        percorso_pdf(lettera).unlink()

        risposta = self._riprova(lettera_id, "pdf")

        self.assertEqual(risposta.status_code, 200)
        self.assertTrue(risposta.json()["esito"]["ok"])
        self.assertTrue(percorso_pdf(lettera).is_file())

    def test_riprova_email_di_completamento_nello_stesso_thread(self):
        lettera_id = self._emetti()["trasmittal_id"]
        self._completa(lettera_id)

        risposta = self._riprova(lettera_id, "email_completamento")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(len(mail.outbox), 3)
        message_id = TransmittalInterno.objects.get(pk=lettera_id).message_id
        self.assertEqual(mail.outbox[2].extra_headers["In-Reply-To"], message_id)

    def test_riprova_richiede_il_permesso_di_scrittura(self):
        lettera_id = self._emetti()["trasmittal_id"]
        self._completa(lettera_id)
        self.client.force_login(self.qc_bg)

        risposta = self.client.post(
            self._url(f"lettere/{lettera_id}/retry/"),
            data=json.dumps({"step": "pdf"}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 403)


class DownloadPdfTests(_LetteraTestCase):
    """Il PDF definitivo si scarica a lettera completata; il PDF del momento sempre."""

    def test_pdf_definitivo_bloccato_finche_manca_una_presa_visione(self):
        lettera_id = self._emetti()["trasmittal_id"]
        url = self._url(f"lettere/{lettera_id}/file/")

        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 409)
        self.assertIn("Manca: QC, PROD", risposta.json()["error"])

        self._prendi_visione(self.qc_bg, lettera_id)
        self.client.force_login(self.writer)
        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 409)
        self.assertIn("Manca: PROD", risposta.json()["error"])

        self._prendi_visione(self.prod_bg, lettera_id)
        risposta = self.client.get(url)
        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "application/pdf")
        # Letto fino in fondo il test client chiude il file: su Windows un file
        # aperto bloccherebbe la pulizia della cartella temporanea.
        self.assertTrue(b"".join(risposta.streaming_content).startswith(b"%PDF"))

    def test_pdf_del_momento_sempre_disponibile_anche_in_sola_lettura(self):
        lettera_id = self._emetti()["trasmittal_id"]
        self.client.force_login(self.estraneo)

        risposta = self.client.get(self._url(f"lettere/{lettera_id}/pdf/"))

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "application/pdf")
        self.assertTrue(risposta.content.startswith(b"%PDF"))
        # Generato al momento: niente scritto sul fileserver.
        self.assertFalse(percorso_pdf(TransmittalInterno.objects.get(pk=lettera_id)).exists())

    def test_pdf_del_momento_di_un_altra_commessa_404(self):
        lettera_id = self._emetti()["trasmittal_id"]
        Testata.objects.create(job="99101", sito_costruttivo=self.bg)

        risposta = self.client.get(self._url(f"lettere/{lettera_id}/pdf/", job="99101"))

        self.assertEqual(risposta.status_code, 404)


class _PdfRegistra:
    """Finto FPDF che registra i testi di ``cell()``: si controlla un blocco del
    modulo senza estrarre il testo dal PDF (nessuna libreria per farlo qui)."""

    _font_family = "Helvetica"
    l_margin = 10

    def __init__(self):
        self.testi = []

    def get_y(self):
        return 0

    def cell(self, w, h, testo="", **kwargs):
        self.testi.append(testo)

    def __getattr__(self, nome):
        return lambda *args, **kwargs: None


class BloccoDistribuzionePdfTests(_LetteraTestCase):
    """PAPER COPIES DISTRIBUTION: nome e data/ora della presa visione, o riga vuota."""

    def setUp(self):
        super().setUp()
        self.lettera = TransmittalInterno.objects.get(pk=self._emetti()["trasmittal_id"])

    def _testi(self):
        from src.pdf import _build_distribuzione_copie

        prese = {p.ruolo: p for p in self.lettera.prese_visione.select_related("utente")}
        pdf = _PdfRegistra()
        _build_distribuzione_copie(pdf, prese)
        return pdf.testi

    def _registra(self, utente, ruolo, ora):
        PresaVisioneTransmittalInterno.objects.create(
            trasmittal=self.lettera,
            utente=utente,
            ruolo=ruolo,
            registrata_il=timezone.make_aware(datetime(2026, 11, 2, *ora)),
        )

    def test_vuoto_senza_prese_visione(self):
        self.assertEqual(
            self._testi(),
            ["PAPER COPIES DISTRIBUTION", "SIGNATURE", "DATE", "PRODUCTION:", "QUALITY:"],
        )

    def test_parziale_con_la_sola_qualita(self):
        self._registra(self.qc_bg, QC, (9, 15))

        testi = self._testi()

        self.assertEqual(
            testi[testi.index("QUALITY:") + 1 :], ["Quinto Qualita", "02/11/2026 09:15"]
        )
        self.assertEqual(testi[testi.index("PRODUCTION:") + 1], "QUALITY:")

    def test_completo(self):
        self._registra(self.qc_bg, QC, (9, 15))
        self._registra(self.prod_bg, PROD, (10, 40))

        testi = self._testi()

        self.assertEqual(
            testi[testi.index("PRODUCTION:") :],
            [
                "PRODUCTION:",
                "Paola Produzione",
                "02/11/2026 10:40",
                "QUALITY:",
                "Quinto Qualita",
                "02/11/2026 09:15",
            ],
        )


class ElencoLettereStatoTests(_LetteraTestCase):
    """L'elenco lettere riporta stato, prese visione e cosa può fare chi lo chiede."""

    def _voce(self, utente):
        self.client.force_login(utente)
        return self.client.get(self._url("lettere/")).json()["lettere"][0]

    def test_stato_e_prese_visione_nel_tempo(self):
        lettera_id = self._emetti()["trasmittal_id"]

        voce = self._voce(self.writer)
        self.assertEqual(voce["stato"], "in_attesa")
        self.assertEqual(voce["ruoli_mancanti"], ["QC", "PROD"])
        self.assertEqual(voce["prese_visione"], [])

        self._prendi_visione(self.qc_bg, lettera_id)
        voce = self._voce(self.writer)
        self.assertEqual(voce["stato"], "parziale")
        self.assertEqual(voce["ruoli_mancanti"], ["PROD"])
        self.assertEqual(voce["prese_visione"][0]["utente"], "Quinto Qualita")
        self.assertEqual(voce["prese_visione"][0]["sigla"], "QC")
        self.assertTrue(voce["prese_visione"][0]["registrata_il"])

        self._prendi_visione(self.prod_bg, lettera_id)
        voce = self._voce(self.writer)
        self.assertEqual(voce["stato"], "completato")
        self.assertEqual([p["sigla"] for p in voce["prese_visione"]], ["QC", "PROD"])
        self.assertTrue(voce["pdf_presente"])

    def test_pulsante_presa_visione_solo_per_i_ruoli_mancanti_di_chi_chiede(self):
        lettera_id = self._emetti()["trasmittal_id"]

        self.assertEqual(
            self._voce(self.qc_bg)["puo_prendere_visione"], [{"ruolo": QC, "sigla": "QC"}]
        )
        self.assertEqual(
            self._voce(self.prod_bg)["puo_prendere_visione"], [{"ruolo": PROD, "sigla": "PROD"}]
        )
        self.assertEqual(self._voce(self.writer)["puo_prendere_visione"], [])
        self.assertEqual(self._voce(self.qc_pd)["puo_prendere_visione"], [])

        self._prendi_visione(self.qc_bg, lettera_id)
        self.assertEqual(self._voce(self.qc_bg)["puo_prendere_visione"], [])

    def test_la_pagina_ha_il_pulsante_presa_visione_e_la_stampa(self):
        self.client.force_login(self.qc_bg)

        pagina = self.client.get(f"/commesse/{self.testata.job}/trasmittal-interno/")

        self.assertContains(pagina, "window.prendiVisione")
        self.assertContains(pagina, "/presa-visione/")
        self.assertContains(pagina, '/pdf/" target="_blank"')


class PresaVisioneAdminTests(TestCase):
    """Le prese visione si consultano in admin ma si registrano solo dall'app."""

    def test_registrata_in_sola_lettura(self):
        model_admin = admin.site._registry[PresaVisioneTransmittalInterno]

        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))


class MigrazioneFirmatariTests(TransactionTestCase):
    """La migrazione 0062 cambia l'unicità dei firmatari senza perdere quelli esistenti."""

    # Il flush finale non deve portarsi via i dati delle migrazioni (es. il gruppo Servizio).
    serialized_rollback = True

    PRIMA = [("core", "0061_gruppo_servizio")]
    DOPO = [("core", "0062_presa_visione_trasmittal_interno")]

    def test_i_firmatari_esistenti_restano_e_ne_entrano_altri_per_lo_stesso_ruolo(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.PRIMA)
        apps = executor.loader.project_state(self.PRIMA).apps
        Stabilimento_ = apps.get_model("core", "Stabilimento")
        User_ = apps.get_model("core", "User")
        Firmatario = apps.get_model("core", "FirmatarioStabilimento")
        sito = Stabilimento_.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        primo = User_.objects.create(username="mig_qc", email="mig-qc@b.it")
        prod = User_.objects.create(username="mig_prod", email="mig-prod@b.it")
        Firmatario.objects.create(stabilimento=sito, ruolo="qualita", utente=primo)
        Firmatario.objects.create(stabilimento=sito, ruolo="produzione", utente=prod)

        executor = MigrationExecutor(connection)
        executor.migrate(self.DOPO)
        apps = executor.loader.project_state(self.DOPO).apps
        Firmatario = apps.get_model("core", "FirmatarioStabilimento")
        User_ = apps.get_model("core", "User")

        self.assertEqual(
            sorted(Firmatario.objects.values_list("utente__username", "ruolo")),
            [("mig_prod", "produzione"), ("mig_qc", "qualita")],
        )
        secondo = User_.objects.create(username="mig_qc2", email="mig-qc2@b.it")
        Firmatario.objects.create(stabilimento_id=sito.pk, ruolo="qualita", utente=secondo)
        self.assertEqual(Firmatario.objects.filter(ruolo="qualita").count(), 2)
