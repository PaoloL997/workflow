import io
import tempfile
from pathlib import Path

import openpyxl
from botocore.exceptions import EndpointConnectionError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings
from PIL import Image

from ..models import (
    Documento,
    Reparto,
    Revisione,
    Testata,
)
from ..services import media as media_service

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────

User = get_user_model()


def _make_fixtures_mock(reparto_acronimo: str = "QC"):
    """Create DB objects for unit tests that mock the filesystem.

    Args:
        reparto_acronimo: Acronimo to assign to the test reparto.

    Returns:
        Dict with created model instances keyed by name.
    """
    reparto = Reparto.objects.create(nome="Qualità e Controllo", acronimo=reparto_acronimo)
    testata = Testata.objects.create(job="25056")

    doc_qmdbi = Documento.objects.create(
        testata=testata,
        vendor_doc="25056-QMDBI",
        reparto=reparto.nome,
    )
    doc_qcpa = Documento.objects.create(
        testata=testata,
        vendor_doc="25056-01-QCPA",
        reparto=reparto.nome,
    )

    rev_qmdbi_0 = Revisione.objects.create(
        documento=doc_qmdbi,
        rev_no=0,
        dis_act_date="2025-09-05",
        rec_act_date="2025-11-17",
    )
    rev_qcpa_0 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=0,
        dis_act_date="2025-09-05",
        rec_act_date="2025-10-14",
    )
    rev_qcpa_1 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=1,
        dis_act_date="2025-11-07",
        rec_act_date="2025-11-10",
    )
    rev_qcpa_2 = Revisione.objects.create(
        documento=doc_qcpa,
        rev_no=2,
        dis_act_date="2025-11-13",
        rec_act_date="2025-11-16",
    )

    return {
        "reparto": reparto,
        "testata": testata,
        "doc_qmdbi": doc_qmdbi,
        "doc_qcpa": doc_qcpa,
        "rev_qmdbi_0": rev_qmdbi_0,
        "rev_qcpa_0": rev_qcpa_0,
        "rev_qcpa_1": rev_qcpa_1,
        "rev_qcpa_2": rev_qcpa_2,
    }


def _trasmittal_dir(jobs_root, job: str) -> Path:
    folder = Path(jobs_root) / job / "PROGETTO" / "DCC" / "TRANSMITTAL"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _trasmittal_path(jobs_root, job: str, numero: int) -> Path:
    return (
        Path(jobs_root)
        / job
        / "PROGETTO"
        / "DCC"
        / "TRANSMITTAL"
        / f"Transmittal {job}-{numero}.pdf"
    )


def _write_trasmittal(jobs_root, job, numero, content=b"%PDF", filename=None):
    folder = _trasmittal_dir(jobs_root, job)
    name = filename or f"Transmittal {job}-{numero}.pdf"
    path = folder / name
    path.write_bytes(content)
    return path


def _make_integration_fixtures():
    """Create DB fixtures pointing to the real fileserver structure.

    Both documents are under Z:\\JOBS\\25056\\PROGETTO\\QC\\ as observed on the
    real fileserver. This creates fresh records in the test DB.

    Returns:
        Dict with Revisione instances keyed by name.
    """
    import datetime

    reparto, _ = Reparto.objects.get_or_create(
        acronimo="QC",
        defaults={"nome": "Qualità e Controllo"},
    )
    testata, _ = Testata.objects.get_or_create(
        job="25056",
        defaults={"client": "Test", "job_detail": "Integration test"},
    )
    doc_qmdbi, _ = Documento.objects.get_or_create(
        testata=testata,
        vendor_doc="25056-QMDBI",
        defaults={"reparto": reparto.nome, "doc_title": "QMDBI"},
    )
    doc_qcpa, _ = Documento.objects.get_or_create(
        testata=testata,
        vendor_doc="25056-01-QCPA",
        defaults={"reparto": reparto.nome, "doc_title": "QCPA"},
    )

    rev_qmdbi_0, _ = Revisione.objects.get_or_create(
        documento=doc_qmdbi,
        rev_no=0,
        defaults={
            "dis_act_date": datetime.date(2025, 9, 5),
            "rec_act_date": datetime.date(2025, 11, 17),
        },
    )
    rev_qcpa_0, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=0,
        defaults={
            "dis_act_date": datetime.date(2025, 9, 5),
            "rec_act_date": datetime.date(2025, 10, 14),
        },
    )
    rev_qcpa_1, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=1,
        defaults={
            "dis_act_date": datetime.date(2025, 11, 7),
            "rec_act_date": datetime.date(2025, 11, 10),
        },
    )
    rev_qcpa_2, _ = Revisione.objects.get_or_create(
        documento=doc_qcpa,
        rev_no=2,
        defaults={
            "dis_act_date": datetime.date(2025, 11, 13),
            "rec_act_date": datetime.date(2025, 11, 16),
        },
    )

    return {
        "rev_qmdbi_0": rev_qmdbi_0,
        "rev_qcpa_0": rev_qcpa_0,
        "rev_qcpa_1": rev_qcpa_1,
        "rev_qcpa_2": rev_qcpa_2,
    }


