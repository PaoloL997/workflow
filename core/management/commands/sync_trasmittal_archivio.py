"""Allinea la table transmittal ai PDF già presenti su TRANSMITTAL_PATH."""

from django.core.management.base import BaseCommand

from core.models import Testata
from core.services.trasmittal_archivio import sync_trasmittal_da_cartella


class Command(BaseCommand):
    help = (
        "Crea righe transmittal per i PDF già in cartella (id + data file, "
        "senza documenti/revisioni). Non sovrascrive righe esistenti."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            default="",
            help="Allinea solo questa commessa. Se omesso, tutte le testate.",
        )

    def handle(self, *args, **options):
        job = (options.get("job") or "").strip()
        if job:
            jobs = [job]
            if not Testata.objects.filter(job=job).exists():
                self.stderr.write(self.style.ERROR(f'Commessa "{job}" non trovata.'))
                return
        else:
            jobs = list(Testata.objects.order_by("job").values_list("job", flat=True))

        total = 0
        for j in jobs:
            created = sync_trasmittal_da_cartella(j)
            total += created
            if created:
                self.stdout.write(f"  {j}: +{created}")
        self.stdout.write(self.style.SUCCESS(f"Allineati {total} transmittal."))
