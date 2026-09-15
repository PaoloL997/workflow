"""Anagrafiche e archivio del trasmittal interno (form MQ 7.5-04)."""

import logging
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Max, Prefetch
from django.utils import timezone

from ..models import (
    DestinatarioTransmittalInterno,
    DestinazioneDocumento,
    Documento,
    IndirizzoStabilimento,
    OrigineDestinatarioTransmittalInterno,
    PersonaCommessa,
    Reparto,
    RigaTransmittalInterno,
    RuoloPersonaCommessa,
    Stabilimento,
    TipoDestinatarioTransmittalInterno,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
)
from .fileserver import get_base_path, get_jobs_root, trova_file
from .revisione_label import format_revisione_label

logger = logging.getLogger(__name__)

EMAIL_EXPORT = "export@brembanarolle.com"


class TrasmittalInternoAnnullaError(Exception):
    """Annullamento non consentito (non è l'ultimo trasmittal del giorno)."""


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
    codici = list(codici_bc or [])
    if not codici:
        return {"to": [], "cc": []}

    indirizzi = IndirizzoStabilimento.objects.filter(
        stabilimento__codice_bc__in=codici, attivo=True
    ).values_list("email", "tipo")

    to, cc = [], []
    visti_to, visti_cc = set(), set()
    for email, tipo in indirizzi:
        chiave = email.strip().lower()
        if tipo == TipoIndirizzoStabilimento.TO:
            if chiave not in visti_to:
                visti_to.add(chiave)
                to.append(email)
        elif chiave not in visti_cc:
            visti_cc.add(chiave)
            cc.append(email)

    cc = [email for email in cc if email.strip().lower() not in visti_to]
    return {"to": to, "cc": cc}


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


def documenti_ut(testata):
    """Documenti UT della commessa: le righe della griglia destinazioni.

    Reparto.acronimo "UT" identifica il reparto; Documento.reparto ne porta
    il nome (vedi core.services.commesse.prepara_per_dcc per lo stesso
    accoppiamento). Nessun reparto con quell'acronimo → nessun documento.
    """
    reparto_ut = Reparto.objects.filter(acronimo="UT").first()
    if reparto_ut is None:
        return Documento.objects.none()
    return Documento.objects.filter(testata=testata, reparto=reparto_ut.nome)


def elenco_destinazioni_ut(testata):
    """Documenti UT della commessa con le destinazioni cartacee correnti.

    Returns:
        Lista di dict ``{"id", "vendor_doc", "doc_title", "codici_bc"}``,
        ordinata per ``vendor_doc``. ``codici_bc`` è la lista dei
        ``Stabilimento.codice_bc`` attualmente destinatari del documento.
    """
    documenti = (
        documenti_ut(testata).prefetch_related("destinazioni__stabilimento").order_by("vendor_doc")
    )
    return [
        {
            "id": documento.pk,
            "vendor_doc": documento.vendor_doc,
            "doc_title": documento.doc_title,
            "codici_bc": [
                destinazione.stabilimento.codice_bc for destinazione in documento.destinazioni.all()
            ],
        }
        for documento in documenti
    ]


def imposta_destinazioni_ut(testata, documento_id, codici_bc):
    """``imposta_destinazioni``, ristretto ai documenti UT della commessa data.

    Raises:
        Documento.DoesNotExist: se ``documento_id`` non è un documento UT di
            ``testata`` (commessa sbagliata, o non è UT).
    """
    documento = documenti_ut(testata).get(pk=documento_id)
    imposta_destinazioni(documento, codici_bc)
    return documento


