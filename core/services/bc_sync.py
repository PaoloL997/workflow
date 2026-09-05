"""Controllo di congruenza giornaliero fra Business Central e l'archivio.

Quando una commessa viene creata, cliente, PO, descrizione e data consegna
vengono precompilati da Business Central (vedi ``commesse.fetch_from_bc``).
Quei dati in BC possono cambiare nel tempo: questo modulo li riconfronta,
aggiorna le testate disallineate e tiene traccia di ogni modifica in
``AggiornamentoBC``.

Regole di allineamento:
- BC è la fonte di verità solo per i campi che precompila;
- un valore vuoto in BC non sovrascrive mai un valore presente nel sistema;
- le commesse chiuse (con data consegna effettiva) sono escluse, salvo
  richiesta esplicita.

Punto di ingresso operativo: ``python manage.py sync_business_central``,
da schedulare una volta al giorno.
"""

from __future__ import annotations

import logging

import pandas as pd
from django.db import transaction

from ..date_fmt import format_display_date
from ..models import AggiornamentoBC, Testata
from .commesse import _parse_date, fetch_from_bc

logger = logging.getLogger(__name__)

# Campi di Testata precompilati da Business Central: sono quelli da tenere
# allineati. ``job`` è la chiave di ricerca e non viene mai toccato.
CAMPI_SINCRONIZZATI = {
    "client": "Cliente",
    "po_no": "PO cliente",
    "job_detail": "Descrizione",
    "delivery_date": "Data consegna",
}


class BusinessCentralNonDisponibile(Exception):
    """La connessione a Business Central non è utilizzabile."""


def _max_length(campo: str) -> int | None:
    return Testata._meta.get_field(campo).max_length


def _normalizza(campo: str, valore):
    """Valore confrontabile per un campo, oppure ``None`` se non valorizzato.

    I testi vengono ripuliti e troncati alla lunghezza massima della colonna,
    così un valore BC più lungo non risulta perennemente disallineato rispetto
    a quello salvato.
    """
    if valore is None:
        return None
    try:
        if pd.isna(valore):
            return None
    except (TypeError, ValueError):
        pass
    if campo.endswith("_date"):
        if isinstance(valore, str):
            return _parse_date(valore.strip()[:10])
        if hasattr(valore, "date"):  # datetime / pandas.Timestamp
            return valore.date()
        return _parse_date(valore)
    testo = str(valore).strip()
    if not testo:
        return None
    limite = _max_length(campo)
    return testo[:limite] if limite else testo


def valore_visualizzato(valore) -> str:
    """Rappresentazione testuale di un valore per log e report."""
    if valore is None:
        return ""
    if hasattr(valore, "isoformat"):
        return valore.isoformat()
    return str(valore)


def confronta_commessa(testata: Testata, dati_bc: dict) -> list[dict]:
    """Campi in cui Business Central differisce dalla commessa salvata.

    Args:
        testata: Commessa presente nel sistema.
        dati_bc: Dati restituiti da ``fetch_from_bc``.

    Returns:
        Lista di dict con ``campo``, ``etichetta``, ``attuale`` e ``bc``.
        I campi che BC non valorizza vengono ignorati: un dato mancante in BC
        non deve cancellare quello inserito nel sistema.
    """
    differenze = []
    for campo, etichetta in CAMPI_SINCRONIZZATI.items():
        if campo not in dati_bc:
            continue
        valore_bc = _normalizza(campo, dati_bc.get(campo))
        if valore_bc is None:
            continue
        valore_attuale = _normalizza(campo, getattr(testata, campo))
        if valore_bc == valore_attuale:
            continue
        differenze.append(
            {
                "campo": campo,
                "etichetta": etichetta,
                "attuale": valore_attuale,
                "bc": valore_bc,
            }
        )
    return differenze


def sincronizza_commessa(testata: Testata, dati_bc: dict, dry_run: bool = False) -> list[dict]:
    """Allinea una commessa ai dati BC e registra le modifiche applicate.

    Args:
        testata: Commessa da allineare.
        dati_bc: Dati restituiti da ``fetch_from_bc``.
        dry_run: Se ``True`` calcola le differenze senza salvare nulla.

    Returns:
        Lista delle differenze trovate (le stesse di ``confronta_commessa``).
    """
    differenze = confronta_commessa(testata, dati_bc)
    if not differenze or dry_run:
        return differenze

    with transaction.atomic():
        for diff in differenze:
            setattr(testata, diff["campo"], diff["bc"])
        testata.save(update_fields=[d["campo"] for d in differenze])
        AggiornamentoBC.objects.bulk_create(
            [
                AggiornamentoBC(
                    testata=testata,
                    campo=d["campo"],
                    valore_precedente=valore_visualizzato(d["attuale"]),
                    valore_nuovo=valore_visualizzato(d["bc"]),
                )
                for d in differenze
            ]
        )
    logger.info(
        'BC sync: commessa "%s" aggiornata — %s',
        testata.job,
        ", ".join(
            f"{d['etichetta']}: {valore_visualizzato(d['attuale']) or '—'} → "
            f"{valore_visualizzato(d['bc'])}"
            for d in differenze
        ),
    )
    return differenze


