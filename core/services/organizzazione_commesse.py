"""Lettura del file Excel "Organizzazione Commesse" (MQ 8.3-06).

Foglio "Commesse", una riga per commessa: colonne PM/PE/WE/QCI, di solito un
solo cognome ciascuna, non sempre valorizzate. Best-effort per costruzione:
il file vive su una share di rete mantenuta a mano, la sua struttura non è
sotto il nostro controllo.

Il foglio "Nomi" (cognome → prefisso username, per ruolo) non è letto qui.
Per abbinare i cognomi a un utente registrato si usa invece
``User.last_name``: più affidabile, perché è il dato che l'app già mantiene
(il foglio "Nomi" può disallinearsi senza che nessuno se ne accorga).
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


def trova_utente_per_cognome(cognome: str):
    """Utente registrato con questo cognome (``User.last_name``, case-insensitive).

    ``None`` se non c'è nessuna corrispondenza o ce n'è più di una: in
    entrambi i casi è troppo ambiguo per decidere da soli — il cognome sul
    foglio può essere scritto male, o la persona può non essere registrata
    in workflow. Va risolto a mano (via admin).
    """
    from ..models import User

    corrispondenze = list(User.objects.filter(last_name__iexact=(cognome or "").strip()))
    return corrispondenze[0] if len(corrispondenze) == 1 else None


def _crea_persona(testata, ruolo, cognome):
    """Crea una PersonaCommessa da un cognome del foglio.

    Prova prima ad abbinarlo a un utente registrato; se non c'è
    corrispondenza univoca, la crea come testo libero (nessun errore: va
    solo segnalata come "da risolvere" a chi chiama).

    Returns:
        (persona, abbinato: bool)
    """
    from ..models import PersonaCommessa

    utente = trova_utente_per_cognome(cognome)
    if utente:
        return PersonaCommessa.objects.create(testata=testata, ruolo=ruolo, utente=utente), True
    return (
        PersonaCommessa.objects.create(testata=testata, ruolo=ruolo, nome_libero=cognome),
        False,
    )


def backfill_persone_commessa(jobs=None, dry_run=False) -> dict:
    """Popola PM/PE/QCI/WE per le commesse già esistenti, dal foglio Excel.

    Idempotente a livello di ruolo: una commessa che ha già almeno una
    ``PersonaCommessa`` per un ruolo non viene toccata per quel ruolo (non
    duplica, non sovrascrive correzioni fatte a mano via admin); un ruolo
    ancora vuoto viene popolato se il foglio ha dei nomi. Ogni cognome viene
    abbinato a un utente registrato quando possibile (vedi
    ``trova_utente_per_cognome``); altrimenti resta testo libero e compare
    in ``da_risolvere``.

    Args:
        jobs: Iterable di job su cui limitare il backfill; tutte le
            commesse se omesso.
        dry_run: Se True, calcola cosa verrebbe fatto senza scrivere nulla.

    Returns:
        Dict con ``aggiornate`` (job con almeno un ruolo popolato),
        ``non_trovate`` (job assenti nel foglio), ``ruoli_saltati`` (già
        popolati, non toccati) e ``da_risolvere`` (lista di
        ``{"job", "ruolo", "nome"}`` per i cognomi non abbinati a un utente).
    """
    from ..models import PersonaCommessa, Testata

    qs = Testata.objects.filter(job__in=list(jobs)) if jobs else Testata.objects.all()
    testate = list(qs.order_by("job"))
    dati = leggi_organizzazione_commesse()

    aggiornate = []
    non_trovate = []
    ruoli_saltati = 0
    da_risolvere = []
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
                for nome in nomi:
                    if dry_run:
                        abbinato = trova_utente_per_cognome(nome) is not None
                    else:
                        _, abbinato = _crea_persona(testata, ruolo, nome)
                    if not abbinato:
                        da_risolvere.append({"job": testata.job, "ruolo": ruolo, "nome": nome})
                nomi_creati += len(nomi)
        if nomi_creati:
            aggiornate.append(testata.job)

    return {
        "aggiornate": aggiornate,
        "non_trovate": non_trovate,
        "ruoli_saltati": ruoli_saltati,
        "da_risolvere": da_risolvere,
        "dry_run": dry_run,
    }


def risolvi_persone_libere(jobs=None, dry_run=False) -> dict:
    """Riprova ad abbinare a un utente registrato le PersonaCommessa già a testo libero.

    Utile dopo aver corretto un nome sul foglio, o dopo che una persona si è
    registrata in workflow: non serve rileggere il foglio, il cognome è già
    salvato in ``nome_libero``.

    Args:
        jobs: Iterable di job su cui limitare la ricerca; tutte le commesse
            se omesso.
        dry_run: Se True, calcola cosa verrebbe risolto senza scrivere nulla.

    Returns:
        Dict con ``risolte`` (lista di ``{"job", "ruolo", "nome"}`` abbinate)
        e ``non_risolte`` (stesso formato, ancora senza corrispondenza).
    """
    from ..models import PersonaCommessa

    qs = PersonaCommessa.objects.filter(utente__isnull=True).exclude(nome_libero="")
    if jobs:
        qs = qs.filter(testata__job__in=list(jobs))

    risolte = []
    non_risolte = []
    for persona in qs.select_related("testata").order_by("testata__job", "ruolo"):
        voce = {"job": persona.testata.job, "ruolo": persona.ruolo, "nome": persona.nome_libero}
        utente = trova_utente_per_cognome(persona.nome_libero)
        if not utente:
            non_risolte.append(voce)
            continue
        risolte.append(voce)
        if not dry_run:
            persona.utente = utente
            persona.nome_libero = ""
            persona.save(update_fields=["utente", "nome_libero"])

    return {"risolte": risolte, "non_risolte": non_risolte, "dry_run": dry_run}
