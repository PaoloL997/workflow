"""Precompila le destinazioni cartacee UT dal vecchio file Excel.

Il reparto UT produceva, per ogni commessa, un file di testo con due colonne
per riga separate da spazio: il B&R Doc e una sequenza di 5 cifre 0/1 che
indicano se il documento va spedito in copia cartacea a Valbrembo,
Albignasego, Marghera, Ricengo, Schio — in quest'ordine, che coincide con i
``codice_bc`` 1..5 già assegnati a quegli stabilimenti (vedi la migration
``0045_popola_sigla_codice_bc_stabilimenti``). Il file vive in
``{FILESERVER_JOBS_PATH}/{job}/PROGETTO/UT/TRANSMITTAL/{job}-RecipientsData.txt``
e può non esistere per una commessa: è normale, non un errore.

Il vecchio strumento resta in uso durante la transizione, quindi il file
continua ad aggiornarsi: qui però lo trattiamo come un seed una tantum, non
come una sincronizzazione continua. Un documento con almeno una
``DestinazioneDocumento`` già registrata — a mano nell'app o da un import
precedente — non viene mai più toccato, per non cancellare correzioni fatte
a mano nel frattempo.
"""

from __future__ import annotations

import logging
import re

from ..models import DestinazioneDocumento, Testata
from .fileserver import get_base_path
from .trasmittal_interno import documenti_ut, imposta_destinazioni

logger = logging.getLogger(__name__)

_CARTELLA = "TRANSMITTAL"
_RIGA_RE = re.compile(r"^(\S+)\s+([01]{5})\s*$")


def percorso_recipients_data(job: str):
    """Ritorna il percorso del file, esista o meno."""
    return get_base_path((job or "").strip(), "UT") / _CARTELLA / f"{job}-RecipientsData.txt"


def leggi_recipients_data(job: str) -> dict[str, set[int]] | None:
    """Legge il file e ritorna ``{vendor_doc: {codici_bc}}``.

    Le righe malformate (non due colonne, o la seconda non esattamente 5
    cifre 0/1) vengono ignorate e loggate come warning.

    Returns:
        ``None`` se il file non esiste o non è leggibile; un dict (vuoto se
        il file c'è ma non ha righe valide) altrimenti.
    """
    percorso = percorso_recipients_data(job)
    if not percorso.is_file():
        return None

    try:
        testo = percorso.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning('Import destinazioni: impossibile leggere "%s": %s', percorso, exc)
        return None

    risultato: dict[str, set[int]] = {}
    for numero_riga, riga in enumerate(testo.splitlines(), start=1):
        riga = riga.strip()
        if not riga:
            continue
        match = _RIGA_RE.match(riga)
        if not match:
            logger.warning(
                'Import destinazioni (%s): riga %d non riconosciuta: "%s"',
                job,
                numero_riga,
                riga,
            )
            continue
        vendor_doc, bitmask = match.groups()
        risultato[vendor_doc] = {i + 1 for i, bit in enumerate(bitmask) if bit == "1"}
    return risultato


def importa_destinazioni_commessa(testata, dry_run: bool = False) -> dict:
    """Precompila le destinazioni UT di una commessa dal file, se presente.

    Non tocca un documento UT che ha già almeno una destinazione registrata.

    Args:
        dry_run: Calcola cosa verrebbe fatto senza scrivere nulla.

    Returns:
        Dict con ``trovato`` (bool: il file esiste), ``precompilati``
        (lista di vendor_doc), ``gia_impostati`` (int), ``non_trovati``
        (vendor_doc nel file assenti fra i documenti UT della commessa).
    """
    dati = leggi_recipients_data(testata.job)
    report: dict = {
        "trovato": dati is not None,
        "precompilati": [],
        "gia_impostati": 0,
        "non_trovati": [],
    }
    if dati is None:
        return report

    documenti = {d.vendor_doc: d for d in documenti_ut(testata)}
    documenti_gia_impostati = set(
        DestinazioneDocumento.objects.filter(documento__in=documenti.values())
        .values_list("documento__vendor_doc", flat=True)
        .distinct()
    )

    for vendor_doc, codici_bc in dati.items():
        documento = documenti.get(vendor_doc)
        if documento is None:
            report["non_trovati"].append(vendor_doc)
            continue
        if vendor_doc in documenti_gia_impostati:
            report["gia_impostati"] += 1
            continue
        if not dry_run:
            imposta_destinazioni(documento, codici_bc)
        report["precompilati"].append(vendor_doc)

    return report


def importa_destinazioni_tutte_le_commesse(
    jobs=None, includi_chiuse: bool = False, dry_run: bool = False
) -> dict:
    """Precompila le destinazioni UT su più commesse (o tutte quelle aperte).

    Pensata per il controllo giornaliero, accanto alla sincronizzazione BC:
    una commessa in errore (es. condivisione di rete momentaneamente
    irraggiungibile) non ferma le altre.

    Returns:
        Dict con ``controllate``, ``con_file`` (commesse in cui il file
        esiste), ``precompilati`` (totale documenti), ``gia_impostati``
        (totale), ``non_trovati`` (lista di ``{"job", "vendor_doc"}``),
        ``errori`` (lista di ``{"job", "errore"}``) e ``dry_run``.
    """
    qs = Testata.objects.all()
    if jobs:
        qs = qs.filter(job__in=list(jobs))
    elif not includi_chiuse:
        qs = qs.filter(actual_delivery_date__isnull=True)

    report: dict = {
        "controllate": 0,
        "con_file": 0,
        "precompilati": 0,
        "gia_impostati": 0,
        "non_trovati": [],
        "errori": [],
        "dry_run": bool(dry_run),
    }
    for testata in qs.order_by("job"):
        report["controllate"] += 1
        try:
            esito = importa_destinazioni_commessa(testata, dry_run=dry_run)
        except Exception as exc:  # una commessa in errore non ferma le altre
            logger.exception('Import destinazioni: errore sulla commessa "%s".', testata.job)
            report["errori"].append({"job": testata.job, "errore": str(exc)})
            continue
        if not esito["trovato"]:
            continue
        report["con_file"] += 1
        report["precompilati"] += len(esito["precompilati"])
        report["gia_impostati"] += esito["gia_impostati"]
        for vendor_doc in esito["non_trovati"]:
            report["non_trovati"].append({"job": testata.job, "vendor_doc": vendor_doc})

    logger.info(
        "Import destinazioni: controllate %d commesse, %d con file, "
        "%d documenti precompilati, %d già impostati, %d errori%s",
        report["controllate"],
        report["con_file"],
        report["precompilati"],
        report["gia_impostati"],
        len(report["errori"]),
        " (dry-run)" if report["dry_run"] else "",
    )
    return report
