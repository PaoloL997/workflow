"""File caricati dagli utenti (foto profilo e firme) e il loro storage.

Lo storage è quello di default di Django: il bucket S3 di SeaweedFS sul
server (deploy/install-seaweedfs-service.ps1), una cartella in sviluppo (vedi
``config.settings.storage_media_da_env``). Il bucket è privato, quindi le
immagini le serve sempre l'app (``risposta_immagine``) e mai un URL diretto.
"""

import logging
import mimetypes
import time
from dataclasses import dataclass, field

from botocore.exceptions import BotoCoreError, ClientError
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404, HttpResponse

logger = logging.getLogger(__name__)

# Cosa può sollevare lo storage quando non risponde: OSError per la cartella
# locale, le eccezioni di botocore per S3 (che non derivano da OSError).
ERRORI_STORAGE = (OSError, BotoCoreError, ClientError)

# Solo questi tipi vengono serviti: un file .html o .svg caricato come foto
# profilo non deve mai arrivare al browser come pagina dell'app.
TIPI_IMMAGINE = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


# Dopo un errore lo storage si considera giù per questo tempo: le richieste
# successive rispondono subito invece di riprovare. Su Windows una porta locale
# chiusa (servizio fermo) rifiuta la connessione con secondi di ritardo, e
# ogni foto profilo terrebbe occupato un thread di Waitress.
PAUSA_DOPO_ERRORE_SECONDI = 30
_storage_giu_fino = 0.0


def _storage_in_pausa() -> bool:
    return time.monotonic() < _storage_giu_fino


def _segna_storage_giu():
    global _storage_giu_fino
    _storage_giu_fino = time.monotonic() + PAUSA_DOPO_ERRORE_SECONDI


class StorageNonDisponibile(RuntimeError):
    """Lo storage dei file caricati non risponde."""

    def __init__(self, messaggio="Archivio di firme e foto non raggiungibile: riprova tra poco."):
        super().__init__(messaggio)


def leggi_bytes(campo) -> bytes | None:
    """Contenuto del file di un ``FileField``, o ``None`` se non c'è.

    Raises:
        StorageNonDisponibile: Se lo storage non risponde. A differenza di un
            file mancante, non va trattato come "nessuna immagine": chi chiama
            deve poter fallire in modo visibile e riprovare.
    """
    if not campo:
        return None
    if _storage_in_pausa():
        raise StorageNonDisponibile()
    try:
        with campo.open("rb") as file:
            return file.read()
    except FileNotFoundError:
        logger.warning("File %s registrato ma assente dallo storage.", campo.name)
        return None
    except ERRORI_STORAGE as exc:
        _segna_storage_giu()
        logger.warning("Storage non raggiungibile leggendo %s.", campo.name, exc_info=True)
        raise StorageNonDisponibile() from exc


def risposta_immagine(campo, *, cache_control):
    """Risposta HTTP con l'immagine di un ``FileField``.

    404 se non c'è, se manca dallo storage o se il nome non è di un'immagine;
    503 se lo storage non risponde (subito, se ha appena dato errore).
    """
    if not campo:
        raise Http404
    tipo, _ = mimetypes.guess_type(campo.name)
    if tipo not in TIPI_IMMAGINE:
        raise Http404
    if _storage_in_pausa():
        return HttpResponse(status=503)
    try:
        file = campo.open("rb")
    except FileNotFoundError:
        raise Http404 from None
    except ERRORI_STORAGE:
        _segna_storage_giu()
        logger.warning("Immagine %s non leggibile dallo storage.", campo.name, exc_info=True)
        return HttpResponse(status=503)
    risposta = FileResponse(file, content_type=tipo)
    risposta["Cache-Control"] = cache_control
    return risposta


def elimina_file(nomi):
    """Cancella dallo storage i file sostituiti o rimossi.

    Si chiama dopo aver salvato il nuovo valore: se la cancellazione fallisce
    resta solo un file orfano, che non fa danni; l'errore va nel log.
    """
    for nome in nomi:
        if not nome:
            continue
        try:
            default_storage.delete(nome)
        except ERRORI_STORAGE:
            logger.warning("File %s non cancellato dallo storage.", nome, exc_info=True)


@dataclass
class ReportCopia:
    copiati: list[str] = field(default_factory=list)
    gia_presenti: list[str] = field(default_factory=list)
    da_copiare: list[str] = field(default_factory=list)
    # (nome del file, username degli utenti che lo usano)
    mancanti: list[tuple[str, list[str]]] = field(default_factory=list)


def nomi_media_utenti() -> dict[str, list[str]]:
    """Nomi dei file di foto profilo e firme in uso, con gli username che li usano."""
    from ..models import User

    nomi: dict[str, list[str]] = {}
    for username, avatar, firma in User.objects.values_list("username", "avatar", "firma"):
        for nome in (avatar, firma):
            if nome:
                nomi.setdefault(nome, []).append(username)
    return nomi


def copia_media_su_storage(sorgente, destinazione, *, dry_run=False) -> ReportCopia:
    """Copia foto profilo e firme da uno storage all'altro, con lo stesso nome.

    Serve per passare dalla cartella media al bucket S3: il nome nel database
    resta quello, quindi non c'è niente da aggiornare. Copia solo i file usati
    da un utente (un file già cancellato non torna) e salta quelli già presenti
    nella destinazione, quindi si può rilanciare quante volte si vuole.

    Raises:
        RuntimeError: Se la destinazione salva un file con un nome diverso, che
            nel database non corrisponderebbe più.
    """
    report = ReportCopia()
    for nome, utenti in sorted(nomi_media_utenti().items()):
        if destinazione.exists(nome):
            report.gia_presenti.append(nome)
            continue
        try:
            presente = sorgente.exists(nome)
        except SuspiciousFileOperation:
            presente = False
        if not presente:
            report.mancanti.append((nome, utenti))
            continue
        if dry_run:
            report.da_copiare.append(nome)
            continue
        with sorgente.open(nome, "rb") as file:
            salvato = destinazione.save(nome, file)
        if salvato != nome:
            raise RuntimeError(f"{nome} salvato come {salvato}: il database non lo troverebbe.")
        report.copiati.append(nome)
    return report
