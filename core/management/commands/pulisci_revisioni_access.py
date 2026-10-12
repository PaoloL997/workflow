"""Rimuove le revisioni "orfane" da un export Revisioni.xlsx del vecchio Access.

Una revisione è orfana se è l'ultima del documento e:
- la penultima ha una risposta cliente che non prevede nuova revisione
  (``StatoEsterno.crea_nuova_rev`` False), e
- lei stessa ha solo la data di invio prevista (niente invio/rientro
  effettivo né risposta).

Sostituisce lo script ``Access/clean_revisioni.py``: stessa logica
(``core.services.revisioni_cleanup``), ma lanciato con ``manage.py`` e con
il percorso del file passato esplicitamente.
"""

import shutil
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError

from core.services.access_source import get_access_connection
from core.services.revisioni_cleanup import (
    access_codes_without_nuova_rev,
    drop_orphan_revisioni,
    find_orphan_indices,
)


def _leggi_revisioni_da_access() -> pd.DataFrame:
    conn = get_access_connection()
    try:
        return pd.read_sql("SELECT * FROM [Revisioni]", conn)
    finally:
        conn.close()


class Command(BaseCommand):
    help = (
        "Rimuove le revisioni orfane da un export Revisioni.xlsx del vecchio Access "
        "(backup .xlsx.bak accanto al file). Con --from-access legge la tabella dal "
        "database Access configurato in .env e produce solo il report, senza scrivere."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="",
            help="Percorso di Revisioni.xlsx da pulire (obbligatorio senza --from-access).",
        )
        parser.add_argument(
            "--from-access",
            action="store_true",
            help="Legge da ACCESS_MDB_PATH (.env) invece che dal file: solo report.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra il conteggio delle righe da rimuovere senza modificare il file.",
        )

    def handle(self, *args, **options):
        from_access = options["from_access"]
        dry_run = options["dry_run"]
        percorso = Path(options["file"]) if options["file"] else None

        if from_access:
            self.stdout.write("Lettura revisioni dal database Access configurato in .env")
            df = _leggi_revisioni_da_access()
        else:
            if percorso is None:
                raise CommandError("Indicare --file <Revisioni.xlsx> oppure --from-access.")
            if not percorso.exists():
                raise CommandError(f"File non trovato: {percorso}")
            self.stdout.write(f"Lettura: {percorso}")
            df = pd.read_excel(percorso)

        self.stdout.write(f"Righe totali: {len(df)}")
        codes = access_codes_without_nuova_rev()
        self.stdout.write(f"Status senza nuova revisione (crea_nuova_rev=False): {sorted(codes)}")
        orphans = find_orphan_indices(df, no_nuova_rev_codes=codes)
        self.stdout.write(f"Revisioni orfane da rimuovere: {len(orphans)}")

        if dry_run:
            self.stdout.write("(Dry-run: nessuna modifica)")
            return
        if from_access:
            self.stdout.write("Modalità --from-access: solo report, nessuna scrittura su Access.")
            return
        if not orphans:
            self.stdout.write("Nessuna revisione orfana trovata. File invariato.")
            return

        backup = percorso.with_suffix(".xlsx.bak")
        shutil.copy2(percorso, backup)
        self.stdout.write(f"Backup salvato: {backup}")
        df_clean = drop_orphan_revisioni(df, no_nuova_rev_codes=codes)
        df_clean.to_excel(percorso, index=False)
        self.stdout.write(
            self.style.SUCCESS(f"Scritto: {percorso} ({len(df_clean)} righe, -{len(orphans)})")
        )
