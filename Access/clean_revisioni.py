"""
clean_revisioni.py — Rimuove le revisioni "orfane" da Revisioni.xlsx.

Una revisione è orfana se:
  - la revisione effettiva precedente (per lo stesso documento) aveva Status = "A" (Approved), E
  - la revisione corrente non è mai stata spedita (DisActDate = null)
    né ricevuta (RecActDate = null) né ha una risposta del cliente (Status = null).

Gestisce catene consecutive: quando una revisione viene rimossa, il prev_effective_status
non viene aggiornato, così eventuali ulteriori orfane successive vengono rimosse anch'esse.

Uso:
    python Access/clean_revisioni.py [--dry-run]
    python Access/clean_revisioni.py --from-access [--dry-run]

Opzioni:
    --dry-run      Mostra il conteggio delle righe da rimuovere senza modificare il file.
    --from-access  Legge da ACCESS_MDB_PATH (.env) invece che da Revisioni.xlsx.
"""

import os
import shutil
import sys
from pathlib import Path

import django
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from core.services.access_source import get_access_connection  # noqa: E402
from core.services.revisioni_cleanup import drop_orphan_revisioni, find_orphan_indices  # noqa: E402

XLSX_PATH = Path(__file__).parent / "Revisioni.xlsx"
BACKUP_PATH = XLSX_PATH.with_suffix(".xlsx.bak")


def _load_revisioni_from_access() -> pd.DataFrame:
    conn = get_access_connection()
    try:
        return pd.read_sql("SELECT * FROM [Revisioni]", conn)
    finally:
        conn.close()


def main(dry_run: bool = False, from_access: bool = False) -> None:
    if from_access:
        print("Lettura revisioni dal database Access configurato in .env")
        df = _load_revisioni_from_access()
    else:
        if not XLSX_PATH.exists():
            print(f"Errore: file non trovato: {XLSX_PATH}")
            sys.exit(1)
        print(f"Lettura: {XLSX_PATH}")
        df = pd.read_excel(XLSX_PATH)

    total = len(df)
    print(f"Righe totali: {total}")

    orphans = find_orphan_indices(df)
    print(f"Revisioni orfane da rimuovere: {len(orphans)}")

    if dry_run:
        print("(Dry-run: nessuna modifica)")
        return

    if from_access:
        print("Modalità --from-access: solo report, nessuna scrittura sul database Access.")
        return

    if not orphans:
        print("Nessuna revisione orfana trovata. File invariato.")
        return

    shutil.copy2(XLSX_PATH, BACKUP_PATH)
    print(f"Backup salvato: {BACKUP_PATH}")

    df_clean = drop_orphan_revisioni(df)
    df_clean.to_excel(XLSX_PATH, index=False)
    print(f"File aggiornato: {XLSX_PATH}")
    print(f"Righe rimanenti: {len(df_clean)} (rimosse {total - len(df_clean)})")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    from_access = "--from-access" in sys.argv
    main(dry_run=dry_run, from_access=from_access)
