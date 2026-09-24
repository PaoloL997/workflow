"""Filesystem service for accessing files on the jobs fileserver.

All operations are restricted to the JOBS root directory defined by
``settings.FILESERVER_JOBS_PATH``.
"""

from __future__ import annotations

import os
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


def _scandir_files(directory: Path):
    """Yield ``os.DirEntry`` for the regular files in ``directory``.

    Uses ``os.scandir`` rather than ``Path.iterdir`` because on a network
    share (SMB), ``DirEntry.is_file()``/``.stat()`` reuse the metadata
    already returned by the directory listing itself — ``Path`` objects from
    ``iterdir()`` don't cache that, so each ``is_file()``/``.stat()`` call
    becomes its own network round trip. On a share with a few dozen files
    that difference is a couple hundred milliseconds; with realistic latency
    it can turn a page load into a multi-second (or worse, per-caller-loop,
    multi-minute) wait — see ``elenco_selezione_ut``.

    Returns empty if ``directory`` does not exist.
    """
    try:
        with os.scandir(directory) as it:
            entries = list(it)
    except OSError:
        return []
    return [e for e in entries if e.is_file()]


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
    needle = vendor_doc.lower()
    return [
        {
            "percorso": entry.path,
            "nome": entry.name,
            "estensione": Path(entry.name).suffix.lstrip(".").lower(),
        }
        for entry in _scandir_files(directory)
        if needle in entry.name.lower()
    ]


def elenca_cartella(directory: Path) -> list[dict]:
    """List all files in a directory in a single scan, with their mtime.

    Unlike ``trova_file``, this does not filter by name: it exists so callers
    matching many names against the same directory (e.g. one document list)
    can scan it once and match in memory, instead of re-scanning per name —
    each scan is a full network round trip on a fileserver share.

    Args:
        directory: Directory to scan. Returns empty list if it does not exist.

    Returns:
        List of dicts, each with keys ``percorso``, ``nome``, ``estensione``,
        ``mtime`` (``float`` epoch seconds, or ``None`` if unreadable).
    """
    results = []
    for entry in _scandir_files(directory):
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = None
        results.append(
            {
                "percorso": entry.path,
                "nome": entry.name,
                "estensione": Path(entry.name).suffix.lstrip(".").lower(),
                "mtime": mtime,
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