def imposta_destinazione_stabilimento_bulk(testata, codice_bc, documento_ids, attiva):
    """Attiva o disattiva un singolo stabilimento sulle destinazioni di più documenti UT.

    Usata per la selezione in blocco della griglia destinazioni: il chiamante
    passa esplicitamente gli id dei documenti su cui agire (tipicamente quelli
    attualmente visibili dopo un filtro), così l'azione tocca solo quelli.
    Eventuali id che non sono documenti UT di ``testata`` — perché di
    un'altra commessa, o non UT — vengono ignorati silenziosamente: non è un
    errore, sono semplicemente fuori dal set su cui questa griglia può agire.

    Returns:
        I documenti effettivamente aggiornati.
    """
    documenti = list(
        documenti_ut(testata)
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
    4. se almeno un documento è di tipo SHn, ``EMAIL_EXPORT`` → CC.

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
            ``"tpi"``, ``"note"``, ``"cliente"`` (default ``True``).
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
                tpi=riga.get("tpi", ""),
                note=riga.get("note", ""),
                cliente=riga.get("cliente", True),
                posizione=posizione,
            )
            riga_creata.siti.set(siti_del_documento(documento))

        DestinatarioTransmittalInterno.objects.bulk_create(
            _destinatari_trasmittal(trasmittal, testata, documenti, siti_coinvolti(documenti))
        )

    return trasmittal


def data_impegno(oggi):
    """Termine entro cui va completata la distribuzione delle copie cartacee.

    Il giorno lavorativo successivo a ``oggi``: normalmente il giorno dopo,
    ma se questo cade di sabato o domenica si passa al lunedì (quindi il
    venerdì il termine è tre giorni dopo). Non è la data di firma.
    """
    successivo = oggi + timedelta(days=1)
    while successivo.weekday() >= 5:  # 5 = sabato, 6 = domenica
        successivo += timedelta(days=1)
    return successivo


def percorso_pdf(trasmittal):
    """Percorso del PDF di una lettera: ``{JOBS}/{job}/Progetto/UT/Transmittal/{nome}.pdf``."""
    return (
        get_jobs_root()
        / trasmittal.testata.job
        / "Progetto"
        / "UT"
        / "Transmittal"
        / f"{trasmittal.nome}.pdf"
    )


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
    cartella = get_base_path(job, "DCC") / "DA SPEDIRE" / trasmittal.nome
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
            trova_file(get_base_path(job, reparto.acronimo), documento.vendor_doc)
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


def stato_file_documento_ut(documento):
    """Se il file corrente del documento UT è risolvibile sul fileserver.

    Stessa logica semplificata di ``prepara_per_dcc``: nella cartella base
    del reparto, per nome (``trova_file``). Zero o più corrispondenze non è
    risolvibile — stessa regola, stesso esito di quando la lettera arriverà
    davvero alla preparazione DCC, senza sorprese a quel punto.

    Returns:
        Dict ``{"trovato": bool, "modificato_il": datetime | None}``.
    """
    reparto = Reparto.objects.filter(nome=documento.reparto).first()
    if not reparto or not reparto.acronimo:
        return {"trovato": False, "modificato_il": None}
    trovati = trova_file(
        get_base_path(documento.testata.job, reparto.acronimo), documento.vendor_doc
    )
    if len(trovati) != 1:
        return {"trovato": False, "modificato_il": None}
    try:
        mtime = Path(trovati[0]["percorso"]).stat().st_mtime
    except OSError:
        return {"trovato": True, "modificato_il": None}
    return {
        "trovato": True,
        "modificato_il": datetime.fromtimestamp(mtime, tz=timezone.get_current_timezone()),
    }


