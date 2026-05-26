"""Filesystem service for accessing files on the jobs fileserver.

All operations are restricted to the JOBS root directory defined by
``settings.FILESERVER_JOBS_PATH``.
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def get_jobs_root() -> Path:
    """Return the root Path of the jobs fileserver directory.

    Returns:
        Path object pointing to the JOBS root (e.g. ``Z:\\JOBS``).
    """
    return Path(settings.FILESERVER_JOBS_PATH)


def get_base_path(commessa: str, reparto_acronimo: str) -> Path:
    """Return the base directory for a job/department combination.

    This folder contains the latest revisions sent to the client.

    Args:
        commessa: Job number (e.g. ``"25056"``).
        reparto_acronimo: Department acronym (e.g. ``"QMD"``).

    Returns:
        Path: ``{JOBS_ROOT}/{commessa}/PROGETTO/{reparto_acronimo}``
    """
    return get_jobs_root() / commessa / "PROGETTO" / reparto_acronimo


def get_ricevuti_path(commessa: str, reparto_acronimo: str, data_str: str) -> Path:
    """Return the RICEVUTI sub-directory for a specific reception date.

    Args:
        commessa: Job number.
        reparto_acronimo: Department acronym.
        data_str: Reception date in ``YYYY-MM-DD`` format.

    Returns:
        Path: ``{base_path}/RICEVUTI/{data_str}``
    """
    return get_base_path(commessa, reparto_acronimo) / "RICEVUTI" / data_str


def trova_file(directory: Path, vendor_doc: str) -> list[dict]:
    """Find all files in a directory whose name contains ``vendor_doc``.

    The match is case-insensitive. Only regular files (not directories) are
    returned. Files may be prefixed with conventions such as
    "Check copy of " or "Check_copy_of_", so a substring match is used
    rather than a prefix match.

    Args:
        directory: Directory to scan. Returns empty list if it does not exist.
        vendor_doc: Internal document name to match (e.g. ``"25056-QMDBI"``).

    Returns:
        List of dicts, each with keys ``percorso``, ``nome``, ``estensione``.
    """
    if not directory.exists() or not directory.is_dir():
        return []

    needle = vendor_doc.lower()
    results = []
    for entry in directory.iterdir():
        if entry.is_file() and needle in entry.name.lower():
            results.append(
                {
                    "percorso": str(entry),
                    "nome": entry.name,
                    "estensione": entry.suffix.lstrip(".").lower(),
                }
            )
    return results


def lista_directory(path_str: str | None = None) -> dict:
    """List the contents of a directory, restricted to the JOBS root.

    Directories are sorted before files; within each group entries are sorted
    alphabetically (case-insensitive).

    Args:
        path_str: Absolute path to list. Defaults to the JOBS root when ``None``
            or empty string.

    Returns:
        Dict with keys:
            - ``percorso_corrente``: absolute path of the listed directory.
            - ``percorso_padre``: parent path, or ``None`` if already at root.
            - ``entries``: list of dicts with ``nome``, ``percorso``, ``tipo``
              (``"cartella"`` or ``"file"``), ``estensione``.

    Raises:
        PermissionError: If ``path_str`` is outside the JOBS root.
        FileNotFoundError: If the path does not exist or is not a directory.
    """
    jobs_root = get_jobs_root()
    target = Path(path_str) if path_str else jobs_root

    # Security: ensure target is within JOBS root
    try:
        target.resolve().relative_to(jobs_root.resolve())
    except ValueError:
        raise PermissionError("Accesso negato: percorso fuori dalla cartella JOBS.")

    if not target.exists():
        raise FileNotFoundError(f"Cartella non trovata: {target}")
    if not target.is_dir():
        raise FileNotFoundError(f"Il percorso non è una cartella: {target}")

    entries = []
    for entry in sorted(
        target.iterdir(),
        key=lambda e: (not e.is_dir(), e.name.lower()),
    ):
        entries.append(
            {
                "nome": entry.name,
                "percorso": str(entry),
                "tipo": "cartella" if entry.is_dir() else "file",
                "estensione": entry.suffix.lstrip(".").lower() if entry.is_file() else "",
            }
        )

    is_root = target.resolve() == jobs_root.resolve()
    return {
        "percorso_corrente": str(target),
        "percorso_padre": str(target.parent) if not is_root else None,
        "entries": entries,
    }
