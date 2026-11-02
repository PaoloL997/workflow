"""Anagrafiche e archivio del trasmittal interno (form MQ 7.5-04)."""

import logging
import re
import shutil
from datetime import datetime
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.db.models import Max, Prefetch
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from ..models import (
    DestinatarioTransmittalInterno,
    DestinazioneDocumento,
    Documento,
    FirmatarioStabilimento,
    IndirizzoDefaultTrasmittalInterno,
    IndirizzoStabilimento,
    OrigineDestinatarioTransmittalInterno,
    PersonaCommessa,
    PresaVisioneTransmittalInterno,
    Reparto,
    Revisione,
    RigaTransmittalInterno,
    RuoloFirmatarioStabilimento,
    RuoloPersonaCommessa,
    Stabilimento,
    Testata,
    TipoDestinatarioTransmittalInterno,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
    User,
)
from .fileserver import (
    elenca_cartella,
    get_base_path,
    get_jobs_root,
    scegli_corrispondenza_esatta,
    trova_file,
)
from .revisione_label import MAX_LUNGHEZZA_ETICHETTA, format_revisione_label, numero_revisione
from .stato_interno import INVIATO, RICEVUTO, stato_interno_effettivo_da_revisione
from .ultima_revisione import ORDINE_DECRESCENTE, ultima_revisione

logger = logging.getLogger(__name__)

EMAIL_EXPORT = "export@brembanarolle.com"


class TrasmittalInternoAnnullaError(Exception):
    """Annullamento non consentito (non è l'ultimo trasmittal del giorno)."""


class TrasmittalInternoPresaVisioneError(Exception):
    """Presa visione rifiutata, con il codice HTTP che la descrive.

    ``status`` è 400 (richiesta incompleta, es. ruolo da indicare), 403 (chi
    clicca non è firmatario del ruolo sui siti della lettera) o 409 (ruolo già
    visionato).
    """

    def __init__(self, messaggio, status=400):
        super().__init__(messaggio)
        self.status = status


class TrasmittalInternoNonCompletatoError(Exception):
    """Passo che richiede entrambe le prese visione (PDF, DCC, email di completamento)."""


# Reparti i cui documenti entrano nel trasmittal interno, per Reparto.acronimo.
# Conta solo un reparto che esiste in anagrafica: oggi non c'è un reparto WE, i
# suoi documenti entreranno da soli quando l'admin lo creerà.
REPARTI_TRASMITTAL_INTERNO = ("UT", "QC", "WE")


# Documenti SHn: nel vecchio strumento Excel riconosciuti dal pattern DOS
# "?????-??-ESH*" sul nome file. `Documento` non ha un campo di tipo/categoria
# dedicato (verificato: solo item_no, vendor_doc, client_doc_no,
# contractor_doc_no, client_doc_class, doc_title, reparto, remarks), quindi il
# pattern si applica a `vendor_doc`, l'unico campo che porta quell'identificativo
# (es. "25056-01-ESH1"). "?" = un carattere qualsiasi, "*" = zero o più.
_PATTERN_DOCUMENTO_SHN = re.compile(r"^.{5}-.{2}-ESH.*$", re.IGNORECASE)


def _e_documento_shn(documento):
    """True se ``documento.vendor_doc`` corrisponde al pattern dei documenti SHn."""
    return bool(_PATTERN_DOCUMENTO_SHN.match(documento.vendor_doc or ""))


def indirizzi_per_siti(codici_bc):
    """Email TO/CC attive per un elenco di siti, per il trasmittal interno.

    Args:
        codici_bc: Iterable di codici sito Business Central (``Stabilimento.codice_bc``).

    Returns:
        ``{"to": [...], "cc": [...]}``, liste di email senza duplicati
        (confronto case-insensitive) e senza sovrapposizioni: un indirizzo
        presente sia tra i TO che tra i CC di uno o più siti compare solo
        tra i TO. Un elenco di codici vuoto, o senza corrispondenze, dà
        ``{"to": [], "cc": []}``.
    """
    return _indirizzi_to_cc(IndirizzoStabilimento, TipoIndirizzoStabilimento.TO, codici_bc)


def _indirizzi_to_cc(modello, tipo_to, codici_bc):
    """TO/CC attivi di ``modello`` per i siti dati, deduplicati (vedi ``indirizzi_per_siti``)."""
    codici = list(codici_bc or [])
    if not codici:
        return {"to": [], "cc": []}

    indirizzi = modello.objects.filter(stabilimento__codice_bc__in=codici, attivo=True).values_list(
        "email", "tipo"
    )

    to, cc = [], []
    visti_to, visti_cc = set(), set()
    for email, tipo in indirizzi:
        chiave = email.strip().lower()
        if tipo == tipo_to:
            if chiave not in visti_to:
                visti_to.add(chiave)
                to.append(email)
        elif chiave not in visti_cc:
            visti_cc.add(chiave)
            cc.append(email)

    cc = [email for email in cc if email.strip().lower() not in visti_to]
    return {"to": to, "cc": cc}


def indirizzi_default_per_siti(codici_bc):
    """Email TO/CC "sempre in copia" attive per un elenco di siti, gestite da admin.

    Come ``indirizzi_per_siti``, ma da ``IndirizzoDefaultTrasmittalInterno``
    (indirizzi aggiuntivi per stabilimento, es. la casella qualità del sito,
    tenuti separati dall'anagrafica TO/CC "operativa" di
    ``IndirizzoStabilimento``).

    Args:
        codici_bc: Iterable di codici sito Business Central (``Stabilimento.codice_bc``).

    Returns:
        ``{"to": [...], "cc": [...]}``, liste di email senza duplicati
        (confronto case-insensitive) e senza sovrapposizioni, come
        ``indirizzi_per_siti``.
    """
    return _indirizzi_to_cc(
        IndirizzoDefaultTrasmittalInterno, TipoDestinatarioTransmittalInterno.TO, codici_bc
    )


def siti_del_documento(documento):
    """Stabilimenti destinatari della copia cartacea di un documento, per codice sito."""
    return list(
        Stabilimento.objects.filter(documenti_destinati__documento=documento).order_by("codice_bc")
    )


def imposta_destinazioni(documento, codici_bc):
    """Sostituisce l'intero set di stabilimenti destinatari di un documento.

    Non accumula: le destinazioni già registrate ma non più presenti in
    ``codici_bc`` vengono rimosse. Un elenco vuoto azzera le destinazioni del
    documento. Solo gli stabilimenti con un codice sito valorizzato possono
    essere destinazioni: un codice senza corrispondenza è ignorato.
    """
    stabilimenti = Stabilimento.objects.filter(codice_bc__in=list(codici_bc or []))
    with transaction.atomic():
        DestinazioneDocumento.objects.filter(documento=documento).delete()
        DestinazioneDocumento.objects.bulk_create(
            DestinazioneDocumento(documento=documento, stabilimento=stabilimento)
            for stabilimento in stabilimenti
        )


def siti_coinvolti(documenti):
    """Unione, deduplicata e ordinata per codice sito, delle destinazioni di più documenti."""
    return list(
        Stabilimento.objects.filter(documenti_destinati__documento__in=documenti)
        .distinct()
        .order_by("codice_bc")
    )


# ── Griglia destinazioni cartacee (pagina trasmittal interno) ──────────────────


def stabilimenti_costruttivi():
    """Stabilimenti con un codice sito Business Central, in ordine di codice.

    Sono le colonne della griglia destinazioni: solo i siti costruttivi (gli
    unici verso cui una copia cartacea ha senso) possono comparire, mai gli
    stabilimenti senza codice_bc.
    """
    return list(Stabilimento.objects.filter(codice_bc__isnull=False).order_by("codice_bc"))


def _reparti_trasmittal():
    """Reparti in anagrafica con un acronimo di ``REPARTI_TRASMITTAL_INTERNO``."""
    return list(Reparto.objects.filter(acronimo__in=REPARTI_TRASMITTAL_INTERNO))


def documenti_trasmittal(testata):
    """Documenti UT, QC e WE della commessa: le righe della griglia destinazioni.

    Reparto.acronimo identifica il reparto; Documento.reparto ne porta il nome
    (vedi core.services.commesse.prepara_per_dcc per lo stesso accoppiamento).
    Nessuno di quei reparti in anagrafica → nessun documento.
    """
    nomi = [reparto.nome for reparto in _reparti_trasmittal()]
    if not nomi:
        return Documento.objects.none()
    return Documento.objects.filter(testata=testata, reparto__in=nomi)


def elenco_destinazioni(testata):
    """Documenti UT, QC e WE della commessa con le destinazioni cartacee correnti.

    Come ``elenco_selezione``, la cartella di ogni reparto sul fileserver è
    scansionata una volta sola per ricavare l'ultima modifica del file di
    ogni documento.

    Returns:
        Lista di dict ``{"id", "vendor_doc", "doc_title", "file_modificato_il",
        "codici_bc"}``, ordinata per ``vendor_doc``. ``codici_bc`` è la lista
        dei ``Stabilimento.codice_bc`` attualmente destinatari del documento;
        ``file_modificato_il`` l'ISO datetime del file risolto, o ``None``.
    """
    documenti = list(
        documenti_trasmittal(testata)
        .prefetch_related("destinazioni__stabilimento")
        .order_by("vendor_doc")
    )
    if not documenti:
        return []
    indici = _indici_cartelle_reparti(testata, documenti)
    return [
        {
            "id": documento.pk,
            "vendor_doc": documento.vendor_doc,
            "doc_title": documento.doc_title,
            "file_modificato_il": _data_modifica_iso(_cerca_file_documento(indici, documento)),
            "codici_bc": [
                destinazione.stabilimento.codice_bc for destinazione in documento.destinazioni.all()
            ],
        }
        for documento in documenti
    ]


def imposta_destinazioni_commessa(testata, documento_id, codici_bc):
    """``imposta_destinazioni``, ristretto ai documenti UT, QC e WE della commessa data.

    Raises:
        Documento.DoesNotExist: se ``documento_id`` non è un documento di
            ``testata`` di quei reparti (commessa sbagliata, o altro reparto).
    """
    documento = documenti_trasmittal(testata).get(pk=documento_id)
    imposta_destinazioni(documento, codici_bc)
    return documento


