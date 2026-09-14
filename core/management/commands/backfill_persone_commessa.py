"""Backfill una tantum di PM/PE/QCI/WE per le commesse esistenti."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.organizzazione_commesse import backfill_persone_commessa


class Command(BaseCommand):
    help = (
        "Backfill una tantum di PM/PE/QCI/WE per le commesse esistenti, "
        "leggendo il file Excel di organizzazione commesse. Best-effort: "
        "salta le commesse il cui job non è nel foglio e i ruoli già "
        "popolati. Sicuro da rieseguire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            default="",
            help="Limita il backfill a questa commessa. Se omesso, tutte.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe fatto senza scrivere nulla.",
        )

    def handle(self, *args, **options):
        job = (options.get("job") or "").strip()
        jobs = None
        if job:
            if not Testata.objects.filter(job=job).exists():
                self.stderr.write(self.style.ERROR(f'Commessa "{job}" non trovata.'))
                return
            jobs = [job]

        try:
            report = backfill_persone_commessa(jobs=jobs, dry_run=options["dry_run"])
        except FileNotFoundError as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        for job_aggiornato in report["aggiornate"]:
            self.stdout.write(f"  {job_aggiornato}: PM/PE/QCI/WE popolati")

        if options["verbosity"] >= 2:
            for job_mancante in report["non_trovate"]:
                self.stdout.write(f"  {job_mancante}: non presente nel foglio")

        riepilogo = (
            f"Commesse aggiornate: {len(report['aggiornate'])}, "
            f"job non trovati nel foglio: {len(report['non_trovate'])}, "
            f"ruoli già presenti saltati: {report['ruoli_saltati']}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))
