import io
import sys
from datetime import date, datetime, time, timedelta
from unittest.mock import Mock, patch

import pandas as pd
from django.core.management import call_command
from django.test import Client, TestCase
from django.utils import timezone

from ..models import (
    AggiornamentoBC,
    EsecuzioneSchedulata,
    Permesso,
    Stabilimento,
    Testata,
)
from ..services import scheduler
from ..services.bc_sync import (
    BusinessCentralNonDisponibile,
    confronta_commessa,
    list_aggiornamenti,
    sincronizza_commesse,
    sincronizza_sito_costruttivo,
)
from ..services.commesse import (
    fetch_from_bc,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _FakeBusinessCentral, _FakeBusinessCentralSito


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


class ArchivioBcSyncApiTest(TestCase):
    """Pulsante "Aggiorna da BC" nella pagina Informazioni archivio."""

    def setUp(self):
        self.testata = Testata.objects.create(
            job="26010",
            client="Cliente Vecchio",
            po_no="PO-1",
            job_detail="Descrizione vecchia",
            delivery_date=date(2026, 1, 10),
        )
        self.writer = User.objects.create_user(
            "writer_bcsync", "writer_bcsync@example.com", "pw", permesso=Permesso.WRITING
        )
        self.reader = User.objects.create_user(
            "reader_bcsync", "reader_bcsync@example.com", "pw", permesso=Permesso.READING
        )
        self.client = Client()
        self.client.force_login(self.writer)

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

    def test_sincronizza_e_ritorna_gli_aggiornamenti(self):
        self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["aggiornate"], 1)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Nuovo")
        self.assertEqual(
            {a["campo"] for a in data["aggiornamenti_bc"]},
            {"client"},
        )

    def test_nessuna_differenza_ritorna_lista_vuota(self):
        self._attiva_bc({"26010": {"job": "26010"}})

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["aggiornate"], 0)
        self.assertEqual(data["aggiornamenti_bc"], [])

    def test_sincronizza_anche_commessa_chiusa(self):
        self.testata.actual_delivery_date = date(2026, 2, 1)
        self.testata.save(update_fields=["actual_delivery_date"])
        self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["aggiornate"], 1)

    def test_commessa_non_trovata_in_bc(self):
        self._attiva_bc({})

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.json())

    def test_bc_non_disponibile(self):
        self._attiva_bc({"26010": {"job": "26010"}}, conn=False)

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 503)

    def test_commessa_inesistente_404(self):
        response = self.client.post("/api/commesse/NON-ESISTE/archivio/bc-sync/")
        self.assertEqual(response.status_code, 404)

    def test_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.reader)
        self._attiva_bc({"26010": {"job": "26010", "client": "Cliente Nuovo"}})

        response = self.client.post("/api/commesse/26010/archivio/bc-sync/")

        self.assertEqual(response.status_code, 403)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.client, "Cliente Vecchio")

    def test_get_non_ammesso(self):
        response = self.client.get("/api/commesse/26010/archivio/bc-sync/")
        self.assertEqual(response.status_code, 405)


