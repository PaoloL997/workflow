"""Seed del corpo di un Quality Control Plan da un file JSON.

Serve ad avere dati realistici su cui provare l'editor del corpo. Il file è un
elenco di sezioni, nell'ordine del documento originale:

    [{"titolo": "Documents Approval",
      "steps": [{"codice": "PIM", "extent": 1.0,
                 "punti": {"B&R": "H", "LNG CANADA": "H", "A.I.": "-"},
                 "remarks": null}]}]

Il corpo si crea con le stesse funzioni di servizio dell'interfaccia
(``crea_sezione``, ``aggiungi_step``, ``aggiorna_step``, ``imposta_punti``):
snapshot, riferimenti documentali e punti d'intervento escono esattamente come
se qualcuno li inserisse dalla pagina del piano.

Quello che nel file non torna col sistema — un codice che non è nel catalogo,
un ente che non è sul piano — diventa un'anomalia nel riepilogo e il seed va
avanti, perché anche un piano vero ha voci scritte a mano. Fanno eccezione i
punti d'intervento che il modello non sa rappresentare: lì il seed si ferma
prima di scrivere, perché come estendere il modello va deciso, non indovinato.
"""

import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from ..models import (
    AttivitaQCP,
    PuntoIntervento,
    QualityControlPlan,
    QualityControlPlanStep,
    Testata,
)
from .quality_control_plan import (
    aggiorna_step,
    aggiungi_step,
    crea_sezione,
    elimina_sezione,
    imposta_punti,
    normalizza_punto,
)


class SeedNonValido(Exception):
    """Il seed non si può eseguire: il messaggio dice perché e cosa fare."""


class _AnnullaDryRun(Exception):
    """Annulla la transazione di un dry-run dopo averlo eseguito per intero."""


def _dove(numero, titolo, numero_step=None):
    testo = f'sezione {numero} "{titolo}"'
    return f"{testo}, step {numero_step}" if numero_step else testo


def _spazi(testo):
    """Il testo con gli spazi ridotti a uno solo: per suggerire, mai per decidere."""
    return " ".join(testo.split())


