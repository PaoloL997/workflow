"""Copia foto profilo e firme dalla cartella media allo storage S3."""

from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage
from django.core.management.base import BaseCommand, CommandError

from core.services.media import copia_media_su_storage


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
        "Copia le foto profilo e le firme degli utenti dalla cartella media "
        "(MEDIA_ROOT) allo storage configurato, cioè il bucket S3 indicato da "
        "S3_BUCKET nel .env. I file mantengono lo stesso nome, quindi il database "
        "non cambia. Copia solo i file usati da un utente e salta quelli già "
        "presenti: sicuro da rieseguire."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sorgente",
            default="",
            help="Cartella da cui copiare. Se omessa, MEDIA_ROOT.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe copiato senza scrivere nulla.",
        )

    def handle(self, *args, **options):
        _forza_utf8(self.stdout)
        _forza_utf8(self.stderr)

        cartella = Path(options["sorgente"] or settings.MEDIA_ROOT).resolve()
        if not cartella.is_dir():
            raise CommandError(f"La cartella {cartella} non esiste.")
        if (
            isinstance(default_storage, FileSystemStorage)
            and Path(default_storage.location).resolve() == cartella
        ):
            raise CommandError(
                "La destinazione coincide con la sorgente: configura lo storage S3 "
                "(S3_BUCKET nel .env) prima di copiare."
            )

        try:
            report = copia_media_su_storage(
                FileSystemStorage(location=cartella),
                default_storage,
                dry_run=options["dry_run"],
            )
        except RuntimeError as exc:
            raise CommandError(str(exc)) from exc

        for nome, utenti in report.mancanti:
            self.stderr.write(
                self.style.WARNING(
                    f"  {nome}: non trovato in {cartella} (utenti: {', '.join(utenti)})"
                )
            )
        if options["verbosity"] >= 2:
            for nome in report.copiati or report.da_copiare:
                self.stdout.write(f"  {nome}")

        copiati = (
            f"{len(report.da_copiare)} da copiare (dry-run)"
            if options["dry_run"]
            else f"{len(report.copiati)} copiati"
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"File media: {copiati}, {len(report.gia_presenti)} già presenti, "
                f"{len(report.mancanti)} mancanti nella cartella."
            )
        )