class SincronizzazioneSitoCostruttivoTests(TestCase):
    """Backfill di Testata.sito_costruttivo dal codice sito Business Central."""

    def setUp(self):
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        self.senza_sito = Testata.objects.create(job="99050")

    def _attiva_bc(self, codici_per_job, conn=True):
        fake = _FakeBusinessCentralSito(codici_per_job, conn=conn)
        patcher = patch("core.services.bc_sync._apri_connessione", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_imposta_il_sito_dal_codice_bc(self):
        self._attiva_bc({"99050": "1"})

        report = sincronizza_sito_costruttivo()

        self.senza_sito.refresh_from_db()
        self.assertEqual(self.senza_sito.sito_costruttivo_id, self.bg.pk)
        self.assertEqual(report["aggiornate"], 1)
        self.assertEqual(report["aggiornamenti"], [{"job": "99050", "stabilimento": "Valbrembo"}])

    def test_registra_l_aggiornamento_per_il_pannello_archivio(self):
        self._attiva_bc({"99050": "2"})

        sincronizza_sito_costruttivo()

        voci = {v["campo"]: v for v in list_aggiornamenti("99050")}
        self.assertEqual(voci["sito_costruttivo"]["etichetta"], "Sito costruttivo")
        self.assertEqual(voci["sito_costruttivo"]["nuovo"], "Albignasego")

    def test_non_sovrascrive_un_sito_gia_impostato(self):
        self.senza_sito.sito_costruttivo = self.pd
        self.senza_sito.save(update_fields=["sito_costruttivo"])
        fake = self._attiva_bc({"99050": "1"})

        report = sincronizza_sito_costruttivo()

        self.senza_sito.refresh_from_db()
        self.assertEqual(self.senza_sito.sito_costruttivo_id, self.pd.pk)
        self.assertEqual(report["controllate"], 0)
        self.assertEqual(fake.chiusa, False)  # mai aperta: nessuna commessa da controllare

    def test_commessa_non_trovata_o_senza_sito_in_bc(self):
        self._attiva_bc({"99050": None})

        report = sincronizza_sito_costruttivo()

        self.assertEqual(report["non_trovate"], ["99050"])
        self.assertEqual(report["aggiornate"], 0)
        self.senza_sito.refresh_from_db()
        self.assertIsNone(self.senza_sito.sito_costruttivo_id)

    def test_codice_sito_senza_stabilimento_corrispondente(self):
        self._attiva_bc({"99050": "999"})

        report = sincronizza_sito_costruttivo()

        self.assertEqual(report["senza_stabilimento"], [{"job": "99050", "codice_sito": "999"}])
        self.senza_sito.refresh_from_db()
        self.assertIsNone(self.senza_sito.sito_costruttivo_id)

    def test_errore_su_una_commessa_non_ferma_le_altre(self):
        altra = Testata.objects.create(job="99051")
        self._attiva_bc({"99050": RuntimeError("query fallita"), "99051": "2"})

        report = sincronizza_sito_costruttivo()

        self.assertEqual(len(report["errori"]), 1)
        self.assertEqual(report["errori"][0]["job"], "99050")
        altra.refresh_from_db()
        self.assertEqual(altra.sito_costruttivo_id, self.pd.pk)

    def test_dry_run_non_scrive_nulla(self):
        self._attiva_bc({"99050": "1"})

        report = sincronizza_sito_costruttivo(dry_run=True)

        self.assertEqual(report["aggiornate"], 1)
        self.senza_sito.refresh_from_db()
        self.assertIsNone(self.senza_sito.sito_costruttivo_id)

    def test_limita_a_un_job(self):
        Testata.objects.create(job="99052")
        self._attiva_bc({"99050": "1", "99052": "2"})

        report = sincronizza_sito_costruttivo(jobs=["99050"])

        self.assertEqual(report["controllate"], 1)
        self.assertEqual(Testata.objects.get(job="99052").sito_costruttivo_id, None)

    def test_connessione_non_disponibile(self):
        self._attiva_bc({"99050": "1"}, conn=False)

        with self.assertRaises(BusinessCentralNonDisponibile):
            sincronizza_sito_costruttivo()


class ComandoSyncBusinessCentralTests(TestCase):
    """Il comando ``sync_business_central``, pensato per l'esecuzione giornaliera."""

    def setUp(self):
        self.testata = Testata.objects.create(job="26010", client="Cliente Vecchio")

    def _attiva_bc(self, dati_per_job, conn=True, codici_sito=None):
        fake = _FakeBusinessCentral(dati_per_job, conn=conn, codici_sito=codici_sito)
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

    def test_il_comando_aggiorna_anche_il_sito_costruttivo(self):
        bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self._attiva_bc(
            {"26010": {"job": "26010", "client": "Cliente Nuovo"}},
            codici_sito={"26010": "1"},
        )
        out = io.StringIO()

        call_command("sync_business_central", stdout=out)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.sito_costruttivo_id, bg.pk)
        output = out.getvalue()
        self.assertIn("26010: sito costruttivo -> Valbrembo", output)
        self.assertIn("Sito costruttivo — controllate 1 commesse, aggiornate 1", output)

    def test_il_comando_non_sovrascrive_un_sito_gia_impostato(self):
        pd_stabilimento = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        self.testata.sito_costruttivo = pd_stabilimento
        self.testata.save(update_fields=["sito_costruttivo"])
        self._attiva_bc(
            {"26010": {"job": "26010", "client": "Cliente Nuovo"}},
            codici_sito={"26010": "1"},  # BG: diverso, ma il campo è già impostato
        )
        out = io.StringIO()

        call_command("sync_business_central", stdout=out)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.sito_costruttivo_id, pd_stabilimento.pk)

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


