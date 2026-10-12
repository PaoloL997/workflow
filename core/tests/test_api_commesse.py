"""API di commesse, indirizzi, documenti, revisioni, ricezione, export e anomalie.

Prima di questo modulo il CRUD via HTTP non aveva nessun test: i servizi
erano coperti, le viste no.
"""

import json

from django.core import mail
from django.test import Client, TestCase
from django.utils import timezone

from ..models import (
    CartellaModelloDocumento,
    Documento,
    IndirSped,
    Permesso,
    Reparto,
    Revisione,
    StatoEsterno,
    Testata,
)
from ._fixtures import User

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _ApiTestCase(TestCase):
    """Un writer loggato e una commessa con un documento e la sua revisione 0."""

    def setUp(self):
        self.client = Client()
        self.writer = User.objects.create_user(
            "api_writer", "api-writer@b.it", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(self.writer)
        self.testata = Testata.objects.create(
            job="26200", client="Cliente API", time_cli_doc_rev=10
        )
        self.doc = Documento.objects.create(
            testata=self.testata, vendor_doc="26200-A", doc_title="Documento A"
        )
        self.rev0 = Revisione.objects.create(documento=self.doc, rev_no=0)

    def _json(self, method, url, payload=None):
        return getattr(self.client, method)(
            url, data=json.dumps(payload or {}), content_type="application/json"
        )


class CommesseApiTests(_ApiTestCase):
    def test_crea_commessa(self):
        risposta = self._json("post", "/api/commesse/", {"job": "26201", "client": "Nuovo"})

        self.assertEqual(risposta.status_code, 201)
        self.assertEqual(risposta.json()["data"]["job"], "26201")
        self.assertTrue(Testata.objects.filter(job="26201", client="Nuovo").exists())

    def test_crea_commessa_con_job_duplicato_viene_rifiutata(self):
        # L'unicità la intercetta full_clean (422) prima del vincolo del DB (409).
        risposta = self._json("post", "/api/commesse/", {"job": self.testata.job})

        self.assertEqual(risposta.status_code, 422)
        self.assertIn("job", risposta.json()["error"])
        self.assertEqual(Testata.objects.filter(job=self.testata.job).count(), 1)

    def test_crea_commessa_senza_job_e_un_422(self):
        risposta = self._json("post", "/api/commesse/", {"job": "", "client": "X"})

        self.assertEqual(risposta.status_code, 422)
        self.assertIn("job", risposta.json()["error"])

    def test_json_non_valido_e_un_400(self):
        risposta = self.client.post("/api/commesse/", data="{", content_type="application/json")

        self.assertEqual(risposta.status_code, 400)

    def test_dettaglio_e_404(self):
        self.assertEqual(
            self.client.get(f"/api/commesse/{self.testata.job}/").json()["data"]["client"],
            "Cliente API",
        )
        self.assertEqual(self.client.get("/api/commesse/NOPE/").status_code, 404)

    def test_aggiorna_commessa(self):
        risposta = self._json(
            "put",
            f"/api/commesse/{self.testata.job}/",
            {"client": "Cliente nuovo", "po_no": "PO-1"},
        )

        self.assertEqual(risposta.status_code, 200)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente nuovo")
        self.assertEqual(self.testata.po_no, "PO-1")

    def test_chi_legge_soltanto_non_aggiorna(self):
        reader = User.objects.create_user("api_reader", "api-reader@b.it", "pw")
        self.client.force_login(reader)

        risposta = self._json("put", f"/api/commesse/{self.testata.job}/", {"client": "X"})

        self.assertEqual(risposta.status_code, 403)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente API")

    def test_chiudi_commessa_una_volta_sola(self):
        risposta = self.client.post(f"/api/commesse/{self.testata.job}/chiudi/")

        self.assertEqual(risposta.status_code, 200)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.actual_delivery_date, timezone.localdate())
        self.assertEqual(
            self.client.post(f"/api/commesse/{self.testata.job}/chiudi/").status_code, 409
        )
        self.assertEqual(self.client.post("/api/commesse/NOPE/chiudi/").status_code, 404)

    def test_un_admin_elimina_la_commessa_un_writer_ne_chiede_l_eliminazione(self):
        richiesta = self.client.delete(f"/api/commesse/{self.testata.job}/")

        self.assertEqual(richiesta.status_code, 200)
        self.assertTrue(Testata.objects.filter(job=self.testata.job).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.testata.job, mail.outbox[0].subject + mail.outbox[0].body)

        admin = User.objects.create_user(
            "api_admin", "api-admin@b.it", "pw", permesso=Permesso.ADMIN
        )
        self.client.force_login(admin)
        eliminazione = self.client.delete(f"/api/commesse/{self.testata.job}/")

        self.assertEqual(eliminazione.status_code, 200)
        self.assertFalse(Testata.objects.filter(job=self.testata.job).exists())
        self.assertFalse(Documento.objects.filter(pk=self.doc.pk).exists())


