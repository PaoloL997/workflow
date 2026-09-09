"""Quality Control Plan: precompilazione da Business Central, creazione ed elenco.

La testata del piano si precompila da BC dove il dato esiste e dal sistema dove
BC non arriva; quello che non ha ancora una sorgente resta da compilare a mano.
I valori vengono poi salvati così come sono: il piano è un documento, e deve
restare identico a com'era quando è stato creato. Vale anche per la sede: si
sceglie fra gli stabilimenti in impostazioni, ma sul piano finisce il nome, non
un riferimento — se domani lo stabilimento viene rinominato, il piano già emesso
resta com'era.

BC può essere irraggiungibile. Quando succede la precompilazione non fallisce:
restituisce i campi che sa comunque riempire e dice perché mancano gli altri.
"""

import logging
from datetime import date

from django.db import transaction

from ..date_fmt import format_display_date
from ..models import QualityControlPlan, QualityControlPlanItem, Stabilimento, Testata
from .commesse import _parse_date
from .revisione_label import lettera_a_numero, numero_a_lettera

logger = logging.getLogger(__name__)

# Unica costante di testata: uguale su ogni piano, quindi non è una colonna.
VENDOR = "Brembana & Rolle"

# Titolo proposto: numero di commessa, "QCP" e una lettera progressiva.
TITOLO_SUFFISSO = "QCP"

# Nessuno step è ancora modellato, quindi il completamento è per forza a zero.
# Quando gli step esisteranno questa diventa un conteggio vero: è calcolata qui,
# e non scritta nel template, perché così cambia in un punto solo.
PERCENTUALE_INIZIALE = 0

MAX_ITEMS = 200

_MAX_ITEM_NO = 200
_MAX_DESCRIZIONE = 300

# Campi scrivibili dal client. Vendor e Job n. non ci sono di proposito: sono
# costante e derivato, e vanno ignorati anche se il client li manda.
_QCP_FIELDS = {
    "titolo",
    "doc_no",
    "location",
    "sheet",
    "project",
    "dwg_no",
    "owner",
    "po_no",
    "data",
    "purchaser",
    "descrizione_item",
    "serial_no",
    "prepared_by",
}


def _clean_qcp_fields(data):
    return {k: v for k, v in data.items() if k in _QCP_FIELDS}


def _apri_connessione():
    """Apre un connettore Business Central (isolato per facilitare i test)."""
    from src.erp.business_central import BusinessCentral

    return BusinessCentral()


def nome_utente(user):
    """Nome da mostrare come compilatore, con gli stessi fallback dei trasmittal."""
    if user is None:
        return ""
    nome = (getattr(user, "nome_completo", None) or user.get_full_name() or "").strip()
    if not nome:
        nome = (user.get_username() or "").strip()
    return nome


def titolo_predefinito(job):
    """Titolo proposto per un nuovo piano: ``{job}-QCP{lettera}``.

    La lettera avanza sui piani già esistenti della commessa: A il primo, poi B,
    C… Si guarda il titolo salvato e non quanti piani ci sono, così una lettera
    già usata non viene riproposta nemmeno se nel mezzo qualcuno ha riscritto un
    titolo a mano o ha cancellato un piano.
    """
    prefisso = f"{job}-{TITOLO_SUFFISSO}"
    ultimo = -1
    titoli = QualityControlPlan.objects.filter(testata_id=job).values_list("titolo", flat=True)
    for titolo in titoli:
        sigla = str(titolo or "").strip().upper()
        if not sigla.startswith(prefisso.upper()):
            continue
        numero = lettera_a_numero(sigla[len(prefisso) :])
        if numero is not None and numero > ultimo:
            ultimo = numero
    return f"{prefisso}{numero_a_lettera(ultimo + 1)}"


def nome_stabilimento(user):
    """Sede da proporre: quella dell'utente, quando ne ha una in impostazioni."""
    sede = getattr(user, "stabilimento", None) if user is not None else None
    return sede.nome if sede else ""


