"""Catalogo attività del Quality Control Plan: import dal JSON e consultazione.

Il catalogo è un'anagrafica globale, uguale per tutte le commesse. Il JSON in
``core/data/`` è la sorgente che ne ricrea il contenuto in ogni ambiente; dopo
l'import si mantiene dall'admin.

L'import è idempotente: la chiave è codice + capitolo, quindi rieseguirlo
aggiorna le righe esistenti invece di duplicarle. Il flag ``attivo`` non viene
toccato: un'attività disattivata dall'admin resta disattivata anche dopo un
nuovo import.
"""

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Min, Q

from ..models import AttivitaQCP

CATALOGO_PREDEFINITO = Path(__file__).resolve().parents[1] / "data" / "catalogo_attivita_qcp.json"

# Colonne che arrivano dal JSON. ``attivo`` non c'è di proposito: è una scelta
# dell'admin, non un dato della sorgente.
CAMPI = (
    "codice",
    "divisione",
    "capitolo",
    "descrizione",
    "test_inspection",
    "reference_doc_tipo",
    "reference_doc_valore",
    "acceptance_criteria",
    "documento_richiesto",
    "tecnica",
    "tipo",
    "ordine",
)

# Risultati massimi dell'API: il selettore mostra una lista da scorrere, non
# l'intero catalogo; chi ne vuole di più restringe la ricerca.
LIMITE_RISULTATI = 100


class CatalogoNonValido(Exception):
    """Il JSON non si può importare: il messaggio dice quale riga e perché."""


def leggi_catalogo(percorso):
    """Righe del JSON, che deve essere un elenco di oggetti."""
    try:
        righe = json.loads(Path(percorso).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogoNonValido(f"File non trovato: {percorso}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogoNonValido(f"JSON non valido: {exc}") from exc
    if not isinstance(righe, list):
        raise CatalogoNonValido("Il catalogo deve essere un elenco di attività.")
    return righe


def _descrivi(numero, riga):
    """Come citare una riga negli errori: posizione nel JSON e riga dell'Excel."""
    excel = riga.get("riga_excel") if isinstance(riga, dict) else None
    return f"riga {numero}" + (f" (riga Excel {excel})" if excel else "")


def _valida(numero, riga):
    """I valori di una riga, pronti per il modello, o CatalogoNonValido."""
    dove = _descrivi(numero, riga)
    if not isinstance(riga, dict):
        raise CatalogoNonValido(f"{dove}: non è un oggetto.")
    mancanti = [campo for campo in CAMPI if campo not in riga]
    if mancanti:
        raise CatalogoNonValido(f"{dove}: mancano {', '.join(mancanti)}.")

    dati = {}
    for campo in CAMPI:
        valore = riga[campo]
        if campo == "ordine":
            if isinstance(valore, bool) or not isinstance(valore, int):
                raise CatalogoNonValido(f"{dove}: ordine deve essere un numero intero.")
            dati[campo] = valore
            continue
        if not isinstance(valore, str):
            raise CatalogoNonValido(f"{dove}: {campo} deve essere un testo.")
        # I residui di formule Excel (="...") sono già stati ripuliti dal
        # file: se ne ricompare uno, la sorgente va sistemata, non importata.
        if valore.startswith('="'):
            raise CatalogoNonValido(f"{dove}: {campo} contiene una formula Excel ({valore}).")
        dati[campo] = valore.strip()

    try:
        AttivitaQCP(**dati).full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:
        dettagli = "; ".join(
            f"{campo}: {' '.join(messaggi)}" for campo, messaggi in exc.message_dict.items()
        )
        raise CatalogoNonValido(f"{dove}: {dettagli}") from exc
    return dati


def importa_catalogo(righe, dry_run=False):
    """Crea o aggiorna le attività del catalogo; nulla se una riga è malformata.

    Tutte le righe vengono controllate prima di scrivere, e la scrittura avviene
    in una sola transazione: l'import o riesce intero o non tocca il database.
    Restituisce i conteggi (creati, aggiornati, invariati) e le chiavi coinvolte.
    """
    validate = []
    chiavi = {}
    for numero, riga in enumerate(righe, start=1):
        dati = _valida(numero, riga)
        chiave = (dati["codice"], dati["capitolo"])
        if chiave in chiavi:
            raise CatalogoNonValido(
                f"{_descrivi(numero, riga)}: codice e capitolo già usati alla riga {chiavi[chiave]}."
            )
        chiavi[chiave] = numero
        validate.append(dati)

    report = {"creati": [], "aggiornati": [], "invariati": [], "dry_run": dry_run}
    esistenti = {(a.codice, a.capitolo): a for a in AttivitaQCP.objects.all()}
    with transaction.atomic():
        for dati in validate:
            chiave = (dati["codice"], dati["capitolo"])
            attivita = esistenti.get(chiave)
            if attivita is None:
                report["creati"].append(chiave)
                if not dry_run:
                    AttivitaQCP.objects.create(**dati)
                continue
            modifiche = {c: v for c, v in dati.items() if getattr(attivita, c) != v}
            if not modifiche:
                report["invariati"].append(chiave)
                continue
            report["aggiornati"].append(chiave)
            if not dry_run:
                for campo, valore in modifiche.items():
                    setattr(attivita, campo, valore)
                attivita.save(update_fields=list(modifiche))
    return report


def serialize_attivita(attivita, piano=None):
    dati = {
        "id": attivita.pk,
        **{campo: getattr(attivita, campo) for campo in CAMPI},
    }
    if piano is not None:
        # Il riferimento come uscirebbe sullo step di quel piano: il modo più
        # rapido per accorgersi di aver scelto l'attività sbagliata.
        dati["reference_doc_risolto"] = attivita.risolvi_reference_doc(piano)
    return dati


def capitoli_attivi():
    """Capitoli del catalogo che hanno attività attive, nell'ordine del catalogo."""
    return list(
        AttivitaQCP.objects.filter(attivo=True)
        .values("capitolo")
        .annotate(primo=Min("ordine"))
        .order_by("primo", "capitolo")
        .values_list("capitolo", flat=True)
    )


def cerca_attivita(
    capitolo=None, divisione=None, tipo=None, q=None, limite=LIMITE_RISULTATI, piano=None
):
    """Attività attive, filtrate e in ordine di catalogo, fino a ``limite``.

    ``q`` cerca su codice e descrizione senza badare alle maiuscole; con più
    parole, ciascuna deve comparire (in uno dei due campi): "base welding"
    trova "VT-Complete base welding". Con ``piano`` ogni attività porta anche il
    riferimento documentale già risolto per quel piano.
    """
    qs = AttivitaQCP.objects.filter(attivo=True)
    if capitolo:
        qs = qs.filter(capitolo=capitolo)
    if divisione:
        qs = qs.filter(divisione=divisione)
    if tipo:
        qs = qs.filter(tipo=tipo)
    for parola in (q or "").split():
        qs = qs.filter(Q(codice__icontains=parola) | Q(descrizione__icontains=parola))

    totale = qs.count()
    attivita = [serialize_attivita(a, piano) for a in qs.order_by("ordine", "id")[:limite]]
    return {
        "attivita": attivita,
        "totale": totale,
        "limite": limite,
        "troncato": totale > len(attivita),
    }
