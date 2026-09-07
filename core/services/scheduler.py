"""Scheduler interno: esegue i lavori periodici senza cron né Task Scheduler.

Oggi c'è un solo lavoro, il controllo di congruenza con Business Central
(``core.services.bc_sync``), che deve girare una volta al giorno a un orario
fisso. Invece di registrare un'attività pianificata sul server — configurazione
fuori dal repository, da rifare a ogni macchina — l'applicazione avvia un
thread che si sveglia a intervalli regolari e verifica se è il momento.

Come si tiene una sola esecuzione al giorno:

- lo stato sta in database (``EsecuzioneSchedulata``), non in memoria, così
  sopravvive ai riavvii ed è condiviso fra i processi (in Docker il sito gira
  con più worker gunicorn, ognuno con il proprio thread);
- il turno si prenota con ``select_for_update(skip_locked=True)``: chi arriva
  secondo trova la riga occupata ed esce subito;
- la prenotazione viene scritta *prima* di eseguire, e la sync — che dura
  minuti — gira fuori dalla transazione, senza tenere un lock aperto.

Se il server era spento all'ora prevista, il lavoro parte al primo giro utile
dopo l'avvio: la condizione non è "sono le 17:00" ma "sono passate le 17:00 e
oggi non ho ancora girato". Se invece l'esecuzione fallisce (ERP irraggiungibile),
l'errore viene registrato e si ritenta il giorno dopo, senza tentativi ripetuti.
"""

from __future__ import annotations

import atexit
import logging
import os
import sys
import threading
from datetime import datetime, time

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from ..models import EsecuzioneSchedulata
from .bc_sync import BusinessCentralNonDisponibile, sincronizza_commesse

logger = logging.getLogger(__name__)

NOME_JOB = "bc_sync"

ORARIO_PREDEFINITO = time(17, 0)

# Comandi di manutenzione: lo scheduler non deve partire mentre girano, o si
# ritroverebbe a lavorare su un database di test o a metà di una migrazione.
COMANDI_SENZA_SCHEDULER = {
    "test",
    "migrate",
    "makemigrations",
    "sqlmigrate",
    "showmigrations",
    "collectstatic",
    "shell",
    "dbshell",
    "createsuperuser",
    "changepassword",
    "loaddata",
    "dumpdata",
    "check",
    "sync_business_central",
}

_stop = threading.Event()
_thread: threading.Thread | None = None


def _ora_schedulata() -> time:
    """Orario giornaliero configurato, ``17:00`` se il valore non è valido."""
    valore = str(getattr(settings, "BC_SYNC_ORARIO", "")).strip()
    if not valore:
        return ORARIO_PREDEFINITO
    try:
        return datetime.strptime(valore, "%H:%M").time()
    except ValueError:
        logger.warning(
            'Scheduler: BC_SYNC_ORARIO "%s" non è nel formato HH:MM, uso %s.',
            valore,
            ORARIO_PREDEFINITO.strftime("%H:%M"),
        )
        return ORARIO_PREDEFINITO


def _deve_eseguire(ultima, adesso) -> bool:
    """``True`` se l'orario è passato e oggi il lavoro non è ancora girato.

    Args:
        ultima: Momento dell'ultima esecuzione, ``None`` se non è mai girato.
        adesso: Momento attuale, nel fuso orario locale.

    Il confronto è su date locali e non su un intervallo di 24 ore: se il
    server era spento alle 17:00 e riparte alle 19:00, il lavoro di oggi viene
    recuperato al primo controllo.
    """
    if adesso.time() < _ora_schedulata():
        return False
    if ultima is None:
        return True
    return timezone.localtime(ultima).date() < adesso.date()


def _riepilogo(report: dict) -> str:
    return (
        f"controllate {report['controllate']}, "
        f"aggiornate {report['aggiornate']}, "
        f"non trovate in BC {len(report['non_trovate'])}, "
        f"errori {len(report['errori'])}"
    )


