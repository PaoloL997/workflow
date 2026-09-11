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
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, IntegerField, Max, OuterRef, Prefetch, Subquery
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from ..date_fmt import format_display_date
from ..models import (
    AttivitaQCP,
    EsitoFirma,
    PuntoIntervento,
    QualityControlPlan,
    QualityControlPlanAgency,
    QualityControlPlanCode,
    QualityControlPlanInterventionPoint,
    QualityControlPlanItem,
    QualityControlPlanSection,
    QualityControlPlanSignature,
    QualityControlPlanSpec,
    QualityControlPlanStep,
    Stabilimento,
    Testata,
)
from .commesse import _parse_date
from .revisione_label import lettera_a_numero, numero_a_lettera

logger = logging.getLogger(__name__)

# Unica costante di testata: uguale su ogni piano, quindi non è una colonna.
VENDOR = "Brembana & Rolle"

# Titolo proposto: numero di commessa, "QCP" e una lettera progressiva.
TITOLO_SUFFISSO = "QCP"

MAX_ITEMS = 200

_MAX_ITEM_NO = 200
_MAX_DESCRIZIONE = 300

# Dicitura dei requisiti sì/no nel documento stampato.
REQUIRED = "REQUIRED"
NOT_REQUIRED = "NOT REQUIRED"

_QCP_FLAGS = ("asme_stamp", "national_board", "lethal_service", "h2s_service")

# Codici proposti nella tendina "Applicable codes" (foglio DATI, K2:K15). Sono un
# suggerimento, non un vincolo: nell'Excel la cella è libera, quindi anche un
# codice fuori elenco va accettato. Per questo non sono ``choices`` sul modello.
CODICI_PROPOSTI = (
    "ASME VIII Div.2 Cl.1 Ed 2023",
    "ASME VIII Div.1 Ed 2025",
    "ASME V Ed 2023",
    "ASME V Ed 2019",
    "ASME II/A Ed 2021",
    "ASME II/A Ed 2019",
    "ASME II/C Ed 2021",
    "ASME II/C Ed 2019",
    "ASME IX Ed 2021",
    "ASME IX Ed 2019",
    "PED 2014/68/EU",
    'TEMA "R" 11th Edition',
    "API 660 9TH Ed.2015",
    "API 934-C",
)

# Primo ente di ispezione proposto: il vendor stesso, con la sigla del documento.
ENTE_PREDEFINITO = "B&R"

# Righe massime per lista: quelle che l'Excel ha a disposizione (DATI D2:D13,
# F2:F13 e D16:D21).
MAX_CODES = 12
MAX_SPECS = 12
MAX_AGENCIES = 6


@dataclass(frozen=True)
class ListaTestata:
    """Una delle liste di testata: codici applicabili, spec del cliente, enti.

    Si comportano tutte allo stesso modo — testo libero, in ordine, senza
    doppioni e fino a un massimo — e cambiano solo per modello, colonna e limite.
    Descriverle qui permette una sola pulizia e una sola serializzazione per
    tutte e tre, invece di tre copie.
    """

    chiave: str  # nome nel payload e nella risposta, e related_name sul piano
    modello: type
    campo: str  # colonna che contiene il valore
    massimo: int
    nome: str  # come la lista si chiama nei messaggi all'utente

    @property
    def lunghezza(self):
        return self.modello._meta.get_field(self.campo).max_length


LISTE = (
    ListaTestata("codes", QualityControlPlanCode, "codice", MAX_CODES, "Codici applicabili"),
    ListaTestata("specs", QualityControlPlanSpec, "spec", MAX_SPECS, "Spec del cliente"),
    ListaTestata("agencies", QualityControlPlanAgency, "nome", MAX_AGENCIES, "Enti di ispezione"),
)

