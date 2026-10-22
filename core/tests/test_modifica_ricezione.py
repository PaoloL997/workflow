"""Correzione o annullamento di una ricezione: ``POST /api/revisioni/<pk>/modifica-ricezione/``.

La revisione 0 è stata inviata il 1° aprile e registrata come rientrata il 20
aprile con una risposta che chiede una nuova revisione; la ricezione ha creato
la revisione 1 ancora vuota, con l'invio pianificato a rientro + 14 giorni del
vendor: lo stato tipico su cui si corregge una ricezione registrata male.
"""

import json
from datetime import date, timedelta

from django.test import Client, TestCase
from django.utils import timezone

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


class ModificaRicezioneApiTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.writer = User.objects.create_user(
            "mr_writer", "mr-writer@b.it", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(self.writer)
        self.commented = StatoEsterno.objects.create(
            nome="Commented", lettera="C", colore="#F59B1D", crea_nuova_rev=True
        )
        self.testata = Testata.objects.create(job="26320", time_cli_doc_rev=10, time_ven_doc_rev=14)
        self.doc = Documento.objects.create(testata=self.testata, vendor_doc="26320-A")
        self.rev0 = Revisione.objects.create(
            documento=self.doc,
            rev_no=0,
            dis_act_date=date(2026, 4, 1),
            rec_plan_date=date(2026, 4, 11),
            rec_act_date=date(2026, 4, 20),
            int_status="ricevuto",
            ext_status=self.commented,
            crea_nuova_rev=True,
        )
        self.rev1 = Revisione.objects.create(
            documento=self.doc, rev_no=1, dis_plan_date=date(2026, 5, 4)
        )

    def _url(self, pk=None):
        return f"/api/revisioni/{pk or self.rev0.pk}/modifica-ricezione/"

    def _post(self, payload, pk=None):
        return self.client.post(
            self._url(pk), data=json.dumps(payload), content_type="application/json"
        )

    def _assert_rev0_invariata(self):
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 20))
        self.assertEqual(self.rev0.ext_status_id, self.commented.pk)
        self.assertEqual(self.rev0.int_status, "ricevuto")
        self.assertTrue(self.rev0.crea_nuova_rev)

    def _assert_rev1_invariata(self):
        self.rev1.refresh_from_db()
        self.assertEqual(self.rev1.dis_plan_date, date(2026, 5, 4))

    # ── Cambio della data di rientro ──────────────────────────────────────────

    def test_cambio_data_ricalcola_l_invio_pianificato_della_successiva_vuota(self):
        risposta = self._post({"rec_act_date": "2026-04-22"})

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertTrue(dati["ok"])
        self.assertEqual(dati["revisione"]["id"], self.rev0.pk)
        self.assertEqual(dati["revisione"]["rec_act_date"], "2026-04-22")
        self.assertEqual(dati["successiva"]["azione"], "aggiornata")
        self.assertEqual(dati["successiva"]["revisione"]["id"], self.rev1.pk)
        # Come alla ricezione: nuovo rientro + time_ven_doc_rev.
        self.assertEqual(dati["successiva"]["revisione"]["dis_plan_date"], "2026-05-06")

        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 22))
        # Il resto della ricezione e i dati dell'invio restano.
        self.assertEqual(self.rev0.ext_status_id, self.commented.pk)
        self.assertEqual(self.rev0.int_status, "ricevuto")
        self.assertTrue(self.rev0.crea_nuova_rev)
        self.assertEqual(self.rev0.dis_act_date, date(2026, 4, 1))
        self.assertEqual(self.rev0.rec_plan_date, date(2026, 4, 11))
        self.rev1.refresh_from_db()
        self.assertEqual(self.rev1.dis_plan_date, date(2026, 5, 6))

    def test_cambio_data_con_successiva_lavorata_cambia_solo_la_data(self):
        self.rev1.dis_act_date = date(2026, 5, 2)
        self.rev1.save()

        risposta = self._post({"rec_act_date": "2026-04-22"})

        self.assertEqual(risposta.status_code, 200)
        successiva = risposta.json()["successiva"]
        self.assertEqual(successiva["azione"], "nessuna")
        self.assertEqual(successiva["revisione"]["id"], self.rev1.pk)
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 22))
        self._assert_rev1_invariata()
        self.assertEqual(self.rev1.dis_act_date, date(2026, 5, 2))

    def test_cambio_data_senza_giorni_del_vendor_non_cancella_l_invio_pianificato(self):
        self.testata.time_ven_doc_rev = None
        self.testata.save()

        risposta = self._post({"rec_act_date": "2026-04-22"})

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["successiva"]["azione"], "nessuna")
        self._assert_rev1_invariata()

    def test_cambio_data_senza_successiva(self):
        self.rev1.delete()

        risposta = self._post({"rec_act_date": "2026-04-22"})

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["successiva"], {"azione": "nessuna", "revisione": None})
        self.assertEqual(self.doc.revisioni.count(), 1)

    def test_rientro_il_giorno_dell_invio_o_oggi_e_ammesso(self):
        for giorno in (date(2026, 4, 1), timezone.localdate()):
            with self.subTest(giorno=giorno):
                risposta = self._post({"rec_act_date": giorno.isoformat()})

                self.assertEqual(risposta.status_code, 200)
                self.rev0.refresh_from_db()
                self.assertEqual(self.rev0.rec_act_date, giorno)

    def test_data_prima_dell_invio_nel_futuro_o_uguale_e_un_400(self):
        casi = {
            "prima dell'invio": ("2026-03-31", "precedente alla data di invio"),
            "nel futuro": ((timezone.localdate() + timedelta(days=1)).isoformat(), "futuro"),
            "uguale": ("2026-04-20", "già questa"),
        }
        for caso, (giorno, messaggio) in casi.items():
            with self.subTest(caso=caso):
                risposta = self._post({"rec_act_date": giorno})

                self.assertEqual(risposta.status_code, 400)
                self.assertIn(messaggio, risposta.json()["error"])
        self._assert_rev0_invariata()
        self._assert_rev1_invariata()

    def test_body_mancante_o_data_non_iso_e_un_400(self):
        for payload in (
            {},
            {"rec_act_date": ""},
            {"rec_act_date": "20/04/2026"},
            {"rec_act_date": "20260422"},
            {"rec_act_date": "2026-W17-3"},
            {"rec_act_date": "2026-02-30"},
            {"rec_act_date": 20260422},
            [],
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self._post(payload).status_code, 400)
        for body in ("", "{"):
            with self.subTest(body=body):
                risposta = self.client.post(self._url(), data=body, content_type="application/json")
                self.assertEqual(risposta.status_code, 400)
        self._assert_rev0_invariata()
        self._assert_rev1_invariata()

    # ── Annullamento della ricezione ──────────────────────────────────────────

    def test_annullamento_elimina_la_successiva_vuota_e_riporta_la_revisione_inviata(self):
        risposta = self._post({"rec_act_date": None})

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertEqual(dati["revisione"]["int_status"], "inviato_al_cliente")
        self.assertIsNone(dati["revisione"]["rec_act_date"])
        self.assertIsNone(dati["revisione"]["ext_status"])
        self.assertFalse(dati["revisione"]["crea_nuova_rev"])
        self.assertEqual(dati["successiva"]["azione"], "eliminata")
        self.assertEqual(dati["successiva"]["revisione"]["id"], self.rev1.pk)

        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "inviato_al_cliente")
        self.assertIsNone(self.rev0.rec_act_date)
        self.assertIsNone(self.rev0.ext_status_id)
        self.assertFalse(self.rev0.crea_nuova_rev)
        # Le date dell'invio restano.
        self.assertEqual(self.rev0.dis_act_date, date(2026, 4, 1))
        self.assertEqual(self.rev0.rec_plan_date, date(2026, 4, 11))
        self.assertFalse(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_annullamento_con_successiva_lavorata_e_un_409_e_non_cambia_nulla(self):
        lavorazioni = {
            "inviata": lambda: Revisione.objects.filter(pk=self.rev1.pk).update(
                dis_act_date=date(2026, 5, 2)
            ),
            "file collegato": lambda: RevisioneFileLink.objects.create(
                revisione=self.rev1, percorso=r"Z:\JOBS\26320\x.pdf"
            ),
            "in un trasmittal": lambda: Transmittal.objects.create(
                testata=self.testata, numero=1
            ).revisioni.add(self.rev1),
        }
        for caso, lavora in lavorazioni.items():
            with self.subTest(caso=caso):
                lavora()

                risposta = self._post({"rec_act_date": None})

                self.assertEqual(risposta.status_code, 409)
                self.assertEqual(
                    risposta.json()["error"],
                    "La revisione successiva è già in lavorazione, correggere manualmente.",
                )
                self._assert_rev0_invariata()
                self._assert_rev1_invariata()

                # Un caso alla volta: la successiva torna vuota.
                Revisione.objects.filter(pk=self.rev1.pk).update(dis_act_date=None)
                RevisioneFileLink.objects.filter(revisione=self.rev1).delete()
                self.rev1.trasmittal.clear()

    def test_annullamento_senza_successiva(self):
        self.rev1.delete()

        risposta = self._post({"rec_act_date": None})

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["successiva"], {"azione": "nessuna", "revisione": None})
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "inviato_al_cliente")
        self.assertIsNone(self.rev0.rec_act_date)
        self.assertEqual(self.doc.revisioni.count(), 1)

    def test_dopo_l_annullamento_la_ricezione_si_registra_di_nuovo(self):
        self._post({"rec_act_date": None})

        risultato = esegui_ricezione(
            [
                {
                    "doc_id": self.doc.pk,
                    "rec_act_date": "2026-04-25",
                    "ext_status_id": self.commented.pk,
                    "crea_nuova_revisione": True,
                }
            ]
        )

        self.assertEqual([r["rev_no"] for r in risultato], [0, 1])
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.rec_act_date, date(2026, 4, 25))
        self.assertEqual(self.doc.revisioni.get(rev_no=1).dis_plan_date, date(2026, 5, 9))

    # ── Precondizioni ─────────────────────────────────────────────────────────

    def test_revisione_non_rientrata_e_un_400(self):
        inviata = Revisione.objects.create(
            documento=self.doc,
            rev_no=2,
            dis_act_date=date(2026, 6, 1),
            int_status="inviato_al_cliente",
        )
        # Stato salvato "ricevuto" ma senza data di rientro: non è rientrata.
        senza_data = Revisione.objects.create(documento=self.doc, rev_no=3, int_status="ricevuto")
        for rev in (self.rev1, inviata, senza_data):
            for payload in ({"rec_act_date": "2026-06-10"}, {"rec_act_date": None}):
                with self.subTest(rev=rev.rev_no, payload=payload):
                    risposta = self._post(payload, pk=rev.pk)

                    self.assertEqual(risposta.status_code, 400)
                    self.assertEqual(
                        risposta.json()["error"],
                        "La revisione non risulta rientrata dal cliente: niente da modificare.",
                    )
        inviata.refresh_from_db()
        self.assertEqual(inviata.int_status, "inviato_al_cliente")
        self.assertIsNone(inviata.rec_act_date)
        self._assert_rev1_invariata()

    def test_revisione_inesistente_e_un_404(self):
        risposta = self._post({"rec_act_date": None}, pk=999999)

        self.assertEqual(risposta.status_code, 404)
        self.assertEqual(risposta.json()["error"], "Revisione non trovata.")

    # ── Permessi ──────────────────────────────────────────────────────────────

    def _esiti(self):
        """Risposta di ricezione_api e del nuovo endpoint per l'utente corrente."""
        ricezione = self.client.post(
            "/api/ricezione/", data=json.dumps({"entries": []}), content_type="application/json"
        )
        return ricezione, self._post({"rec_act_date": None})

    def test_utente_in_sola_lettura_ha_lo_stesso_esito_di_ricezione(self):
        lettore = User.objects.create_user(
            "mr_reader", "mr-reader@b.it", "pw", permesso=Permesso.READING
        )
        self.client.force_login(lettore)

        ricezione, risposta = self._esiti()

        self.assertEqual(risposta.status_code, 403)
        self.assertEqual(risposta.status_code, ricezione.status_code)
        self.assertEqual(risposta.json(), ricezione.json())
        self._assert_rev0_invariata()
        self.assertTrue(Revisione.objects.filter(pk=self.rev1.pk).exists())

    def test_utente_non_autenticato_ha_lo_stesso_esito_di_ricezione(self):
        self.client.logout()

        ricezione, risposta = self._esiti()

        self.assertEqual((ricezione.status_code, risposta.status_code), (401, 401))
        self._assert_rev0_invariata()

    def test_solo_post(self):
        self.assertEqual(self.client.get(self._url()).status_code, 405)
        self._assert_rev0_invariata()
