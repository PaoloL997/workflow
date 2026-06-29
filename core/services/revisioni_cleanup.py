"""Filter orphan revisions from legacy Access/Excel data."""

import pandas as pd


def _is_na(val) -> bool:
    try:
        return pd.isna(val)
    except (TypeError, ValueError):
        return False


def find_orphan_indices(df: pd.DataFrame) -> set:
    """Return the index labels of orphan revision rows."""
    orphans: set = set()

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
            else:
                prev_eff_status = status_val if status_val else None

    return orphans


def drop_orphan_revisioni(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* without orphan revision rows."""
    orphans = find_orphan_indices(df)
    if not orphans:
        return df.copy()
    return df.drop(index=list(orphans)).reset_index(drop=True)
