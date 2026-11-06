"""Filesystem service for accessing files on the jobs fileserver.

All operations are restricted to the JOBS root directory defined by
``settings.FILESERVER_JOBS_PATH``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import NamedTuple

from django.conf import settings

# Sottocartelle della cartella di invio in cui finiscono le revisioni superate
# (UT usa OBSOLETI, QC usa SUPERATI o OBSOLETI).
CARTELLE_REVISIONI_SUPERATE = ("OBSOLETI", "SUPERATI")

_ESTENSIONI_FILE = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".dwg")


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


def get_cartella_invio(commessa: str, reparto_acronimo: str) -> Path:
    """Cartella dei file inviati al cliente per un documento.

    I documenti UT stanno in ``PROGETTO/UT``; tutti gli altri (QC, WE, PM,
    AM) in ``PROGETTO/QC``. Lì c'è l'ultima revisione inviata, le precedenti
    nelle sottocartelle ``CARTELLE_REVISIONI_SUPERATE``.

    Args:
        commessa: Job number.
        reparto_acronimo: Department acronym of the document.

    Returns:
        Path: ``{JOBS_ROOT}/{commessa}/PROGETTO/UT`` or ``.../PROGETTO/QC``.
    """
    cartella = "UT" if (reparto_acronimo or "").strip().upper() == "UT" else "QC"
    return get_base_path(commessa, cartella)


class RevisioneNelNome(NamedTuple):
    """Revisione letta dal nome di un file (vedi ``estrai_revisione``)."""

    token: str | None
    """``"2"`` o ``"A"``; ``""`` se dopo il codice non c'è nulla; ``None`` se non si capisce."""
    solo_revisione: bool
    """True se dopo la revisione il nome non ha altro testo (``Rev.2`` sì, ``Rev.2A`` no)."""


# " (2)" in fondo al nome è una copia di Windows, non una revisione.
_COPIA_WINDOWS = re.compile(r"\s*\(\d+\)\s*$")
_REVISIONE_NEL_NOME = re.compile(
    r"""^[\s_.\-]*(?:
        rev(?:isione)?[\s._\-,]*(?P<rev_num>\d{1,3})(?!\d)   # Rev0 _REV_0 Rev.0 rev,4 Rev-5 Rev 0 Rev1.0 Rev2A
      | rev[\s._\-]*(?P<rev_let>[a-z]{1,2}\d?)(?![a-z0-9])  # Rev A  rev.D  RevZ0
      | r[\s_]*(?P<r_num>\d{1,3})(?!\d)                     # _R0 R00 -R3 R_0
      | (?P<num>\d{1,3})(?!\d)                              # _0 -00 _2.0 _3RA
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def estrai_revisione(nome_file: str, vendor_doc: str) -> RevisioneNelNome | None:
    """Prova a leggere la revisione dal nome di un file inviato.

    Guarda solo il testo che segue ``vendor_doc`` (cercato a parola intera,
    così ``…-ESH1`` non trova ``…-ESH10``). Numero e lettera vengono
    normalizzati: ``Rev.01`` → ``"1"``, ``rev.d`` → ``"D"``.

    TODO: bisognerà uniformare la maniera in cui gli utenti salvano i file
    delle revisioni vecchie (OBSOLETI/SUPERATI). Oggi convivono decine di
    formati (``Rev0``, ``_0``, ``_R0``, ``Rev.0``, ``_Rev_0``, ``Rev A``, file
    senza suffisso, testo libero come ``_RA`` o ``priced``…) e questa funzione
    prova a indovinarli: sulle commesse 25/26 legge il numero di circa 9 file
    su 10 in UT e 2 su 3 in QC.

    Args:
        nome_file: Nome del file (con estensione).
        vendor_doc: Codice del documento.

    Returns:
        ``None`` se il codice non compare nel nome; altrimenti una
        ``RevisioneNelNome``.
    """
    if not vendor_doc.strip():
        return None
    stem = nome_file
    while os.path.splitext(stem)[1].lower() in _ESTENSIONI_FILE:
        stem = os.path.splitext(stem)[0]
    codice = re.search(
        rf"(?<![0-9a-z]){re.escape(vendor_doc.strip())}(?![0-9a-z])", stem, re.IGNORECASE
    )
    if codice is None:
        return None
    resto = _COPIA_WINDOWS.sub("", stem[codice.end() :])
    if not resto.strip(" _.-"):
        return RevisioneNelNome("", True)
    m = _REVISIONE_NEL_NOME.match(resto)
    if m is None:
        return RevisioneNelNome(None, False)
    numero = m.group("rev_num") or m.group("r_num") or m.group("num")
    token = str(int(numero)) if numero is not None else m.group("rev_let").upper()
    return RevisioneNelNome(token, not resto[m.end() :].strip(" _.-"))


def _scandir_files(directory: Path):
    """Yield ``os.DirEntry`` for the regular files in ``directory``.

    Uses ``os.scandir`` rather than ``Path.iterdir`` because on a network
    share (SMB), ``DirEntry.is_file()``/``.stat()`` reuse the metadata
    already returned by the directory listing itself — ``Path`` objects from
    ``iterdir()`` don't cache that, so each ``is_file()``/``.stat()`` call
    becomes its own network round trip. On a share with a few dozen files
    that difference is a couple hundred milliseconds; with realistic latency
    it can turn a page load into a multi-second (or worse, per-caller-loop,
    multi-minute) wait — see ``elenco_selezione``.

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


def scegli_corrispondenza_esatta(trovati: list[dict], vendor_doc: str) -> list[dict]:
    """Spareggio fra più file che contengono ``vendor_doc`` nel nome.

    La ricerca per sottostringa trova anche i documenti il cui codice contiene
    quello cercato (``…-ESH1`` trova pure ``…-ESH10``). Con più candidati vale
    quello in cui il codice non è né preceduto né seguito da una lettera o una
    cifra, se è uno solo; altrimenti ``trovati`` resta com'è.

    Args:
        trovati: Corrispondenze per sottostringa (dict con la chiave ``nome``).
        vendor_doc: Codice del documento cercato.

    Returns:
        ``trovati``, oppure la lista col solo file che corrisponde esattamente.
    """
    if len(trovati) < 2:
        return trovati
    parola_intera = re.compile(rf"(?<![0-9a-z]){re.escape(vendor_doc.lower())}(?![0-9a-z])")
    esatti = [f for f in trovati if parola_intera.search(f["nome"].lower())]
    return esatti if len(esatti) == 1 else trovati


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