class IndirizziApiTests(_ApiTestCase):
    def _url(self):
        return f"/api/commesse/{self.testata.job}/indirizzi/"

    def test_crea_elenca_modifica_ed_elimina(self):
        creato = self._json(
            "post", self._url(), {"consignee": "Magazzino", "city": "Bergamo", "country": "IT"}
        )
        self.assertEqual(creato.status_code, 201)
        pk = creato.json()["data"]["id"]

        elenco = self.client.get(self._url()).json()["indirizzi"]
        self.assertEqual([i["consignee"] for i in elenco], ["Magazzino"])

        modificato = self._json("patch", f"/api/indirizzi/{pk}/", {"city": "Milano"})
        self.assertEqual(modificato.status_code, 200)
        self.assertEqual(IndirSped.objects.get(pk=pk).city, "Milano")

        self.assertEqual(self.client.delete(f"/api/indirizzi/{pk}/").status_code, 200)
        self.assertFalse(IndirSped.objects.filter(pk=pk).exists())

    def test_404_su_commessa_e_indirizzo_inesistenti(self):
        self.assertEqual(self.client.get("/api/commesse/NOPE/indirizzi/").status_code, 404)
        self.assertEqual(
            self._json("post", "/api/commesse/NOPE/indirizzi/", {"city": "X"}).status_code, 404
        )
        self.assertEqual(self._json("patch", "/api/indirizzi/999999/", {}).status_code, 404)
        self.assertEqual(self.client.delete("/api/indirizzi/999999/").status_code, 404)

    def test_campo_troppo_lungo_e_un_400(self):
        risposta = self._json("post", self._url(), {"zip_code": "1" * 21})

        self.assertEqual(risposta.status_code, 400)
        self.assertFalse(IndirSped.objects.filter(testata=self.testata).exists())


