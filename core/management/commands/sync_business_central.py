"""Controllo giornaliero di congruenza fra Business Central e le commesse."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.bc_sync import BusinessCentralNonDisponibile, sincronizza_commesse


class Command(BaseCommand):
    help = (
        "Confronta cliente, PO, descrizione e data consegna delle commesse con "
        "Business Central e aggiorna quelle disallineate, registrando ogni "
        "modifica. Pensato per essere eseguito una volta al giorno da uno "
        "scheduler (Task Scheduler su Windows, cron su Linux)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            default="",
            help="Controlla solo questa commessa. Se omesso, tutte quelle aperte.",
        )
        parser.add_argument(
            "--tutte",
            action="store_true",
            help="Includi anche le commesse chiuse (con data consegna effettiva).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra le differenze senza salvare nulla.",
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
            report = sincronizza_commesse(
                jobs=jobs,
                includi_chiuse=options["tutte"],
                dry_run=options["dry_run"],
            )
        except BusinessCentralNonDisponibile as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        for agg in report["aggiornamenti"]:
            precedente = agg["precedente"] or "—"
            self.stdout.write(f"  {agg['job']}: {agg['etichetta']}: {precedente} → {agg['nuovo']}")

        if options["verbosity"] >= 2:
            for job_mancante in report["non_trovate"]:
                self.stdout.write(f"  {job_mancante}: non presente in Business Central")

        for errore in report["errori"]:
            self.stderr.write(self.style.WARNING(f"  {errore['job']}: {errore['errore']}"))

        riepilogo = (
            f"Controllate {report['controllate']} commesse, "
            f"aggiornate {report['aggiornate']}, "
            f"non trovate in BC {len(report['non_trovate'])}, "
            f"errori {len(report['errori'])}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))
