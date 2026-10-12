from datetime import UTC, date, datetime

from django.test import Client, SimpleTestCase, TestCase

from ..models import (
    CommessaPin,
    Permesso,
    Testata,
)
from ..page_title import format_commessa_page_title
from ..services.commesse import (
    MAX_PINNED_COMMESSE,
    list_home_commesse,
    pin_commessa,
)
from ..templatetags.page_title_extras import commessa_title

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User


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


class TitoloPaginaCommessaTests(SimpleTestCase):
    """Nel titolo della pagina la commessa si legge dal numero, non dalla parola."""

    def test_la_pagina_della_commessa_mostra_solo_il_numero(self):
        self.assertEqual(format_commessa_page_title("25056"), "25056")

    def test_le_sezioni_hanno_il_numero_davanti_al_nome(self):
        self.assertEqual(
            format_commessa_page_title("25056", "Lista documenti"),
            "25056 · Lista documenti",
        )

    def test_senza_numero_resta_il_nome_della_sezione(self):
        self.assertEqual(format_commessa_page_title("", "Archivio"), "Archivio")
        self.assertEqual(format_commessa_page_title(None), "Commessa")
        self.assertEqual(format_commessa_page_title("   "), "Commessa")

    def test_il_tag_legge_il_numero_da_testata_dizionario_o_stringa(self):
        self.assertEqual(commessa_title(Testata(job="26010")), "26010")
        self.assertEqual(commessa_title({"job": "26010"}, "Archivio"), "26010 · Archivio")
        self.assertEqual(commessa_title("26010"), "26010")
        self.assertEqual(commessa_title(None, "Archivio"), "Archivio")


class TitoloPaginaCommessaViewTests(TestCase):
    """Le pagine della commessa portano il numero nel nome che compare in alto."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "titolo_user",
            "titolo@brembanarolle.com",
            "pw",
            permesso=Permesso.READING,
        )
        self.client.force_login(self.user)
        self.testata = Testata.objects.create(job="26042", client="Cliente Titolo")

    def test_ogni_pagina_della_commessa_ha_il_numero_nel_titolo(self):
        job = self.testata.job
        attesi = {
            "": job,
            "documenti/": f"{job} · Lista documenti",
            "archivio/": f"{job} · Archivio",
            "emissione/": f"{job} · Gestisci emissione",
            "ricezione/": f"{job} · Gestisci ricezione",
            "situazione/": f"{job} · Situazione documenti",
        }
        for sezione, titolo in attesi.items():
            with self.subTest(sezione=sezione or "commessa"):
                response = self.client.get(f"/commesse/{job}/{sezione}")

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f"<title>{titolo}</title>")
                self.assertNotContains(response, "<title>Commessa</title>")

    def test_fuori_dalla_commessa_il_titolo_non_cambia(self):
        response = self.client.get("/commesse/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Elenco Commesse</title>")


class DateDisplayFormatTests(SimpleTestCase):
    """Dates are shown as ``10 jan 2026`` across the app."""

    def test_format_display_date(self):
        import datetime

        from ..date_fmt import format_display_date

        self.assertEqual(format_display_date(datetime.date(2026, 1, 10)), "10 jan 2026")
        self.assertEqual(format_display_date("2026-03-05"), "5 mar 2026")
        self.assertEqual(format_display_date(None), "")
        self.assertEqual(format_display_date(""), "")

    def test_pdf_date_line(self):
        from src.pdf import _fmt_date

        self.assertEqual(_fmt_date("2026-01-10", "Milano"), "Milano, 10 jan 2026")
        self.assertEqual(_fmt_date("2026-01-10", ""), "10 jan 2026")


class FormatDisplayDateTests(SimpleTestCase):
    def test_datetime_aware_si_legge_nel_fuso_locale(self):
        from core.date_fmt import format_display_date

        # 23:30 UTC del 14 marzo = 00:30 del 15 marzo a Roma.
        self.assertEqual(
            format_display_date(datetime(2026, 3, 14, 23, 30, tzinfo=UTC)), "15 mar 2026"
        )

    def test_datetime_naive_e_date_restano_come_sono(self):
        from core.date_fmt import format_display_date

        self.assertEqual(format_display_date(datetime(2026, 3, 14, 23, 30)), "14 mar 2026")
        self.assertEqual(format_display_date(date(2026, 1, 10)), "10 jan 2026")