# Campi scrivibili dal client. Vendor e Job n. non ci sono di proposito: sono
# costante e derivato, e vanno ignorati anche se il client li manda.
_QCP_FIELDS = {
    *_QCP_FLAGS,
    "rev_no",
    "mdmt",
    "notification_advice_time",
    "dwg_base",
    "serial_base",
    "foglio_dwg",
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


def _parse_rev_no(valore):
    """Rev n. dal payload: vuoto vale 0, il resto deve essere un intero."""
    if valore is None or (isinstance(valore, str) and not valore.strip()):
        return 0
    if isinstance(valore, bool):  # True è un int per Python, non per l'utente
        raise ValueError("Rev n. non valido.")
    if isinstance(valore, int):
        return valore
    if isinstance(valore, str) and valore.strip().isdecimal():
        return int(valore.strip())
    raise ValueError("Rev n. non valido.")


def _parse_flag(chiave, valore):
    """Un requisito sì/no: il client manda un booleano, assente vale no."""
    if valore is None:
        return False
    if isinstance(valore, bool):
        return valore
    nome = QualityControlPlan._meta.get_field(chiave).verbose_name
    raise ValueError(f"Valore non valido per {nome}.")


def etichetta_requisito(valore):
    return REQUIRED if valore else NOT_REQUIRED


def mdmt_senza_unita(valore):
    """MDMT senza l'unità, se l'utente l'ha scritta: "-25 °C" e "-25°c" → "-25".

    Serve a mostrare numero e unità con pesi diversi, e a non ripetere l'unità.
    """
    testo = (valore or "").strip()
    if testo.replace(" ", "").lower().endswith("°c"):
        testo = testo[: testo.rindex("°")].strip()
    return testo


def mdmt_con_unita(valore):
    """MDMT da mostrare, con l'unità: "-25" diventa "-25 °C", vuoto resta vuoto."""
    numero = mdmt_senza_unita(valore)
    return f"{numero} °C" if numero else ""


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


def iniziali(nome):
    """Iniziali per l'avatar: nome e cognome, "Paolo Litta" → "PL"; vuoto resta vuoto."""
    parole = (nome or "").split()
    if not parole:
        return ""
    lettere = parole[0][0] + (parole[-1][0] if len(parole) > 1 else "")
    return lettere.upper()


def intestazione_items(codici):
    """Gli item come si leggono nell'intestazione: "ITEM 1E/2E-1201".

    I codici di Business Central contengono già la parola ("ITEM 2253E001"):
    in quel caso non la si ripete.
    """
    testo = " / ".join(codici)
    if not testo:
        return ""
    return testo if testo.lower().startswith("item") else f"ITEM {testo}"


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
        # Doc n., Dwg n. e Serial n. vuoti vuol dire "calcolati": si scrivono
        # solo per forzare un numero diverso.
        "doc_no": "",
        "sheet": "",
        "dwg_no": "",
        "serial_no": "",
        "descrizione_item": "",
        # BC non ha né disegno né matricola: i componenti della numerazione e i
        # dati tecnici partono vuoti, e i requisiti da "non richiesto".
        "dwg_base": "",
        "serial_base": "",
        "foglio_dwg": "",
        "rev_no": 0,
        "mdmt": "",
        "notification_advice_time": "",
        **dict.fromkeys(_QCP_FLAGS, False),
        # Nemmeno codici, spec ed enti hanno una fonte in BC: si propone solo il
        # vendor come primo ente, il resto si compila a mano.
        "codes": [],
        "specs": [],
        "agencies": [ENTE_PREDEFINITO],
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


def _clean_lista(lista, raw):
    """Valori di una lista di testata, ripuliti, in ordine e senza doppioni.

    Le liste sono facoltative: assente o vuota va bene, a differenza degli item.
    I doppioni si scartano come per gli item, perché il vincolo di unicità
    trasformerebbe un valore ripetuto in un 500. Righe vuote e doppioni non
    contano per il massimo: conta quello che resta. Un valore troppo lungo si
    rifiuta invece di troncarlo, perché due valori troncati potrebbero diventare
    uguali e tornare a scontrarsi col vincolo.
    """
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise ValueError(f"{lista.nome}: elenco non valido.")

    valori = []
    visti = set()
    for voce in raw:
        if voce is None:
            continue
        if not isinstance(voce, str):
            raise ValueError(f"{lista.nome}: elenco non valido.")
        valore = voce.strip()
        if not valore or valore in visti:
            continue
        if len(valore) > lista.lunghezza:
            raise ValueError(f"{lista.nome}: al massimo {lista.lunghezza} caratteri per riga.")
        visti.add(valore)
        valori.append(valore)
        # Ci si ferma al primo in più: inutile ripulire il resto di un elenco
        # che va comunque rifiutato.
        if len(valori) > lista.massimo:
            raise ValueError(f"{lista.nome}: al massimo {lista.massimo}.")
    return valori


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
    liste = {lista.chiave: _clean_lista(lista, data.get(lista.chiave)) for lista in LISTE}

    campi = _clean_qcp_fields(data)
    campi["data"] = _parse_date(campi.get("data"))
    if "rev_no" in campi:
        campi["rev_no"] = _parse_rev_no(campi["rev_no"])
    for flag in _QCP_FLAGS:
        if flag in campi:
            campi[flag] = _parse_flag(flag, campi[flag])
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
        for lista in LISTE:
            lista.modello.objects.bulk_create(
                [
                    lista.modello(piano=piano, ordine=ordine, **{lista.campo: valore})
                    for ordine, valore in enumerate(liste[lista.chiave])
                ]
            )
    return piano


def serialize_piano(piano):
    """Il piano come lo si mostra.

    ``doc_no``, ``dwg_no`` e ``serial_no`` sono i numeri effettivi: quello
    scritto a mano se c'è, altrimenti quello calcolato. I ``*_calcolato``
    restano esposti per far vedere cosa darebbe la regola.
    """
    items = list(piano.items.all())
    return {
        "id": piano.pk,
        "job_no": piano.testata_id,
        "titolo": piano.titolo,
        "vendor": VENDOR,
        "doc_no": piano.doc_no_effettivo,
        "doc_no_calcolato": piano.doc_no_calcolato,
        "location": piano.location,
        "sheet": piano.sheet,
        "project": piano.project,
        "dwg_no": piano.dwg_no_effettivo,
        "dwg_no_calcolato": piano.dwg_no_calcolato,
        "serial_no": piano.serial_no_effettivo,
        "serial_no_calcolato": piano.serial_no_calcolato,
        "dwg_base": piano.dwg_base,
        "serial_base": piano.serial_base,
        "foglio_dwg": piano.foglio_dwg,
        "rev_no": piano.rev_no,
        "mdmt": piano.mdmt,
        "mdmt_display": mdmt_con_unita(piano.mdmt),
        "mdmt_numero": mdmt_senza_unita(piano.mdmt),
        "notification_advice_time": piano.notification_advice_time,
        **{flag: getattr(piano, flag) for flag in _QCP_FLAGS},
        **{f"{flag}_label": etichetta_requisito(getattr(piano, flag)) for flag in _QCP_FLAGS},
        "requisiti_richiesti": sum(bool(getattr(piano, flag)) for flag in _QCP_FLAGS),
        "owner": piano.owner,
        "po_no": piano.po_no,
        "data": piano.data.isoformat() if piano.data else None,
        "data_display": format_display_date(piano.data) if piano.data else "",
        "purchaser": piano.purchaser,
        "descrizione_item": piano.descrizione_item,
        "prepared_by": piano.prepared_by,
        "prepared_by_iniziali": iniziali(piano.prepared_by),
        "items": [{"item_no": i.item_no, "descrizione": i.descrizione} for i in items],
        "items_label": " / ".join(i.item_no for i in items),
        "items_intestazione": intestazione_items([i.item_no for i in items]),
        # Codici, spec ed enti nell'ordine salvato: per gli enti è la posizione
        # della colonna nel corpo del piano.
        **{
            lista.chiave: [
                getattr(riga, lista.campo) for riga in getattr(piano, lista.chiave).all()
            ]
            for lista in LISTE
        },
        # Punti firmati sui punti da firmare (vedi ``avanzamento``).
        **_avanzamento_in_elenco(piano),
    }


# Quello che serve per mostrare un piano: una query per relazione, qualunque sia
# il numero di righe o di piani.
_RELAZIONI = ("items", *(lista.chiave for lista in LISTE))


def get_piano(job, pk):
    """Un piano della commessa, con item, codici, spec ed enti già caricati e i
    conteggi delle firme per la percentuale.

    Come per l'eliminazione, il piano si cerca dentro la commessa dell'URL: un
    id di un'altra commessa risponde come inesistente.
    """
    piani = _con_avanzamento(QualityControlPlan.objects.prefetch_related(*_RELAZIONI))
    return piani.get(pk=pk, testata_id=job)


def delete_piano(job, pk):
    """Elimina un piano con tutto ciò che gli appartiene: item, codici, spec, enti, corpo.

    Il piano si cerca dentro la commessa dell'URL: un id che appartiene a
    un'altra commessa risponde come inesistente invece di cancellarla lì. Un
    piano con firme registrate, anche annullate, non si elimina: le firme sono
    uno storico da conservare.
    """
    piano = QualityControlPlan.objects.get(pk=pk, testata_id=job)
    if _ha_firme(punto__step__sezione__piano=piano):
        raise ValueError(
            "Il piano ha firme registrate: non si elimina, perché lo storico delle firme "
            "va conservato."
        )
    piano.delete()


def list_piani(job):
    """I piani della commessa, con la percentuale calcolata dal database.

    Item, codici, spec ed enti con una query per relazione, e i conteggi delle
    firme dentro la query dei piani: lo stesso numero di query con uno o con
    cento piani, qualunque sia il numero di punti.
    """
    Testata.objects.get(job=job)  # 404 coerente sulle commesse inesistenti
    qs = QualityControlPlan.objects.filter(testata_id=job).prefetch_related(*_RELAZIONI)
    return [serialize_piano(p) for p in _con_avanzamento(qs)]


# ─────────────────────────────────────────────
# CORPO DEL PIANO: sezioni, step e punti d'intervento
# ─────────────────────────────────────────────

# Campi dello step copiati dal catalogo quando lo si inserisce (lo snapshot); il
# riferimento documentale si aggiunge già risolto per il piano.
CAMPI_DAL_CATALOGO = (
    "descrizione",
    "test_inspection",
    "acceptance_criteria",
    "documento_richiesto",
    "tecnica",
)
CAMPI_SNAPSHOT = (*CAMPI_DAL_CATALOGO, "reference_doc", "report_no")
# Campi che l'utente può correggere su uno step già inserito.
CAMPI_STEP_MODIFICABILI = (*CAMPI_SNAPSHOT, "extent", "remarks")

# Attività inseribili in una volta: più dell'intero catalogo non ha senso.
MAX_STEP_PER_INSERIMENTO = 300


def get_piano_corpo(job, pk):
    """Il piano della commessa indicata: un id di un'altra commessa non esiste."""
    return QualityControlPlan.objects.get(pk=pk, testata_id=job)


def get_sezione(job, pk, sid):
    """Una sezione, solo se appartiene al piano e il piano alla commessa."""
    return QualityControlPlanSection.objects.select_related("piano").get(
        pk=sid, piano_id=pk, piano__testata_id=job
    )


def get_step(job, pk, stid):
    """Uno step, solo se appartiene al piano e il piano alla commessa."""
    return QualityControlPlanStep.objects.select_related("sezione__piano").get(
        pk=stid, sezione__piano_id=pk, sezione__piano__testata_id=job
    )


def _id(valore, cosa):
    """Un id arrivato dal client: intero positivo, non un booleano."""
    if isinstance(valore, bool):
        raise ValueError(f"{cosa} non valido.")
    try:
        numero = int(valore)
    except (TypeError, ValueError):
        raise ValueError(f"{cosa} non valido.") from None
    if numero <= 0:
        raise ValueError(f"{cosa} non valido.")
    return numero


def _etichetta_step(campo):
    return str(QualityControlPlanStep._meta.get_field(campo).verbose_name)


def _testo_step(campo, valore):
    """Un testo per lo step, ripulito e dentro la lunghezza della colonna."""
    if valore is None:
        return ""
    if not isinstance(valore, str):
        raise ValueError(f"{_etichetta_step(campo)}: deve essere un testo.")
    testo = valore.strip()
    massimo = QualityControlPlanStep._meta.get_field(campo).max_length
    if len(testo) > massimo:
        raise ValueError(f"{_etichetta_step(campo)}: al massimo {massimo} caratteri.")
    return testo


def _parse_extent(valore):
    """Extent come frazione fra 0 e 1 (0.1 = 10%), con al massimo tre decimali.

    Si accetta un formato solo. Percentuale e frazione non si distinguono per i
    valori fino a 1 — "1" è 100% o 1%? — quindi accettarle entrambe vorrebbe
    dire indovinare. Se l'interfaccia mostra percentuali, converte lei.
    """
    errore = "Extent non valido: indica una frazione fra 0 e 1 (0.1 = 10%)."
    if isinstance(valore, bool) or valore is None:
        raise ValueError(errore)
    try:
        numero = Decimal(str(valore).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(errore) from None
    if not numero.is_finite() or numero < 0 or numero > 1:
        raise ValueError(errore)
    if numero.normalize().as_tuple().exponent < -3:
        raise ValueError("Extent: al massimo tre decimali.")
    return numero.quantize(Decimal("0.001"))


def _prossimo_ordine(qs):
    """Posizione in coda: dopo la più alta, anche se nel mezzo ci sono buchi."""
    massimo = qs.aggregate(massimo=Max("ordine"))["massimo"]
    return 0 if massimo is None else massimo + 1


def _parse_ordine(valore, quanti):
    """Posizione (da 0) fra ``quanti`` elementi."""
    if isinstance(valore, bool):
        raise ValueError("Ordine non valido.")
    try:
        ordine = int(valore)
    except (TypeError, ValueError):
        raise ValueError("Ordine non valido.") from None
    if not 0 <= ordine < quanti:
        raise ValueError(f"Ordine non valido: da 0 a {quanti - 1}.")
    return ordine


def riordina(oggetti, ordine):
    """Mette sezioni o step fratelli nell'ordine dato, con un solo UPDATE.

    ``oggetti`` sono tutti i fratelli (le sezioni di un piano o gli step di una
    sezione); ``ordine`` è l'elenco dei loro id nella nuova sequenza, ciascuno
    una volta sola. Un elenco parziale si rifiuta: lascerebbe posizioni doppie.
    """
    oggetti = list(oggetti)
    per_id = {oggetto.pk: oggetto for oggetto in oggetti}
    if not isinstance(ordine, (list, tuple)):
        raise ValueError("Ordine non valido.")
    ids = [_id(pk, "Elemento") for pk in ordine]
    if len(ids) != len(per_id) or set(ids) != set(per_id):
        raise ValueError("L'ordine deve elencare tutti gli elementi, una volta sola.")
    if not oggetti:
        return
    for posizione, pk in enumerate(ids):
        per_id[pk].ordine = posizione
    type(oggetti[0]).objects.bulk_update(oggetti, ["ordine"])


def _fratelli(oggetto):
    if isinstance(oggetto, QualityControlPlanSection):
        return QualityControlPlanSection.objects.filter(piano_id=oggetto.piano_id)
    return QualityControlPlanStep.objects.filter(sezione_id=oggetto.sezione_id)


def sposta(oggetto, ordine):
    """Porta una sezione o uno step alla posizione ``ordine`` (da 0) fra i fratelli."""
    fratelli = list(_fratelli(oggetto))
    posizione = _parse_ordine(ordine, len(fratelli))
    ids = [fratello.pk for fratello in fratelli if fratello.pk != oggetto.pk]
    ids.insert(posizione, oggetto.pk)
    riordina(fratelli, ids)
    oggetto.ordine = posizione


def _rinumera(fratelli):
    """Dopo una cancellazione le posizioni tornano 0, 1, 2… senza buchi."""
    fratelli = list(fratelli)
    riordina(fratelli, [fratello.pk for fratello in fratelli])


def _titolo_sezione(titolo):
    if not isinstance(titolo, str) or not titolo.strip():
        raise ValueError("Il titolo della sezione è obbligatorio.")
    testo = titolo.strip()
    massimo = QualityControlPlanSection._meta.get_field("titolo").max_length
    if len(testo) > massimo:
        raise ValueError(f"Titolo della sezione: al massimo {massimo} caratteri.")
    return testo


def crea_sezione(piano, titolo, ordine=None):
    """Nuova sezione del piano: in coda, o alla posizione ``ordine`` (da 0)."""
    titolo = _titolo_sezione(titolo)
    with transaction.atomic():
        sezione = QualityControlPlanSection.objects.create(
            piano=piano, titolo=titolo, ordine=_prossimo_ordine(piano.sections.all())
        )
        if ordine is not None:
            sposta(sezione, ordine)
    return sezione


def aggiorna_sezione(sezione, dati):
    """Rinomina (``titolo``) e/o sposta (``ordine``, da 0) una sezione."""
    if not isinstance(dati, dict) or not ({"titolo", "ordine"} & set(dati)):
        raise ValueError("Indica il nuovo titolo o la nuova posizione della sezione.")
    with transaction.atomic():
        if "titolo" in dati:
            sezione.titolo = _titolo_sezione(dati["titolo"])
            sezione.save(update_fields=["titolo"])
        if "ordine" in dati:
            sposta(sezione, dati["ordine"])
    return sezione


def elimina_sezione(sezione):
    """Elimina una sezione con i suoi step; le altre si ricompattano.

    Una sezione con step firmati (anche solo firme annullate) non si elimina:
    lo storico delle firme va conservato.
    """
    if _ha_firme(punto__step__sezione=sezione):
        raise ValueError(
            f'La sezione "{sezione.titolo}" ha step con firme registrate: non si elimina, '
            "perché lo storico delle firme va conservato."
        )
    with transaction.atomic():
        piano_id = sezione.piano_id
        sezione.delete()
        _rinumera(QualityControlPlanSection.objects.filter(piano_id=piano_id))


def _attivita_attive(ids):
    """Le attività attive del catalogo con questi id, nell'ordine dato.

    Lo stesso id può ripetersi (la stessa prova in due punti della sezione).
    Se uno manca o è disattivato non si inserisce nulla.
    """
    if not isinstance(ids, (list, tuple)) or not ids:
        raise ValueError("Indica almeno un'attività del catalogo.")
    if len(ids) > MAX_STEP_PER_INSERIMENTO:
        raise ValueError(f"Al massimo {MAX_STEP_PER_INSERIMENTO} attività per volta.")
    puliti = [_id(pk, "Attività") for pk in ids]
    trovate = AttivitaQCP.objects.filter(attivo=True).in_bulk(puliti)
    mancanti = [str(pk) for pk in dict.fromkeys(puliti) if pk not in trovate]
    if mancanti:
        raise ValueError(f"Attività non trovate o disattivate nel catalogo: {', '.join(mancanti)}.")
    return [trovate[pk] for pk in puliti]


def _snapshot_da_catalogo(attivita, piano):
    return {
        **{campo: getattr(attivita, campo) for campo in CAMPI_DAL_CATALOGO},
        "reference_doc": attivita.risolvi_reference_doc(piano),
    }


def _valori_step_manuale(dati):
    """Uno step scritto a mano: i testi dello snapshot, remarks ed extent."""
    if not isinstance(dati, dict):
        raise ValueError("Per uno step senza catalogo servono i dati, a partire dalla descrizione.")
    valori = {campo: _testo_step(campo, dati.get(campo)) for campo in (*CAMPI_SNAPSHOT, "remarks")}
    if not valori["descrizione"]:
        raise ValueError("La descrizione dello step è obbligatoria.")
    if "extent" in dati:
        valori["extent"] = _parse_extent(dati["extent"])
    return valori


def _crea_punti(steps, piano):
    """Un punto "-" per ogni ente del piano su ciascuno step.

    Uno step non resta mai senza punti: l'interfaccia conta su una riga per
    ente. Un piano senza enti dà semplicemente step senza punti.
    """
    enti = list(piano.agencies.values_list("pk", flat=True))
    QualityControlPlanInterventionPoint.objects.bulk_create(
        [
            QualityControlPlanInterventionPoint(step=step, agency_id=ente)
            for step in steps
            for ente in enti
        ]
    )


def aggiungi_step(sezione, attivita_id=None, dati=None):
    """Nuovo step in coda alla sezione, dal catalogo o scritto a mano.

    Dal catalogo si copiano descrizione, test/inspection, acceptance criteria,
    documento richiesto e tecnica, più il riferimento documentale risolto per il
    piano; ``dati`` non serve. A mano, i valori arrivano da ``dati`` e la
    descrizione è obbligatoria. In entrambi i casi lo step nasce con un punto
    d'intervento "-" per ogni ente del piano.
    """
    piano = sezione.piano
    if attivita_id is not None:
        attivita = _attivita_attive([attivita_id])[0]
        valori = {"attivita": attivita, **_snapshot_da_catalogo(attivita, piano)}
    else:
        valori = _valori_step_manuale(dati)
    with transaction.atomic():
        step = QualityControlPlanStep.objects.create(
            sezione=sezione, ordine=_prossimo_ordine(sezione.steps.all()), **valori
        )
        _crea_punti([step], piano)
    return step


def aggiungi_step_multipli(sezione, attivita_ids):
    """Più attività del catalogo in coda alla sezione, nell'ordine passato.

    È il caso normale: nell'Excel le attività si inseriscono in sequenza, e
    l'utente ne sceglierà diverse insieme. Una sola transazione: o entrano
    tutte o nessuna.
    """
    attivita = _attivita_attive(attivita_ids)
    piano = sezione.piano
    with transaction.atomic():
        inizio = _prossimo_ordine(sezione.steps.all())
        steps = QualityControlPlanStep.objects.bulk_create(
            [
                QualityControlPlanStep(
                    sezione=sezione,
                    attivita=voce,
                    ordine=inizio + indice,
                    **_snapshot_da_catalogo(voce, piano),
                )
                for indice, voce in enumerate(attivita)
            ]
        )
        _crea_punti(steps, piano)
    return steps


def aggiorna_step(step, **campi):
    """Corregge uno step già inserito: snapshot, report n., extent e remarks.

    La correzione resta sullo step, il catalogo non si tocca. Campi diversi da
    questi si ignorano, così il client può rimandare lo step com'è arrivato.
    """
    modifiche = {}
    for campo, valore in campi.items():
        if campo not in CAMPI_STEP_MODIFICABILI:
            continue
        modifiche[campo] = (
            _parse_extent(valore) if campo == "extent" else _testo_step(campo, valore)
        )
    if not modifiche:
        raise ValueError("Nessun campo da modificare.")
    if "descrizione" in modifiche and not modifiche["descrizione"]:
        raise ValueError("La descrizione dello step è obbligatoria.")
    for campo, valore in modifiche.items():
        setattr(step, campo, valore)
    step.save(update_fields=list(modifiche))
    return step


def sposta_in_sezione(step, sezione, ordine=None):
    """Porta uno step in un'altra sezione dello stesso piano.

    Va alla posizione ``ordine`` (da 0) della sezione di arrivo, o in coda se
    manca. Entrambe le sezioni restano numerate 0, 1, 2… senza buchi: è il
    trascinamento fra sezioni dell'editor, fatto in una sola richiesta.
    """
    if sezione.piano_id != step.sezione.piano_id:
        raise ValueError("La sezione di destinazione non appartiene al piano di questo step.")
    if sezione.pk == step.sezione_id:
        if ordine is not None:
            sposta(step, ordine)
        return step
    with transaction.atomic():
        origine_id = step.sezione_id
        step.sezione = sezione
        step.ordine = _prossimo_ordine(sezione.steps.all())
        step.save(update_fields=["sezione", "ordine"])
        _rinumera(QualityControlPlanStep.objects.filter(sezione_id=origine_id))
        # In coda si ricompatta comunque la sezione di arrivo: _prossimo_ordine
        # dà il massimo più uno, anche se nel mezzo ci fossero buchi.
        arrivo = sezione.steps.count() - 1 if ordine is None else ordine
        sposta(step, arrivo)
    return step


def modifica_step(step, dati):
    """Correzioni (vedi ``aggiorna_step``) e/o spostamento di uno step.

    ``ordine`` sposta lo step (da 0) nella sua sezione; insieme a ``sezione``
    (l'id di una sezione dello stesso piano) lo porta in quella sezione, in coda
    se ``ordine`` manca. Tutto in una transazione: se lo spostamento fallisce,
    anche le correzioni vengono annullate.
    """
    if not isinstance(dati, dict):
        raise ValueError("Dati dello step non validi.")
    campi = {campo: valore for campo, valore in dati.items() if campo in CAMPI_STEP_MODIFICABILI}
    if not campi and "ordine" not in dati and "sezione" not in dati:
        raise ValueError("Nessun campo da modificare.")
    with transaction.atomic():
        if campi:
            aggiorna_step(step, **campi)
        if "sezione" in dati:
            try:
                sezione = QualityControlPlanSection.objects.get(
                    pk=_id(dati["sezione"], "Sezione"), piano_id=step.sezione.piano_id
                )
            except QualityControlPlanSection.DoesNotExist:
                raise ValueError("La sezione di destinazione non esiste in questo piano.") from None
            sposta_in_sezione(step, sezione, dati.get("ordine"))
        elif "ordine" in dati:
            sposta(step, dati["ordine"])
    return step


def elimina_step(step):
    """Elimina uno step; quelli dopo risalgono e la numerazione si ricalcola.

    Uno step con firme registrate (anche annullate) non si elimina: lo storico
    delle firme va conservato.
    """
    if _ha_firme(punto__step=step):
        raise ValueError(
            "Lo step ha firme registrate: non si elimina, perché lo storico delle firme "
            "va conservato."
        )
    with transaction.atomic():
        sezione_id = step.sezione_id
        step.delete()
        _rinumera(QualityControlPlanStep.objects.filter(sezione_id=sezione_id))


SEPARATORE_PUNTI = "/"
_STATI_PUNTO = tuple(
    codice for codice in PuntoIntervento.values if codice != PuntoIntervento.NON_COINVOLTO
)


def normalizza_punto(valore):
    """Il punto d'intervento come si salva, o ValueError col perché.

    Un ente può avere più stati insieme sullo stesso step: "R/SW" è review più
    spot witness. Si scrivono separati da "/", nell'ordine dato e senza
    ripetizioni; maiuscole e spazi non contano. "-" (non coinvolto) sta solo da
    solo: insieme a un altro stato si contraddirebbe.
    """
    ammessi = ", ".join(PuntoIntervento.values)
    errore = (
        f"Punto d'intervento non valido: {valore}. Ammessi: {ammessi}, anche più di uno "
        'separati da "/" (per esempio R/SW); "-" solo da solo.'
    )
    if not isinstance(valore, str):
        raise ValueError(errore)
    parti = [parte.strip().upper() for parte in valore.split(SEPARATORE_PUNTI)]
    if parti == [PuntoIntervento.NON_COINVOLTO]:
        return PuntoIntervento.NON_COINVOLTO.value
    if any(parte not in _STATI_PUNTO for parte in parti):
        raise ValueError(errore)
    return SEPARATORE_PUNTI.join(dict.fromkeys(parti))


def etichetta_punto(codice):
    """Descrizione di un punto, anche composto: "R/SW" → "Review + Spot witness"."""
    etichette = dict(PuntoIntervento.choices)
    return " + ".join(etichette.get(parte, parte) for parte in codice.split(SEPARATORE_PUNTI))


def imposta_punto(step, agency, punto):
    """Il punto d'intervento di un ente su uno step: uno o più stati, oppure "-".

    I valori ammessi sono quelli di ``normalizza_punto``. L'ente deve essere del
    piano dello step: un punto riferito all'ente di un altro piano è un errore,
    non un dato. Un punto con una firma valida non cambia: la firma attesta
    quel controllo, quindi prima va annullata.
    """
    if agency.piano_id != step.sezione.piano_id:
        raise ValueError(f'L\'ente "{agency.nome}" non appartiene al piano di questo step.')
    codice = normalizza_punto(punto)
    firmato = QualityControlPlanInterventionPoint.objects.filter(
        step=step, agency=agency, firme__annullata_il__isnull=True, firme__isnull=False
    ).exclude(punto=codice)
    if firmato.exists():
        raise ValueError(
            f'Il punto di "{agency.nome}" è già firmato: per cambiarlo annulla prima la firma.'
        )
    riga, _ = QualityControlPlanInterventionPoint.objects.update_or_create(
        step=step, agency=agency, defaults={"punto": codice}
    )
    return riga


def imposta_punti(step, valori):
    """Più punti dello stesso step, da ``[{"agency": id, "punto": "W"}, …]``.

    O si applicano tutti o nessuno: un ente sbagliato annulla anche gli altri.
    """
    if not isinstance(valori, list) or not valori:
        raise ValueError("Indica almeno un punto d'intervento.")
    richieste = []
    for voce in valori:
        if not isinstance(voce, dict):
            raise ValueError("Punti d'intervento non validi.")
        richieste.append((_id(voce.get("agency"), "Ente"), voce.get("punto")))
    enti = QualityControlPlanAgency.objects.in_bulk([agency_id for agency_id, _ in richieste])
    with transaction.atomic():
        for agency_id, punto in richieste:
            agency = enti.get(agency_id)
            if agency is None:
                raise ValueError(f"Ente {agency_id} non trovato.")
            imposta_punto(step, agency, punto)
    return step


def sincronizza_punti(piano):
    """Riallinea i punti d'intervento agli enti della copertina.

    Quando si aggiunge un ente, gli step esistenti ricevono il suo punto "-";
    quando lo si toglie, i punti rimasti senza ente spariscono. Va chiamata
    ovunque gli enti del piano cambiano. Restituisce quanti punti ha creato e
    quanti rimosso.
    """
    enti = list(piano.agencies.values_list("pk", flat=True))
    punti = QualityControlPlanInterventionPoint.objects.filter(step__sezione__piano=piano)
    with transaction.atomic():
        rimossi, _ = punti.exclude(agency_id__in=enti).delete()
        esistenti = set(punti.values_list("step_id", "agency_id"))
        steps = QualityControlPlanStep.objects.filter(sezione__piano=piano).values_list(
            "pk", flat=True
        )
        mancanti = [
            QualityControlPlanInterventionPoint(step_id=step_id, agency_id=ente)
            for step_id in steps
            for ente in enti
            if (step_id, ente) not in esistenti
        ]
        QualityControlPlanInterventionPoint.objects.bulk_create(mancanti)
    return {"creati": len(mancanti), "rimossi": rimossi}


def _serialize_step(step, numero):
    return {
        "id": step.pk,
        "numero": numero,
        "ordine": step.ordine,
        "attivita_id": step.attivita_id,
        **{campo: getattr(step, campo) for campo in CAMPI_SNAPSHOT},
        "extent": float(step.extent),
        "remarks": step.remarks,
        # Nell'ordine degli enti, cioè delle colonne del piano.
        "punti": [_serialize_punto(p) for p in step.punti.all()],
    }


def _serialize_punto(punto):
    """Un punto d'intervento con la sua firma valida (o ``None``).

    ``firme_registrate`` conta anche le annullate: dice se c'è uno storico da
    consultare. Firme e conteggio arrivano precaricati (``_punti_con_firme``).
    """
    firme = getattr(punto, "firme_valide", None)
    if firme is None:
        firme = list(_firme_valide().filter(punto=punto))
    return {
        "id": punto.pk,
        "agency_id": punto.agency_id,
        "punto": punto.punto,
        "firma": serialize_firma(firme[0]) if firme else None,
        "firme_registrate": getattr(punto, "firme_registrate", len(firme)),
    }


def _punti_con_firme(punti):
    """I punti con la firma valida precaricata (e il suo utente) e le firme contate."""
    return punti.annotate(firme_registrate=Count("firme")).prefetch_related(
        Prefetch("firme", queryset=_firme_valide(), to_attr="firme_valide")
    )


def serialize_corpo(piano):
    """Il corpo del piano: sezioni > step > punti, con la numerazione degli step.

    La numerazione non è una colonna: si conta qui, attraversando sezioni e step
    in ordine, come la formula dell'Excel, così resta giusta dopo ogni
    inserimento, spostamento o cancellazione. Il corpo si legge con un numero
    fisso di query (enti, sezioni, step, punti, firme valide), qualunque sia il
    numero di step o di firme.
    """
    enti = list(piano.agencies.all())
    punti = _punti_con_firme(
        QualityControlPlanInterventionPoint.objects.order_by("agency__ordine", "agency_id")
    )
    steps = QualityControlPlanStep.objects.order_by("ordine", "id").prefetch_related(
        Prefetch("punti", queryset=punti)
    )
    sezioni = piano.sections.order_by("ordine", "id").prefetch_related(
        Prefetch("steps", queryset=steps)
    )

    numero = 0
    risultato = []
    for indice, sezione in enumerate(sezioni, start=1):
        voci = []
        for step in sezione.steps.all():
            numero += 1
            voci.append(_serialize_step(step, numero))
        risultato.append(
            {
                "id": sezione.pk,
                "numero": indice,
                "titolo": sezione.titolo,
                "ordine": sezione.ordine,
                "steps": voci,
            }
        )
    return {
        "enti": [{"id": e.pk, "nome": e.nome, "posizione": i} for i, e in enumerate(enti, 1)],
        "punti_disponibili": [
            {"codice": codice, "etichetta": etichetta}
            for codice, etichetta in PuntoIntervento.choices
        ],
        "sezioni": risultato,
        "totale_step": numero,
    }


# Testi di uno step, nell'ordine in cui li mostra l'editor: la descrizione sulla
# prima riga dello step, gli altri sulla seconda.
CAMPI_DETTAGLIO_STEP = (
    "descrizione",
    "test_inspection",
    "reference_doc",
    "acceptance_criteria",
    "documento_richiesto",
    "tecnica",
    "report_no",
    "remarks",
)
# Sigla con cui ogni testo della seconda riga si presenta nell'editor.
_SIGLE_DETTAGLIO = {
    "test_inspection": "test",
    "reference_doc": "ref",
    "acceptance_criteria": "acc",
    "documento_richiesto": "doc",
    "tecnica": "tec",
    "report_no": "rep",
    "remarks": "rem",
}


# Etichette dei testi dello step nell'editor, in inglese come la pagina del piano.
# Quelle del modello (``_etichetta_step``) restano per l'admin e i messaggi del
# server.
_ETICHETTE_EDITOR = {
    "descrizione": "Description",
    "test_inspection": "Test / inspection",
    "reference_doc": "Reference doc.",
    "acceptance_criteria": "Acceptance criteria",
    "documento_richiesto": "Required document",
    "tecnica": "Technique",
    "report_no": "Report no.",
    "remarks": "Remarks",
}


def campi_dettaglio_step():
    """Nome, etichetta, sigla e lunghezza massima dei testi di uno step, per l'editor.

    La lunghezza è letta dal modello: il limite del campo nella pagina è sempre
    quello della colonna.
    """
    return [
        {
            "nome": campo,
            "etichetta": _ETICHETTE_EDITOR[campo],
            "sigla": _SIGLE_DETTAGLIO.get(campo, ""),
            "max_length": QualityControlPlanStep._meta.get_field(campo).max_length,
        }
        for campo in CAMPI_DETTAGLIO_STEP
    ]


def extent_in_percentuale(extent):
    """Extent come lo mostra l'editor: 0.125 → "12,5", 1 → "100".

    L'API resta in frazione (vedi ``_parse_extent``); la pagina mostra e
    accetta percentuali, con la virgola dei decimali, e converte lei.
    """
    testo = f"{Decimal(str(extent)) * 100:.1f}"
    return (testo[:-2] if testo.endswith(".0") else testo).replace(".", ",")


def stato_firma(punto):
    """Lo stato di firma di un punto serializzato, come lo legge chi scorre il piano.

    In inglese, come il resto della pagina: "" per "-" (niente da firmare), "to
    be signed", oppure esito, autore e data: "conforming, signed by Mario Rossi
    on 12 sep 2026 16:40".
    """
    if punto["punto"] == PuntoIntervento.NON_COINVOLTO:
        return ""
    firma = punto["firma"]
    if firma is None:
        return "to be signed"
    return (
        f"{firma['esito_etichetta'].lower()}, signed by {firma['utente']} "
        f"on {firma['firmato_il_display']}"
    )


def corpo_per_pagina(piano):
    """Il corpo come lo disegna la pagina del piano.

    Oltre a ``serialize_corpo``, ogni step ha:

    - ``celle``: una per ente della copertina, nel suo ordine, col punto
      (codice, id, firma valida) e la sua descrizione, compreso lo stato di
      firma. Un ente senza punto sullo step (non dovrebbe capitare: vedi
      ``sincronizza_punti``) mostra "-" invece di far scivolare le colonne;
    - ``testo_descrizione`` e ``dettagli``: i testi dello step
      (``campi_dettaglio_step``) col valore; la descrizione sta sulla prima
      riga, gli altri sulla seconda;
    - ``extent_percentuale``: l'extent come lo mostra la pagina.

    Ogni sezione conta i suoi punti da firmare e firmati, con la percentuale
    (``None`` se non ha punti da firmare), e ``avanzamento`` è quello del piano:
    gli stessi numeri di ``avanzamento(piano)``, contati sui punti già letti
    invece che con altre query. ``ente_caratteri`` è la lunghezza del nome
    d'ente più lungo.

    ``prototipo_step`` è uno step vuoto con le stesse chiavi: il modello da cui
    la pagina crea le righe nuove, così il markup è uno solo.
    """
    corpo = serialize_corpo(piano)
    campi = campi_dettaglio_step()
    vuoto = {"id": "", "punto": PuntoIntervento.NON_COINVOLTO, "firma": None, "firme_registrate": 0}

    def celle(punti):
        per_ente = {punto["agency_id"]: punto for punto in punti}
        risultato = []
        for ente in corpo["enti"]:
            punto = per_ente.get(ente["id"], vuoto)
            risultato.append(
                {
                    "ente": ente,
                    **punto,
                    "etichetta": etichetta_punto(punto["punto"]),
                    "stato_firma": stato_firma(punto),
                }
            )
        return risultato

    def testi(step):
        valori = [{**campo, "valore": step.get(campo["nome"], "")} for campo in campi]
        return {
            "testo_descrizione": next(v for v in valori if v["nome"] == "descrizione"),
            "dettagli": [v for v in valori if v["nome"] != "descrizione"],
        }

    def conta(steps):
        punti = [
            p for s in steps for p in s["punti"] if p["punto"] != PuntoIntervento.NON_COINVOLTO
        ]
        return len(punti), sum(p["firma"] is not None for p in punti)

    totale_piano = firmati_piano = 0
    for sezione in corpo["sezioni"]:
        for step in sezione["steps"]:
            step["celle"] = celle(step["punti"])
            step.update(testi(step))
            step["extent_percentuale"] = extent_in_percentuale(step["extent"])
        totale, firmati = conta(sezione["steps"])
        sezione.update(
            {
                "punti_da_firmare": totale,
                "punti_firmati": firmati,
                "percentuale": percentuale_firmati(firmati, totale) if totale else None,
            }
        )
        totale_piano += totale
        firmati_piano += firmati
    corpo["avanzamento"] = {
        "totale": totale_piano,
        "firmati": firmati_piano,
        "da_firmare": totale_piano - firmati_piano,
        "percentuale": percentuale_firmati(firmati_piano, totale_piano),
        "completo": bool(totale_piano) and firmati_piano == totale_piano,
    }
    # Caratteri del nome d'ente più lungo: le colonne dei punti si allargano
    # quanto basta a mostrarlo per intero.
    corpo["ente_caratteri"] = max((len(ente["nome"]) for ente in corpo["enti"]), default=0)
    corpo["esiti_firma"] = [
        {"codice": codice, "etichetta": etichetta} for codice, etichetta in EsitoFirma.choices
    ]
    corpo["prototipo_step"] = {
        "celle": celle([]),
        **testi({}),
        "extent_percentuale": extent_in_percentuale(1),
    }
    return corpo


# ─────────────────────────────────────────────
# FIRME DEI PUNTI D'INTERVENTO E AVANZAMENTO
# Firma elettronica semplice: l'utente autenticato dichiara che il controllo è
# avvenuto e si registra chi, con quale esito e quando (vedi il modello
# QualityControlPlanSignature, che è append-only).
# ─────────────────────────────────────────────

_MAX_TESTO_FIRMA = 2000


def _firme_valide():
    return QualityControlPlanSignature.objects.filter(annullata_il__isnull=True).select_related(
        "utente"
    )


def _firma_valida():
    """Condizione "il punto ha una firma valida", dentro una query sui punti."""
    return Exists(
        QualityControlPlanSignature.objects.filter(punto=OuterRef("pk"), annullata_il__isnull=True)
    )


def _ha_firme(**filtro):
    """Se esistono firme, anche annullate: le cose che le contengono non si cancellano."""
    return QualityControlPlanSignature.objects.filter(**filtro).exists()


def percentuale_firmati(firmati, totale):
    """Percentuale intera, per difetto: 100 solo quando è firmato tutto. Senza punti, 0."""
    return firmati * 100 // totale if totale else 0


def _con_avanzamento(piani):
    """I piani con ``punti_da_firmare`` e ``punti_firmati``, contati dal database.

    Due subquery dentro la query dei piani: nessuna query in più, qualunque sia
    il numero di piani o di punti.
    """
    punti = (
        QualityControlPlanInterventionPoint.objects.filter(step__sezione__piano=OuterRef("pk"))
        .exclude(punto=PuntoIntervento.NON_COINVOLTO)
        .order_by()
        .values("step__sezione__piano")
    )

    def conta(qs):
        return Coalesce(
            Subquery(qs.annotate(n=Count("pk")).values("n")[:1], output_field=IntegerField()), 0
        )

    return piani.annotate(
        punti_da_firmare=conta(punti), punti_firmati=conta(punti.filter(_firma_valida()))
    )


def _avanzamento_in_elenco(piano):
    """Percentuale e conteggi per l'elenco piani: dalle annotazioni se ci sono."""
    if hasattr(piano, "punti_da_firmare"):
        totale, firmati = piano.punti_da_firmare, piano.punti_firmati
    else:  # un piano appena creato, senza annotazioni
        conti = avanzamento(piano)
        totale, firmati = conti["totale"], conti["firmati"]
    return {
        "percentuale": percentuale_firmati(firmati, totale),
        "punti_da_firmare": totale,
        "punti_firmati": firmati,
    }


def avanzamento(piano):
    """Quanto del piano è firmato.

    Da firmare sono i punti d'intervento diversi da "-", cioè con un ente
    coinvolto; firmati quelli con una firma valida. I "-" restano fuori: sulla
    26026, 534 punti su 672. La percentuale è intera e per difetto, 0 per un
    piano senza punti. ``enti`` è il dettaglio per ente, nell'ordine delle
    colonne. Tre query (totali, firmati, enti), qualunque sia il piano.
    """
    da_firmare = (
        QualityControlPlanInterventionPoint.objects.filter(step__sezione__piano=piano)
        .exclude(punto=PuntoIntervento.NON_COINVOLTO)
        .order_by()
    )
    totali = dict(da_firmare.values_list("agency_id").annotate(n=Count("pk")))
    firmati = dict(
        da_firmare.filter(_firma_valida()).values_list("agency_id").annotate(n=Count("pk"))
    )
    enti = []
    for posizione, ente in enumerate(piano.agencies.all(), start=1):
        totale_ente, firmati_ente = totali.get(ente.pk, 0), firmati.get(ente.pk, 0)
        enti.append(
            {
                "id": ente.pk,
                "nome": ente.nome,
                "posizione": posizione,
                "totale": totale_ente,
                "firmati": firmati_ente,
                "percentuale": percentuale_firmati(firmati_ente, totale_ente),
            }
        )
    totale, n_firmati = sum(totali.values()), sum(firmati.values())
    return {
        "totale": totale,
        "firmati": n_firmati,
        "da_firmare": totale - n_firmati,
        "percentuale": percentuale_firmati(n_firmati, totale),
        "completo": bool(totale) and n_firmati == totale,
        "enti": enti,
    }


def data_ora(valore):
    """Data e ora locali come le mostra la pagina: "12 sep 2026 16:40"."""
    locale = timezone.localtime(valore)
    return f"{format_display_date(locale)} {locale:%H:%M}"


def url_immagine_firma(utente):
    """Da dove la pagina legge l'immagine di firma di un utente, "" se non ne ha.

    Passa dalla vista ``firma_utente``, che richiede l'accesso, e non dall'URL
    dei file caricati, che Django serve solo in sviluppo: così la firma si vede
    in ogni installazione. Il nome del file nel parametro cambia a ogni nuova
    immagine, e il browser non mostra quella vecchia.
    """
    if not utente.firma:
        return ""
    return f"{reverse('firma_utente', args=[utente.pk])}?v={quote(utente.firma.name)}"


def serialize_firma(firma):
    """Una firma come la mostrano pagina e API.

    L'immagine è quella attuale dell'utente (vedi il TODO sul modello): per
    firmare serve averla, ma se poi l'utente la toglie qui resta "" e la pagina
    mostra nome e data.
    """
    utente = firma.utente
    annullata_da = firma.annullata_da if firma.annullata_da_id else None
    return {
        "id": firma.pk,
        "punto_id": firma.punto_id,
        "utente_id": utente.pk,
        "utente": nome_utente(utente),
        "immagine": url_immagine_firma(utente),
        "firmato_il": firma.firmato_il.isoformat(),
        "firmato_il_display": data_ora(firma.firmato_il),
        "esito": firma.esito,
        "esito_etichetta": firma.get_esito_display(),
        "note": firma.note,
        "valida": firma.valida,
        "annullata_il": firma.annullata_il.isoformat() if firma.annullata_il else None,
        "annullata_il_display": data_ora(firma.annullata_il) if firma.annullata_il else "",
        "annullata_da": nome_utente(annullata_da) if annullata_da else "",
        "motivo_annullo": firma.motivo_annullo,
    }


def _esito_firma(valore):
    if valore not in EsitoFirma.values:
        ammessi = ", ".join(etichetta.lower() for _, etichetta in EsitoFirma.choices)
        raise ValueError(f"Esito della firma non valido: scegli fra {ammessi}.")
    return valore


def _testo_firma(valore, cosa):
    if valore is None:
        return ""
    if not isinstance(valore, str):
        raise ValueError(f"{cosa}: deve essere un testo.")
    testo = valore.strip()
    if len(testo) > _MAX_TESTO_FIRMA:
        raise ValueError(f"{cosa}: al massimo {_MAX_TESTO_FIRMA} caratteri.")
    return testo


def get_punto(job, pk, pid):
    """Un punto d'intervento, solo se è di uno step del piano e il piano della commessa."""
    return QualityControlPlanInterventionPoint.objects.select_related(
        "agency", "step__sezione__piano"
    ).get(pk=pid, step__sezione__piano_id=pk, step__sezione__piano__testata_id=job)


def get_firma(job, pk, fid):
    """Una firma, solo se è di un punto del piano e il piano della commessa."""
    return QualityControlPlanSignature.objects.select_related("punto__step__sezione__piano").get(
        pk=fid, punto__step__sezione__piano_id=pk, punto__step__sezione__piano__testata_id=job
    )


def _richiedi_immagine_firma(utente):
    """Per firmare serve la propria immagine di firma: è quella che si vede sugli step."""
    if not getattr(utente, "firma", None):
        raise ValueError(
            "Per firmare serve la tua immagine di firma: caricala nel profilo, poi firma."
        )


def firma_punto(punto, utente, esito, note=""):
    """Registra la firma di ``utente`` sul punto d'intervento, con esito e note.

    Firma solo chi ha caricato la propria immagine di firma. Su un punto "-" non
    c'è niente da firmare. Un punto ha al massimo una firma valida: una seconda
    la respinge il vincolo del database, anche quando arriva insieme alla prima
    (due clic ravvicinati).
    """
    _richiedi_immagine_firma(utente)
    esito = _esito_firma(esito)
    note = _testo_firma(note, "Note")
    if punto.punto == PuntoIntervento.NON_COINVOLTO:
        raise ValueError('Il punto è "-": nessun ente coinvolto, non c\'è niente da firmare.')
    try:
        with transaction.atomic():
            return QualityControlPlanSignature.objects.create(
                punto=punto, utente=utente, esito=esito, note=note
            )
    except IntegrityError:
        raise ValueError(
            "Il punto ha già una firma valida: per correggerla va annullata."
        ) from None


def firma_step(step, utente, esito, note=""):
    """Firma in una volta tutti i punti dello step con un ente coinvolto.

    In officina il controllo si esegue una volta, non una per ente. I punti già
    firmati restano come sono; se non ne resta nessuno da firmare, o lo step ha
    solo "-", si rifiuta. O si firmano tutti gli altri o nessuno. Restituisce
    le firme create. Come per ``firma_punto`` serve l'immagine di firma.
    """
    _richiedi_immagine_firma(utente)
    esito = _esito_firma(esito)
    note = _testo_firma(note, "Note")
    punti = list(
        step.punti.exclude(punto=PuntoIntervento.NON_COINVOLTO)
        .annotate(firmato=_firma_valida())
        .order_by("agency__ordine", "agency_id")
    )
    if not punti:
        raise ValueError('Lo step non ha punti da firmare: per tutti gli enti vale "-".')
    da_firmare = [punto for punto in punti if not punto.firmato]
    if not da_firmare:
        raise ValueError("Tutti i punti dello step sono già firmati.")
    try:
        with transaction.atomic():
            return QualityControlPlanSignature.objects.bulk_create(
                [
                    QualityControlPlanSignature(punto=punto, utente=utente, esito=esito, note=note)
                    for punto in da_firmare
                ]
            )
    except IntegrityError:
        raise ValueError(
            "Un punto dello step è stato firmato nel frattempo: ricarica e riprova."
        ) from None


def annulla_firma(firma, utente, motivo):
    """Annulla una firma valida, che resta nello storico con chi, quando e perché.

    Il motivo è obbligatorio. Il punto torna da firmare e si può firmare di
    nuovo. Si scrivono solo i campi dell'annullamento, e solo se la firma è
    ancora valida: due annullamenti ravvicinati non si sovrascrivono.
    """
    motivo = _testo_firma(motivo, "Motivo")
    if not motivo:
        raise ValueError("Scrivi il motivo dell'annullamento: resta nello storico della firma.")
    annullate = QualityControlPlanSignature.objects.filter(
        pk=firma.pk, annullata_il__isnull=True
    ).update(annullata_il=timezone.now(), annullata_da=utente, motivo_annullo=motivo)
    if not annullate:
        raise ValueError("La firma è già stata annullata.")
    firma.refresh_from_db()
    return firma


def storico_punto(punto):
    """Tutte le firme del punto, valide e annullate, dalla più recente."""
    firme = punto.firme.select_related("utente", "annullata_da").order_by("-firmato_il", "-id")
    return [serialize_firma(firma) for firma in firme]


def punti_con_firma(ids):
    """I punti con questi id, serializzati con la firma valida, in tre query."""
    punti = _punti_con_firme(
        QualityControlPlanInterventionPoint.objects.filter(pk__in=ids).order_by("pk")
    )
    return [_serialize_punto(punto) for punto in punti]