def sedi_disponibili():
    """Nomi degli stabilimenti fra cui si può scegliere, in ordine alfabetico."""
    return list(Stabilimento.objects.values_list("nome", flat=True))


def _testo(valore):
    """Valore di BC ripulito: pandas restituisce NaN al posto delle stringhe vuote."""
    if valore is None:
        return ""
    testo = str(valore).strip()
    return "" if testo.lower() in ("nan", "none", "nat") else testo


def _righe(df):
    return [] if df is None or df.empty else df.to_dict("records")


def _dati_bc(job, bc=None):
    """Testata e item da Business Central.

    Restituisce ``(testata, items, warning)``. Non solleva mai: se BC non
    risponde, testata e items sono vuoti e il warning spiega cosa è successo.
    """
    connessione_propria = bc is None
    try:
        if connessione_propria:
            bc = _apri_connessione()
        if getattr(bc, "conn", None) is None:
            return {}, [], "Business Central non raggiungibile: alcuni campi sono da compilare."

        testata_righe = _righe(bc.get_qcp_testata(job))
        item_righe = _righe(bc.get_qcp_items(job))
    except Exception as exc:  # una commessa senza ERP resta comunque creabile
        logger.warning('QCP: lettura da Business Central fallita per "%s": %s', job, exc)
        return {}, [], "Business Central non raggiungibile: alcuni campi sono da compilare."
    finally:
        if connessione_propria and bc is not None:
            bc.close()

    testata = testata_righe[0] if testata_righe else {}

    # Lo scope of supply può ripetere lo stesso codice su più righe: il selettore
    # deve proporlo una volta sola, altrimenti compaiono voci identiche.
    items = []
    visti = set()
    for riga in item_righe:
        item_no = _testo(riga.get("item"))
        if not item_no or item_no in visti:
            continue
        visti.add(item_no)
        items.append(
            {
                "item_no": item_no[:_MAX_ITEM_NO],
                "descrizione": _testo(riga.get("descrizione"))[:_MAX_DESCRIZIONE],
            }
        )

    warning = None
    if not testata_righe and not items:
        warning = "Commessa non trovata in Business Central: alcuni campi sono da compilare."
    return testata, items, warning


def dati_precompilati(job, user, bc=None):
    """Valori proposti per un nuovo piano, più gli item selezionabili."""
    t = Testata.objects.get(job=job)
    bc_testata, items, warning = _dati_bc(job, bc=bc)

    # BC è la fonte per progetto e owner; per PO e cliente il sistema ha già il
    # dato e BC lo sovrascrive solo se valorizzato — la stessa regola del
    # controllo giornaliero: un valore vuoto in BC non cancella nulla. La sede
    # non arriva da BC: si sceglie fra gli stabilimenti in impostazioni, e si
    # propone quello dell'utente.
    campi = {
        "titolo": titolo_predefinito(t.job),
        "vendor": VENDOR,
        "job_no": t.job,
        "location": nome_stabilimento(user),
        "project": _testo(bc_testata.get("progetto")),
        "owner": _testo(bc_testata.get("owner")),
        "purchaser": _testo(bc_testata.get("purchaser")) or t.client,
        "po_no": _testo(bc_testata.get("po_cliente")) or t.po_no,
        "data": date.today().isoformat(),
        "prepared_by": nome_utente(user),
        # Senza una regola di calcolo restano da compilare a mano.
        "doc_no": "",
        "sheet": "",
        "dwg_no": "",
        "serial_no": "",
        "descrizione_item": "",
    }
    return {
        "data": campi,
        "items": items,
        "sedi": sedi_disponibili(),
        "bc_disponibile": warning is None,
        "warning": warning,
    }