def leggi_corpo(percorso):
    """Le sezioni del file, controllate (vedi ``valida_corpo``)."""
    try:
        dati = json.loads(Path(percorso).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SeedNonValido(f"File non trovato: {percorso}") from exc
    except json.JSONDecodeError as exc:
        raise SeedNonValido(f"JSON non valido: {exc}") from exc
    return valida_corpo(dati)


def valida_corpo(dati):
    """Controlla forma e punti del file prima di scrivere qualsiasi cosa.

    I limiti dei singoli valori (lunghezze, extent fra 0 e 1) li controllano le
    funzioni di servizio durante il seed; qui si ferma quello che renderebbe il
    seed impossibile o sbagliato in partenza.
    """
    if not isinstance(dati, list) or not dati:
        raise SeedNonValido("Il file deve essere un elenco di sezioni.")
    for numero, sezione in enumerate(dati, start=1):
        titolo = sezione.get("titolo") if isinstance(sezione, dict) else None
        if not isinstance(titolo, str) or not titolo.strip():
            raise SeedNonValido(f"sezione {numero}: manca il titolo.")
        if not isinstance(sezione.get("steps"), list):
            raise SeedNonValido(f"{_dove(numero, titolo)}: steps deve essere un elenco.")
        for numero_step, step in enumerate(sezione["steps"], start=1):
            dove = _dove(numero, titolo, numero_step)
            codice = step.get("codice") if isinstance(step, dict) else None
            if not isinstance(codice, str) or not codice.strip():
                raise SeedNonValido(f"{dove}: manca il codice.")
            if not isinstance(step.get("punti") or {}, dict):
                raise SeedNonValido(f"{dove}: punti deve essere un oggetto ente → punto.")
            if step.get("remarks") is not None and not isinstance(step["remarks"], str):
                raise SeedNonValido(f"{dove}: remarks deve essere un testo o null.")
            extent = step.get("extent")
            if extent is not None and (
                isinstance(extent, bool) or not isinstance(extent, (int, float))
            ):
                raise SeedNonValido(f"{dove}: extent deve essere un numero o null.")

    non_rappresentabili = punti_non_rappresentabili(dati)
    if non_rappresentabili:
        elenco = "; ".join(
            f'"{valore}" ({voce["volte"]} volt{"a" if voce["volte"] == 1 else "e"}, '
            f"la prima in {voce['primo']})"
            for valore, voce in non_rappresentabili.items()
        )
        ammessi = ", ".join(PuntoIntervento.values)
        raise SeedNonValido(
            f"Punti d'intervento che il modello non sa rappresentare: {elenco}. "
            f'Valori ammessi: {ammessi}, anche più di uno separati da "/" (per esempio '
            "R/SW). Il seed non li forza e non li tronca: prima va deciso come "
            "estendere PuntoIntervento, poi si rilancia."
        )
    return dati


def _rappresentabile(valore):
    try:
        normalizza_punto(valore)
    except ValueError:
        return False
    return True


def punti_non_rappresentabili(sezioni):
    """I valori di punto che il modello non sa rappresentare, con dove compaiono.

    La regola è ``normalizza_punto``, la stessa di ``imposta_punto``: qui si
    rifiuta esattamente quello che rifiuterebbe il servizio. ``null`` non è un
    valore: è un punto non indicato, gestito dal seed.
    """
    trovati = {}
    for numero, sezione in enumerate(sezioni, start=1):
        for numero_step, step in enumerate(sezione["steps"], start=1):
            for ente, valore in (step.get("punti") or {}).items():
                if valore is None or _rappresentabile(valore):
                    continue
                voce = trovati.setdefault(
                    str(valore),
                    {
                        "volte": 0,
                        "primo": f'{_dove(numero, sezione["titolo"], numero_step)}, ente "{ente}"',
                    },
                )
                voce["volte"] += 1
    return trovati


def piano_della_commessa(job):
    """L'unico piano della commessa: senza piani, o con più d'uno, ci si ferma.

    Il seed non crea piani: il piano, con i suoi enti di ispezione, si crea
    dalla pagina della commessa.
    """
    if not Testata.objects.filter(job=job).exists():
        raise SeedNonValido(f"La commessa {job} non esiste.")
    piani = list(QualityControlPlan.objects.filter(testata_id=job).order_by("pk"))
    if not piani:
        raise SeedNonValido(
            f"La commessa {job} non ha un Quality Control Plan. Crealo dalla sezione "
            "Quality Control Plan della commessa, con in copertina gli enti di ispezione "
            "usati nel file, poi rilancia il seed: il seed non crea piani."
        )
    if len(piani) > 1:
        elenco = ", ".join(f'{piano.pk} "{piano.titolo}"' for piano in piani)
        raise SeedNonValido(
            f"La commessa {job} ha {len(piani)} piani ({elenco}) e il seed non sa quale "
            "riempire. Elimina quelli in più dalla sezione Quality Control Plan della "
            "commessa, oppure usa una commessa di prova con un piano solo."
        )
    return piani[0]


def corpo_esistente(piano):
    """Quante sezioni e quanti step ha già il piano."""
    return (
        piano.sections.count(),
        QualityControlPlanStep.objects.filter(sezione__piano=piano).count(),
    )


def semina_corpo(piano, sezioni, reset=False, dry_run=False):
    """Crea sul piano il corpo descritto da ``sezioni`` (già passate da ``valida_corpo``).

    Un piano che ha già un corpo non si tocca, a meno di ``reset``: rilanciare il
    seed non deve duplicare sezioni o step. Con ``reset`` le sezioni esistenti, e
    con loro step e punti, si eliminano prima di ricreare. Tutto avviene in una
    transazione: se qualcosa fallisce non resta niente a metà. Con ``dry_run``
    si fanno davvero tutte le operazioni e poi si annulla la transazione, così il
    riepilogo, anomalie comprese, è quello che uscirebbe senza.

    Restituisce il riepilogo: sezioni e step creati (e quanti a mano), punti
    impostati, cosa è stato eliminato e le anomalie incontrate.
    """
    sezioni_esistenti, steps_esistenti = corpo_esistente(piano)
    if sezioni_esistenti and not reset:
        raise SeedNonValido(
            f'Il piano "{piano.titolo}" ha già un corpo (sezioni: {sezioni_esistenti}, '
            f"step: {steps_esistenti}): rilanciare il seed lo duplicherebbe. Usa --reset "
            "per eliminarlo e ricrearlo dal file."
        )
    report = {
        "piano": piano,
        "sezioni": 0,
        "steps": 0,
        "manuali": 0,
        "punti": 0,
        "eliminate_sezioni": sezioni_esistenti if reset else 0,
        "eliminati_steps": steps_esistenti if reset else 0,
        "anomalie": [],
        "dry_run": dry_run,
    }
    try:
        with transaction.atomic():
            if reset:
                for sezione in list(piano.sections.all()):
                    try:
                        elimina_sezione(sezione)
                    except ValueError as exc:  # sezione con firme: lo storico resta
                        raise SeedNonValido(f"Reset impossibile. {exc}") from exc
            _crea_corpo(piano, sezioni, report)
            if dry_run:
                raise _AnnullaDryRun
    except _AnnullaDryRun:
        pass
    return report


def _crea_corpo(piano, sezioni, report):
    # Lo stesso codice può stare in più capitoli ("Pickling and passivation" è
    # sia in NDE sia in ISPEZIONI FINALI): si tengono tutte, in ordine di catalogo.
    catalogo = defaultdict(list)
    for attivita in AttivitaQCP.objects.filter(attivo=True).order_by("ordine", "id"):
        catalogo[attivita.codice].append(attivita)
    catalogo_per_spazi = {_spazi(codice): codice for codice in catalogo}
    enti = {ente.nome: ente for ente in piano.agencies.all()}
    enti_per_spazi = {_spazi(nome).casefold(): nome for nome in enti}

    enti_mancanti = Counter()
    enti_nel_file = set()
    punti_non_indicati = []

    for numero, dati_sezione in enumerate(sezioni, start=1):
        titolo = dati_sezione["titolo"]
        try:
            sezione = crea_sezione(piano, titolo)
        except ValueError as exc:
            raise SeedNonValido(f"{_dove(numero, titolo)}: {exc}") from exc
        report["sezioni"] += 1

        for numero_step, dati_step in enumerate(dati_sezione["steps"], start=1):
            dove = _dove(numero, titolo, numero_step)
            try:
                step = _crea_step(sezione, dati_step, dove, catalogo, catalogo_per_spazi, report)
                punti = []
                for nome, valore in (dati_step.get("punti") or {}).items():
                    enti_nel_file.add(nome)
                    ente = enti.get(nome)
                    if ente is None:
                        enti_mancanti[nome] += 1
                    elif valore is None:
                        punti_non_indicati.append(f'{dove}, ente "{nome}"')
                    else:
                        punti.append({"agency": ente.pk, "punto": valore})
                if punti:
                    imposta_punti(step, punti)
                    report["punti"] += len(punti)
            except ValueError as exc:
                raise SeedNonValido(f"{dove}: {exc}") from exc

    for nome, volte in enti_mancanti.items():
        simile = enti_per_spazi.get(_spazi(nome).casefold())
        nota = f' (sul piano c\'è "{simile}")' if simile else ""
        report["anomalie"].append(
            f'Ente "{nome}" non presente sul piano{nota}, punti saltati: {volte}. Gli enti '
            "si definiscono nella copertina del piano, il seed non li crea."
        )
    for dove in punti_non_indicati:
        report["anomalie"].append(f'{dove}: punto non indicato nel file (null), resta "-".')
    senza_valori = [nome for nome in enti if nome not in enti_nel_file]
    if senza_valori:
        report["anomalie"].append(
            "Enti del piano che nel file non hanno punti: "
            + ", ".join(f'"{nome}"' for nome in senza_valori)
            + '; i loro punti restano "-".'
        )


def _crea_step(sezione, dati_step, dove, catalogo, catalogo_per_spazi, report):
    """Uno step dal catalogo o, se il codice non c'è, scritto a mano; poi extent e remarks."""
    codice = dati_step["codice"].strip()
    candidate = catalogo.get(codice, [])
    if candidate:
        if len(candidate) > 1:
            capitoli = ", ".join(attivita.capitolo for attivita in candidate)
            report["anomalie"].append(
                f'{dove}: "{codice}" è nel catalogo in {len(candidate)} capitoli ({capitoli}); '
                f'usata l\'attività di "{candidate[0].capitolo}", la prima in ordine di catalogo.'
            )
        step = aggiungi_step(sezione, attivita_id=candidate[0].pk)
    else:
        simile = catalogo_per_spazi.get(_spazi(codice))
        nota = f' (nel catalogo c\'è "{simile}", con spazi diversi)' if simile else ""
        report["anomalie"].append(
            f'{dove}: "{codice}" non è nel catalogo{nota}; creato come step manuale '
            "con il codice come descrizione."
        )
        step = aggiungi_step(sezione, dati={"descrizione": codice})
        report["manuali"] += 1
    report["steps"] += 1

    # Solo quello che cambia rispetto a come lo step è nato: niente salvataggi a vuoto.
    correzioni = {}
    extent = dati_step.get("extent")
    if extent is not None and Decimal(str(extent)) != step.extent:
        correzioni["extent"] = extent
    if dati_step.get("remarks"):
        correzioni["remarks"] = dati_step["remarks"]
    if correzioni:
        aggiorna_step(step, **correzioni)
    return step
