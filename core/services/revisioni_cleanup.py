"""Filter orphan revisions from legacy Access/Excel data.

An orphan is the *last* revision of a document when both are true:
  1. the penultimate client response has ``crea_nuova_rev=False``
     (from Impostazioni / StatoEsterno);
  2. the last row has only DisPlanDate (no DisActDate, RecPlanDate,
     RecActDate, or Status).
"""

import pandas as pd

# Access single-letter codes → human-readable name (mirrors import_old._STATUS_MAP).
_STATUS_CODE_TO_NOME = {
    "A": "Approved",
    "I": "Commented - To be issued as Final",
    "C": "Commented - To be resubmitted - Work can proceed",
    "F": "Final - As Built",
    "Z": "For Information",
    "O": "Old",
    "R": "Rejected - Work can not proceed",
    "S": "Superseeded",
}
_NOME_TO_CODE = {v: k for k, v in _STATUS_CODE_TO_NOME.items()}

# Fallback when StatoEsterno is not configured yet (tests / first install).
_DEFAULT_NO_NUOVA_REV_CODES = frozenset({"A", "F", "Z"})


def _is_na(val) -> bool:
    try:
        return pd.isna(val)
    except (TypeError, ValueError):
        return False


def _status_val(row) -> str:
    if _is_na(row.get("Status")):
        return ""
    return str(row["Status"]).strip()


def normalize_revisioni_vendor_doc(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with VendorDoc trimmed (fixes trailing spaces in Access)."""
    out = df.copy()
    if "VendorDoc" in out.columns:
        out["VendorDoc"] = out["VendorDoc"].apply(
            lambda v: str(v).strip() if not _is_na(v) else v
        )
    return out


def access_codes_without_nuova_rev() -> frozenset[str]:
    """Access Status codes whose StatoEsterno has crea_nuova_rev=False."""
    from ..models import StatoEsterno

    codes = set()
    for s in StatoEsterno.objects.filter(crea_nuova_rev=False):
        code = _NOME_TO_CODE.get(s.nome)
        if code:
            codes.add(code)
    return frozenset(codes) if codes else _DEFAULT_NO_NUOVA_REV_CODES


def _only_dis_plan_date(row) -> bool:
    """True when DisPlanDate is set and every other workflow field is empty."""
    if _is_na(row.get("DisPlanDate")):
        return False
    if not _is_na(row.get("DisActDate")):
        return False
    if not _is_na(row.get("RecActDate")):
        return False
    if "RecPlanDate" in row.index and not _is_na(row.get("RecPlanDate")):
        return False
    if _status_val(row) != "":
        return False
    return True


def _penultimate_non_prevede_nuova_rev(row, no_nuova_rev_codes: frozenset[str]) -> bool:
    code = _status_val(row)
    return bool(code) and code in no_nuova_rev_codes


def find_orphan_indices(
    df: pd.DataFrame,
    *,
    no_nuova_rev_codes: frozenset[str] | None = None,
) -> set:
    """Return the index labels of orphan revision rows (last rev only)."""
    codes = no_nuova_rev_codes or _DEFAULT_NO_NUOVA_REV_CODES
    orphans: set = set()
    valid = normalize_revisioni_vendor_doc(df)
    valid = valid[valid["VendorDoc"].notna()].copy()

    for _vdoc, grp in valid.groupby("VendorDoc", sort=False):
        grp_sorted = grp.sort_values("RevNo")
        if len(grp_sorted) < 2:
            continue
        penultimate = grp_sorted.iloc[-2]
        ultimate = grp_sorted.iloc[-1]
        if _penultimate_non_prevede_nuova_rev(penultimate, codes) and _only_dis_plan_date(
            ultimate
        ):
            orphans.add(ultimate.name)

    return orphans


def drop_orphan_revisioni(
    df: pd.DataFrame,
    *,
    no_nuova_rev_codes: frozenset[str] | None = None,
) -> pd.DataFrame:
    """Return a copy of *df* without orphan revision rows (VendorDoc normalized)."""
    normalized = normalize_revisioni_vendor_doc(df)
    orphans = find_orphan_indices(normalized, no_nuova_rev_codes=no_nuova_rev_codes)
    if not orphans:
        return normalized
    return normalized.drop(index=list(orphans)).reset_index(drop=True)
