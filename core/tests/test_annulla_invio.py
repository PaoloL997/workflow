"""Annullamento dell'invio al cliente: ``POST /api/revisioni/<pk>/annulla-invio/``.

La revisione 0 è stata emessa (inviata al cliente con data di invio e data di
ricezione prevista) ma il cliente non ha ancora risposto: lo stato tipico in cui
un invio registrato per errore si annulla.
"""

from datetime import date

from django.test import Client, TestCase

from ..models import Documento, Permesso, Revisione, StatoEsterno, Testata, Transmittal
from ._fixtures import User


class AnnullaInvioApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.writer = User.objects.create_user(
            "ai_writer", "ai-writer@b.it", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(self.writer)
        self.testata = Testata.objects.create(job="26310", time_cli_doc_rev=10)
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="26310-A")
        self.rev0 = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_plan_date=date(2026, 3, 25),
            dis_act_date=date(2026, 4, 1),
            rec_plan_date=date(2026, 4, 11),
            int_status="inviato_al_cliente",
        )

    def _post(self, pk=None):
        return self.client.post(f"/api/revisioni/{pk or self.rev0.pk}/annulla-invio/")

    def _assert_rev0_invariata(self):
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "inviato_al_cliente")
        self.assertEqual(self.rev0.dis_act_date, date(2026, 4, 1))
        self.assertEqual(self.rev0.rec_plan_date, date(2026, 4, 11))

    def test_annulla_invio_riporta_la_revisione_da_emettere(self):
        trasmittal = Transmittal.objects.create(
            testata=self.testata, numero=1, data_emissione=date(2026, 4, 1)
        )
        trasmittal.revisioni.add(self.rev0)

        risposta = self._post()

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertTrue(dati["ok"])
        self.assertEqual(dati["revisione"]["id"], self.rev0.pk)
        self.assertEqual(dati["revisione"]["int_status"], "da_emettere")
        self.assertIsNone(dati["revisione"]["dis_act_date"])
        self.assertIsNone(dati["revisione"]["rec_plan_date"])

        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "da_emettere")
        self.assertIsNone(self.rev0.dis_act_date)
        self.assertIsNone(self.rev0.rec_plan_date)
        # Il resto della revisione e il trasmittal in cui è stata emessa restano.
        self.assertEqual(self.rev0.dis_plan_date, date(2026, 3, 25))
        self.assertIsNone(self.rev0.rec_act_date)
        self.assertIsNone(self.rev0.ext_status_id)
        self.assertTrue(trasmittal.revisioni.filter(pk=self.rev0.pk).exists())

    def test_revisione_non_inviata_e_un_400(self):
        self.rev0.int_status = "da_emettere"
        self.rev0.dis_act_date = None
        self.rev0.rec_plan_date = None
        self.rev0.save()

        risposta = self._post()

        self.assertEqual(risposta.status_code, 400)
        self.assertEqual(
            risposta.json()["error"],
            "La revisione non risulta inviata al cliente: niente da annullare.",
        )
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "da_emettere")

    def test_revisione_gia_rientrata_e_un_400_e_non_cambia_nulla(self):
        self.rev0.rec_act_date = date(2026, 4, 9)
        self.rev0.save()

        risposta = self._post()

        self.assertEqual(risposta.status_code, 400)
        self.assertEqual(
            risposta.json()["error"],
            "La revisione è già rientrata dal cliente: l'invio non si può annullare.",
        )
        self._assert_rev0_invariata()
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 9))

    def test_revisione_con_risposta_del_cliente_e_un_400(self):
        approved = StatoEsterno.objects.create(
            nome="Approved", lettera="A", colore="#00B050", crea_nuova_rev=False
        )
        self.rev0.ext_status = approved
        self.rev0.save()

        self.assertEqual(self._post().status_code, 400)
        self._assert_rev0_invariata()
        self.assertEqual(self.rev0.ext_status_id, approved.pk)

    def test_revisione_inesistente_e_un_404(self):
        risposta = self._post(pk=self.rev0.pk + 1000)

        self.assertEqual(risposta.status_code, 404)
        self.assertEqual(risposta.json()["error"], "Revisione non trovata.")

    def test_solo_post(self):
        self.assertEqual(
            self.client.get(f"/api/revisioni/{self.rev0.pk}/annulla-invio/").status_code, 405
        )
        self._assert_rev0_invariata()

    def test_utente_senza_permessi_di_scrittura_e_un_403_come_la_ricezione(self):
        reader = User.objects.create_user(
            "ai_reader", "ai-reader@b.it", "pw", permesso=Permesso.READING
        )
        self.client.force_login(reader)

        risposta = self._post()
        ricezione = self.client.post("/api/ricezione/", data="{}", content_type="application/json")

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(risposta.status_code, ricezione.status_code)
        self.assertEqual(risposta.json(), ricezione.json())
        self._assert_rev0_invariata()
