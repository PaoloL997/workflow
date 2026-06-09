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

Opzioni:
    --dry-run   Mostra il conteggio delle righe da rimuovere senza modificare il file.
"""

import shutil
import sys
from pathlib import Path

import pandas as pd


XLSX_PATH = Path(__file__).parent / "Revisioni.xlsx"
BACKUP_PATH = XLSX_PATH.with_suffix(".xlsx.bak")


def _is_na(val) -> bool:
    try:
        return pd.isna(val)
    except (TypeError, ValueError):
        return False


def find_orphan_indices(df: pd.DataFrame) -> set:
    """Return the index labels of orphan rows."""
    orphans = set()

    valid = df[df["VendorDoc"].notna()].copy()

    for _vdoc, grp in valid.groupby("VendorDoc", sort=False):
        grp_sorted = grp.sort_values("RevNo")
        prev_eff_status = None

        for idx, rv in grp_sorted.iterrows():
            dis_null = _is_na(rv["DisActDate"])
            rec_null = _is_na(rv["RecActDate"])
            status_val = str(rv["Status"]).strip() if not _is_na(rv["Status"]) else ""
            status_null = status_val == ""

            if prev_eff_status == "A" and dis_null and rec_null and status_null:
                orphans.add(idx)
                # Non aggiornare prev_eff_status: gestisce catene consecutive
            else:
                prev_eff_status = status_val if status_val else None

    return orphans


def main(dry_run: bool = False) -> None:
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
        print("(Dry-run: nessuna modifica al file)")
        return

    if not orphans:
        print("Nessuna revisione orfana trovata. File invariato.")
        return

    # Backup
    shutil.copy2(XLSX_PATH, BACKUP_PATH)
    print(f"Backup salvato: {BACKUP_PATH}")

    df_clean = df.drop(index=list(orphans)).reset_index(drop=True)
    df_clean.to_excel(XLSX_PATH, index=False)
    print(f"File aggiornato: {XLSX_PATH}")
    print(f"Righe rimanenti: {len(df_clean)} (rimosse {total - len(df_clean)})")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    main(dry_run=dry_run)
