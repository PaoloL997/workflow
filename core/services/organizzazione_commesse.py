"""Lettura del file Excel "Organizzazione Commesse" (MQ 8.3-06).

Foglio "Commesse", una riga per commessa: colonne PM/PE/WE/QCI, di solito un
solo cognome ciascuna, non sempre valorizzate. Best-effort per costruzione:
il file vive su una share di rete mantenuta a mano, la sua struttura non è
sotto il nostro controllo.

Il foglio "Nomi" (cognome → prefisso username, per ruolo) non è letto qui:
potrebbe in futuro servire per collegare automaticamente questi nomi a utenti
registrati, ma per ora l'import da report li tratta sempre come testo libero.
"""

import logging
from pathlib import Path

import openpyxl
from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)

_FOGLIO = "Commesse"
_RIGA_INTESTAZIONE = 2
_COLONNA_JOB = "Job no."
_COLONNE_RUOLO = {"PM": "pm", "PE": "pe", "WE": "we", "QCI": "qci"}


def _dividi_nomi(valore) -> list[str]:
    """Divide una cella grezza in singoli nomi.

    "N/A" (l'intera cella, case-insensitive) vale vuoto: va riconosciuto
    prima di spezzare su "/", altrimenti "N/A" diventerebbe due nomi ("N" e
    "A"). Poi spezza su "/" e a capo, strippando ogni parte e scartando le
    vuote. Non tenta di interpretare oltre questo un testo libero malformato
    (limite noto del foglio sorgente).
    """
    if not valore:
        return []
    testo = str(valore).strip()
    if testo.lower() in ("n/a", "na"):
        return []
    pezzi = testo.replace("\n", "/").split("/")
    return [pezzo.strip() for pezzo in pezzi if pezzo.strip()]


def _normalizza_job(valore) -> str:
    """Normalizza una cella 'Job no.' al formato stringa di Testata.job."""
    if valore is None:
        return ""
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)
    return str(valore).strip()


def leggi_organizzazione_commesse(path=None) -> dict[str, dict[str, list[str]]]:
    """Legge il foglio "Commesse" e ritorna i nomi PM/PE/WE/QCI per commessa.

    Alcune commesse hanno più righe (una per sotto-voce/DWG): i nomi delle
    righe con lo stesso "Job no." si uniscono per ruolo, deduplicati
    case-insensitive, invece che lasciare l'ultima riga sovrascrivere le
    precedenti (verificato sul file reale: capita, es. job "23068").

    Returns:
        ``{job: {"pm": [...], "pe": [...], "qci": [...], "we": [...]}}``.

    Raises:
        FileNotFoundError: se il file non esiste al percorso configurato.
    """
    xlsm_path = Path(path or settings.ORGANIZZAZIONE_COMMESSE_XLSM_PATH)
    if not xlsm_path.is_file():
        raise FileNotFoundError(f'File organizzazione commesse non trovato: "{xlsm_path}"')

    wb = openpyxl.load_workbook(xlsm_path, read_only=True, data_only=True, keep_vba=False)
    try:
        ws = wb[_FOGLIO]
        righe = ws.iter_rows(min_row=_RIGA_INTESTAZIONE, values_only=True)
        intestazione = next(righe)
        indice = {str(nome).strip(): i for i, nome in enumerate(intestazione) if nome is not None}
        idx_job = indice.get(_COLONNA_JOB)
        if idx_job is None:
            logger.warning('Colonna "%s" non trovata nel foglio "%s".', _COLONNA_JOB, _FOGLIO)
            return {}

        risultato: dict[str, dict[str, list[str]]] = {}
        visti: dict[str, dict[str, set[str]]] = {}
        for riga in righe:
            job = _normalizza_job(riga[idx_job] if idx_job < len(riga) else None)
            if not job:
                continue
            ruoli = risultato.setdefault(job, {chiave: [] for chiave in _COLONNE_RUOLO.values()})
            visti_job = visti.setdefault(job, {chiave: set() for chiave in _COLONNE_RUOLO.values()})
            for colonna, chiave in _COLONNE_RUOLO.items():
                idx = indice.get(colonna)
                valore = riga[idx] if idx is not None and idx < len(riga) else None
                for nome in _dividi_nomi(valore):
                    chiave_dedup = nome.lower()
                    if chiave_dedup not in visti_job[chiave]:
                        visti_job[chiave].add(chiave_dedup)
                        ruoli[chiave].append(nome)
        return risultato
    finally:
        wb.close()


def persone_per_job(job: str, path=None) -> dict[str, list[str]] | None:
    """Ruoli PM/PE/QCI/WE per una singola commessa, o None se non nel foglio."""
    return leggi_organizzazione_commesse(path).get((job or "").strip())


def backfill_persone_commessa(jobs=None, dry_run=False) -> dict:
    """Popola PM/PE/QCI/WE per le commesse già esistenti, dal foglio Excel.

    Idempotente a livello di ruolo: una commessa che ha già almeno una
    ``PersonaCommessa`` per un ruolo non viene toccata per quel ruolo (non
    duplica, non sovrascrive correzioni fatte a mano via admin); un ruolo
    ancora vuoto viene popolato se il foglio ha dei nomi.

    Args:
        jobs: Iterable di job su cui limitare il backfill; tutte le
            commesse se omesso.
        dry_run: Se True, calcola cosa verrebbe fatto senza scrivere nulla.

    Returns:
        Dict con ``aggiornate`` (job con almeno un ruolo popolato),
        ``non_trovate`` (job assenti nel foglio) e ``ruoli_saltati``
        (già popolati, non toccati).
    """
    from ..models import PersonaCommessa, Testata

    qs = Testata.objects.filter(job__in=list(jobs)) if jobs else Testata.objects.all()
    testate = list(qs.order_by("job"))
    dati = leggi_organizzazione_commesse()

    aggiornate = []
    non_trovate = []
    ruoli_saltati = 0
    for testata in testate:
        ruoli = dati.get(testata.job)
        if ruoli is None:
            non_trovate.append(testata.job)
            continue
        nomi_creati = 0
        with transaction.atomic():
            for ruolo, nomi in ruoli.items():
                if not nomi:
                    continue
                if PersonaCommessa.objects.filter(testata=testata, ruolo=ruolo).exists():
                    ruoli_saltati += 1
                    continue
                if not dry_run:
                    for nome in nomi:
                        PersonaCommessa.objects.create(
                            testata=testata, ruolo=ruolo, nome_libero=nome
                        )
                nomi_creati += len(nomi)
        if nomi_creati:
            aggiornate.append(testata.job)

    return {
        "aggiornate": aggiornate,
        "non_trovate": non_trovate,
        "ruoli_saltati": ruoli_saltati,
        "dry_run": dry_run,
    }
