"""Anagrafiche e archivio del trasmittal interno (form MQ 7.5-04)."""

import re
import shutil
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models import (
    DestinatarioTransmittalInterno,
    DestinazioneDocumento,
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

EMAIL_EXPORT = "export@brembanarolle.com"

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


def _email_persone(testata, ruolo):
    """Email, in ordine di inserimento, delle persone risolte (utente registrato) per un ruolo."""
    return list(
        PersonaCommessa.objects.filter(testata=testata, ruolo=ruolo, utente__isnull=False)
        .exclude(utente__email="")
        .order_by("id")
        .values_list("utente__email", flat=True)
    )


def _destinatari_trasmittal(trasmittal, testata, documenti, siti):
    """Costruisce i ``DestinatarioTransmittalInterno`` (non salvati) secondo le regole.

    Ordine di applicazione (rilevante per la deduplica finale):
    1. indirizzi di stabilimento dei siti coinvolti (TO/CC da anagrafica);
    2. PM della commessa → TO;
    3. PE e QCI della commessa → CC;
    4. se almeno un documento è di tipo SHn, ``EMAIL_EXPORT`` → CC.

    Un ruolo non valorizzato su nessuna ``PersonaCommessa`` risolta per la
    commessa non è un errore: contribuisce semplicemente zero indirizzi.

    Deduplica finale, case-insensitive sull'email normalizzata: un indirizzo
    presente sia tra i TO che tra i CC resta solo tra i TO, mantenendo
    l'origine della sua prima occorrenza (nell'ordine sopra).

    WE non è incluso: non è definito da quale campo della commessa dedurre la
    sua lista di distribuzione (nessun ``OrigineDestinatarioTransmittalInterno.WE``
    esiste per questo motivo) — va aggiunto quando quella sorgente sarà chiara,
    non inventato qui.
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
        DestinatarioTransmittalInterno(
            trasmittal=trasmittal,
            email=email_per_chiave[chiave],
            tipo=TipoDestinatarioTransmittalInterno.TO
            if to_per_chiave.get(chiave)
            else TipoDestinatarioTransmittalInterno.CC,
            origine=origine_per_chiave[chiave],
        )
        for chiave in ordine
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


def salva_pdf(trasmittal):
    """Genera il PDF del trasmittal interno e lo scrive sul fileserver.

    Destinazione: ``{JOBS}/{job}/Progetto/UT/Transmittal/{nome}.pdf``,
    creando le cartelle mancanti.

    Returns:
        Il ``Path`` del file scritto.

    Raises:
        PermissionError: se il percorso risultante è fuori dalla cartella JOBS.
    """
    job = trasmittal.testata.job
    cartella = get_jobs_root() / job / "Progetto" / "UT" / "Transmittal"
    destinazione = cartella / f"{trasmittal.nome}.pdf"
    try:
        destinazione.resolve().relative_to(get_jobs_root().resolve())
    except ValueError:
        raise PermissionError("Percorso non autorizzato: fuori dalla cartella JOBS.") from None

    from src.pdf import genera_trasmittal_interno_pdf

    pdf_bytes = genera_trasmittal_interno_pdf(trasmittal)
    cartella.mkdir(parents=True, exist_ok=True)
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