def imposta_destinazione_stabilimento_bulk(testata, codice_bc, documento_ids, attiva):
    """Attiva o disattiva un singolo stabilimento sulle destinazioni di più documenti.

    Usata per la selezione in blocco della griglia destinazioni: il chiamante
    passa esplicitamente gli id dei documenti su cui agire (tipicamente quelli
    attualmente visibili dopo un filtro), così l'azione tocca solo quelli.
    Eventuali id che non sono documenti UT, QC o WE di ``testata`` — perché
    di un'altra commessa, o di un altro reparto — vengono ignorati
    silenziosamente: non è un errore, sono semplicemente fuori dal set su cui
    questa griglia può agire.

    Returns:
        I documenti effettivamente aggiornati.
    """
    documenti = list(
        documenti_trasmittal(testata)
        .filter(pk__in=list(documento_ids or []))
        .prefetch_related("destinazioni__stabilimento")
    )
    for documento in documenti:
        codici = {d.stabilimento.codice_bc for d in documento.destinazioni.all()}
        if attiva:
            codici.add(codice_bc)
        else:
            codici.discard(codice_bc)
        imposta_destinazioni(documento, codici)
    return documenti


def _email_persone(testata, ruolo):
    """Email, in ordine di inserimento, delle persone risolte (utente registrato) per un ruolo."""
    return list(
        PersonaCommessa.objects.filter(testata=testata, ruolo=ruolo, utente__isnull=False)
        .exclude(utente__email="")
        .order_by("id")
        .values_list("utente__email", flat=True)
    )


def _deduplica_destinatari(voci):
    """Deduplica case-insensitive una lista di (email, tipo, origine).

    Un indirizzo presente sia tra i TO che tra i CC resta solo tra i TO,
    mantenendo l'origine della sua prima occorrenza nell'ordine dato.

    Returns:
        Lista di dict ``{"email", "tipo", "origine"}``.
    """
    ordine, email_per_chiave, origine_per_chiave, to_per_chiave = [], {}, {}, {}
    for email, tipo, origine in voci:
        chiave = email.strip().lower()
        if chiave not in origine_per_chiave:
            origine_per_chiave[chiave] = origine
            email_per_chiave[chiave] = email
            ordine.append(chiave)
        if tipo == TipoDestinatarioTransmittalInterno.TO:
            to_per_chiave[chiave] = True

    return [
        {
            "email": email_per_chiave[chiave],
            "tipo": TipoDestinatarioTransmittalInterno.TO
            if to_per_chiave.get(chiave)
            else TipoDestinatarioTransmittalInterno.CC,
            "origine": origine_per_chiave[chiave],
        }
        for chiave in ordine
    ]


def _costruisci_destinatari(testata, documenti, siti):
    """Destinatari che risulterebbero per una lettera con questi documenti.

    Non persiste nulla: usata sia da ``_destinatari_trasmittal`` (che li
    trasforma in righe da salvare) sia dall'anteprima (che li mostra così
    come sono, modificabili prima della conferma).

    Ordine di applicazione (rilevante per la deduplica finale, vedi
    ``_deduplica_destinatari``):
    1. indirizzi di stabilimento dei siti coinvolti (TO/CC da anagrafica);
    2. PM della commessa → TO;
    3. PE e QCI della commessa → CC;
    4. se almeno un documento è di tipo SHn, ``EMAIL_EXPORT`` → CC;
    5. indirizzi default attivi dei siti coinvolti
       (``IndirizzoDefaultTrasmittalInterno``, TO/CC da admin, per
       stabilimento) — stesso ambito del punto 1, lista separata.

    Un ruolo non valorizzato su nessuna ``PersonaCommessa`` risolta per la
    commessa non è un errore: contribuisce semplicemente zero indirizzi.

    WE non è incluso: non è definito da quale campo della commessa dedurre la
    sua lista di distribuzione (nessun ``OrigineDestinatarioTransmittalInterno.WE``
    esiste per questo motivo) — va aggiunto quando quella sorgente sarà chiara,
    non inventato qui.

    Returns:
        Lista di dict ``{"email", "tipo", "origine"}``.
    """
    indirizzi = indirizzi_per_siti([s.codice_bc for s in siti])

    voci = [
        (
            email,
            TipoDestinatarioTransmittalInterno.TO,
            OrigineDestinatarioTransmittalInterno.STABILIMENTO,
        )
        for email in indirizzi["to"]
    ]
    voci += [
        (
            email,
            TipoDestinatarioTransmittalInterno.CC,
            OrigineDestinatarioTransmittalInterno.STABILIMENTO,
        )
        for email in indirizzi["cc"]
    ]
    voci += [
        (email, TipoDestinatarioTransmittalInterno.TO, OrigineDestinatarioTransmittalInterno.PM)
        for email in _email_persone(testata, RuoloPersonaCommessa.PM)
    ]
    voci += [
        (email, TipoDestinatarioTransmittalInterno.CC, OrigineDestinatarioTransmittalInterno.PE)
        for email in _email_persone(testata, RuoloPersonaCommessa.PE)
    ]
    voci += [
        (email, TipoDestinatarioTransmittalInterno.CC, OrigineDestinatarioTransmittalInterno.QCI)
        for email in _email_persone(testata, RuoloPersonaCommessa.QCI)
    ]
    if any(_e_documento_shn(documento) for documento in documenti):
        voci.append(
            (
                EMAIL_EXPORT,
                TipoDestinatarioTransmittalInterno.CC,
                OrigineDestinatarioTransmittalInterno.EXPORT,
            )
        )

    default = indirizzi_default_per_siti([s.codice_bc for s in siti])
    voci += [
        (
            email,
            TipoDestinatarioTransmittalInterno.TO,
            OrigineDestinatarioTransmittalInterno.DEFAULT,
        )
        for email in default["to"]
    ]
    voci += [
        (
            email,
            TipoDestinatarioTransmittalInterno.CC,
            OrigineDestinatarioTransmittalInterno.DEFAULT,
        )
        for email in default["cc"]
    ]

    return _deduplica_destinatari(voci)


def _destinatari_trasmittal(trasmittal, testata, documenti, siti):
    """``_costruisci_destinatari``, come righe ``DestinatarioTransmittalInterno`` da salvare."""
    return [
        DestinatarioTransmittalInterno(trasmittal=trasmittal, **voce)
        for voce in _costruisci_destinatari(testata, documenti, siti)
    ]


def prossimo_progressivo(testata, data):
    """Primo progressivo libero per una commessa in un giorno di emissione.

    Riparte da 1 ogni giorno, per commessa: non collide fra giorni o
    commesse diverse.
    """
    ultimo = TransmittalInterno.objects.filter(testata=testata, data=data).aggregate(
        Max("progressivo")
    )["progressivo__max"]
    return (ultimo or 0) + 1


def componi_nome(testata, data, progressivo):
    """Nome leggibile della lettera: ``<job>_<yyyy-mm-dd>_E<n>``."""
    return f"{testata.job}_{data.isoformat()}_E{progressivo}"


def crea_trasmittal_interno(testata, righe, utente, data=None, note=""):
    """Crea un trasmittal interno, con le sue righe e i destinatari di stabilimento.

    Args:
        testata: Commessa a cui appartiene la lettera.
        righe: Iterable non vuoto di dict, uno per documento incluso, con le
            chiavi ``"documento"`` (istanza ``Documento``, obbligatoria),
            ``"revisione"`` (obbligatoria) e le opzionali ``"copie"``,
            ``"tpi"`` (bool, default ``False``), ``"tpi_destinatario"``,
            ``"note"``, ``"cliente"`` (default ``True``).
            L'ordine nell'iterable è l'ordine di stampa (``posizione``).
        utente: Chi emette la lettera (``TransmittalInterno.creato_da``).
        data: Giorno di emissione; oggi se omesso.
        note: Note libere del modulo.

    Returns:
        Il ``TransmittalInterno`` creato.

    Per ogni riga, i siti coinvolti sono copiati da ``DestinazioneDocumento``
    come SNAPSHOT (``RigaTransmittalInterno.siti``): la lettera già emessa non
    cambia se le destinazioni del documento cambiano in seguito. I
    destinatari di tipo STABILIMENTO sono dedotti da ``indirizzi_per_siti``
    sull'unione dei siti di tutte le righe.

    Non tocca nessuno stato dei documenti. Oltre agli indirizzi di
    stabilimento, i destinatari includono il PM della commessa (TO), PE e
    QCI (CC) e, se almeno un documento è di tipo SHn, ``EMAIL_EXPORT`` (CC) —
    vedi ``_destinatari_trasmittal``. WE resta escluso: la sua lista di
    distribuzione non è ancora definita.
    """
    righe = list(righe)
    if not righe:
        raise ValueError("Un trasmittal interno deve avere almeno una riga.")
    data = data or timezone.localdate()

    with transaction.atomic():
        # Lock sulla commessa: due emissioni simultanee nello stesso giorno
        # calcolerebbero lo stesso progressivo e la seconda fallirebbe sul
        # vincolo di unicità (vedi anche trasmittal_archivio.emetti_e_archivia).
        Testata.objects.select_for_update().get(pk=testata.pk)
        progressivo = prossimo_progressivo(testata, data)
        trasmittal = TransmittalInterno.objects.create(
            testata=testata,
            data=data,
            progressivo=progressivo,
            nome=componi_nome(testata, data, progressivo),
            creato_da=utente,
            note=note,
        )

        documenti = []
        for posizione, riga in enumerate(righe, start=1):
            documento = riga["documento"]
            documenti.append(documento)
            riga_creata = RigaTransmittalInterno.objects.create(
                trasmittal=trasmittal,
                documento=documento,
                revisione=riga["revisione"],
                copie=riga.get("copie"),
                tpi=riga.get("tpi", False),
                tpi_destinatario=riga.get("tpi_destinatario", ""),
                note=riga.get("note", ""),
                cliente=riga.get("cliente", True),
                posizione=posizione,
            )
            riga_creata.siti.set(siti_del_documento(documento))

        DestinatarioTransmittalInterno.objects.bulk_create(
            _destinatari_trasmittal(trasmittal, testata, documenti, siti_coinvolti(documenti))
        )

    return trasmittal


def _percorso_pdf_da(job, nome):
    return get_jobs_root() / job / "Progetto" / "UT" / "Transmittal" / f"{nome}.pdf"


def percorso_pdf(trasmittal):
    """Percorso del PDF di una lettera: ``{JOBS}/{job}/Progetto/UT/Transmittal/{nome}.pdf``."""
    return _percorso_pdf_da(trasmittal.testata.job, trasmittal.nome)