class ComandoBackfillSitoCostruttivoTests(TestCase):
    """Il comando ``backfill_sito_costruttivo``, eseguito una tantum a mano."""

    def setUp(self):
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.testata = Testata.objects.create(job="99060")

    def _attiva_bc(self, codici_per_job, conn=True):
        fake = _FakeBusinessCentralSito(codici_per_job, conn=conn)
        patcher = patch("core.services.bc_sync._apri_connessione", return_value=fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def test_il_comando_aggiorna_e_riepiloga(self):
        self._attiva_bc({"99060": "1"})
        out = io.StringIO()

        call_command("backfill_sito_costruttivo", stdout=out)

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.sito_costruttivo_id, self.bg.pk)
        output = out.getvalue()
        self.assertIn("99060: sito costruttivo -> Valbrembo", output)
        self.assertIn("aggiornate 1", output)

    def test_il_comando_in_dry_run_non_salva(self):
        self._attiva_bc({"99060": "1"})
        out = io.StringIO()

        call_command("backfill_sito_costruttivo", "--dry-run", stdout=out)

        self.testata.refresh_from_db()
        self.assertIsNone(self.testata.sito_costruttivo_id)
        self.assertIn("[dry-run]", out.getvalue())

    def test_il_comando_accetta_una_singola_commessa(self):
        Testata.objects.create(job="99061")
        self._attiva_bc({"99060": "1", "99061": "1"})

        call_command("backfill_sito_costruttivo", "--job", "99060", stdout=io.StringIO())

        self.testata.refresh_from_db()
        self.assertEqual(self.testata.sito_costruttivo_id, self.bg.pk)
        self.assertIsNone(Testata.objects.get(job="99061").sito_costruttivo_id)

    def test_il_comando_segnala_una_commessa_inesistente(self):
        self._attiva_bc({})
        err = io.StringIO()

        call_command("backfill_sito_costruttivo", "--job", "99999", stderr=err)

        self.assertIn("non trovata", err.getvalue())

    def test_il_comando_segnala_business_central_non_raggiungibile(self):
        self._attiva_bc({"99060": "1"}, conn=False)
        err = io.StringIO()

        call_command("backfill_sito_costruttivo", stderr=err)

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
        self._sync_sito_finta()
        self._sync_destinazioni_finta()
        return mock

    def _sync_sito_finta(self, **report):
        """Sostituisce la sincronizzazione del sito costruttivo con un doppio di test."""
        dati = {
            "controllate": 0,
            "aggiornate": 0,
            "senza_stabilimento": [],
            "errori": [],
        }
        dati.update(report)
        finta = patch("core.services.scheduler.sincronizza_sito_costruttivo", return_value=dati)
        mock = finta.start()
        self.addCleanup(finta.stop)
        return mock

    def _sync_destinazioni_finta(self, **report):
        """Sostituisce l'import delle destinazioni UT con un doppio di test."""
        dati = {
            "controllate": 0,
            "con_file": 0,
            "precompilati": 0,
            "gia_impostati": 0,
            "non_trovati": [],
            "errori": [],
            "dry_run": False,
        }
        dati.update(report)
        finta = patch(
            "core.services.scheduler.importa_destinazioni_tutte_le_commesse", return_value=dati
        )
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

    def test_sincronizza_anche_il_sito_costruttivo(self):
        self._sync_finta()
        sync_sito = self._sync_sito_finta(controllate=5, aggiornate=2)
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        sync_sito.assert_called_once_with()
        esito = self._stato().esito
        self.assertIn("sito costruttivo", esito)
        self.assertIn("controllate 5", esito)
        self.assertIn("aggiornate 2", esito)

    def test_sito_costruttivo_non_disponibile_non_blocca_la_sync_principale(self):
        sync = self._sync_finta()
        finta = patch(
            "core.services.scheduler.sincronizza_sito_costruttivo",
            side_effect=BusinessCentralNonDisponibile("ERP irraggiungibile"),
        )
        finta.start()
        self.addCleanup(finta.stop)
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        sync.assert_called_once_with()
        esito = self._stato().esito
        self.assertIn("controllate 3", esito)  # la sync principale è comunque registrata
        self.assertIn("sito costruttivo: errore", esito)

    def test_precompila_anche_le_destinazioni_ut(self):
        self._sync_finta()
        sync_destinazioni = self._sync_destinazioni_finta(controllate=5, con_file=2, precompilati=7)
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        sync_destinazioni.assert_called_once_with()
        esito = self._stato().esito
        self.assertIn("destinazioni UT", esito)
        self.assertIn("con file 2", esito)
        self.assertIn("precompilati 7", esito)

    def test_destinazioni_ut_in_errore_non_blocca_il_resto(self):
        sync = self._sync_finta()
        finta = patch(
            "core.services.scheduler.importa_destinazioni_tutte_le_commesse",
            side_effect=RuntimeError("condivisione di rete irraggiungibile"),
        )
        finta.start()
        self.addCleanup(finta.stop)
        adesso = self._momento(self.oggi, 17, 1)

        self.assertTrue(scheduler.esegui_se_dovuto(adesso=adesso))

        sync.assert_called_once_with()
        esito = self._stato().esito
        self.assertIn("controllate 3", esito)  # la sync principale è comunque registrata
        self.assertIn("destinazioni UT: errore", esito)

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
        self._sync_sito_finta()
        self._sync_destinazioni_finta()
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
        self._sync_sito_finta()
        self._sync_destinazioni_finta()

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