def _costruisci_xlsm_organizzazione(percorso, righe):
    """Un file Excel "Organizzazione Commesse" minimo, per i test.

    righe: lista di dict con chiavi Job/PM/PE/WE/QCI (e opzionalmente altre
    colonne del foglio reale, ignorate se assenti).
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Commesse"
    ws.append(["", "", "", "PROJECT TEAM", "", "", "", "", "", "", ""])
    ws.append(
        [
            "Job no.",
            "DWG / ITEM",
            "Client ",
            "PM",
            "PE",
            "WE",
            "QCI",
            "Plant",
            "Delivery",
            "Note",
            "Closed",
        ]
    )
    for riga in righe:
        ws.append(
            [
                riga.get("Job"),
                riga.get("DWG"),
                riga.get("Client"),
                riga.get("PM"),
                riga.get("PE"),
                riga.get("WE"),
                riga.get("QCI"),
                riga.get("Plant"),
                riga.get("Delivery"),
                riga.get("Note"),
                riga.get("Closed"),
            ]
        )
    wb.save(percorso)


def _media_temporanea(test):
    """Cartella media temporanea su disco per un test che salva file.

    Sostituisce anche lo storage: se il .env configura S3, i test non lo
    toccano mai. ``staticfiles`` va ripetuto perché STORAGES si sostituisce
    per intero.
    """
    media = tempfile.TemporaryDirectory()
    test.addCleanup(media.cleanup)
    impostazioni = override_settings(
        MEDIA_ROOT=media.name,
        STORAGES={
            **settings.STORAGES,
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        },
    )
    impostazioni.enable()
    test.addCleanup(impostazioni.disable)
    # Un test che simula lo storage giù non deve lasciarlo "in pausa" agli altri.
    test.addCleanup(setattr, media_service, "_storage_giu_fino", 0.0)
    return media.name


def _storage_irraggiungibile():
    """Lo storage che non risponde, come uno S3 spento."""
    return EndpointConnectionError(endpoint_url="http://127.0.0.1:3900")


def _dai_firma(utente, nome="firme/prova.png"):
    """L'utente con un'immagine di firma.

    Basta il nome del file: non serve leggerlo. I test che caricano davvero
    l'immagine usano ``_png`` e una cartella media temporanea.
    """
    utente.firma = nome
    utente.save(update_fields=["firma"])
    return utente


def _png(dimensione=(160, 48), modo="RGBA", formato="PNG"):
    """Un'immagine vera, come la carica un utente."""
    buffer = io.BytesIO()
    Image.new(modo, dimensione, (20, 40, 90, 0) if modo == "RGBA" else (255, 255, 255)).save(
        buffer, format=formato
    )
    return buffer.getvalue()


class _FakeBusinessCentral:
    """Connettore Business Central finto con dati preparati per commessa.

    Un valore ``Exception`` fra i dati viene sollevato al posto della risposta,
    così da simulare una query fallita su una singola commessa.
    """

    def __init__(self, dati_per_job, conn=True, codici_sito=None):
        self.dati_per_job = dati_per_job
        self.conn = "connessione-finta" if conn else None
        self.jobs_richiesti = []
        self.chiusa = False
        # sync_business_central invoca anche la sync del sito costruttivo
        # nella stessa passata: di norma nessun test di questa classe se ne
        # occupa, quindi "nessun sito trovato" è il comportamento neutro di
        # default — un test puntuale può passare codici_sito per verificare
        # anche quella parte.
        self.codici_sito = codici_sito or {}

    def dati_commessa(self, job):
        self.jobs_richiesti.append(job)
        dati = self.dati_per_job.get(job, {})
        if isinstance(dati, Exception):
            raise dati
        return dict(dati)

    def get_commessa_codice_sito(self, job):
        return self.codici_sito.get(job)

    def close(self):
        self.chiusa = True


class _FakeBusinessCentralSito:
    """Connettore finto per get_commessa_codice_sito, per commessa.

    Un valore ``Exception`` fra i dati viene sollevato al posto della
    risposta, per simulare una query fallita su una singola commessa.
    """

    def __init__(self, codici_per_job, conn=True):
        self.codici_per_job = codici_per_job
        self.conn = "connessione-finta" if conn else None
        self.chiusa = False

    def get_commessa_codice_sito(self, job):
        codice = self.codici_per_job.get(job)
        if isinstance(codice, Exception):
            raise codice
        return codice

    def close(self):
        self.chiusa = True