def _percorso_dcc_da(job, nome):
    return get_base_path(job, "DCC") / "DA SPEDIRE" / nome


def percorso_pdf_lettera(job, trasmittal_id):
    """Percorso del PDF di una lettera già emessa, verificata per commessa e percorso.

    Raises:
        TransmittalInterno.DoesNotExist: nessuna lettera con questo id per questa commessa.
        PermissionError: percorso risultante fuori dalla cartella JOBS (difesa in
            profondità: il nome è generato da noi, non dovrebbe mai accadere).
    """
    trasmittal = TransmittalInterno.objects.select_related("testata").get(
        pk=trasmittal_id, testata__job=job
    )
    destinazione = percorso_pdf(trasmittal)
    try:
        destinazione.resolve().relative_to(get_jobs_root().resolve())
    except ValueError:
        raise PermissionError("Percorso non autorizzato: fuori dalla cartella JOBS.") from None
    return destinazione


def salva_pdf(trasmittal):
    """Genera il PDF del trasmittal interno e lo scrive sul fileserver.

    Destinazione: ``{JOBS}/{job}/Progetto/UT/Transmittal/{nome}.pdf``,
    creando le cartelle mancanti.

    Returns:
        Il ``Path`` del file scritto.

    Raises:
        PermissionError: se il percorso risultante è fuori dalla cartella JOBS.
    """
    destinazione = percorso_pdf(trasmittal)
    try:
        destinazione.resolve().relative_to(get_jobs_root().resolve())
    except ValueError:
        raise PermissionError("Percorso non autorizzato: fuori dalla cartella JOBS.") from None

    from src.pdf import genera_trasmittal_interno_pdf

    pdf_bytes = genera_trasmittal_interno_pdf(trasmittal)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    destinazione.write_bytes(pdf_bytes)
    return destinazione


def prepara_per_dcc(trasmittal):
    """Copia per il DCC i PDF dei documenti trasmessi al cliente in questa lettera.

    Cartella di destinazione: ``{JOBS}/{job}/PROGETTO/DCC/DA SPEDIRE/{nome}``.
    È lo stesso ramo "DA SPEDIRE" già letto da
    ``core.services.trasmittal_archivio`` come fallback per il transmittal
    cliente, ma un livello diverso: quel modulo guarda solo dentro
    "DA SPEDIRE/TRANSMITTAL" (una sottocartella fissa), mai le cartelle
    sorelle, quindi la cartella creata qui — che si chiama come la lettera,
    mai "TRANSMITTAL" — non viene scambiata per un transmittal cliente.

    Solo le righe con ``cliente=True`` sono considerate. Se non ce n'è
    nessuna, non viene creato nulla (a differenza del vecchio strumento
    Excel, che creava la cartella e poi la rimuoveva se vuota).

    Il PDF di ogni documento si cerca con la stessa logica di
    ``core.services.commesse.risolvi_file_revisione``, semplificata: nella
    cartella base del reparto (``get_base_path``), per nome (``trova_file``).
    Un documento non trovato — zero o più corrispondenze — non annulla la
    copia degli altri: compare nell'esito, così la UI potrà segnalarlo.

    Args:
        trasmittal: Il ``TransmittalInterno`` da preparare per il DCC.

    Returns:
        Dict con:
            - ``cartella``: percorso della cartella di destinazione, o
              ``None`` se non ci sono righe con ``cliente=True``.
            - ``copiati``: lista di dict ``{"documento_id", "vendor_doc", "file"}``.
            - ``mancanti``: lista di dict ``{"documento_id", "vendor_doc"}``.

    Idempotente: rieseguirla su un trasmittal già preparato sovrascrive gli
    stessi file (stesso nome), senza duplicarli né sollevare eccezioni.

    Raises:
        PermissionError: se il percorso risultante è fuori dalla cartella JOBS.
    """
    righe = list(
        trasmittal.righe.filter(cliente=True).select_related("documento").order_by("posizione")
    )
    if not righe:
        return {"cartella": None, "copiati": [], "mancanti": []}

    job = trasmittal.testata.job
    cartella = _percorso_dcc_da(job, trasmittal.nome)
    try:
        cartella.resolve().relative_to(get_jobs_root().resolve())
    except ValueError:
        raise PermissionError("Percorso non autorizzato: fuori dalla cartella JOBS.") from None
    cartella.mkdir(parents=True, exist_ok=True)

    copiati, mancanti = [], []
    for riga in righe:
        documento = riga.documento
        reparto = Reparto.objects.filter(nome=documento.reparto).first()
        trovati = (
            scegli_corrispondenza_esatta(
                trova_file(get_base_path(job, reparto.acronimo), documento.vendor_doc),
                documento.vendor_doc,
            )
            if reparto and reparto.acronimo
            else []
        )
        if len(trovati) != 1:
            mancanti.append({"documento_id": documento.pk, "vendor_doc": documento.vendor_doc})
            continue
        sorgente = Path(trovati[0]["percorso"])
        shutil.copyfile(sorgente, cartella / sorgente.name)
        copiati.append(
            {
                "documento_id": documento.pk,
                "vendor_doc": documento.vendor_doc,
                "file": sorgente.name,
            }
        )

    return {"cartella": str(cartella), "copiati": copiati, "mancanti": mancanti}


# ── Creazione lettera: selezione, anteprima, conferma, elenco ──────────────────

_RUOLI_AVVISO_ANTEPRIMA = {
    RuoloPersonaCommessa.PM: "PM",
    RuoloPersonaCommessa.PE: "PE",
    RuoloPersonaCommessa.QCI: "QCI",
}


def _serializza_sito(stabilimento):
    return {
        "sigla": stabilimento.sigla,
        "nome": stabilimento.nome,
        "codice_bc": stabilimento.codice_bc,
    }


def ruoli_persona_mancanti(testata):
    """Ruoli PM/PE/QCI senza alcuna email risolta per la commessa.

    Non distingue "ruolo mai impostato" da "impostato ma nessun nome è
    risolto a un utente registrato": in entrambi i casi quel ruolo non porta
    nessun destinatario nella lettera, che è ciò che conta per l'avviso in
    anteprima.
    """
    return [
        etichetta
        for ruolo, etichetta in _RUOLI_AVVISO_ANTEPRIMA.items()
        if not _email_persone(testata, ruolo)
    ]


def _cerca_in_indice(indice, vendor_doc):
    """Stessa regola di corrispondenza di ``trova_file``, su un elenco già scansionato.

    Con più file che contengono il codice, ``scegli_corrispondenza_esatta`` dà la
    precedenza a quello che coincide col documento (ESH1 contro ESH10).
    """
    needle = vendor_doc.lower()
    trovati = [f for f in indice if needle in f["nome"].lower()]
    return scegli_corrispondenza_esatta(trovati, vendor_doc)


def _indici_cartelle_reparti(testata, documenti):
    """File della cartella di ciascun reparto dei documenti dati, una scansione per reparto.

    La cartella è ``get_base_path(job, acronimo)``: si scansionano solo i
    reparti che compaiono fra ``documenti``.

    Returns:
        Dict ``{nome del reparto: [file, ...]}``, con le chiavi di
        ``Documento.reparto``.
    """
    nomi = {documento.reparto for documento in documenti}
    return {
        reparto.nome: elenca_cartella(get_base_path(testata.job, reparto.acronimo))
        for reparto in _reparti_trasmittal()
        if reparto.nome in nomi
    }


def _cerca_file_documento(indici, documento):
    """``_cerca_in_indice`` nella sola cartella del reparto del documento."""
    return _cerca_in_indice(indici.get(documento.reparto, []), documento.vendor_doc)


def _data_modifica_iso(trovati):
    """ISO datetime dell'ultima modifica del file, se ``trovati`` ne contiene esattamente uno.

    Con nessun file o più file corrispondenti il documento non ha un file
    risolto (stessa regola di ``elenco_selezione``): ``None``.
    """
    if len(trovati) != 1 or not trovati[0]["mtime"]:
        return None
    return datetime.fromtimestamp(
        trovati[0]["mtime"], tz=timezone.get_current_timezone()
    ).isoformat()


def _revisione_da_emettere(revisione):
    """Se la revisione è da emettere al cliente, come nell'elenco di «Gestisci emissione».

    Regola: lo stato interno effettivo non è né «inviato al cliente» né
    «ricevuto». La lettera di trasmittal interno accompagna le revisioni su cui
    si lavora prima di spedirle al cliente, non quelle già emesse.
    """
    return stato_interno_effettivo_da_revisione(revisione) not in (INVIATO, RICEVUTO)


def _motivo_non_da_emettere(revisione, etichetta):
    """Perché l'ultima revisione del documento tiene fuori il documento dalla lettera."""
    if stato_interno_effettivo_da_revisione(revisione) == INVIATO:
        return f"Rev {etichetta} già inviata al cliente."
    return f"Rev {etichetta} già ricevuta dal cliente."


