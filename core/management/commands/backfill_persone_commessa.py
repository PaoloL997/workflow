"""Backfill una tantum di PM/PE/QCI/WE per le commesse esistenti."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.organizzazione_commesse import (
    backfill_persone_commessa,
    risolvi_persone_libere,
)


class Command(BaseCommand):
    help = (
        "Backfill una tantum di PM/PE/QCI/WE per le commesse esistenti, "
        "leggendo il file Excel di organizzazione commesse. Ogni cognome "
        "viene abbinato a un utente registrato quando possibile; best-effort "
        "per il resto: salta le commesse il cui job non è nel foglio e i "
        "ruoli già popolati. Sicuro da rieseguire. Con --risolvi-esistenti, "
        "riprova invece ad abbinare le PersonaCommessa già a testo libero "
        "(senza rileggere il foglio)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            default="",
            help="Limita l'operazione a questa commessa. Se omesso, tutte.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe fatto senza scrivere nulla.",
        )
        parser.add_argument(
            "--risolvi-esistenti",
            action="store_true",
            help=(
                "Non legge il foglio: riprova ad abbinare a un utente "
                "registrato le PersonaCommessa già salvate come testo libero."
            ),
        )

    def handle(self, *args, **options):
        job = (options.get("job") or "").strip()
        jobs = None
        if job:
            if not Testata.objects.filter(job=job).exists():
                self.stderr.write(self.style.ERROR(f'Commessa "{job}" non trovata.'))
                return
            jobs = [job]

        if options["risolvi_esistenti"]:
            self._risolvi_esistenti(jobs, options)
            return

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

        self._scrivi_da_risolvere(report["da_risolvere"])

        riepilogo = (
            f"Commesse aggiornate: {len(report['aggiornate'])}, "
            f"job non trovati nel foglio: {len(report['non_trovate'])}, "
            f"ruoli già presenti saltati: {report['ruoli_saltati']}, "
            f"da risolvere a mano: {len(report['da_risolvere'])}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))

    def _risolvi_esistenti(self, jobs, options):
        report = risolvi_persone_libere(jobs=jobs, dry_run=options["dry_run"])

        for voce in report["risolte"]:
            self.stdout.write(f"  {voce['job']} - {voce['ruolo'].upper()}: {voce['nome']}")

        self._scrivi_da_risolvere(report["non_risolte"])

        riepilogo = (
            f"Abbinate a un utente registrato: {len(report['risolte'])}, "
            f"ancora da risolvere a mano: {len(report['non_risolte'])}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))

    def _scrivi_da_risolvere(self, voci):
        if not voci:
            return
        self.stdout.write(
            self.style.WARNING("Da risolvere (nessun utente registrato corrispondente):")
        )
        for voce in voci:
            self.stdout.write(f"  {voce['job']} - {voce['ruolo'].upper()}: {voce['nome']}")