class ArchivioSitoCostruttivoManualeTests(TestCase):
    """Il sito costruttivo si può impostare/correggere a mano da Informazioni archivio."""

    def setUp(self):
        self.valido = Stabilimento.objects.create(nome="Valbrembo", sigla="VB", codice_bc=1)
        self.non_valido = Stabilimento.objects.create(nome="Milano", sigla=None, codice_bc=None)
        self.testata = Testata.objects.create(job="26010")
        self.writer = User.objects.create_user(
            "writer_sito", "writer_sito@example.com", "pw", permesso=Permesso.WRITING
        )
        self.client = Client()
        self.client.force_login(self.writer)

    def test_dropdown_mostra_solo_stabilimenti_con_codice_bc(self):
        response = self.client.get(f"/commesse/{self.testata.job}/archivio/")

        self.assertContains(response, "Valbrembo")
        self.assertNotContains(response, "Milano")

    def test_salvataggio_imposta_il_sito_costruttivo(self):
        response = self.client.put(
            f"/api/commesse/{self.testata.job}/",
            data={"sito_costruttivo_id": self.valido.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.testata.refresh_from_db()
        self.assertEqual(self.testata.sito_costruttivo_id, self.valido.id)

    def test_stabilimento_senza_codice_bc_viene_rifiutato(self):
        response = self.client.put(
            f"/api/commesse/{self.testata.job}/",
            data={"sito_costruttivo_id": self.non_valido.id},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 422)
        self.testata.refresh_from_db()
        self.assertIsNone(self.testata.sito_costruttivo_id)

    def test_si_puo_azzerare_il_sito_costruttivo(self):
        self.testata.sito_costruttivo = self.valido
        self.testata.save(update_fields=["sito_costruttivo"])

        response = self.client.put(
            f"/api/commesse/{self.testata.job}/",
            data={"sito_costruttivo_id": None},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.testata.refresh_from_db()
        self.assertIsNone(self.testata.sito_costruttivo_id)