def elenco_selezione(testata):
    """Documenti UT, QC e WE della commessa per la selezione della lettera trasmittal interno.

    A differenza della griglia destinazioni, ogni documento porta anche la
    sua validità per la lettera: un documento senza revisione registrata,
    con l'ultima revisione già emessa (vedi ``_revisione_da_emettere``)
    o senza file risolvibile sul fileserver è segnalato SUBITO qui
    (``selezionabile`` False, ``motivo`` spiegato) — non al momento della
    creazione come faceva il vecchio strumento Excel, che bloccava l'intera
    lettera.

    Il file di ogni documento si cerca nella cartella del SUO reparto. Ogni
    cartella viene scansionata una volta sola (non una volta per documento,
    che su una share di rete con molti documenti è il motivo per cui questa
    vista poteva metterci a lungo a caricare) e le revisioni/destinazioni
    sono precaricate con prefetch invece di una query ciascuna.

    Returns:
        Lista di dict ordinata per ``vendor_doc``, uno per documento, con:
        - ``id``, ``vendor_doc``, ``doc_title``
        - ``revisione_corrente``: etichetta della revisione più recente
          ("" se nessuna)
        - ``revisioni_ammissibili``: le revisioni del documento che possono
          comparire nella lettera, come dict ``{"etichetta", "numero"}``: solo
          l'ultima, se è da emettere (vuota se il documento non è
          selezionabile)
        - ``file_modificato_il``: ISO datetime del file risolto, o ``None``
        - ``siti``: destinazioni cartacee salvate (INVOLVED SITES), lista di
          dict ``{"sigla", "nome", "codice_bc"}``
        - ``selezionabile``: bool
        - ``motivo``: perché non è selezionabile, altrimenti ``""``
    """
    documenti = list(
        documenti_trasmittal(testata)
        .prefetch_related(
            Prefetch("revisioni", queryset=Revisione.objects.order_by(*ORDINE_DECRESCENTE)),
            Prefetch(
                "destinazioni",
                queryset=DestinazioneDocumento.objects.select_related("stabilimento").order_by(
                    "stabilimento__codice_bc"
                ),
            ),
        )
        .order_by("vendor_doc")
    )
    if not documenti:
        return []

    indici = _indici_cartelle_reparti(testata, documenti)

    risultato = []
    for documento in documenti:
        voce = {
            "id": documento.pk,
            "vendor_doc": documento.vendor_doc,
            "doc_title": documento.doc_title,
            "revisione_corrente": "",
            "revisioni_ammissibili": [],
            "file_modificato_il": None,
            "siti": [_serializza_sito(d.stabilimento) for d in documento.destinazioni.all()],
            "selezionabile": False,
            "motivo": "",
        }
        latest_rev = ultima_revisione(documento)  # dal prefetch, nessuna query
        if latest_rev is None:
            voce["motivo"] = "Nessuna revisione registrata."
            risultato.append(voce)
            continue
        formato = (testata.rev_let_flag, testata.rev_sequenza)
        voce["revisione_corrente"] = format_revisione_label(
            latest_rev.rev_no, latest_rev.rev_let, *formato
        )
        if not _revisione_da_emettere(latest_rev):
            voce["motivo"] = _motivo_non_da_emettere(latest_rev, voce["revisione_corrente"])
            risultato.append(voce)
            continue
        voce["revisioni_ammissibili"] = [
            {
                "etichetta": voce["revisione_corrente"],
                "numero": numero_revisione(latest_rev.rev_no, latest_rev.rev_let, *formato),
            }
        ]
        trovati = _cerca_file_documento(indici, documento)
        if len(trovati) != 1:
            voce["motivo"] = (
                "Più file corrispondenti sul fileserver."
                if trovati
                else "Nessun file trovato sul fileserver."
            )
            risultato.append(voce)
            continue
        voce["file_modificato_il"] = _data_modifica_iso(trovati)
        voce["selezionabile"] = True
        risultato.append(voce)
    return risultato


def _prepara_righe(testata, righe_payload):
    """Valida e converte il payload delle righe (dict JSON) per ``crea_trasmittal_interno``.

    Ogni voce richiede ``documento_id`` (un documento selezionabile di
    questa commessa) e ``revisione`` (una delle sue ``revisioni_ammissibili``
    di ``elenco_selezione``); ``copie``, ``tpi``, ``tpi_destinatario``,
    ``note``, ``cliente`` sono opzionali. Il primo problema trovato interrompe
    con un ``ValueError`` esplicito — niente lettera creata a metà da un
    payload malformato o da una selezione che nel frattempo è diventata non
    valida.

    ``tpi``/``tpi_destinatario`` replicano le note (b)/(c) del modulo: se il
    documento va a un ispettore terzo (``tpi`` True), va specificato chi
    (``tpi_destinatario`` non vuoto); altrimenti il destinatario non ha senso
    e deve restare vuoto — stessa regola di ``RigaTransmittalInterno.clean``.
    """
    if not righe_payload:
        raise ValueError("Selezionare almeno un documento.")
    stati = {voce["id"]: voce for voce in elenco_selezione(testata)}
    documenti_map = {d.pk: d for d in documenti_trasmittal(testata)}
    righe = []
    for voce in righe_payload:
        documento_id = voce.get("documento_id")
        stato = stati.get(documento_id)
        if stato is None:
            raise ValueError(f"Documento {documento_id} non valido per questa commessa.")
        if not stato["selezionabile"]:
            raise ValueError(f"{stato['vendor_doc']}: {stato['motivo']}")
        revisione = str(voce.get("revisione") or "").strip()
        if not revisione:
            raise ValueError(f"{stato['vendor_doc']}: revisione mancante.")
        if len(revisione) > MAX_LUNGHEZZA_ETICHETTA:
            # Limite della colonna RigaTransmittalInterno.revisione: meglio un
            # 400 chiaro qui che un errore del database a lettera già creata.
            raise ValueError(
                f"{stato['vendor_doc']}: la revisione «{revisione}» supera i "
                f"{MAX_LUNGHEZZA_ETICHETTA} caratteri."
            )
        if revisione not in {r["etichetta"] for r in stato["revisioni_ammissibili"]}:
            # Stessa regola dello stepper: il client non può aggirarla.
            raise ValueError(
                f"{stato['vendor_doc']}: la revisione «{revisione}» non è ammessa nella "
                "lettera: solo la revisione da emettere."
            )
        tpi = bool(voce.get("tpi", False))
        tpi_destinatario = str(voce.get("tpi_destinatario") or "").strip()
        if tpi and not tpi_destinatario:
            raise ValueError(f"{stato['vendor_doc']}: specificare il destinatario TPI.")
        if not tpi and tpi_destinatario:
            raise ValueError(
                f"{stato['vendor_doc']}: il destinatario TPI ha senso solo se TPI è attivo."
            )
        righe.append(
            {
                "documento": documenti_map[documento_id],
                "revisione": revisione,
                "copie": voce.get("copie") or None,
                "tpi": tpi,
                "tpi_destinatario": tpi_destinatario,
                "note": str(voce.get("note") or "").strip(),
                "cliente": bool(voce.get("cliente", True)),
            }
        )
    return righe


def _verifica_siti_lettera(righe):
    """Una lettera deve coinvolgere almeno un sito: senza, nessuno può prenderne visione.

    La presa visione spetta ai firmatari QC e PROD dei siti coinvolti (vedi
    ``registra_presa_visione``): una lettera senza siti resterebbe in attesa
    per sempre, senza PDF né cartella DCC.

    Raises:
        ValueError: nessun documento delle righe ha un sito coinvolto.
    """
    if not siti_coinvolti([riga["documento"] for riga in righe]):
        raise ValueError(
            "Nessun documento della lettera ha un sito coinvolto: senza siti nessuno può "
            "prenderne visione. Imposta le destinazioni dei documenti e riprova."
        )


def anteprima_destinatari(testata, documenti):
    """Destinatari che risulterebbero per una lettera con questi documenti, senza persistere nulla."""
    return _costruisci_destinatari(testata, documenti, siti_coinvolti(documenti))


def anteprima_trasmittal(testata, righe_payload, utente=None):
    """Anteprima di una lettera: riepilogo righe, destinatari risolti, ruoli mancanti.

    Non persiste nulla. Solleva ``ValueError`` se il payload non è valido
    (vedi ``_prepara_righe``): stesso controllo che varrà alla creazione
    vera, così l'anteprima non promette una lettera che poi la conferma
    rifiuterebbe.

    ``utente`` è chi sta compilando la lettera: se dato, l'anteprima riporta
    in ``mittente`` l'indirizzo da cui partirà davvero l'email (vedi
    ``mittente_trasmittal``), così chi emette lo vede prima di confermare.
    """
    righe = _prepara_righe(testata, righe_payload)
    _verifica_siti_lettera(righe)
    documenti = [riga["documento"] for riga in righe]
    oggi = timezone.localdate()
    # Anteprima del nome: il progressivo reale si assegna solo alla creazione
    # vera, dentro la transazione — se nel frattempo un'altra lettera viene
    # emessa per questa commessa, il nome effettivo potrebbe differire di
    # un'unità. Stesso limite che aveva la preview del vecchio strumento.
    nome_preview = componi_nome(testata, oggi, prossimo_progressivo(testata, oggi))
    ha_dcc = any(riga["cliente"] for riga in righe)
    return {
        "nome_preview": nome_preview,
        "percorso_pdf_preview": str(_percorso_pdf_da(testata.job, nome_preview)),
        "percorso_dcc_preview": str(_percorso_dcc_da(testata.job, nome_preview))
        if ha_dcc
        else None,
        "righe": [
            {
                "documento_id": riga["documento"].pk,
                "vendor_doc": riga["documento"].vendor_doc,
                "doc_title": riga["documento"].doc_title,
                "revisione": riga["revisione"],
                "copie": riga["copie"],
                "tpi": riga["tpi"],
                "tpi_destinatario": riga["tpi_destinatario"],
                "note": riga["note"],
                "cliente": riga["cliente"],
                "siti": [_serializza_sito(s) for s in siti_del_documento(riga["documento"])],
            }
            for riga in righe
        ],
        "destinatari": anteprima_destinatari(testata, documenti),
        "ruoli_mancanti": ruoli_persona_mancanti(testata),
        "mittente": mittente_trasmittal(utente) if utente is not None else None,
    }


def anteprima_pdf_bytes(testata, righe_payload, utente, note="", data=None):
    """PDF che risulterebbe dalla lettera descritta, senza persistere nulla.

    Crea davvero il trasmittal (con le sue righe e i suoi destinatari)
    dentro una transazione sempre annullata: è l'unico modo per riusare la
    generazione PDF reale (che legge le righe dal database) senza duplicarne
    la logica in una seconda versione "in memoria".
    """
    righe = _prepara_righe(testata, righe_payload)
    with transaction.atomic():
        trasmittal = crea_trasmittal_interno(testata, righe, utente, data=data, note=note)

        from src.pdf import genera_trasmittal_interno_pdf

        pdf_bytes = genera_trasmittal_interno_pdf(trasmittal)
        transaction.set_rollback(True)
    return pdf_bytes


