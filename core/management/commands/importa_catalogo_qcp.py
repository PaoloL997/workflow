"""Import del catalogo attività del Quality Control Plan dal JSON di seed."""

from django.core.management.base import BaseCommand, CommandError

from core.services.catalogo_qcp import (
    CATALOGO_PREDEFINITO,
    CatalogoNonValido,
    importa_catalogo,
    leggi_catalogo,
)

from .sync_business_central import _forza_utf8


class Command(BaseCommand):
    help = (
        "Importa il catalogo attività del Quality Control Plan da un file JSON. "
        "Idempotente: rieseguirlo aggiorna le attività esistenti (stesso codice e "
        "capitolo) invece di duplicarle, e non riattiva quelle disattivate "
        "dall'admin. Se una riga è malformata non importa nulla."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "percorso",
            nargs="?",
            default=str(CATALOGO_PREDEFINITO),
            help="File JSON da importare. Se omesso, quello in core/data/.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe creato o aggiornato senza salvare nulla.",
        )

    def handle(self, *args, **options):
        _forza_utf8(self.stdout)
        _forza_utf8(self.stderr)

        try:
            righe = leggi_catalogo(options["percorso"])
            report = importa_catalogo(righe, dry_run=options["dry_run"])
        except CatalogoNonValido as exc:
            raise CommandError(f"Import interrotto, nessuna attività salvata. {exc}") from exc

        if options["verbosity"] >= 2 or report["dry_run"]:
            for codice, capitolo in report["creati"]:
                self.stdout.write(f"  + {capitolo}: {codice}")
            for codice, capitolo in report["aggiornati"]:
                self.stdout.write(f"  ~ {capitolo}: {codice}")

        riepilogo = (
            f"Creati {len(report['creati'])}, "
            f"aggiornati {len(report['aggiornati'])}, "
            f"invariati {len(report['invariati'])}."
        )
        if report["dry_run"]:
            riepilogo = f"[dry-run] {riepilogo}"
        self.stdout.write(self.style.SUCCESS(riepilogo))