def elenco_selezione_ut(testata):
    """Documenti UT della commessa per la selezione della lettera trasmittal interno.

    A differenza della griglia destinazioni, ogni documento porta anche la
    sua validità per la lettera: un documento senza revisione registrata o
    senza file risolvibile sul fileserver è segnalato SUBITO qui
    (``selezionabile`` False, ``motivo`` spiegato) — non al momento della
    creazione come faceva il vecchio strumento Excel, che bloccava l'intera
    lettera.

    Returns:
        Lista di dict ordinata per ``vendor_doc``, uno per documento, con:
        - ``id``, ``vendor_doc``, ``doc_title``
        - ``revisione_corrente``: etichetta della revisione più recente
          ("" se nessuna)
        - ``file_modificato_il``: ISO datetime del file risolto, o ``None``
        - ``siti``: destinazioni cartacee salvate (INVOLVED SITES), lista di
          dict ``{"sigla", "nome", "codice_bc"}``
        - ``selezionabile``: bool
        - ``motivo``: perché non è selezionabile, altrimenti ``""``
    """
    risultato = []
    for documento in documenti_ut(testata).order_by("vendor_doc"):
        voce = {
            "id": documento.pk,
            "vendor_doc": documento.vendor_doc,
            "doc_title": documento.doc_title,
            "revisione_corrente": "",
            "file_modificato_il": None,
            "siti": [_serializza_sito(s) for s in siti_del_documento(documento)],
            "selezionabile": False,
            "motivo": "",
        }
        latest_rev = documento.revisioni.order_by("-rev_no", "-pk").first()
        if latest_rev is None:
            voce["motivo"] = "Nessuna revisione registrata."
            risultato.append(voce)
            continue
        voce["revisione_corrente"] = format_revisione_label(
            latest_rev.rev_no, latest_rev.rev_let, testata.rev_let_flag
        )
        stato_file = stato_file_documento_ut(documento)
        if not stato_file["trovato"]:
            voce["motivo"] = "Nessun file trovato sul fileserver."
            risultato.append(voce)
            continue
        voce["file_modificato_il"] = (
            stato_file["modificato_il"].isoformat() if stato_file["modificato_il"] else None
        )
        voce["selezionabile"] = True
        risultato.append(voce)
    return risultato


def _prepara_righe(testata, righe_payload):
    """Valida e converte il payload delle righe (dict JSON) per ``crea_trasmittal_interno``.

    Ogni voce richiede ``documento_id`` (un documento UT selezionabile di
    questa commessa) e ``revisione``; ``copie``, ``tpi``, ``note``,
    ``cliente`` sono opzionali. Il primo problema trovato interrompe con un
    ``ValueError`` esplicito — niente lettera creata a metà da un payload
    malformato o da una selezione che nel frattempo è diventata non valida.
    """
    if not righe_payload:
        raise ValueError("Selezionare almeno un documento.")
    stati = {voce["id"]: voce for voce in elenco_selezione_ut(testata)}
    documenti_map = {d.pk: d for d in documenti_ut(testata)}
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
        righe.append(
            {
                "documento": documenti_map[documento_id],
                "revisione": revisione,
                "copie": voce.get("copie") or None,
                "tpi": str(voce.get("tpi") or "").strip(),
                "note": str(voce.get("note") or "").strip(),
                "cliente": bool(voce.get("cliente", True)),
            }
        )
    return righe


def anteprima_destinatari(testata, documenti):
    """Destinatari che risulterebbero per una lettera con questi documenti, senza persistere nulla."""
    return _costruisci_destinatari(testata, documenti, siti_coinvolti(documenti))


