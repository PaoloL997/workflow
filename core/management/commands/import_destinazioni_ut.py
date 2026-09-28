"""Precompila le destinazioni UT dal vecchio file RecipientsData.txt."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.recipients_import import importa_destinazioni_tutte_le_commesse


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
        "Precompila le DestinazioneDocumento dei documenti UT dal vecchio file "
        "<job>-RecipientsData.txt sul fileserver, se presente. Tocca solo i "
        "documenti senza nessuna destinazione già registrata: un valore già "
        "impostato (a mano o da un import precedente) non viene mai sovrascritto. "
        "Sicuro da rieseguire."
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
            help="Mostra cosa verrebbe precompilato senza salvare nulla.",
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

        report = importa_destinazioni_tutte_le_commesse(
            jobs=jobs,
            includi_chiuse=options["tutte"],
            dry_run=options["dry_run"],
        )

        if options["verbosity"] >= 2:
            for voce in report["non_trovati"]:
                self.stdout.write(
                    f'  {voce["job"]}: "{voce["vendor_doc"]}" nel file ma non fra i '
                    "documenti UT della commessa"
                )

        for errore in report["errori"]:
            self.stderr.write(self.style.WARNING(f"  {errore['job']}: {errore['errore']}"))

        riepilogo = (
            f"Controllate {report['controllate']} commesse, "
            f"{report['con_file']} con il file, "
            f"{report['precompilati']} documenti precompilati, "
            f"{report['gia_impostati']} già impostati, "
            f"{len(report['non_trovati'])} non trovati fra i documenti UT, "
            f"{len(report['errori'])} errori."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))