def sostituisci_destinatari(trasmittal, destinatari_payload):
    """Sostituisce i destinatari di un trasmittal con quelli confermati in anteprima.

    È il controllo che nel vecchio strumento avveniva sulla bozza Outlook
    prima dell'invio: l'utente può correggere/aggiungere/rimuovere indirizzi
    proposti automaticamente prima della conferma definitiva.

    Args:
        destinatari_payload: iterable di dict ``{"email", "tipo", "origine"}``.

    Raises:
        ValueError: un'email non valida, un ``tipo``/``origine`` non
            riconosciuto, o nessun destinatario in TO dopo la deduplica.
    """
    voci = []
    for voce in destinatari_payload or []:
        email = str(voce.get("email") or "").strip()
        if not email:
            continue
        try:
            validate_email(email)
        except ValidationError:
            raise ValueError(f'Indirizzo email non valido: "{email}".') from None
        tipo = voce.get("tipo")
        if tipo not in TipoDestinatarioTransmittalInterno.values:
            raise ValueError(f'Tipo destinatario non valido: "{tipo}".')
        origine = voce.get("origine")
        if origine not in OrigineDestinatarioTransmittalInterno.values:
            raise ValueError(f'Origine destinatario non valida: "{origine}".')
        voci.append((email, tipo, origine))

    destinatari = _deduplica_destinatari(voci)
    if not any(d["tipo"] == TipoDestinatarioTransmittalInterno.TO for d in destinatari):
        raise ValueError("Serve almeno un destinatario in TO.")

    with transaction.atomic():
        trasmittal.destinatari.all().delete()
        DestinatarioTransmittalInterno.objects.bulk_create(
            DestinatarioTransmittalInterno(trasmittal=trasmittal, **d) for d in destinatari
        )


def indirizzi_email_noti():
    """Indirizzi email già presenti nell'applicazione, per l'autocompletamento in anteprima.

    Unisce, in quest'ordine: gli utenti attivi, gli indirizzi attivi degli
    stabilimenti, quelli di default del trasmittal interno e i destinatari
    delle lettere già emesse (compresi quelli aggiunti a mano). Deduplica
    senza distinguere maiuscole/minuscole, come ``_deduplica_destinatari``: a
    parità di indirizzo resta la prima fonte, così un utente tiene il suo nome.

    Returns:
        Lista di dict ``{"email", "nome"}`` ordinata per email. ``nome`` è il
        nome dell'utente, "Stabilimento <sigla>" o ``""``.
    """
    candidati = [
        (utente.email, utente.nome_completo)
        for utente in User.objects.filter(is_active=True).exclude(email="")
    ]
    for modello in (IndirizzoStabilimento, IndirizzoDefaultTrasmittalInterno):
        candidati += [
            (email, f"Stabilimento {sigla or nome}")
            for email, sigla, nome in modello.objects.filter(attivo=True).values_list(
                "email", "stabilimento__sigla", "stabilimento__nome"
            )
        ]
    candidati += [
        (email, "")
        for email in DestinatarioTransmittalInterno.objects.order_by()
        .values_list("email", flat=True)
        .distinct()
    ]

    per_chiave = {}
    for email, nome in candidati:
        email = (email or "").strip()
        chiave = email.lower()
        if chiave and chiave not in per_chiave:
            per_chiave[chiave] = {"email": email, "nome": nome}
    return sorted(per_chiave.values(), key=lambda voce: voce["email"].lower())


def _tabella_testo_righe(trasmittal):
    """Tabella testuale delle righe della lettera, stesse colonne del PDF.

    Riusa ``_INT_COLS``/``_int_row_value`` di ``src.pdf`` come unica fonte di
    verità per colonne e valori: l'email non deve poter divergere dal PDF su
    cosa mostra per ogni riga.
    """
    from src.pdf import _INT_COLS, _int_row_value

    righe = list(
        trasmittal.righe.select_related("documento")
        .prefetch_related(Prefetch("siti", queryset=Stabilimento.objects.order_by("codice_bc")))
        .order_by("posizione")
    )
    intestazioni = [colonna[1] for colonna in _INT_COLS]
    chiavi = [colonna[0] for colonna in _INT_COLS]
    valori = [[_int_row_value(riga, chiave) or "-" for chiave in chiavi] for riga in righe]

    larghezze = [
        max([len(intestazioni[i])] + [len(riga[i]) for riga in valori])
        for i in range(len(intestazioni))
    ]

    def _formatta(celle):
        return "  ".join(cella.ljust(larghezze[i]) for i, cella in enumerate(celle))

    return "\n".join(
        [_formatta(intestazioni), "  ".join("-" * w for w in larghezze)]
        + [_formatta(riga) for riga in valori]
    )


# Presa visione: i due ruoli, nell'ordine in cui compaiono in email, elenco e
# messaggi (QC prima di PROD), con la sigla usata nei testi.
_RUOLI_PRESA_VISIONE = (
    RuoloFirmatarioStabilimento.QUALITA,
    RuoloFirmatarioStabilimento.PRODUZIONE,
)
_SIGLA_RUOLO = {
    RuoloFirmatarioStabilimento.QUALITA: "QC",
    RuoloFirmatarioStabilimento.PRODUZIONE: "PROD",
}

STATO_IN_ATTESA = "in_attesa"
STATO_PARZIALE = "parziale"
STATO_COMPLETATO = "completato"

TESTO_IN_ATTESA = "In attesa di presa visione QC e PROD"


def _data_ora(momento):
    """``gg/mm/aaaa hh:mm`` nell'ora locale, come nelle email e nel PDF."""
    return timezone.localtime(momento).strftime("%d/%m/%Y %H:%M")


def _righe_note(trasmittal):
    """Le tre righe libere della lettera, le stesse del riquadro NOTES del PDF."""
    from src.pdf import _righe_note_libere

    return _righe_note_libere(trasmittal.note)


def _riquadro_note_testo(trasmittal):
    """Riquadro NOTES dell'email di emissione: le tre righe numerate 1) 2) 3)."""
    righe = [f"{i}) {testo}".rstrip() for i, testo in enumerate(_righe_note(trasmittal), start=1)]
    return "\n".join(["NOTES", *righe])


def link_lettera(trasmittal, base_url=""):
    """Indirizzo della pagina del trasmittal interno della commessa, aperta su questa lettera.

    La base è ``settings.WORKFLOW_BASE_URL``. Se è vuota vale ``base_url``,
    l'indirizzo con cui chi emette (o chi riprova l'invio) ha aperto l'app,
    passato dalla view; senza nessuna delle due resta il solo percorso.
    """
    base = (getattr(settings, "WORKFLOW_BASE_URL", "") or base_url or "").rstrip("/")
    percorso = reverse("trasmittal_interno_detail", args=[trasmittal.testata.job])
    return f"{base}{percorso}?lettera={trasmittal.pk}"


def _corpo_email_emissione(trasmittal, link):
    """Corpo dell'email di emissione: è la lettera per chi la riceve, non solo un avviso.

    Intestazione, messaggio facoltativo di chi emette, tabella delle righe
    (stesse colonne del PDF, così il destinatario sa cosa gli è stato
    trasmesso), riquadro NOTES con le tre righe libere della lettera e la riga
    di stato con il link alla pagina in Workflow. Il percorso del PDF non c'è:
    il PDF si salva solo dopo le due prese visione, e lo riporta l'email di
    completamento (``_corpo_email_completamento``).

    Versione testo semplice: fa da corpo per i client senza HTML e da
    fallback, ma si allinea per colonna solo con un font monospace — molti
    client (Gmail, Outlook) mostrano il testo semplice con un font
    proporzionale, che rompe l'allineamento. Per questo l'email include anche
    ``_corpo_email_emissione_html`` come alternativa ``text/html``.
    """
    messaggio = (trasmittal.messaggio_email or "").strip()
    return (
        f"{_intestazione_email(trasmittal)}\n\n"
        + (f"{messaggio}\n\n" if messaggio else "")
        + f"{_tabella_testo_righe(trasmittal)}\n\n"
        + f"{_riquadro_note_testo(trasmittal)}\n\n"
        + f"{TESTO_IN_ATTESA}: {link}"
    )


def _righe_visionato(trasmittal):
    """``Visionato da <nome> (QC) il <data ora>``, una riga per presa visione, QC prima di PROD."""
    prese = {p.ruolo: p for p in trasmittal.prese_visione.select_related("utente")}
    return [
        f"Visionato da {prese[ruolo].utente.nome_completo} ({_SIGLA_RUOLO[ruolo]}) "
        f"il {_data_ora(prese[ruolo].registrata_il)}"
        for ruolo in _RUOLI_PRESA_VISIONE
        if ruolo in prese
    ]


def _riga_salvataggio(trasmittal):
    """Dove è salvato il PDF; se il salvataggio non è riuscito lo dice, invece di un percorso vuoto."""
    percorso = percorso_pdf(trasmittal)
    if percorso.is_file():
        return f"Salvato in: {percorso}"
    return (
        f"PDF non ancora salvato (salvataggio non riuscito, da riprovare in Workflow): {percorso}"
    )


def _corpo_email_completamento(trasmittal):
    """Corpo dell'email di completamento: chi ha preso visione, quando, e dove è il PDF."""
    return (
        f"{_intestazione_email(trasmittal)}\n\n"
        + "\n".join(_righe_visionato(trasmittal))
        + f"\n\n{_riga_salvataggio(trasmittal)}"
    )


_EMAIL_TABLE_STYLE = (
    "border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;font-size:13px;"
)
_EMAIL_CELL_STYLE = "border:1px solid #999;padding:4px 8px;text-align:left;white-space:nowrap;"
_EMAIL_HEADER_STYLE = _EMAIL_CELL_STYLE + "background:#eee;font-weight:bold;"


def _tabella_html_righe(trasmittal):
    """Tabella HTML delle righe della lettera: stesse colonne e valori di
    ``_tabella_testo_righe``, ma allineata anche senza font monospace."""
    from src.pdf import _INT_COLS, _int_row_value

    righe = list(
        trasmittal.righe.select_related("documento")
        .prefetch_related(Prefetch("siti", queryset=Stabilimento.objects.order_by("codice_bc")))
        .order_by("posizione")
    )
    intestazioni = [colonna[1] for colonna in _INT_COLS]
    chiavi = [colonna[0] for colonna in _INT_COLS]

    testa = "".join(f'<th style="{_EMAIL_HEADER_STYLE}">{escape(i)}</th>' for i in intestazioni)
    corpo = "".join(
        "<tr>"
        + "".join(
            f'<td style="{_EMAIL_CELL_STYLE}">{escape(_int_row_value(riga, chiave) or "-")}</td>'
            for chiave in chiavi
        )
        + "</tr>"
        for riga in righe
    )
    return f'<table style="{_EMAIL_TABLE_STYLE}"><thead><tr>{testa}</tr></thead><tbody>{corpo}</tbody></table>'


_EMAIL_NOTE_CELL_STYLE = "border:1px solid #999;padding:4px 8px;text-align:left;min-width:400px;"