def commesse_da_controllare(jobs=None, includi_chiuse: bool = False):
    """Testate su cui eseguire il controllo, ordinate per commessa."""
    qs = Testata.objects.all()
    if jobs:
        qs = qs.filter(job__in=list(jobs))
    elif not includi_chiuse:
        qs = qs.filter(actual_delivery_date__isnull=True)
    return qs.order_by("job")


def _apri_connessione():
    """Apre un connettore Business Central (isolato per facilitare i test)."""
    from src.erp.business_central import BusinessCentral

    return BusinessCentral()


def sincronizza_commesse(
    jobs=None,
    includi_chiuse: bool = False,
    dry_run: bool = False,
    bc=None,
) -> dict:
    """Controllo di congruenza fra Business Central e le commesse del sistema.

    Args:
        jobs: Elenco di commesse da controllare; se omesso, tutte quelle aperte.
        includi_chiuse: Include anche le commesse già chiuse.
        dry_run: Calcola le differenze senza salvarle.
        bc: Connettore già aperto da riusare; altrimenti ne viene aperto uno.

    Returns:
        Report con ``controllate``, ``aggiornate``, ``non_trovate``, ``errori``,
        ``aggiornamenti`` e ``dry_run``.

    Raises:
        BusinessCentralNonDisponibile: Se la connessione a BC non è utilizzabile.
    """
    report = {
        "controllate": 0,
        "aggiornate": 0,
        "non_trovate": [],
        "errori": [],
        "aggiornamenti": [],
        "dry_run": bool(dry_run),
    }
    testate = list(commesse_da_controllare(jobs, includi_chiuse))
    if not testate:
        return report

    connessione_propria = bc is None
    connettore = _apri_connessione() if connessione_propria else bc
    try:
        if getattr(connettore, "conn", None) is None:
            raise BusinessCentralNonDisponibile(
                "Connessione a Business Central non disponibile: controlla le "
                "credenziali BUSINESS_CENTRAL_* e la raggiungibilità del server."
            )
        for testata in testate:
            report["controllate"] += 1
            try:
                dati = fetch_from_bc(testata.job, bc=connettore)
                if not dati:
                    report["non_trovate"].append(testata.job)
                    continue
                differenze = sincronizza_commessa(testata, dati, dry_run=dry_run)
            except Exception as exc:  # una commessa in errore non ferma le altre
                logger.exception('BC sync: errore sulla commessa "%s".', testata.job)
                report["errori"].append({"job": testata.job, "errore": str(exc)})
                continue
            if not differenze:
                continue
            report["aggiornate"] += 1
            for diff in differenze:
                report["aggiornamenti"].append(
                    {
                        "job": testata.job,
                        "campo": diff["campo"],
                        "etichetta": diff["etichetta"],
                        "precedente": valore_visualizzato(diff["attuale"]),
                        "nuovo": valore_visualizzato(diff["bc"]),
                    }
                )
    finally:
        if connessione_propria:
            connettore.close()

    logger.info(
        "BC sync: controllate %d commesse, aggiornate %d, non trovate in BC %d, errori %d%s",
        report["controllate"],
        report["aggiornate"],
        len(report["non_trovate"]),
        len(report["errori"]),
        " (dry-run)" if report["dry_run"] else "",
    )
    return report


def _valore_leggibile(campo: str, valore: str) -> str:
    """Valore pronto per l'interfaccia: le date come ``10 jan 2026``."""
    if campo.endswith("_date"):
        return format_display_date(valore)
    return valore


def list_aggiornamenti(job: str, limit: int = 50) -> list[dict]:
    """Ultimi aggiornamenti applicati da Business Central a una commessa."""
    qs = AggiornamentoBC.objects.filter(testata_id=job)[:limit]
    return [
        {
            "id": a.pk,
            "campo": a.campo,
            "etichetta": CAMPI_SINCRONIZZATI.get(a.campo, a.campo),
            "precedente": _valore_leggibile(a.campo, a.valore_precedente),
            "nuovo": _valore_leggibile(a.campo, a.valore_nuovo),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "data": format_display_date(a.created_at),
        }
        for a in qs
    ]