class DocumentiRevisioniApiTests(_ApiTestCase):
    def test_crea_documento_con_revisione_zero(self):
        Reparto.objects.create(nome="Qualità", acronimo="QC")

        risposta = self._json(
            "post",
            f"/api/commesse/{self.testata.job}/documenti/",
            {"vendor_doc": "26200-B", "doc_title": "Documento B", "reparto": "Qualità"},
        )

        self.assertEqual(risposta.status_code, 201)
        dati = risposta.json()["data"]
        self.assertEqual(dati["vendor_doc"], "26200-B")
        self.assertEqual(dati["reparto_acronimo"], "QC")
        self.assertEqual(dati["latest_rev_no"], 0)
        self.assertTrue(Revisione.objects.filter(documento_id=dati["id"], rev_no=0).exists())

    def test_dettaglio_modifica_ed_eliminazione_documento(self):
        dettaglio = self.client.get(f"/api/documenti/{self.doc.pk}/")
        self.assertEqual(dettaglio.status_code, 200)
        self.assertEqual(dettaglio.json()["doc_title"], "Documento A")

        modifica = self._json(
            "patch",
            f"/api/documenti/{self.doc.pk}/",
            {"doc_title": "Titolo nuovo", "doc_penalty": True},
        )
        self.assertEqual(modifica.status_code, 200)
        self.doc.refresh_from_db()
        self.assertEqual(self.doc.doc_title, "Titolo nuovo")
        self.assertTrue(self.doc.doc_penalty)

        self.assertEqual(self.client.delete(f"/api/documenti/{self.doc.pk}/").status_code, 200)
        self.assertFalse(Documento.objects.filter(pk=self.doc.pk).exists())
        self.assertFalse(Revisione.objects.filter(pk=self.rev0.pk).exists())
        self.assertEqual(self.client.get(f"/api/documenti/{self.doc.pk}/").status_code, 404)

    def test_revisioni_elenco_creazione_modifica_eliminazione(self):
        url = f"/api/documenti/{self.doc.pk}/revisioni/"
        self.assertEqual([r["rev_no"] for r in self.client.get(url).json()["revisioni"]], [0])

        creata = self._json("post", url, {"rev_no": 1, "dis_plan_date": "2026-05-01"})
        self.assertEqual(creata.status_code, 201)
        pk = creata.json()["data"]["id"]
        self.assertEqual([r["rev_no"] for r in self.client.get(url).json()["revisioni"]], [0, 1])

        modificata = self._json(
            "patch", f"/api/revisioni/{pk}/", {"dis_act_date": "2026-05-03", "dis_plan_date": ""}
        )
        self.assertEqual(modificata.status_code, 200)
        rev = Revisione.objects.get(pk=pk)
        self.assertEqual(str(rev.dis_act_date), "2026-05-03")
        self.assertIsNone(rev.dis_plan_date)

        self.assertEqual(self.client.delete(f"/api/revisioni/{pk}/").status_code, 200)
        self.assertFalse(Revisione.objects.filter(pk=pk).exists())

    def test_stato_interno_non_previsto_e_un_400(self):
        risposta = self._json("patch", f"/api/revisioni/{self.rev0.pk}/", {"int_status": "boh"})

        self.assertEqual(risposta.status_code, 400)
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "")

    def test_404_su_documento_e_revisione_inesistenti(self):
        self.assertEqual(self.client.get("/api/documenti/999999/revisioni/").status_code, 404)
        self.assertEqual(
            self._json("post", "/api/documenti/999999/revisioni/", {"rev_no": 1}).status_code, 404
        )
        self.assertEqual(self._json("patch", "/api/revisioni/999999/", {}).status_code, 404)
        self.assertEqual(self.client.delete("/api/revisioni/999999/").status_code, 404)
        self.assertEqual(
            self._json("post", "/api/commesse/NOPE/documenti/", {"vendor_doc": "X"}).status_code,
            404,
        )


class RicezioneApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        self.rev0.dis_act_date = "2026-04-01"
        self.rev0.int_status = "inviato_al_cliente"
        self.rev0.save()
        self.approved = StatoEsterno.objects.create(nome="Approved", lettera="A", colore="#00B050")

    def test_registra_la_ricezione(self):
        risposta = self._json(
            "post",
            "/api/ricezione/",
            {
                "entries": [
                    {
                        "doc_id": self.doc.pk,
                        "rec_act_date": "2026-04-20",
                        "ext_status_id": self.approved.pk,
                    }
                ]
            },
        )

        self.assertEqual(risposta.status_code, 200)
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "ricevuto")
        self.assertEqual(self.rev0.ext_status_id, self.approved.pk)
        self.assertEqual(str(self.rev0.rec_act_date), "2026-04-20")

    def test_senza_voci_o_con_risposta_inesistente_e_un_400(self):
        self.assertEqual(self._json("post", "/api/ricezione/", {"entries": []}).status_code, 400)

        risposta = self._json(
            "post",
            "/api/ricezione/",
            {
                "entries": [
                    {"doc_id": self.doc.pk, "rec_act_date": "2026-04-20", "ext_status_id": 999999}
                ]
            },
        )

        self.assertEqual(risposta.status_code, 400)
        self.rev0.refresh_from_db()
        self.assertEqual(self.rev0.int_status, "inviato_al_cliente")

    def test_pagina_ricezione(self):
        self.assertEqual(
            self.client.get(f"/commesse/{self.testata.job}/ricezione/").status_code, 200
        )
        self.assertEqual(self.client.get("/commesse/NOPE/ricezione/").status_code, 404)

    def test_export_ricezione_excel_e_pdf(self):
        url = f"/api/commesse/{self.testata.job}/ricezione/export/"

        excel = self.client.get(url)
        self.assertEqual(excel.status_code, 200)
        self.assertEqual(excel["Content-Type"], XLSX)
        self.assertIn(f"{self.testata.job}_to_be_received_", excel["Content-Disposition"])
        self.assertTrue(excel.content.startswith(b"PK"))

        pdf = self.client.get(url + "?format=pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        self.assertEqual(self.client.get("/api/commesse/NOPE/ricezione/export/").status_code, 404)


class ExportDocumentiApiTests(_ApiTestCase):
    def test_lista_documenti_in_excel(self):
        import io

        import openpyxl

        risposta = self.client.get(f"/api/commesse/{self.testata.job}/export/")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], XLSX)
        self.assertIn(
            f'filename="{self.testata.job}_document_list.xlsx"', risposta["Content-Disposition"]
        )
        foglio = openpyxl.load_workbook(io.BytesIO(risposta.content)).active
        self.assertEqual(foglio["B1"].value, "B&R Doc")
        self.assertEqual(foglio["B2"].value, "26200-A")
        self.assertEqual(foglio["F2"].value, "Documento A")

    def test_404_su_commessa_inesistente(self):
        self.assertEqual(self.client.get("/api/commesse/NOPE/export/").status_code, 404)


