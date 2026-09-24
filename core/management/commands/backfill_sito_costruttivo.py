"""Backfill una tantum di Testata.sito_costruttivo da Business Central."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.bc_sync import BusinessCentralNonDisponibile, sincronizza_sito_costruttivo


def _forza_utf8(wrapper):
    """Porta lo stream su UTF-8 (vedi sync_business_central.py: stessa necessità)."""
    stream = getattr(wrapper, "_out", wrapper)
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        pass


class Command(BaseCommand):
    help = (
        "Backfill una tantum del sito costruttivo delle commesse esistenti, "
        "letto da Business Central (NBT_BRL Location Code). Tocca solo le "
        "commesse senza sito costruttivo: un valore già impostato (anche a "
        "mano via admin) non viene mai sovrascritto. Sicuro da rieseguire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            default="",
            help="Limita l'operazione a questa commessa. Se omesso, tutte quelle aperte.",
        )
        parser.add_argument(
            "--tutte",
            action="store_true",
            help="Includi anche le commesse chiuse (con data consegna effettiva).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra gli abbinamenti senza salvare nulla.",
        )

    def handle(self, *args, **options):
        _forza_utf8(self.stdout)
        _forza_utf8(self.stderr)

        job = (options.get("job") or "").strip()
        jobs = None
        if job:
            if not Testata.objects.filter(job=job).exists():
                self.stderr.write(self.style.ERROR(f'Commessa "{job}" non trovata.'))
                return
            jobs = [job]

        try:
            report = sincronizza_sito_costruttivo(
                jobs=jobs,
                includi_chiuse=options["tutte"],
                dry_run=options["dry_run"],
            )
        except BusinessCentralNonDisponibile as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        for agg in report["aggiornamenti"]:
            self.stdout.write(f"  {agg['job']}: sito costruttivo -> {agg['stabilimento']}")

        if options["verbosity"] >= 2:
            for job_mancante in report["non_trovate"]:
                self.stdout.write(f"  {job_mancante}: non trovata in BC o senza sito assegnato")

        for voce in report["senza_stabilimento"]:
            self.stdout.write(
                self.style.WARNING(
                    f'  {voce["job"]}: codice sito BC "{voce["codice_sito"]}" senza '
                    "stabilimento corrispondente"
                )
            )

        for errore in report["errori"]:
            self.stderr.write(self.style.WARNING(f"  {errore['job']}: {errore['errore']}"))

        riepilogo = (
            f"Controllate {report['controllate']} commesse, "
            f"aggiornate {report['aggiornate']}, "
            f"non trovate/senza sito in BC {len(report['non_trovate'])}, "
            f"senza stabilimento corrispondente {len(report['senza_stabilimento'])}, "
            f"errori {len(report['errori'])}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))