def anteprima_trasmittal(testata, righe_payload):
    """Anteprima di una lettera: riepilogo righe, destinatari risolti, ruoli mancanti.

    Non persiste nulla. Solleva ``ValueError`` se il payload non è valido
    (vedi ``_prepara_righe``): stesso controllo che varrà alla creazione
    vera, così l'anteprima non promette una lettera che poi la conferma
    rifiuterebbe.
    """
    righe = _prepara_righe(testata, righe_payload)
    documenti = [riga["documento"] for riga in righe]
    return {
        "righe": [
            {
                "documento_id": riga["documento"].pk,
                "vendor_doc": riga["documento"].vendor_doc,
                "doc_title": riga["documento"].doc_title,
                "revisione": riga["revisione"],
                "copie": riga["copie"],
                "tpi": riga["tpi"],
                "note": riga["note"],
                "cliente": riga["cliente"],
                "siti": [_serializza_sito(s) for s in siti_del_documento(riga["documento"])],
            }
            for riga in righe
        ],
        "destinatari": anteprima_destinatari(testata, documenti),
        "ruoli_mancanti": ruoli_persona_mancanti(testata),
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


def _corpo_email_trasmittal(trasmittal, percorso):
    """Corpo dell'email: è la lettera per chi la riceve, non solo un avviso.

    Include la tabella delle righe (stesse colonne del PDF, così il
    destinatario sa cosa gli è stato trasmesso senza dover aprire
    l'allegato), il percorso completo dove il PDF è salvato sul fileserver
    e il promemoria che il modulo va firmato a distribuzione avvenuta.
    """
    return (
        f"Trasmittal interno {trasmittal.nome} — commessa {trasmittal.testata.job}.\n\n"
        f"{_tabella_testo_righe(trasmittal)}\n\n"
        f"Salvato in: {percorso}\n\n"
        "Il modulo va firmato (Produzione e Qualità) a distribuzione delle copie "
        "cartacee avvenuta."
    )


def invia_email_trasmittal(trasmittal, pdf_bytes=None):
    """Invia via email il trasmittal interno ai destinatari TO/CC registrati.

    Oggetto e corpo replicano il vecchio strumento: l'oggetto porta il
    riferimento al modulo del sistema qualità (non è decorativo, identifica
    il documento), il corpo è la lettera stessa per chi la riceve — righe,
    percorso di salvataggio, promemoria di firma — non un avviso generico
    che rimanda all'allegato.

    Args:
        pdf_bytes: bytes del PDF da allegare; se omesso, generato al volo
            (un passo in più — preferire passare quello già generato da
            ``salva_pdf`` quando disponibile).

    Returns:
        Dict ``{"to": [...], "cc": [...]}`` con gli indirizzi usati.

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

    if pdf_bytes is None:
        from src.pdf import genera_trasmittal_interno_pdf

        pdf_bytes = genera_trasmittal_interno_pdf(trasmittal)

    email = EmailMessage(
        subject=f"DOCUMENT TRANSMITTAL [Form MQ 7.5-04 Rev.0]: {trasmittal.nome}",
        body=_corpo_email_trasmittal(trasmittal, percorso_pdf(trasmittal)),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=to,
        cc=cc,
    )
    email.attach(f"{trasmittal.nome}.pdf", pdf_bytes, "application/pdf")
    email.send(fail_silently=False)
    return {"to": to, "cc": cc}


def emetti_trasmittal_interno(testata, righe_payload, utente, note="", data=None, destinatari=None):
    """Crea, archivia e distribuisce una lettera di trasmittal interno.

    Un'unica operazione: crea il trasmittal (con i destinatari auto-risolti,
    sostituiti da ``destinatari`` se dato — la conferma dell'anteprima,
    eventualmente modificata dall'utente), salva il PDF sul fileserver,
    prepara la cartella DCC, invia l'email.

    Solo la creazione (righe + destinatari) è atomica e può far fallire tutta
    l'operazione: senza una lettera valida non c'è nulla da archiviare o
    spedire. Ogni passo successivo — PDF, DCC, email — è indipendente e
    best-effort: un suo fallimento non annulla la lettera già creata né gli
    altri passi, ed è riportato nel risultato. Mai fallire in silenzio, mai
    lasciare la lettera "a metà" senza dirlo.

    Raises:
        ValueError: selezione non valida (vedi ``_prepara_righe``) o
            destinatari non validi (vedi ``sostituisci_destinatari``) — in
            questi casi non viene creata nessuna lettera.

    Returns:
        Dict con ``trasmittal_id``, ``nome`` e, per ciascuno di
        ``pdf``/``dcc``/``email``, ``{"ok": bool, "errore": str | None, ...}``.
    """
    righe = _prepara_righe(testata, righe_payload)
    trasmittal = crea_trasmittal_interno(testata, righe, utente, data=data, note=note)
    if destinatari is not None:
        sostituisci_destinatari(trasmittal, destinatari)

    risultato = {"trasmittal_id": trasmittal.pk, "nome": trasmittal.nome}

    pdf_bytes = None
    try:
        percorso = salva_pdf(trasmittal)
        pdf_bytes = percorso.read_bytes()
        risultato["pdf"] = {"ok": True, "errore": None, "percorso": str(percorso)}
    except Exception as exc:
        logger.exception('Salvataggio PDF del trasmittal interno "%s" fallito.', trasmittal.nome)
        risultato["pdf"] = {"ok": False, "errore": str(exc), "percorso": None}

    try:
        esito_dcc = prepara_per_dcc(trasmittal)
        risultato["dcc"] = {"ok": True, "errore": None, **esito_dcc}
    except Exception as exc:
        logger.exception('Preparazione DCC del trasmittal interno "%s" fallita.', trasmittal.nome)
        risultato["dcc"] = {
            "ok": False,
            "errore": str(exc),
            "cartella": None,
            "copiati": [],
            "mancanti": [],
        }

    try:
        esito_email = invia_email_trasmittal(trasmittal, pdf_bytes=pdf_bytes)
        risultato["email"] = {"ok": True, "errore": None, **esito_email}
    except Exception as exc:
        logger.exception('Invio email del trasmittal interno "%s" fallito.', trasmittal.nome)
        risultato["email"] = {"ok": False, "errore": str(exc), "to": [], "cc": []}

    return risultato


def elenco_trasmittal_interni(testata):
    """Lettere di trasmittal interno già emesse per la commessa, più recenti prima.

    ``annullabile`` segue esattamente la regola imposta da
    ``annulla_trasmittal_interno``: solo l'ultimo progressivo di ciascun
    giorno lo è (il progressivo riparte ogni giorno, quindi più di una
    lettera può essere "l'ultima del suo giorno" se la commessa ha lettere
    emesse in giorni diversi).
    """
    lettere = list(
        testata.trasmittal_interni.select_related("creato_da").order_by("-data", "-progressivo")
    )
    giorni_visti = set()
    risultato = []
    for t in lettere:
        annullabile = t.data not in giorni_visti
        giorni_visti.add(t.data)
        risultato.append(
            {
                "id": t.pk,
                "nome": t.nome,
                "data": t.data.isoformat(),
                "n_documenti": t.righe.count(),
                "creato_da": t.creato_da.nome_completo,
                "annullabile": annullabile,
            }
        )
    return risultato


def annulla_trasmittal_interno(trasmittal, utente):
    """Annulla l'ultimo trasmittal interno emesso per la commessa in quel giorno.

    Il progressivo riparte ogni giorno per commessa (vedi
    ``prossimo_progressivo``), quindi "ultimo" è ristretto a
    ``(testata, data)`` di ``trasmittal`` — non all'intera commessa — così
    il progressivo resta coerente: annullare libera davvero il numero più
    alto di quel giorno, non un numero intermedio.

    Elimina il record e le righe (CASCADE), rimuove il PDF dal fileserver e
    i file che questo trasmittal aveva copiato nella cartella preparata per
    il DCC. La cartella stessa viene rimossa solo se resta vuota dopo aver
    tolto quei file: se contiene altro — mai scritto da questo trasmittal,
    dato che il nome della cartella è unico per trasmittal — non viene
    toccata.

    Solo l'eliminazione del record (righe comprese) è transazionale: se la
    rimozione dei file sul fileserver fallisce a metà, il record non sparisce
    comunque a metà — o l'intera cancellazione DB riesce, o nessuna.
    L'eventuale file orfano rimasto sul fileserver è segnalato nel log, non
    bloccante (stessa scelta già fatta per ``trasmittal_archivio.annulla_trasmittal``).

    L'email eventualmente già inviata non può essere ritirata: l'esito lo
    dice sempre esplicitamente, per un avviso chiaro in UI.

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
        cartella_dcc = get_base_path(testata.job, "DCC") / "DA SPEDIRE" / nome
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