def _riquadro_note_html(trasmittal):
    """Riquadro NOTES di ``_riquadro_note_testo`` come tabella a una cella."""
    righe = "<br>".join(
        escape(f"{i}) {testo}".rstrip()) for i, testo in enumerate(_righe_note(trasmittal), start=1)
    )
    return (
        f'<table style="{_EMAIL_TABLE_STYLE}margin-top:12px;"><thead><tr>'
        f'<th style="{_EMAIL_HEADER_STYLE}">NOTES</th></tr></thead>'
        f'<tbody><tr><td style="{_EMAIL_NOTE_CELL_STYLE}">{righe}</td></tr></tbody></table>'
    )


def _corpo_email_emissione_html(trasmittal, link):
    """Versione HTML di ``_corpo_email_emissione``, allegata come alternativa
    ``text/html`` (vedi ``invia_email_emissione``)."""
    messaggio = (trasmittal.messaggio_email or "").strip()
    messaggio_html = "<br>".join(escape(riga) for riga in messaggio.splitlines())
    return (
        f"<p>{escape(_intestazione_email(trasmittal))}</p>"
        + (f"<p>{messaggio_html}</p>" if messaggio else "")
        + _tabella_html_righe(trasmittal)
        + _riquadro_note_html(trasmittal)
        + f'<p><strong>{escape(TESTO_IN_ATTESA)}</strong>: <a href="{escape(link)}">'
        f"{escape(link)}</a></p>"
    )


def _corpo_email_completamento_html(trasmittal):
    """Versione HTML di ``_corpo_email_completamento``."""
    return (
        f"<p>{escape(_intestazione_email(trasmittal))}</p>"
        + "<p>"
        + "<br>".join(escape(riga) for riga in _righe_visionato(trasmittal))
        + "</p>"
        + f"<p>{escape(_riga_salvataggio(trasmittal))}</p>"
    )


def mittente_trasmittal(utente=None):
    """Mittente dell'email di un trasmittal interno: la casella dell'applicazione.

    Solo l'indirizzo di ``DEFAULT_FROM_EMAIL`` (un eventuale nome nel .env si
    ignora): il server di posta lascia spedire solo con la casella con cui
    l'app si autentica, un altro indirizzo viene rifiutato (``550 5.7.0
    Authentication rejected``). Chi ha emesso la lettera compare nel testo
    dell'email (``_intestazione_email``), riceve le risposte e una copia.

    Args:
        utente: Chi ha emesso la lettera; non cambia il mittente, resta per
            le chiamate esistenti.

    Returns:
        L'indirizzo della casella, es. ``"workflow@brembanarolle.com"``.
    """
    return parseaddr(settings.DEFAULT_FROM_EMAIL)[1] or settings.DEFAULT_FROM_EMAIL


def _indirizzo_utente(utente):
    """``"Nome Cognome <email>"`` dell'utente, o ``None`` se non ha un'email."""
    email = (getattr(utente, "email", "") or "").strip()
    return formataddr((utente.nome_completo, email)) if email else None


def _intestazione_email(trasmittal):
    """Prima riga dell'email: lettera, commessa e chi l'ha emessa.

    Il mittente è la casella dell'applicazione, quindi chi scrive si legge qui.
    """
    utente = trasmittal.creato_da
    emesso_da = utente.nome_completo
    email = (getattr(utente, "email", "") or "").strip()
    if email:
        emesso_da = f"{emesso_da} ({email})"
    return (
        f"Trasmittal interno {trasmittal.nome} — commessa {trasmittal.testata.job} "
        f"— emesso da {emesso_da}."
    )


def _oggetto_email(trasmittal):
    """Oggetto delle email della lettera: porta il riferimento al modulo del sistema
    qualità (non è decorativo, identifica il documento). È lo stesso per l'email di
    emissione e per quella di completamento, così restano nello stesso thread."""
    return f"DOCUMENT TRANSMITTAL [Form MQ 7.5-04 Rev.0]: {trasmittal.nome}"


def _destinatari_email(trasmittal):
    """TO e CC delle email della lettera: i destinatari registrati, più chi ha emesso in copia.

    Returns:
        Tupla ``(to, cc)`` di liste di indirizzi; chi ha emesso la lettera è
        aggiunto in coda ai CC se non è già fra i destinatari.

    Raises:
        ValueError: nessun destinatario in TO.
    """
    to = list(
        trasmittal.destinatari.filter(tipo=TipoDestinatarioTransmittalInterno.TO)
        .order_by("email")
        .values_list("email", flat=True)
    )
    cc = list(
        trasmittal.destinatari.filter(tipo=TipoDestinatarioTransmittalInterno.CC)
        .order_by("email")
        .values_list("email", flat=True)
    )
    if not to:
        raise ValueError("Nessun destinatario in TO: impossibile inviare l'email.")
    emittente = (getattr(trasmittal.creato_da, "email", "") or "").strip()
    if emittente and emittente.lower() not in {e.lower() for e in to + cc}:
        cc.append(emittente)
    return to, cc


def _invia_email(trasmittal, body, body_html, headers=None):
    """Invia un'email della lettera ai suoi destinatari TO/CC registrati.

    L'email parte dalla casella dell'applicazione (``mittente_trasmittal``);
    chi ha emesso la lettera (``trasmittal.creato_da``) è scritto nella prima
    riga del testo, e il suo indirizzo va in ``Reply-To`` e in copia, così le
    risposte arrivano a lui e gliene resta un esemplare. Vale anche quando
    l'invio viene ritentato da un'altra persona o parte dalla presa visione
    di qualcun altro: conta chi ha emesso la lettera, che è quanto scritto sul
    modulo. Nessun allegato.

    Con ``TRASMITTAL_INTERNO_EMAIL_TEST_REDIRECT`` impostato l'email va solo a
    quell'indirizzo, con i destinatari veri nell'oggetto e nel testo.

    Returns:
        Dict ``{"to": [...], "cc": [...], "mittente": str}`` con gli
        indirizzi usati (``cc`` comprende chi ha emesso la lettera).

    Raises:
        ValueError: nessun destinatario in TO.
    """
    to, cc = _destinatari_email(trasmittal)
    subject = _oggetto_email(trasmittal)
    invio_to, invio_cc = to, cc
    test_redirect = getattr(settings, "TRASMITTAL_INTERNO_EMAIL_TEST_REDIRECT", "")
    if test_redirect:
        subject = f"[TEST — a: {', '.join(to)}; cc: {', '.join(cc) or '—'}] {subject}"
        avviso_test = f"[TEST] Email reindirizzata da {', '.join(to + cc)} a questo indirizzo."
        body = f"{avviso_test}\n\n{body}"
        body_html = f"<p><strong>{escape(avviso_test)}</strong></p>{body_html}"
        invio_to, invio_cc = [test_redirect], []

    mittente = mittente_trasmittal(trasmittal.creato_da)
    rispondi_a = _indirizzo_utente(trasmittal.creato_da)
    email = EmailMultiAlternatives(
        subject=subject,
        body=body,
        from_email=mittente,
        to=invio_to,
        cc=invio_cc,
        reply_to=[rispondi_a] if rispondi_a else None,
        headers=headers or None,
    )
    email.attach_alternative(body_html, "text/html")
    email.send(fail_silently=False)
    return {"to": to, "cc": cc, "mittente": mittente}


def invia_email_emissione(trasmittal, base_url=""):
    """Email di emissione: avvisa i destinatari che la lettera è emessa e attende la presa visione.

    Corpo in testo e in HTML (vedi ``_corpo_email_emissione``): intestazione,
    messaggio facoltativo, tabella delle righe, riquadro NOTES e la riga di
    stato con il link alla pagina della lettera (``link_lettera``). Nessun
    allegato e nessun percorso del PDF, che a questo punto non esiste ancora.

    Il Message-ID è generato qui (``make_msgid``, sul dominio della casella
    dell'app) e salvato in ``trasmittal.message_id`` dopo l'invio: l'email di
    completamento lo cita in ``In-Reply-To``/``References`` per restare nello
    stesso thread. Un nuovo invio (Riprova) genera e salva un nuovo Message-ID.

    Returns:
        Dict ``{"to", "cc", "mittente", "message_id"}``.

    Raises:
        ValueError: nessun destinatario in TO.
    """
    link = link_lettera(trasmittal, base_url)
    mittente = mittente_trasmittal(trasmittal.creato_da)
    message_id = make_msgid(domain=mittente.rpartition("@")[2] or None)
    esito = _invia_email(
        trasmittal,
        _corpo_email_emissione(trasmittal, link),
        _corpo_email_emissione_html(trasmittal, link),
        headers={"Message-ID": message_id},
    )
    trasmittal.message_id = message_id
    trasmittal.save(update_fields=["message_id"])
    return {**esito, "message_id": message_id}


def invia_email_completamento(trasmittal):
    """Email di completamento: QC e PROD hanno preso visione, il PDF è sul fileserver.

    Stesso oggetto, stessi destinatari, stesso Reply-To e stessa copia a chi
    ha emesso dell'email di emissione, e header ``In-Reply-To`` e
    ``References`` con il Message-ID salvato (``trasmittal.message_id``), così
    i client la mostrano come risposta nello stesso thread. Se l'email di
    emissione non è mai partita il Message-ID manca e l'email parte senza
    quegli header.

    Returns:
        Dict ``{"to", "cc", "mittente"}``.

    Raises:
        ValueError: nessun destinatario in TO.
    """
    headers = None
    if trasmittal.message_id:
        headers = {"In-Reply-To": trasmittal.message_id, "References": trasmittal.message_id}
    return _invia_email(
        trasmittal,
        _corpo_email_completamento(trasmittal),
        _corpo_email_completamento_html(trasmittal),
        headers=headers,
    )


# ── Passi best-effort: emissione, completamento, Riprova ───────────────────────
# Ogni passo è indipendente: un errore è registrato nel log e riportato nel suo
# esito, mai silenzioso, e non ferma gli altri passi.


def _passo_pdf(trasmittal):
    try:
        percorso = salva_pdf(trasmittal)
        return {"ok": True, "errore": None, "percorso": str(percorso)}
    except Exception as exc:
        logger.exception('Salvataggio PDF del trasmittal interno "%s" fallito.', trasmittal.nome)
        return {"ok": False, "errore": str(exc), "percorso": None}


def _passo_dcc(trasmittal):
    try:
        return {"ok": True, "errore": None, **prepara_per_dcc(trasmittal)}
    except Exception as exc:
        logger.exception('Preparazione DCC del trasmittal interno "%s" fallita.', trasmittal.nome)
        return {"ok": False, "errore": str(exc), "cartella": None, "copiati": [], "mancanti": []}


