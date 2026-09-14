"""Anagrafiche e archivio del trasmittal interno (form MQ 7.5-04)."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models import (
    DestinatarioTransmittalInterno,
    DestinazioneDocumento,
    IndirizzoStabilimento,
    OrigineDestinatarioTransmittalInterno,
    RigaTransmittalInterno,
    Stabilimento,
    TipoDestinatarioTransmittalInterno,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
)
from .fileserver import get_jobs_root


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

    Non tocca nessuno stato dei documenti. La risoluzione dei destinatari
    PM/PE/QCI e la regola "export@" per i documenti SHn non sono ancora
    implementate: la sorgente dati non è definita, quindi non vengono
    inventate qui.
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

        # PM, PE, QCI ed export@ (documenti SHn): punti di innesto, non
        # ancora implementati — vedi il docstring.
        indirizzi = indirizzi_per_siti([s.codice_bc for s in siti_coinvolti(documenti)])
        DestinatarioTransmittalInterno.objects.bulk_create(
            [
                DestinatarioTransmittalInterno(
                    trasmittal=trasmittal,
                    email=email,
                    tipo=TipoDestinatarioTransmittalInterno.TO,
                    origine=OrigineDestinatarioTransmittalInterno.STABILIMENTO,
                )
                for email in indirizzi["to"]
            ]
            + [
                DestinatarioTransmittalInterno(
                    trasmittal=trasmittal,
                    email=email,
                    tipo=TipoDestinatarioTransmittalInterno.CC,
                    origine=OrigineDestinatarioTransmittalInterno.STABILIMENTO,
                )
                for email in indirizzi["cc"]
            ]
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
