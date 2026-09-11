"""Seed del corpo del Quality Control Plan di una commessa da un file JSON."""

from django.core.management.base import BaseCommand, CommandError

from core.services.seed_corpo_qcp import (
    SeedNonValido,
    corpo_esistente,
    leggi_corpo,
    piano_della_commessa,
    semina_corpo,
)

from .sync_business_central import _forza_utf8


class Command(BaseCommand):
    help = (
        "Popola il corpo del Quality Control Plan di una commessa (sezioni, step, "
        "punti d'intervento) da un file JSON, per avere dati realistici su cui provare "
        "l'editor. Usa le stesse funzioni di servizio dell'interfaccia. La commessa "
        "deve avere un solo piano, con gli enti di ispezione già in copertina. Non "
        "duplica: se il piano ha già un corpo si ferma, a meno di --reset."
    )

    def add_arguments(self, parser):
        parser.add_argument("--job", required=True, help="Commessa del piano da popolare.")
        parser.add_argument(
            "--file",
            required=True,
            dest="percorso",
            help="File JSON con le sezioni, per esempio core/data/corpo_26026.json.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Esegue tutto e mostra il riepilogo, poi annulla: non salva nulla.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Elimina sezioni e step già presenti sul piano prima di ricrearli. "
            "Chiede conferma.",
        )
        parser.add_argument(
            "--no-input",
            "--noinput",
            action="store_false",
            dest="interactive",
            help="Non chiede conferma: con --reset elimina il corpo esistente senza domandare.",
        )

    def handle(self, *args, **options):
        _forza_utf8(self.stdout)
        _forza_utf8(self.stderr)

        try:
            sezioni = leggi_corpo(options["percorso"])
            piano = piano_della_commessa(options["job"])
            if options["reset"] and not options["dry_run"] and options["interactive"]:
                self._conferma_reset(piano)
            report = semina_corpo(
                piano, sezioni, reset=options["reset"], dry_run=options["dry_run"]
            )
        except SeedNonValido as exc:
            raise CommandError(f"Seed interrotto, nessuna modifica salvata. {exc}") from exc

        self._riepilogo(report)

    def _conferma_reset(self, piano):
        """Il reset distrugge il corpo esistente: si procede solo con un sì esplicito."""
        sezioni, steps = corpo_esistente(piano)
        if not sezioni:
            return
        risposta = input(
            f'Il piano "{piano.titolo}" ha già un corpo (sezioni: {sezioni}, step: {steps}). '
            "--reset lo elimina tutto, punti d'intervento compresi, prima di ricrearlo dal "
            'file. Scrivi "si" per continuare: '
        )
        if risposta.strip().lower() not in ("si", "sì"):
            raise SeedNonValido("Reset annullato: il corpo esistente non è stato toccato.")

    def _riepilogo(self, report):
        piano = report["piano"]
        manuali = report["manuali"]
        di_cui = (
            f" (di cui {manuali} scritt{'o' if manuali == 1 else 'i'} a mano)" if manuali else ""
        )
        righe = [
            f'Piano "{piano.titolo}" della commessa {piano.testata_id}: '
            f"sezioni create {report['sezioni']}, step creati {report['steps']}{di_cui}, "
            f"punti d'intervento impostati {report['punti']}."
        ]
        if report["eliminate_sezioni"]:
            righe.append(
                f"Eliminati prima: sezioni {report['eliminate_sezioni']}, "
                f"step {report['eliminati_steps']}."
            )
        if report["dry_run"]:
            righe = [f"[dry-run] {riga}" for riga in righe]
            righe.append("[dry-run] Nulla è stato salvato.")
        for riga in righe:
            self.stdout.write(self.style.SUCCESS(riga))

        if report["anomalie"]:
            self.stdout.write(self.style.WARNING(f"Anomalie ({len(report['anomalie'])}):"))
            for anomalia in report["anomalie"]:
                self.stdout.write(self.style.WARNING(f"  - {anomalia}"))
        else:
            self.stdout.write("Nessuna anomalia.")