def _esito_email_fallita(trasmittal, exc):
    return {
        "ok": False,
        "errore": str(exc),
        "to": [],
        "cc": [],
        "mittente": mittente_trasmittal(trasmittal.creato_da),
    }


def _passo_email_emissione(trasmittal, base_url=""):
    try:
        return {"ok": True, "errore": None, **invia_email_emissione(trasmittal, base_url)}
    except Exception as exc:
        logger.exception('Invio email del trasmittal interno "%s" fallito.', trasmittal.nome)
        return _esito_email_fallita(trasmittal, exc)


def _passo_email_completamento(trasmittal):
    try:
        return {"ok": True, "errore": None, **invia_email_completamento(trasmittal)}
    except Exception as exc:
        logger.exception(
            'Invio email di completamento del trasmittal interno "%s" fallito.', trasmittal.nome
        )
        return _esito_email_fallita(trasmittal, exc)


def completa_trasmittal_interno(trasmittal):
    """Archivia e distribuisce una lettera su cui QC e PROD hanno preso visione.

    Salva il PDF sul fileserver (``salva_pdf``), prepara la cartella DCC
    (``prepara_per_dcc``) e invia l'email di completamento
    (``invia_email_completamento``), nell'ordine. Ogni passo è indipendente e
    best-effort: un suo fallimento non ferma gli altri ed è riportato nel
    risultato, così si ritenta solo quello (``riprova_passo``).

    Returns:
        Dict con ``pdf``, ``dcc`` ed ``email``, ognuno ``{"ok": bool,
        "errore": str | None, ...}`` (stesso formato dell'emissione).
    """
    return {
        "pdf": _passo_pdf(trasmittal),
        "dcc": _passo_dcc(trasmittal),
        "email": _passo_email_completamento(trasmittal),
    }


PASSI_LETTERA = ("email", "pdf", "dcc", "email_completamento")


def riprova_passo(trasmittal, passo, base_url=""):
    """Ritenta un solo passo di una lettera già creata.

    ``email`` è l'email di emissione e si può sempre ritentare (``base_url``
    serve al suo link, vedi ``link_lettera``). ``pdf``, ``dcc`` ed
    ``email_completamento`` sono i passi di ``completa_trasmittal_interno``:
    hanno senso solo a lettera completata.

    Returns:
        L'esito del passo, nello stesso formato di emissione e completamento.

    Raises:
        ValueError: passo sconosciuto.
        TrasmittalInternoNonCompletatoError: un passo di completamento su una
            lettera a cui manca ancora una presa visione.
    """
    if passo not in PASSI_LETTERA:
        raise ValueError(f"Passo non valido: deve essere uno fra {', '.join(PASSI_LETTERA)}.")
    if passo == "email":
        return _passo_email_emissione(trasmittal, base_url)
    stato = stato_prese_visione(trasmittal.prese_visione.select_related("utente"))
    if stato["stato"] != STATO_COMPLETATO:
        raise TrasmittalInternoNonCompletatoError(
            "La lettera non ha ancora la presa visione di "
            f"{' e '.join(stato['ruoli_mancanti'])}: PDF, cartella DCC ed email di "
            "completamento arrivano dopo."
        )
    if passo == "pdf":
        return _passo_pdf(trasmittal)
    if passo == "dcc":
        return _passo_dcc(trasmittal)
    return _passo_email_completamento(trasmittal)


# ── Presa visione QC / PROD ────────────────────────────────────────────────────


def siti_lettera(trasmittal):
    """Siti coinvolti nella lettera: unione degli snapshot delle sue righe."""
    return Stabilimento.objects.filter(righe_trasmittal_interno__trasmittal=trasmittal).distinct()


def ruoli_presa_visione_ammessi(trasmittal, utente):
    """Ruoli per cui ``utente`` può prendere visione della lettera.

    Un ruolo è ammesso se l'utente è ``FirmatarioStabilimento`` di quel ruolo
    su almeno uno dei siti coinvolti nella lettera (``RigaTransmittalInterno.siti``).
    """
    return set(
        FirmatarioStabilimento.objects.filter(
            utente=utente, stabilimento__in=siti_lettera(trasmittal)
        ).values_list("ruolo", flat=True)
    )


def _serializza_presa_visione(presa):
    return {
        "ruolo": presa.ruolo,
        "sigla": _SIGLA_RUOLO[presa.ruolo],
        "utente": presa.utente.nome_completo,
        "registrata_il": timezone.localtime(presa.registrata_il).isoformat(),
    }


def stato_prese_visione(prese):
    """Stato di una lettera rispetto alle prese visione QC e PROD.

    Args:
        prese: Le ``PresaVisioneTransmittalInterno`` della lettera, con
            ``utente`` già caricato.

    Returns:
        Dict con ``stato`` (``in_attesa``, ``parziale`` o ``completato``),
        ``ruoli_mancanti`` (sigle, QC prima di PROD) e ``prese_visione``
        (lista di dict ``{"ruolo", "sigla", "utente", "registrata_il"}``,
        QC prima di PROD).
    """
    per_ruolo = {presa.ruolo: presa for presa in prese}
    mancanti = [_SIGLA_RUOLO[r] for r in _RUOLI_PRESA_VISIONE if r not in per_ruolo]
    if not mancanti:
        stato = STATO_COMPLETATO
    elif len(mancanti) == len(_RUOLI_PRESA_VISIONE):
        stato = STATO_IN_ATTESA
    else:
        stato = STATO_PARZIALE
    return {
        "stato": stato,
        "ruoli_mancanti": mancanti,
        "prese_visione": [
            _serializza_presa_visione(per_ruolo[r]) for r in _RUOLI_PRESA_VISIONE if r in per_ruolo
        ],
    }


def _ruolo_da_registrare(ruolo, ammessi, registrate):
    """Il ruolo per cui registrare la presa visione: quello chiesto, o quello dedotto.

    Raises:
        TrasmittalInternoPresaVisioneError: ruolo non valido o non ammesso, o
            da indicare perché l'utente è firmatario di entrambi.
    """
    if ruolo:
        if ruolo not in RuoloFirmatarioStabilimento.values:
            raise TrasmittalInternoPresaVisioneError(f'Ruolo non valido: "{ruolo}".', status=400)
        if ruolo not in ammessi:
            sigla = _SIGLA_RUOLO[ruolo]
            raise TrasmittalInternoPresaVisioneError(
                f"Non puoi prendere visione come {sigla}: non sei firmatario {sigla} di "
                "nessuno dei siti coinvolti nella lettera.",
                status=403,
            )
        return ruolo
    if len(ammessi) == 1:
        return next(iter(ammessi))
    mancanti = [r for r in _RUOLI_PRESA_VISIONE if r in ammessi and r not in registrate]
    if len(mancanti) == 1:
        return mancanti[0]
    if not mancanti:
        return _RUOLI_PRESA_VISIONE[0]  # entrambi già visionati: il chiamante risponde 409
    raise TrasmittalInternoPresaVisioneError(
        "Sei firmatario sia QC sia PROD sui siti di questa lettera: indica per quale ruolo "
        "prendi visione.",
        status=400,
    )


def registra_presa_visione(trasmittal, utente, ruolo=None):
    """Registra la presa visione di ``utente`` e, se completa la lettera, la archivia.

    Può prendere visione un utente ``FirmatarioStabilimento`` di quel ruolo
    su almeno uno dei siti coinvolti nella lettera (``ruoli_presa_visione_ammessi``).
    Il ruolo si deduce dai suoi firmatari; ``ruolo`` serve quando è firmatario
    sia QC sia PROD. Una sola presa visione per ruolo.

    La registrazione blocca la riga del trasmittal (``select_for_update``):
    due prese visione contemporanee si mettono in fila, e solo quella che
    completa la coppia QC + PROD avvia ``completa_trasmittal_interno`` (PDF,
    DCC, email di completamento), fuori dalla transazione e best-effort.

    Args:
        trasmittal: La lettera.
        utente: Chi clicca "Presa visione" (l'utente autenticato).
        ruolo: ``RuoloFirmatarioStabilimento`` scelto, facoltativo.

    Returns:
        Dict con ``trasmittal_id``, ``nome``, ``presa_visione`` (la presa
        visione registrata), lo stato (``stato_prese_visione``) e
        ``completamento``: ``None`` se manca ancora un ruolo, altrimenti
        l'esito di ``completa_trasmittal_interno``.

    Raises:
        TrasmittalInternoPresaVisioneError: utente non autorizzato (403),
            ruolo già visionato (409), ruolo non valido o da indicare (400).
    """
    with transaction.atomic():
        trasmittal = (
            TransmittalInterno.objects.select_for_update()
            .select_related("testata", "creato_da")
            .get(pk=trasmittal.pk)
        )
        ammessi = ruoli_presa_visione_ammessi(trasmittal, utente)
        if not ammessi:
            raise TrasmittalInternoPresaVisioneError(
                "Non puoi prendere visione di questa lettera: non sei firmatario QC o PROD "
                "di nessuno dei siti coinvolti.",
                status=403,
            )
        registrate = {p.ruolo: p for p in trasmittal.prese_visione.select_related("utente")}
        ruolo = _ruolo_da_registrare(ruolo, ammessi, registrate)
        if ruolo in registrate:
            gia = registrate[ruolo]
            raise TrasmittalInternoPresaVisioneError(
                f"La presa visione {_SIGLA_RUOLO[ruolo]} è già stata registrata da "
                f"{gia.utente.nome_completo} il {_data_ora(gia.registrata_il)}.",
                status=409,
            )
        try:
            with transaction.atomic():
                presa = PresaVisioneTransmittalInterno.objects.create(
                    trasmittal=trasmittal, utente=utente, ruolo=ruolo
                )
        except IntegrityError:
            raise TrasmittalInternoPresaVisioneError(
                f"La presa visione {_SIGLA_RUOLO[ruolo]} è già stata registrata.", status=409
            ) from None
        registrate[ruolo] = presa

    logger.info(
        'Presa visione %s del trasmittal interno "%s" registrata da %s.',
        _SIGLA_RUOLO[ruolo],
        trasmittal.nome,
        utente.get_username(),
    )
    stato = stato_prese_visione(registrate.values())
    risultato = {
        "trasmittal_id": trasmittal.pk,
        "nome": trasmittal.nome,
        "presa_visione": _serializza_presa_visione(presa),
        **stato,
        "completamento": None,
    }
    if stato["stato"] == STATO_COMPLETATO:
        risultato["completamento"] = completa_trasmittal_interno(trasmittal)
    return risultato


