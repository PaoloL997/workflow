"""Transmittal archive: fileserver PDFs plus database records.

PDFs live in ``{FILESERVER_JOBS_PATH}/{job}/PROGETTO/DCC/TRANSMITTAL``.
Expected filename: ``Transmittal {job}-{id}.pdf`` (case-insensitive).
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path

from django.db import transaction
from django.db.models import Max

from .fileserver import get_base_path, get_jobs_root

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(
    r"^Transmittal\s+(.+)-(\d+)\.pdf$",
    re.IGNORECASE,
)


class TrasmittalAnnullaError(Exception):
    """Cancel is not allowed (not latest, no revisions, or already received)."""


def cartella_trasmittal(job: str) -> Path:
    """Return ``{JOBS}/{job}/PROGETTO/DCC/TRANSMITTAL``."""
    return get_base_path((job or "").strip(), "DCC") / "TRANSMITTAL"


def percorso_previsto(job: str, numero: int) -> Path:
    """Return the destination path for a transmittal PDF (file may not exist)."""
    job_clean = (job or "").strip()
    return cartella_trasmittal(job_clean) / _filename(job_clean, numero)


def _is_inside_jobs(path: Path) -> bool:
    try:
        path.resolve().relative_to(get_jobs_root().resolve())
        return True
    except (ValueError, OSError):
        return False


def lista_trasmittal(job: str) -> list[dict]:
    """List transmittal PDFs for a job on the fileserver.

    Args:
        job: Job number (e.g. ``"25089"``).

    Returns:
        List of dicts with ``id`` (int) and ``nome`` (filename), sorted by
        id descending. Empty if the folder is missing or has no matches.
    """
    job_clean = (job or "").strip()
    if not job_clean:
        return []

    folder = cartella_trasmittal(job_clean)
    if not folder.exists() or not folder.is_dir():
        return []

    items: list[dict] = []
    seen_ids: set[int] = set()
    try:
        entries = folder.iterdir()
    except OSError:
        return []

    for entry in entries:
        if not entry.is_file():
            continue
        if not _is_inside_jobs(entry):
            continue
        match = _FILENAME_RE.match(entry.name)
        if not match:
            continue
        file_job, id_str = match.group(1), match.group(2)
        if file_job.casefold() != job_clean.casefold():
            continue
        transmittal_id = int(id_str)
        if transmittal_id in seen_ids:
            continue
        seen_ids.add(transmittal_id)
        items.append({"id": transmittal_id, "nome": entry.name})

    items.sort(key=lambda item: item["id"], reverse=True)
    return items


def percorso_trasmittal(job: str, transmittal_id: int) -> Path:
    """Resolve a transmittal PDF path inside the job TRANSMITTAL folder.

    Args:
        job: Job number.
        transmittal_id: Numeric transmittal id from the filename.

    Returns:
        Path to the matching PDF file.

    Raises:
        FileNotFoundError: If no matching file exists.
        PermissionError: If the resolved path is outside the JOBS root.
    """
    job_clean = (job or "").strip()
    if not job_clean or transmittal_id < 0:
        raise FileNotFoundError("Transmittal non trovato.")

    folder = cartella_trasmittal(job_clean)
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError("Cartella transmittal non trovata.")

    candidate = percorso_previsto(job_clean, transmittal_id)
    try:
        if not candidate.is_file():
            raise FileNotFoundError("Transmittal non trovato.")
        if not _is_inside_jobs(candidate):
            raise PermissionError("Percorso non autorizzato.")
    except PermissionError:
        raise
    except OSError as exc:
        raise FileNotFoundError("Transmittal non trovato.") from exc

    match = _FILENAME_RE.match(candidate.name)
    if not match:
        raise FileNotFoundError("Transmittal non trovato.")
    if match.group(1).casefold() != job_clean.casefold():
        raise FileNotFoundError("Transmittal non trovato.")
    if int(match.group(2)) != transmittal_id:
        raise FileNotFoundError("Transmittal non trovato.")
    return candidate


def _data_caricamento_file(path: Path) -> date:
    """File creation date on Windows (st_ctime); last-write elsewhere."""
    stat = path.stat()
    ts = getattr(stat, "st_ctime", None) or stat.st_mtime
    return datetime.fromtimestamp(ts).date()


def sync_trasmittal_da_cartella(job: str, *, solo_se_vuota: bool = False) -> int:
    """Create DB rows for files on disk that are not yet in the table.

    Existing rows are left unchanged (including revision links). Date is the
    file creation time; revisions stay empty.

    Args:
        solo_se_vuota: If True, do nothing when the job already has rows.

    Returns:
        Number of rows created.
    """
    from ..models import Testata, Transmittal

    job_clean = (job or "").strip()
    if not job_clean:
        return 0
    try:
        testata = Testata.objects.get(job=job_clean)
    except Testata.DoesNotExist:
        return 0

    if solo_se_vuota and Transmittal.objects.filter(testata=testata).exists():
        return 0

    files = lista_trasmittal(job_clean)
    if not files:
        return 0

    existing = set(Transmittal.objects.filter(testata=testata).values_list("numero", flat=True))
    created = 0
    for item in files:
        numero = item["id"]
        if numero in existing:
            continue
        try:
            path = percorso_trasmittal(job_clean, numero)
            data = _data_caricamento_file(path)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            logger.warning("Sync transmittal %s-%s saltato: %s", job_clean, numero, exc)
            continue
        Transmittal.objects.create(
            testata=testata,
            numero=numero,
            data_emissione=data,
        )
        existing.add(numero)
        created += 1
    return created


def lista_storico(job: str) -> list[dict]:
    """List transmittals for a job from the database (not the fileserver)."""
    from ..models import Transmittal

    job_clean = (job or "").strip()
    if not job_clean:
        return []
    rows = list(
        Transmittal.objects.filter(testata_id=job_clean)
        .prefetch_related("revisioni")
        .order_by("-numero")
    )
    latest_numero = rows[0].numero if rows else None
    items = []
    for t in rows:
        items.append(
            {
                "id": t.numero,
                "codice": t.codice,
                "nome": f"Transmittal {t.codice}.pdf",
                "data": t.data_emissione.isoformat() if t.data_emissione else None,
                "annullabile": _is_annullabile(t, latest_numero),
            }
        )
    return items


def _is_annullabile(trasmittal, latest_numero) -> bool:
    if latest_numero is None or trasmittal.numero != latest_numero:
        return False
    revs = list(trasmittal.revisioni.all())
    if not revs:
        return False
    if any(r.int_status == "ricevuto" or r.rec_act_date for r in revs):
        return False
    return True


def annulla_trasmittal(job: str, numero: int) -> None:
    """Undo the latest app-issued transmittal for a job.

    Restores linked revisions to the pre-emission defaults, deletes the DB
    row, and removes the PDF from the archive folder.

    Raises:
        FileNotFoundError: If the transmittal row does not exist.
        Testata.DoesNotExist: If the job does not exist.
        TrasmittalAnnullaError: If cancel is not allowed.
    """
    from ..models import Testata, Transmittal

    job_clean = (job or "").strip()
    with transaction.atomic():
        testata = Testata.objects.select_for_update().get(job=job_clean)
        trasmittal = (
            Transmittal.objects.select_for_update().filter(testata=testata, numero=numero).first()
        )
        if trasmittal is None:
            raise FileNotFoundError("Transmittal non trovato.")
        latest = Transmittal.objects.filter(testata=testata).aggregate(m=Max("numero")).get("m")
        revs = list(trasmittal.revisioni.all())
        if trasmittal.numero != latest:
            raise TrasmittalAnnullaError("Si può annullare solo l'ultimo transmittal.")
        if not revs:
            raise TrasmittalAnnullaError(
                "Questo transmittal non può essere annullato (nessuna revisione collegata)."
            )
        if any(r.int_status == "ricevuto" or r.rec_act_date for r in revs):
            raise TrasmittalAnnullaError(
                "Non si può annullare: una o più revisioni sono già state ricevute."
            )
        for rev in revs:
            rev.int_status = ""
            rev.dis_act_date = None
            rev.rec_plan_date = None
            rev.save(update_fields=["int_status", "dis_act_date", "rec_plan_date"])
        trasmittal.delete()

    dest = percorso_previsto(job_clean, numero)
    try:
        if dest.is_file() and _is_inside_jobs(dest):
            dest.unlink()
    except OSError as exc:
        logger.warning("Impossibile rimuovere PDF transmittal %s: %s", dest, exc)


def prossimo_numero(job: str) -> int:
    """Next transmittal number: max(DB, files on disk) + 1, skipping existing files."""
    from ..models import Transmittal

    job_clean = (job or "").strip()
    db_max = (
        Transmittal.objects.filter(testata_id=job_clean).aggregate(m=Max("numero")).get("m") or 0
    )
    file_max = 0
    for item in lista_trasmittal(job_clean):
        file_max = max(file_max, item["id"])
    numero = max(db_max, file_max) + 1
    while True:
        candidate = percorso_previsto(job_clean, numero)
        try:
            exists = candidate.is_file()
        except OSError:
            exists = False
        if not exists:
            return numero
        numero += 1


def _filename(job: str, numero: int) -> str:
    return f"Transmittal {job}-{numero}.pdf"


def salva_pdf_trasmittal(job: str, numero: int, pdf_bytes: bytes) -> Path:
    """Write a transmittal PDF into the job TRANSMITTAL folder.

    Raises:
        PermissionError: If the target is outside the JOBS root.
        OSError: If the write fails.
    """
    folder = cartella_trasmittal(job)
    folder.mkdir(parents=True, exist_ok=True)
    dest = percorso_previsto(job, numero)
    if not _is_inside_jobs(dest):
        raise PermissionError("Percorso non autorizzato.")
    dest.write_bytes(pdf_bytes)
    return dest


def emetti_e_archivia(
    job: str,
    doc_ids: list,
    dis_act_date,
    pdf_bytes: bytes,
) -> dict:
    """Write the PDF, emit documents, and persist a Transmittal row.

    If the fileserver write fails, documents are not emitted. If the DB
    commit fails after a successful write, the orphan file is deleted.
    """
    from ..models import Testata, Transmittal
    from .commesse import esegui_emissione

    job_clean = (job or "").strip()
    dest = None
    try:
        with transaction.atomic():
            testata = Testata.objects.select_for_update().get(job=job_clean)
            numero = prossimo_numero(job_clean)
            dest = salva_pdf_trasmittal(job_clean, numero, pdf_bytes)
            updated = esegui_emissione(doc_ids, dis_act_date)
            if isinstance(dis_act_date, str):
                data_emissione = date.fromisoformat(dis_act_date)
            else:
                data_emissione = dis_act_date
            trasmittal = Transmittal.objects.create(
                testata=testata,
                numero=numero,
                data_emissione=data_emissione,
            )
            rev_ids = [row["id"] for row in updated if row.get("id")]
            if rev_ids:
                trasmittal.revisioni.set(rev_ids)
    except Exception:
        if dest is not None:
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                logger.warning("Impossibile rimuovere PDF orfano %s", dest)
        raise

    return {
        "updated": updated,
        "trasmittal": {"id": trasmittal.numero, "codice": trasmittal.codice},
    }