def _clean_items(raw):
    """Item del payload, normalizzati e senza duplicati.

    Accetta sia stringhe sia oggetti ``{"item_no": …, "descrizione": …}``. La
    deduplicazione serve: il vincolo di unicità farebbe altrimenti esplodere la
    creazione con un 500 invece di un errore comprensibile.
    """
    if raw is None:
        raise ValueError("Seleziona almeno un item.")
    if not isinstance(raw, (list, tuple)):
        raise ValueError("Elenco item non valido.")
    if len(raw) > MAX_ITEMS:
        raise ValueError("Troppi item selezionati.")

    items = []
    visti = set()
    for voce in raw:
        if isinstance(voce, dict):
            item_no = str(voce.get("item_no") or "").strip()
            descrizione = str(voce.get("descrizione") or "").strip()
        elif isinstance(voce, str):
            item_no, descrizione = voce.strip(), ""
        else:
            raise ValueError("Elenco item non valido.")
        if not item_no or item_no in visti:
            continue
        visti.add(item_no)
        items.append(
            {
                "item_no": item_no[:_MAX_ITEM_NO],
                "descrizione": descrizione[:_MAX_DESCRIZIONE],
            }
        )

    if not items:
        raise ValueError("Seleziona almeno un item.")
    return items


def _valida_location(nome):
    """La sede deve essere una di quelle in impostazioni.

    Il campo è un menù a scelta, quindi un valore fuori elenco vuol dire client
    manomesso o sede cancellata mentre il modal era aperto: meglio un errore
    leggibile che un piano con una sede che non esiste.
    """
    if nome and not Stabilimento.objects.filter(nome=nome).exists():
        raise ValueError("Sede non valida: scegline una fra quelle in impostazioni.")


def create_piano(job, data, user):
    t = Testata.objects.get(job=job)
    items = _clean_items(data.get("items"))

    campi = _clean_qcp_fields(data)
    campi["data"] = _parse_date(campi.get("data"))
    for chiave, valore in campi.items():
        if chiave != "data" and valore is None:
            campi[chiave] = ""
    _valida_location((campi.get("location") or "").strip())

    piano = QualityControlPlan(testata=t, prepared_by_user=user, **campi)
    if not piano.prepared_by.strip():
        piano.prepared_by = nome_utente(user)
    # Titolo svuotato dall'utente: torna quello proposto, così il piano ha
    # comunque un nome con cui comparire in elenco.
    if not piano.titolo.strip():
        piano.titolo = titolo_predefinito(t.job)

    with transaction.atomic():
        piano.full_clean(exclude=["prepared_by_user"])
        piano.save()
        QualityControlPlanItem.objects.bulk_create(
            [
                QualityControlPlanItem(piano=piano, ordine=ordine, **item)
                for ordine, item in enumerate(items)
            ]
        )
    return piano


def serialize_piano(piano):
    items = list(piano.items.all())
    return {
        "id": piano.pk,
        "job_no": piano.testata_id,
        "titolo": piano.titolo,
        "vendor": VENDOR,
        "doc_no": piano.doc_no,
        "location": piano.location,
        "sheet": piano.sheet,
        "project": piano.project,
        "dwg_no": piano.dwg_no,
        "owner": piano.owner,
        "po_no": piano.po_no,
        "data": piano.data.isoformat() if piano.data else None,
        "data_display": format_display_date(piano.data) if piano.data else "",
        "purchaser": piano.purchaser,
        "descrizione_item": piano.descrizione_item,
        "serial_no": piano.serial_no,
        "prepared_by": piano.prepared_by,
        "items": [{"item_no": i.item_no, "descrizione": i.descrizione} for i in items],
        "items_label": " / ".join(i.item_no for i in items),
        "percentuale": PERCENTUALE_INIZIALE,
    }


def list_piani(job):
    Testata.objects.get(job=job)  # 404 coerente sulle commesse inesistenti
    qs = QualityControlPlan.objects.filter(testata_id=job).prefetch_related("items")
    return [serialize_piano(p) for p in qs]