MAX_MESSAGGIO_EMAIL = 2000


def emetti_trasmittal_interno(
    testata,
    righe_payload,
    utente,
    note="",
    data=None,
    destinatari=None,
    messaggio="",
    base_url="",
):
    """Crea una lettera di trasmittal interno e invia l'email di emissione.

    Crea il trasmittal (con i destinatari auto-risolti, sostituiti da
    ``destinatari`` se dato — la conferma dell'anteprima, eventualmente
    modificata dall'utente) e invia l'email di emissione
    (``invia_email_emissione``). ``messaggio`` è il testo facoltativo scritto
    prima dell'invio: va nell'email, sopra la tabella; ``base_url`` serve al
    link della lettera (vedi ``link_lettera``).

    PDF sul fileserver e cartella DCC NON si preparano qui: arrivano quando
    QC e PROD hanno preso visione (``registra_presa_visione``).

    Solo la creazione (righe + destinatari) è atomica e può far fallire tutta
    l'operazione. L'email è best-effort: un suo fallimento non annulla la
    lettera già creata ed è riportato nel risultato (si ritenta con
    ``riprova_passo``). Mai fallire in silenzio.

    Raises:
        ValueError: selezione non valida (vedi ``_prepara_righe``), nessun
            sito coinvolto (vedi ``_verifica_siti_lettera``), destinatari non
            validi (vedi ``sostituisci_destinatari``) o messaggio troppo lungo
            — in questi casi non viene creata nessuna lettera.

    Returns:
        Dict con ``trasmittal_id``, ``nome``, lo stato delle prese visione
        (``stato_prese_visione``: appena emessa è ``in_attesa``) ed
        ``email``: ``{"ok": bool, "errore": str | None, ...}``.
    """
    messaggio = str(messaggio or "").strip()
    if len(messaggio) > MAX_MESSAGGIO_EMAIL:
        raise ValueError(
            f"Il messaggio dell'email può avere al massimo {MAX_MESSAGGIO_EMAIL} caratteri."
        )
    righe = _prepara_righe(testata, righe_payload)
    _verifica_siti_lettera(righe)
    # Un'unica transazione: se i destinatari confermati non passano la
    # validazione, la lettera (e il suo progressivo del giorno) non deve
    # restare nel database senza email.
    with transaction.atomic():
        trasmittal = crea_trasmittal_interno(testata, righe, utente, data=data, note=note)
        if messaggio:
            trasmittal.messaggio_email = messaggio
            trasmittal.save(update_fields=["messaggio_email"])
        if destinatari is not None:
            sostituisci_destinatari(trasmittal, destinatari)

    return {
        "trasmittal_id": trasmittal.pk,
        "nome": trasmittal.nome,
        **stato_prese_visione([]),
        "email": _passo_email_emissione(trasmittal, base_url),
    }


def elenco_trasmittal_interni(testata, utente=None):
    """Lettere di trasmittal interno già emesse per la commessa, più recenti prima.

    ``annullabile`` segue esattamente la regola imposta da
    ``annulla_trasmittal_interno``: solo l'ultimo progressivo di ciascun
    giorno lo è (il progressivo riparte ogni giorno, quindi più di una
    lettera può essere "l'ultima del suo giorno" se la commessa ha lettere
    emesse in giorni diversi).

    Ogni lettera porta lo stato delle prese visione (``stato_prese_visione``)
    e, in ``puo_prendere_visione``, i ruoli (``{"ruolo", "sigla"}``) per cui
    ``utente`` può registrare ora la presa visione: quelli di cui è
    firmatario su un sito della lettera e che mancano ancora. Senza
    ``utente`` la lista è vuota.

    ``pdf_presente`` dice se il PDF è sul fileserver (``None`` se la cartella
    non si può leggere): senza file il link non porterebbe a niente. Il PDF
    si salva solo a lettera completata.
    """
    lettere = list(
        testata.trasmittal_interni.select_related("creato_da")
        .prefetch_related(
            Prefetch(
                "prese_visione",
                queryset=PresaVisioneTransmittalInterno.objects.select_related("utente"),
            ),
            Prefetch("righe", queryset=RigaTransmittalInterno.objects.prefetch_related("siti")),
        )
        .order_by("-data", "-progressivo")
    )
    firmatario_di = (
        set(
            FirmatarioStabilimento.objects.filter(utente=utente).values_list(
                "stabilimento_id", "ruolo"
            )
        )
        if utente is not None
        else set()
    )
    pdf_sul_fileserver = _pdf_nella_cartella(testata.job)
    giorni_visti = set()
    risultato = []
    for t in lettere:
        annullabile = t.data not in giorni_visti
        giorni_visti.add(t.data)
        righe = list(t.righe.all())
        siti = {sito.pk for riga in righe for sito in riga.siti.all()}
        prese = list(t.prese_visione.all())
        registrati = {presa.ruolo for presa in prese}
        ammessi = {ruolo for stabilimento_id, ruolo in firmatario_di if stabilimento_id in siti}
        risultato.append(
            {
                "id": t.pk,
                "nome": t.nome,
                "data": t.data.isoformat(),
                "n_documenti": len(righe),
                "creato_da": t.creato_da.nome_completo,
                "annullabile": annullabile,
                "pdf_presente": (
                    None
                    if pdf_sul_fileserver is None
                    else f"{t.nome}.pdf".lower() in pdf_sul_fileserver
                ),
                **stato_prese_visione(prese),
                "puo_prendere_visione": [
                    {"ruolo": ruolo, "sigla": _SIGLA_RUOLO[ruolo]}
                    for ruolo in _RUOLI_PRESA_VISIONE
                    if ruolo in ammessi and ruolo not in registrati
                ],
            }
        )
    return risultato


def _pdf_nella_cartella(job):
    """Nomi (minuscoli) dei file nella cartella dei PDF delle lettere della commessa.

    Una sola lettura della cartella per tutto l'elenco, non un controllo per
    lettera sulla share di rete. ``None`` se la cartella non si può leggere:
    in quel caso non si sa se i PDF ci sono.
    """
    cartella = _percorso_pdf_da(job, "x").parent
    try:
        if not cartella.is_dir():
            return set()
        return {f.name.lower() for f in cartella.iterdir()}
    except OSError:
        logger.warning("Cartella dei trasmittal interni %s non leggibile.", cartella, exc_info=True)
        return None


def annulla_trasmittal_interno(trasmittal, utente):
    """Annulla l'ultimo trasmittal interno emesso per la commessa in quel giorno.

    Il progressivo riparte ogni giorno per commessa (vedi
    ``prossimo_progressivo``), quindi "ultimo" è ristretto a
    ``(testata, data)`` di ``trasmittal`` — non all'intera commessa — così
    il progressivo resta coerente: annullare libera davvero il numero più
    alto di quel giorno, non un numero intermedio.

    Elimina il record, le righe e le prese visione (CASCADE) e, se la
    lettera era già completata, rimuove il PDF dal fileserver e i file che
    questo trasmittal aveva copiato nella cartella preparata per il DCC. La cartella stessa viene rimossa solo se resta vuota dopo aver
    tolto quei file: se contiene altro — mai scritto da questo trasmittal,
    dato che il nome della cartella è unico per trasmittal — non viene
    toccata.

    Solo l'eliminazione del record (righe comprese) è transazionale: se la
    rimozione dei file sul fileserver fallisce a metà, il record non sparisce
    comunque a metà — o l'intera cancellazione DB riesce, o nessuna.
    L'eventuale file orfano rimasto sul fileserver è segnalato nel log, non
    bloccante (stessa scelta già fatta per ``trasmittal_archivio.annulla_trasmittal``).

    Le email eventualmente già inviate (emissione, completamento) non
    possono essere ritirate: l'esito lo dice sempre esplicitamente, per un
    avviso chiaro in UI.

    Args:
        trasmittal: Il ``TransmittalInterno`` da annullare.
        utente: Chi esegue l'annullamento (solo per il log).

    Returns:
        Dict con ``pdf_rimosso`` (bool), ``cartella_dcc_rimossa`` (bool) ed
        ``email_avviso`` (stringa fissa, sempre presente).

    Raises:
        TrasmittalInternoAnnullaError: se non è l'ultimo trasmittal interno
            emesso quel giorno per quella commessa.
    """
    with transaction.atomic():
        trasmittal = TransmittalInterno.objects.select_for_update().get(pk=trasmittal.pk)
        testata = trasmittal.testata
        ultimo = (
            TransmittalInterno.objects.filter(testata=testata, data=trasmittal.data)
            .aggregate(m=Max("progressivo"))
            .get("m")
        )
        if trasmittal.progressivo != ultimo:
            raise TrasmittalInternoAnnullaError(
                "Si può annullare solo l'ultimo trasmittal interno emesso in quel giorno."
            )
        nome = trasmittal.nome
        righe_cliente = list(trasmittal.righe.filter(cliente=True).select_related("documento"))
        pdf_path = percorso_pdf(trasmittal)
        cartella_dcc = _percorso_dcc_da(testata.job, nome)
        trasmittal.delete()

    logger.info('Trasmittal interno "%s" annullato da %s.', nome, utente.get_username())

    pdf_rimosso = False
    try:
        if pdf_path.is_file():
            pdf_path.unlink()
            pdf_rimosso = True
    except OSError as exc:
        logger.warning('Impossibile rimuovere il PDF del trasmittal interno "%s": %s', nome, exc)

    cartella_dcc_rimossa = False
    if cartella_dcc.is_dir():
        for riga in righe_cliente:
            for trovato in trova_file(cartella_dcc, riga.documento.vendor_doc):
                try:
                    Path(trovato["percorso"]).unlink()
                except OSError as exc:
                    logger.warning(
                        'Impossibile rimuovere "%s" dalla cartella DCC di "%s": %s',
                        trovato["percorso"],
                        nome,
                        exc,
                    )
        try:
            cartella_dcc.rmdir()
            cartella_dcc_rimossa = True
        except OSError:
            pass  # non vuota: contiene altro, non è di questo trasmittal — non la tocchiamo

    return {
        "pdf_rimosso": pdf_rimosso,
        "cartella_dcc_rimossa": cartella_dcc_rimossa,
        "email_avviso": (
            "Se la lettera era già stata inviata via email, quell'invio resta valido: "
            "l'annullamento non può richiamarlo."
        ),
    }
