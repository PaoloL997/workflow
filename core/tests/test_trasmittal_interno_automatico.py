"""Trasmittal interno, misura temporanea: visionato «in automatico» all'emissione.

Con ``TRASMITTAL_INTERNO_APPROVAZIONE_AUTOMATICA`` la lettera non attende QC e
PROD: la presa visione si registra senza utente, PDF e cartella DCC si
preparano subito e l'email di emissione dice dove sono. Non parte la seconda
email."""

import json
from unittest.mock import patch

from django.core import mail
from django.test import override_settings

from ..models import PresaVisioneTransmittalInterno, TransmittalInterno
from ..services import trasmittal_interno as servizio
from ..services.trasmittal_interno import _percorso_dcc_da, percorso_pdf
from .test_trasmittal_interno_presa_visione import PROD, QC, _LetteraTestCase


@override_settings(TRASMITTAL_INTERNO_APPROVAZIONE_AUTOMATICA=True)
class ApprovazioneAutomaticaTests(_LetteraTestCase):
    def _lettera(self, esito):
        return TransmittalInterno.objects.get(pk=esito["trasmittal_id"])

    def test_registra_qc_e_prod_in_automatico_senza_utente(self):
        esito = self._emetti()

        prese = PresaVisioneTransmittalInterno.objects.filter(trasmittal_id=esito["trasmittal_id"])
        self.assertEqual(sorted(p.ruolo for p in prese), sorted([QC, PROD]))
        self.assertTrue(all(p.automatica and p.utente is None for p in prese))
        self.assertTrue(all(p.registrata_il for p in prese))
        self.assertEqual(esito["stato"], "completato")
        self.assertEqual(esito["ruoli_mancanti"], [])
        self.assertTrue(esito["automatica"])
        self.assertEqual(
            [p["utente"] for p in esito["prese_visione"]], ["in automatico", "in automatico"]
        )

    def test_salva_il_pdf_e_prepara_il_dcc_subito(self):
        esito = self._emetti()
        lettera = self._lettera(esito)

        self.assertTrue(esito["pdf"]["ok"])
        self.assertTrue(percorso_pdf(lettera).is_file())
        self.assertTrue(esito["dcc"]["ok"])
        self.assertEqual(
            sorted(c["vendor_doc"] for c in esito["dcc"]["copiati"]),
            ["99100-01-QC1", "99100-01-UT1"],
        )
        self.assertTrue(_percorso_dcc_da(self.testata.job, lettera.nome).is_dir())

    def test_parte_solo_l_email_di_emissione_con_i_percorsi(self):
        esito = self._emetti()
        lettera = self._lettera(esito)

        self.assertEqual(len(mail.outbox), 1)
        corpo = mail.outbox[0].body
        html = mail.outbox[0].alternatives[0][0]
        self.assertIn("Lettera visionata in automatico (QC e PROD)", corpo)
        self.assertNotIn("In attesa di presa visione", corpo)
        self.assertIn(f"Trasmittal salvato in: {percorso_pdf(lettera)}", corpo)
        cartella = _percorso_dcc_da(self.testata.job, lettera.nome)
        self.assertIn(f"Documenti per il DCC in: {cartella}", corpo)
        self.assertIn(f"?lettera={lettera.pk}", corpo)
        self.assertIn("Lettera visionata in automatico (QC e PROD)", html)
        self.assertIn("Trasmittal salvato in", html)
        self.assertIn("Documenti per il DCC in", html)
        self.assertEqual(mail.outbox[0].attachments, [])

    def test_senza_documenti_per_il_cliente_la_mail_lo_dice(self):
        esito = self._emetti(
            righe=[self._riga(self.doc_ut, cliente=False), self._riga(self.doc_qc, cliente=False)]
        )

        self.assertIsNone(esito["dcc"]["cartella"])
        self.assertIn("Nessun documento per il cliente", mail.outbox[0].body)

    def test_pdf_non_riuscito_non_blocca_la_lettera_e_la_mail_lo_dice(self):
        with patch.object(servizio, "salva_pdf", side_effect=OSError("share non raggiungibile")):
            esito = self._emetti()

        self.assertFalse(esito["pdf"]["ok"])
        self.assertIn("share non raggiungibile", esito["pdf"]["errore"])
        self.assertTrue(TransmittalInterno.objects.filter(pk=esito["trasmittal_id"]).exists())
        self.assertIn("PDF non ancora salvato", mail.outbox[0].body)
        self.assertEqual(len(mail.outbox), 1)

    def test_il_pdf_riporta_in_automatico(self):
        esito = self._emetti()

        from src.pdf import genera_trasmittal_interno_pdf

        pdf = genera_trasmittal_interno_pdf(self._lettera(esito))
        self.assertTrue(pdf.startswith(b"%PDF"))

    def test_elenco_lettere_completato_e_nessuno_puo_prendere_visione(self):
        self._emetti()
        self.client.force_login(self.qc_bg)

        lettere = self.client.get(self._url("lettere/")).json()["lettere"]

        self.assertEqual(lettere[0]["stato"], "completato")
        self.assertEqual(lettere[0]["puo_prendere_visione"], [])
        self.assertEqual(
            [p["utente"] for p in lettere[0]["prese_visione"]], ["in automatico", "in automatico"]
        )

    def test_una_presa_visione_manuale_dopo_l_automatica_risponde_409_senza_ripartire(self):
        esito = self._emetti()
        mail.outbox.clear()

        risposta = self._prendi_visione(self.qc_bg, esito["trasmittal_id"])

        self.assertEqual(risposta.status_code, 409)
        self.assertIn("registrata in automatico", risposta.json()["error"])
        self.assertEqual(mail.outbox, [])

    def test_riprova_pdf_e_dcc_funzionano_come_a_lettera_completata(self):
        esito = self._emetti()
        lettera = self._lettera(esito)
        percorso_pdf(lettera).unlink()

        for passo in ("pdf", "dcc"):
            risposta = self.client.post(
                self._url(f"lettere/{lettera.pk}/retry/"),
                data=json.dumps({"step": passo}),
                content_type="application/json",
            )
            self.assertEqual(risposta.status_code, 200, risposta.content)
            self.assertTrue(risposta.json()["esito"]["ok"])
        self.assertTrue(percorso_pdf(lettera).is_file())

    def test_lettera_senza_siti_resta_vietata(self):
        for documento in (self.doc_ut, self.doc_qc):
            servizio.imposta_destinazioni(documento, [])
        self.client.force_login(self.writer)

        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps({"righe": [self._riga(self.doc_ut)]}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())


@override_settings(TRASMITTAL_INTERNO_APPROVAZIONE_AUTOMATICA=False)
class ApprovazioneAutomaticaSpentaTests(_LetteraTestCase):
    """Spenta, non cambia nulla: la lettera attende QC e PROD, senza PDF né DCC."""

    def test_in_attesa_senza_prese_visione_ne_file(self):
        esito = self._emetti()
        lettera = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])

        self.assertEqual(esito["stato"], "in_attesa")
        self.assertFalse(esito["automatica"])
        self.assertNotIn("pdf", esito)
        self.assertNotIn("dcc", esito)
        self.assertFalse(PresaVisioneTransmittalInterno.objects.exists())
        self.assertFalse(percorso_pdf(lettera).exists())
        self.assertFalse(_percorso_dcc_da(self.testata.job, lettera.nome).exists())
        self.assertIn("In attesa di presa visione QC e PROD", mail.outbox[0].body)
        self.assertNotIn("in automatico", mail.outbox[0].body)