class AnomalieApiTests(_ApiTestCase):
    def setUp(self):
        super().setUp()
        # «Inviato al cliente» senza data di invio: un'anomalia certa.
        self.rev0.int_status = "inviato_al_cliente"
        self.rev0.save()

    def test_elenco_anomalie(self):
        risposta = self.client.get(f"/api/commesse/{self.testata.job}/anomalie/")

        self.assertEqual(risposta.status_code, 200)
        dati = risposta.json()
        self.assertEqual(dati["time_cli_doc_rev"], 10)
        self.assertGreaterEqual(dati["anomalie_totali"], 1)
        self.assertEqual(dati["gruppi"][0]["revisione_id"], self.rev0.pk)
        self.assertIn(
            "INVIATO_SENZA_DISPATCH", [a["codice"] for a in dati["gruppi"][0]["anomalie"]]
        )
        self.assertEqual(self.client.get("/api/commesse/NOPE/anomalie/").status_code, 404)

    def test_ignora_anomalie_di_una_revisione(self):
        url = f"/api/commesse/{self.testata.job}/anomalie/ignora/"

        risposta = self._json("post", url, {"revisione_id": self.rev0.pk})

        self.assertEqual(risposta.status_code, 200)
        self.rev0.refresh_from_db()
        self.assertTrue(self.rev0.ignora_anomalie)
        self.assertEqual(
            self.client.get(f"/api/commesse/{self.testata.job}/anomalie/").json()["count"], 0
        )

    def test_ignora_rifiuta_revisioni_di_altre_commesse_e_payload_vuoto(self):
        url = f"/api/commesse/{self.testata.job}/anomalie/ignora/"
        altra = Testata.objects.create(job="26299")
        doc_altra = Documento.objects.create(testata=altra, vendor_doc="26299-A")
        rev_altra = Revisione.objects.create(documento=doc_altra, rev_no=0)

        self.assertEqual(self._json("post", url, {"revisione_id": rev_altra.pk}).status_code, 400)
        self.assertEqual(self._json("post", url, {}).status_code, 400)
        self.assertEqual(self._json("post", url, {"revisione_id": 999999}).status_code, 404)
        rev_altra.refresh_from_db()
        self.assertFalse(rev_altra.ignora_anomalie)


class ListeApiTests(_ApiTestCase):
    def test_stati_interni_stabilimenti_e_cartelle_modelli(self):
        stati = self.client.get("/api/stati-interni/").json()["stati"]
        self.assertIn("inviato_al_cliente", [s["id"] for s in stati])

        self.assertEqual(self.client.get("/api/stabilimenti/").json()["stabilimenti"], [])

        CartellaModelloDocumento.objects.create(nome="Standard QC")
        cartelle = self.client.get("/api/cartelle-modelli/").json()["data"]
        self.assertEqual([c["nome"] for c in cartelle], ["Standard QC"])

    def test_genera_da_modelli_richiede_una_cartella_esistente(self):
        url = f"/api/commesse/{self.testata.job}/genera-da-modelli/"

        self.assertEqual(self._json("post", url, {}).status_code, 400)
        self.assertEqual(self._json("post", url, {"cartella_id": 999999}).status_code, 404)
        self.assertEqual(
            self._json(
                "post", "/api/commesse/NOPE/genera-da-modelli/", {"cartella_id": 1}
            ).status_code,
            404,
        )