def _prenota(adesso) -> bool:
    """Segna l'esecuzione di oggi come presa in carico da questo processo.

    Returns:
        ``True`` se il turno è nostro, ``False`` se non è ora oppure se un
        altro processo ha già la riga in mano.
    """
    if adesso.time() < _ora_schedulata():
        # Prima dell'orario non serve il database: la stragrande maggioranza
        # dei giri finisce qui, senza una query.
        return False
    EsecuzioneSchedulata.objects.get_or_create(nome=NOME_JOB)
    with transaction.atomic():
        stato = (
            EsecuzioneSchedulata.objects.select_for_update(skip_locked=True)
            .filter(nome=NOME_JOB)
            .first()
        )
        if stato is None:  # riga occupata: un altro processo sta decidendo
            return False
        if not _deve_eseguire(stato.ultima_esecuzione, adesso):
            return False
        stato.ultima_esecuzione = adesso
        stato.esito = "in corso"
        stato.save(update_fields=["ultima_esecuzione", "esito"])
    return True


def esegui_se_dovuto(adesso=None) -> bool:
    """Un giro dello scheduler: prenota il turno e, se spetta a noi, sincronizza.

    L'esito (riepilogo o errore) resta sulla riga ``EsecuzioneSchedulata``, così
    è consultabile dall'admin. Nessuna eccezione esce da qui: il thread che
    chiama questa funzione deve sopravvivere a qualsiasi guasto dell'ERP.

    Returns:
        ``True`` se la sincronizzazione è stata avviata da questa chiamata.
    """
    adesso = adesso or timezone.localtime()
    if not _prenota(adesso):
        return False

    try:
        report = sincronizza_commesse()
        esito = _riepilogo(report)
    except BusinessCentralNonDisponibile as exc:
        # Un tentativo al giorno: l'errore resta a verbale e si ritenta domani.
        logger.error("Scheduler: sincronizzazione BC non eseguita — %s", exc)
        esito = f"errore: {exc}"
    except Exception as exc:  # noqa: BLE001 — il thread non deve morire mai
        logger.exception("Scheduler: sincronizzazione BC fallita.")
        esito = f"errore: {exc}"

    EsecuzioneSchedulata.objects.filter(nome=NOME_JOB).update(esito=esito[:300])
    return True


def _ciclo(intervallo: int) -> None:
    """Loop del thread: attende, poi controlla se c'è da eseguire.

    L'attesa precede il primo controllo, così l'avvio dell'applicazione non
    gareggia con ``migrate`` e ``collectstatic``.
    """
    while not _stop.wait(intervallo):
        try:
            close_old_connections()
            esegui_se_dovuto()
        except Exception:  # noqa: BLE001 — nessun errore può fermare il ciclo
            logger.exception("Scheduler: giro fallito.")
        finally:
            close_old_connections()


def avvia(intervallo: int | None = None) -> bool:
    """Avvia il thread dello scheduler. Idempotente: un solo thread per processo."""
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    if intervallo is None:
        intervallo = int(getattr(settings, "BC_SYNC_INTERVALLO_SECONDI", 300))
    _stop.clear()
    _thread = threading.Thread(
        target=_ciclo,
        args=(intervallo,),
        name="bc-sync-scheduler",
        daemon=True,
    )
    _thread.start()
    atexit.register(ferma)
    logger.info(
        "Scheduler avviato: sincronizzazione BC alle %s, controllo ogni %d secondi.",
        _ora_schedulata().strftime("%H:%M"),
        intervallo,
    )
    return True


def ferma() -> None:
    """Ferma il ciclo al prossimo risveglio (usata da ``atexit`` e dai test)."""
    _stop.set()


def _processo_adatto() -> bool:
    """``False`` per i processi in cui lo scheduler non ha senso o è dannoso.

    Sotto gunicorn o waitress ``sys.argv`` non contiene un comando Django,
    quindi la regola è per esclusione: si esce solo sui comandi di manutenzione
    e sul processo padre dell'autoreload di ``runserver``, che altrimenti
    avvierebbe un secondo thread.
    """
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando in COMANDI_SENZA_SCHEDULER:
        return False
    if comando == "runserver" and os.environ.get("RUN_MAIN") != "true":
        return False
    return True


def avvia_se_previsto() -> bool:
    """Avvia lo scheduler se la configurazione e il processo lo consentono."""
    if not getattr(settings, "BC_SYNC_SCHEDULER", False):
        return False
    if not _processo_adatto():
        return False
    return avvia()
