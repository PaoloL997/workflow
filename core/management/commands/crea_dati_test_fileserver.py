"""Management command to seed test data for the fileserver file-opening feature.

Creates the job 25056 with documents and revisions matching the test scenario:
  - 25056-QMDBI  Rev.0  inviata 05/09/25, ricevuta 17/11/25
  - 25056-01-QCPA  Rev.0  inviata 05/09/25, ricevuta 14/10/25
  - 25056-01-QCPA  Rev.1  inviata 07/11/25, ricevuta 10/11/25
  - 25056-01-QCPA  Rev.2  inviata 13/11/25, ricevuta 16/11/25

Usage::

    python manage.py crea_dati_test_fileserver
    python manage.py crea_dati_test_fileserver --elimina  # rimuove i dati creati

The command is idempotent: running it multiple times produces the same result.
"""

import datetime

from django.core.management.base import BaseCommand

from core.models import Documento, Reparto, Revisione, Testata


class Command(BaseCommand):
    help = "Crea dati di test per la funzionalità di apertura file da revisioni (job 25056)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--elimina",
            action="store_true",
            help="Elimina i dati di test precedentemente creati invece di crearli.",
        )

    def handle(self, *args, **options):
        if options["elimina"]:
            self._elimina()
        else:
            self._crea()

    # ── Private ──────────────────────────────────────────────────────────────

    def _crea(self):
        """Create all test fixtures idempotently."""
        # Reparto QC — acronimo deve corrispondere alla cartella PROGETTO\QC nel fileserver
        reparto_qc, created = Reparto.objects.get_or_create(
            acronimo="QC",
            defaults={"nome": "Qualità e Controllo"},
        )
        self._log_created("Reparto QC", created)

        # Testata (commessa 25056)
        testata, created = Testata.objects.get_or_create(
            job="25056",
            defaults={
                "client": "Cliente Test",
                "job_detail": "Dati di test – apertura file fileserver",
            },
        )
        self._log_created("Testata 25056", created)

        # ── Documento 1: 25056-QMDBI ─────────────────────────────────────────
        doc_qmdbi, created = Documento.objects.get_or_create(
            testata=testata,
            vendor_doc="25056-QMDBI",
            defaults={
                "doc_title": "Quality Manual – Documento BI",
                "reparto": reparto_qc.nome,
                "item_no": "QMD-01",
            },
        )
        self._log_created("Documento 25056-QMDBI", created)

        # Rev. 0 – inviata 05/09/25, ricevuta 17/11/25
        rev_qmdbi_0, created = Revisione.objects.get_or_create(
            documento=doc_qmdbi,
            rev_no=0,
            defaults={
                "dis_act_date": datetime.date(2025, 9, 5),
                "rec_act_date": datetime.date(2025, 11, 17),
            },
        )
        self._log_created("25056-QMDBI  Rev.0", created)

        # ── Documento 2: 25056-01-QCPA ───────────────────────────────────────
        doc_qcpa, created = Documento.objects.get_or_create(
            testata=testata,
            vendor_doc="25056-01-QCPA",
            defaults={
                "doc_title": "Quality Control Plan – Documento A",
                "reparto": reparto_qc.nome,
                "item_no": "QCP-01",
            },
        )
        self._log_created("Documento 25056-01-QCPA", created)

        revisions = [
            (0, datetime.date(2025, 9, 5), datetime.date(2025, 10, 14)),
            (1, datetime.date(2025, 11, 7), datetime.date(2025, 11, 10)),
            (2, datetime.date(2025, 11, 13), datetime.date(2025, 11, 16)),
        ]
        for rev_no, dis, rec in revisions:
            rev, created = Revisione.objects.get_or_create(
                documento=doc_qcpa,
                rev_no=rev_no,
                defaults={"dis_act_date": dis, "rec_act_date": rec},
            )
            self._log_created(f"25056-01-QCPA  Rev.{rev_no}", created)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✓ Dati di test creati (o già presenti)."))
        self.stdout.write("")
        self.stdout.write("Struttura cartelle attesa nel fileserver:")
        self.stdout.write("")
        self.stdout.write("  Z:\\JOBS\\25056\\PROGETTO\\QC\\")
        self.stdout.write("      25056-QMDBI*.pdf          ← Rev.0 inviata")
        self.stdout.write("      25056-01-QCPA*.pdf        ← ultima Rev inviata")
        self.stdout.write("      RICEVUTI\\2025-11-17\\")
        self.stdout.write("          25056-QMDBI*.pdf      ← Rev.0 ricevuta")
        self.stdout.write("      RICEVUTI\\2025-10-14\\")
        self.stdout.write("          25056-01-QCPA*.pdf    ← Rev.0 ricevuta")
        self.stdout.write("      RICEVUTI\\2025-11-10\\")
        self.stdout.write("          25056-01-QCPA*.pdf    ← Rev.1 ricevuta (più file)")
        self.stdout.write("      RICEVUTI\\2025-11-16\\")
        self.stdout.write("          25056-01-QCPA*.pdf    ← Rev.2 ricevuta")
        self.stdout.write("")

    def _elimina(self):
        """Remove all test fixtures for job 25056."""
        deleted_rev, _ = Revisione.objects.filter(documento__testata__job="25056").delete()
        deleted_doc, _ = Documento.objects.filter(testata__job="25056").delete()
        deleted_tes, _ = Testata.objects.filter(job="25056").delete()
        self.stdout.write(
            self.style.WARNING(
                f"Eliminati: {deleted_rev} revisioni, {deleted_doc} documenti, "
                f"{deleted_tes} testata."
            )
        )

    def _log_created(self, label: str, created: bool) -> None:
        """Print a styled creation/skip message."""
        if created:
            self.stdout.write(self.style.SUCCESS(f"  [CREATO]  {label}"))
        else:
            self.stdout.write(f"  [esiste]  {label}")
