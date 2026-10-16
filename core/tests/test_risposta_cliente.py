"""Correzione della risposta del cliente: ``POST /api/revisioni/<pk>/risposta-cliente/``.

La revisione 0 è già rientrata con una risposta che chiede una nuova revisione,
e la ricezione ha creato la revisione 1 ancora vuota: lo stato tipico su cui
si corregge una risposta sbagliata.
"""

import json
from datetime import date

from django.test import Client, TestCase

from ..models import (
    Documento,
    Permesso,
    Revisione,
    RevisioneFileLink,
    StatoEsterno,
    Testata,
    Transmittal,
)
from ..services.commesse import esegui_ricezione
from ._fixtures import User


class RispostaClienteApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.writer = User.objects.create_user(
            "rc_writer", "rc-writer@b.it", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(self.writer)
        self.approved = StatoEsterno.objects.create(
            nome="Approved", lettera="A", colore="#00B050", crea_nuova_rev=False
        )
        self.commented = StatoEsterno.objects.create(
            nome="Commented", lettera="C", colore="#F59B1D", crea_nuova_rev=True
        )
        self.rejected = StatoEsterno.objects.create(
            nome="Rejected", lettera="R", colore="#FF0000", crea_nuova_rev=True
        )
        self.testata = Testata.objects.create(job="26300", time_ven_doc_rev=14)
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="26300-A")
        self.rev0 = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_act_date=date(2026, 4, 1),
            rec_act_date=date(2026, 4, 20),
            int_status="ricevuto",
            ext_status=self.commented,
            crea_nuova_rev=True,
        )
        self.rev1 = Revisione.objects.create(
            documento=self.doc, rev_no=1, dis_plan_date=date(2026, 5, 4), crea_nuova_rev=True
        )

    def _url(self, pk=None):
        return f"/api/revisioni/{pk or self.rev0.pk}/risposta-cliente/"

    def _post(self, payload, pk=None):
        return self.client.post(
            self._url(pk), data=json.dumps(payload), content_type="application/json"
        )

    def _correggi(self, stato):
        return self._post({"ext_status_id": stato.pk})

    def _assert_rev0_invariata(self):
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.ext_status_id, self.commented.pk)
        self.assertTrue(self.rev0.crea_nuova_rev)

    # ── Revisione successiva ──────────────────────────────────────────────────

    def test_risposta_senza_nuova_rev_elimina_la_successiva_vuota(self):
        risposta = self._correggi(self.approved)

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertTrue(dati["ok"])
        self.assertEqual(dati["revisione"]["ext_status"], self.approved.pk)
        self.assertFalse(dati["revisione"]["crea_nuova_rev"])
        self.assertEqual(dati["successiva"]["azione"], "eliminata")
        self.assertEqual(dati["successiva"]["revisione"]["id"], self.rev1.pk)

        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.ext_status_id, self.approved.pk)
        self.assertFalse(self.rev0.crea_nuova_rev)
        self.assertEqual(self.rev0.int_status, "ricevuto")
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 20))
        self.assertFalse(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_successiva_gia_inviata_e_un_409_e_non_cambia_nulla(self):
        self.rev1.dis_act_date = date(2026, 5, 2)
        self.rev1.save()

        risposta = self._correggi(self.approved)

        self.assertEqual(risposta.status_code, 409)
        self.assertEqual(
            risposta.json()["error"],
            "La revisione successiva è già in lavorazione, correggere manualmente.",
        )
        self._assert_rev0_invariata()
        self.rev1.refresh_from_db()
        self.assertEqual(self.rev1.dis_act_date, date(2026, 5, 2))

    def test_successiva_con_file_collegato_non_si_elimina(self):
        RevisioneFileLink.objects.create(revisione=self.rev1, percorso=r"Z:\JOBS\26300\x.pdf")

        self.assertEqual(self._correggi(self.approved).status_code, 409)
        self._assert_rev0_invariata()
        self.assertTrue(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_successiva_in_un_trasmittal_non_si_elimina(self):
        Transmittal.objects.create(testata=self.testata, numero=1).revisioni.add(self.rev1)

        self.assertEqual(self._correggi(self.approved).status_code, 409)
        self._assert_rev0_invariata()
        self.assertTrue(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_risposta_con_nuova_rev_crea_la_successiva(self):
        self.rev1.delete()
        self.rev0.ext_status = self.approved
        self.rev0.crea_nuova_rev = False
        self.rev0.save()

        risposta = self._correggi(self.commented)

        self.assertEqual(risposta.status_code, 200)
        successiva = risposta.json()["successiva"]
        self.assertEqual(successiva["azione"], "creata")
        nuova = Revisione.objects.get(pk=successiva["revisione"]["id"])
        self.assertEqual(nuova.documento_id, self.doc.pk)
        self.assertEqual(nuova.rev_no, 1)
        # Come alla ricezione: rientro della revisione 0 + time_ven_doc_rev.
        self.assertEqual(nuova.dis_plan_date, date(2026, 5, 4))
        self.assertIsNone(nuova.dis_act_date)
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.ext_status_id, self.commented.pk)
        self.assertTrue(self.rev0.crea_nuova_rev)

    def test_risposta_con_nuova_rev_e_successiva_presente_non_la_tocca(self):
        risposta = self._correggi(self.rejected)

        self.assertEqual(risposta.status_code, 200)
        successiva = risposta.json()["successiva"]
        self.assertEqual(successiva["azione"], "nessuna")
        self.assertEqual(successiva["revisione"]["id"], self.rev1.pk)
        self.assertEqual(
            list(self.doc.revisioni.values_list("pk", flat=True).order_by("rev_no")),
            [self.rev0.pk, self.rev1.pk],
        )
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.ext_status_id, self.rejected.pk)

    def test_risposta_senza_nuova_rev_e_senza_successiva_non_fa_altro(self):
        self.rev1.delete()

        risposta = self._correggi(self.approved)

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["successiva"], {"azione": "nessuna", "revisione": None})
        self.assertEqual(self.doc.revisioni.count(), 1)
        self.rev0.refresh_from_db()
        self.assertFalse(self.rev0.crea_nuova_rev)

    # ── Precondizioni ─────────────────────────────────────────────────────────

    def test_revisione_senza_risposta_e_un_400_che_rimanda_alla_ricezione(self):
        self.rev1.ext_status = None
        self.rev1.save()

        risposta = self._post({"ext_status_id": self.approved.pk}, pk=self.rev1.pk)

        self.assertEqual(risposta.status_code, 400)
        self.assertIn("ricezione", risposta.json()["error"])
        self.rev1.refresh_from_db()
        self.assertIsNone(self.rev1.ext_status_id)

    def test_stessa_risposta_e_un_400(self):
        risposta = self._correggi(self.commented)

        self.assertEqual(risposta.status_code, 400)
        self._assert_rev0_invariata()
        self.assertTrue(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_risposta_inesistente_o_mancante_e_un_400(self):
        for payload in ({"ext_status_id": 999999}, {}, {"ext_status_id": "x"}):
            with self.subTest(payload=payload):
                self.assertEqual(self._post(payload).status_code, 400)
        self.assertEqual(
            self.client.post(self._url(), data="{", content_type="application/json").status_code,
            400,
        )
        self._assert_rev0_invariata()

    def test_revisione_inesistente_e_un_404(self):
        self.assertEqual(
            self._post({"ext_status_id": self.approved.pk}, pk=999999).status_code, 404
        )

    # ── Permessi ──────────────────────────────────────────────────────────────

    def _esiti(self):
        """Stato HTTP di ricezione_api e del nuovo endpoint per l'utente corrente."""
        ricezione = self.client.post(
            "/api/ricezione/", data=json.dumps({"entries": []}), content_type="application/json"
        ).status_code
        return ricezione, self._correggi(self.approved).status_code

    def test_utente_in_sola_lettura_ha_lo_stesso_esito_di_ricezione(self):
        lettore = User.objects.create_user(
            "rc_reader", "rc-reader@b.it", "pw", permesso=Permesso.READING
        )
        self.client.force_login(lettore)

        self.assertEqual(self._esiti(), (403, 403))
        self._assert_rev0_invariata()

    def test_utente_non_autenticato_ha_lo_stesso_esito_di_ricezione(self):
        self.client.logout()

        self.assertEqual(self._esiti(), (401, 401))
        self._assert_rev0_invariata()

    def test_solo_post(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)


class CreaRevisioneSuccessivaRicezioneTests(TestCase):
    """La creazione della revisione successiva, estratta da ``esegui_ricezione``,
    pianifica l'invio come prima: rientro + ``time_ven_doc_rev``."""

    def setUp(self):
        self.commented = StatoEsterno.objects.create(nome="Commented", crea_nuova_rev=True)
        self.testata = Testata.objects.create(job="26301", time_ven_doc_rev=14)
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="26301-A")
        Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_act_date=date(2026, 8, 26),
            int_status="inviato_al_cliente",
        )

    def _ricevi(self):
        esegui_ricezione(
            [
                {
                    "doc_id": self.doc.pk,
                    "rec_act_date": "2026-09-10",
                    "ext_status_id": self.commented.pk,
                    "crea_nuova_revisione": True,
                }
            ]
        )
        return self.doc.revisioni.get(rev_no=1)

    def test_data_di_invio_pianificata_con_i_giorni_del_vendor(self):
        nuova = self._ricevi()

        self.assertEqual(nuova.dis_plan_date, date(2026, 9, 24))
        self.assertTrue(nuova.crea_nuova_rev)

    def test_senza_giorni_del_vendor_la_data_resta_vuota(self):
        self.testata.time_ven_doc_rev = None
        self.testata.save()

        self.assertIsNone(self._ricevi().dis_plan_date)
