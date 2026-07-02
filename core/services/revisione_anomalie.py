"""Detect inconsistent revision data (runtime audit, no side effects)."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import Revisione


@dataclass(frozen=True)
class AnomaliaRevisione:
    codice: str
    gravita: str
    messaggio: str
    azione: str
    revisione_id: int
    documento_id: int
    vendor_doc: str
    rev_no: int | None
    rev_let: str

    def to_dict(self) -> dict:
        return asdict(self)


def _is_workflow_empty(rev: Revisione) -> bool:
    return (
        not rev.dis_act_date
        and not rev.rec_act_date
        and not rev.ext_status_id
        and not (rev.int_status or "").strip()
    )


def suggest_bucket(rev: Revisione) -> str:
    """Suggest workflow bucket from current revision data."""
    int_status = (rev.int_status or "").strip()
    if rev.rec_act_date or int_status == "ricevuto":
        return "conclusi"
    if rev.dis_act_date or int_status == "inviato_al_cliente":
        return "da_ricevere"
    return "da_emettere"


BUCKET_LABELS = {
    "da_emettere": "Da emettere",
    "da_ricevere": "Da ricevere",
    "conclusi": "Completata",
}


def bucket_label(bucket: str) -> str:
    return BUCKET_LABELS.get(bucket, bucket)


def _parse_optional_date(val):
    from datetime import date as date_type

    if not val:
        return None
    if isinstance(val, date_type):
        return val
    return date_type.fromisoformat(str(val))


def audit_revisione(
    rev: Revisione,
    *,
    time_cli: int | None = None,
) -> list[AnomaliaRevisione]:
    """Return anomalies for a single revision row."""
    doc = rev.documento
    base = {
        "revisione_id": rev.pk,
        "documento_id": doc.pk,
        "vendor_doc": doc.vendor_doc or "",
        "rev_no": rev.rev_no,
        "rev_let": rev.rev_let or "",
    }
    anomalies: list[AnomaliaRevisione] = []

    if _is_workflow_empty(rev):
        return anomalies

    int_status = (rev.int_status or "").strip()

    if rev.ext_status_id and not rev.rec_act_date:
        anomalies.append(
            AnomaliaRevisione(
                codice="RISPOSTA_SENZA_RICEZIONE",
                gravita="warning",
                messaggio="Risposta cliente registrata senza data di rientro effettiva.",
                azione="Registrare la data di rientro e impostare lo stato interno a Ricevuto.",
                **base,
            )
        )

    if int_status == "inviato_al_cliente" and not rev.dis_act_date:
        anomalies.append(
            AnomaliaRevisione(
                codice="INVIATO_SENZA_DISPATCH",
                gravita="warning",
                messaggio="Stato interno «Inviato al Cliente» senza data di invio effettiva.",
                azione="Rimuovere lo stato inviato oppure registrare la data di invio.",
                **base,
            )
        )

    if rev.dis_act_date and not rev.rec_plan_date and time_cli and not rev.rec_act_date:
        anomalies.append(
            AnomaliaRevisione(
                codice="DISPATCH_SENZA_RIENTRO_PREV",
                gravita="warning",
                messaggio="Invio effettivo registrato senza data di rientro prevista.",
                azione="Calcolare il rientro previsto in base ai giorni revisione cliente.",
                **base,
            )
        )

    if int_status == "ricevuto" and not rev.rec_act_date:
        anomalies.append(
            AnomaliaRevisione(
                codice="INT_STATUS_INCONGRUENTE",
                gravita="warning",
                messaggio="Stato interno «Ricevuto» senza data di rientro effettiva.",
                azione="Allineare lo stato interno alle date oppure registrare la ricezione.",
                **base,
            )
        )
    elif int_status == "inviato_al_cliente" and rev.rec_act_date:
        anomalies.append(
            AnomaliaRevisione(
                codice="INT_STATUS_INCONGRUENTE",
                gravita="warning",
                messaggio="Stato interno «Inviato al Cliente» con data di rientro già valorizzata.",
                azione="Impostare lo stato interno a Ricevuto.",
                **base,
            )
        )

    return anomalies


def audit_commessa(job: str) -> list[AnomaliaRevisione]:
    from ..models import Testata

    testata = Testata.objects.get(job=job)
    time_cli = testata.time_cli_doc_rev
    anomalies: list[AnomaliaRevisione] = []

    documenti = testata.documenti.prefetch_related(
        "revisioni__ext_status",
    ).order_by("pk")

    for doc in documenti:
        revs = sorted(doc.revisioni.all(), key=lambda r: (r.rev_no or 0, r.pk))
        for rev in revs:
            if rev.ignora_anomalie:
                continue
            anomalies.extend(audit_revisione(rev, time_cli=time_cli))

    return anomalies


def audit_commessa_summary(job: str) -> dict:
    anomalies = audit_commessa(job)
    per_codice = dict(Counter(a.codice for a in anomalies))
    revisioni_ids = {a.revisione_id for a in anomalies}
    return {
        "count": len(revisioni_ids),
        "anomalie_totali": len(anomalies),
        "per_codice": per_codice,
    }


def serialize_anomalie_gruppi(job: str, anomalies: list[AnomaliaRevisione]) -> list[dict]:
    from ..models import Revisione
    from .commesse import serialize_revisione

    if not anomalies:
        return []

    grouped: dict[int, list[AnomaliaRevisione]] = {}
    for a in anomalies:
        grouped.setdefault(a.revisione_id, []).append(a)

    rev_map = {
        r.pk: r
        for r in Revisione.objects.filter(pk__in=grouped.keys()).select_related(
            "documento",
            "ext_status",
        )
    }

    latest_by_doc: dict[int, int | None] = {}
    for rev in rev_map.values():
        if rev.documento_id not in latest_by_doc:
            latest = (
                Revisione.objects.filter(documento_id=rev.documento_id)
                .order_by("-rev_no", "-pk")
                .first()
            )
            latest_by_doc[rev.documento_id] = latest.pk if latest else None

    result = []
    for rev_id, anoms in grouped.items():
        rev = rev_map.get(rev_id)
        if rev is None:
            continue
        doc = rev.documento
        bucket = suggest_bucket(rev)
        result.append(
            {
                "revisione_id": rev_id,
                "is_latest": latest_by_doc.get(doc.pk) == rev_id,
                "suggest_bucket": bucket,
                "situazione_attuale": {"id": bucket, "label": bucket_label(bucket)},
                "revisione": serialize_revisione(rev),
                "documento": {
                    "id": doc.pk,
                    "vendor_doc": doc.vendor_doc or "",
                    "doc_title": doc.doc_title or "",
                },
                "anomalie": [
                    {
                        "codice": a.codice,
                        "gravita": a.gravita,
                        "messaggio": a.messaggio,
                        "azione": a.azione,
                    }
                    for a in anoms
                ],
            }
        )

    result.sort(
        key=lambda g: (
            g["documento"]["vendor_doc"],
            g["revisione"]["rev_no"] if g["revisione"] else 0,
        )
    )
    return result


def revisione_is_latest(rev: Revisione) -> bool:
    from ..models import Revisione

    latest = (
        Revisione.objects.filter(documento_id=rev.documento_id).order_by("-rev_no", "-pk").first()
    )
    return latest is not None and latest.pk == rev.pk


def bucket_to_fields(
    rev: Revisione, bucket: str, *, time_cli: int | None, data: dict | None = None
) -> dict:
    """Return revision field updates for a workflow bucket (does not save)."""
    from datetime import timedelta

    data = data or {}
    if bucket == "da_emettere":
        return {
            "int_status": "",
            "dis_act_date": None,
            "rec_plan_date": None,
            "rec_act_date": None,
            "ext_status": None,
        }
    if bucket == "da_ricevere":
        dis_act = _parse_optional_date(data.get("dis_act_date")) or rev.dis_act_date
        if not dis_act:
            raise ValueError("Specificare la data di invio effettiva.")
        rec_plan = rev.rec_plan_date
        if time_cli:
            rec_plan = dis_act + timedelta(days=time_cli)
        return {
            "int_status": "inviato_al_cliente",
            "dis_act_date": dis_act.isoformat(),
            "rec_plan_date": rec_plan.isoformat() if rec_plan else None,
            "rec_act_date": None,
            "ext_status": None,
        }
    if bucket == "conclusi":
        rec_act = _parse_optional_date(data.get("rec_act_date")) or rev.rec_act_date
        if not rec_act:
            raise ValueError("Specificare la data di rientro effettiva.")
        ext_id = data.get("ext_status_id")
        if ext_id in ("", None):
            ext_id = rev.ext_status_id
        dis_act = _parse_optional_date(data.get("dis_act_date")) or rev.dis_act_date
        fields = {
            "int_status": "ricevuto",
            "rec_act_date": rec_act.isoformat(),
            "ext_status": ext_id,
        }
        if dis_act:
            fields["dis_act_date"] = dis_act.isoformat()
            if time_cli and not rev.rec_plan_date:
                rec_plan = dis_act + timedelta(days=time_cli)
                fields["rec_plan_date"] = rec_plan.isoformat()
        return fields
    raise ValueError(f'Classificazione "{bucket}" non valida.')


def classifica_revisione(
    job: str,
    revisione_id: int,
    bucket: str,
    data: dict | None = None,
) -> dict:
    """Apply a workflow bucket to fix revision inconsistencies."""
    from ..models import Revisione, Testata
    from .commesse import serialize_revisione, update_revisione

    allowed = {"da_emettere", "da_ricevere", "conclusi"}
    bucket = (bucket or "").strip()
    if bucket not in allowed:
        raise ValueError(f'Classificazione "{bucket}" non valida.')

    data = data or {}
    testata = Testata.objects.get(job=job)
    rev = Revisione.objects.select_related("documento__testata", "ext_status").get(pk=revisione_id)
    if rev.documento.testata_id != job:
        raise ValueError("La revisione non appartiene a questa commessa.")

    fields = bucket_to_fields(rev, bucket, time_cli=testata.time_cli_doc_rev, data=data)
    r = update_revisione(revisione_id, fields)
    return {"revisione": serialize_revisione(r)}


def risolvi_anomalia(job: str, revisione_id: int, azione: str, data: dict | None = None) -> dict:
    """Deprecated: use classifica_revisione with bucket."""
    bucket_map = {
        "azzera_int_status": "da_emettere",
        "calcola_rec_plan": "da_ricevere",
        "registra_ricezione": "conclusi",
        "sync_int_status_ricevuto": "conclusi",
    }
    bucket = bucket_map.get(azione)
    if not bucket:
        raise ValueError(f'Azione "{azione}" non riconosciuta.')
    return classifica_revisione(job, revisione_id, bucket, data)


def ignora_anomalie_revisione(job: str, revisione_id: int) -> dict:
    """Mark a revision so its anomalies are no longer reported."""
    from ..models import Revisione

    rev = Revisione.objects.select_related("documento__testata").get(pk=revisione_id)
    if rev.documento.testata_id != job:
        raise ValueError("La revisione non appartiene a questa commessa.")
    rev.ignora_anomalie = True
    rev.save(update_fields=["ignora_anomalie"])
    summary = audit_commessa_summary(job)
    return {"revisione_id": revisione_id, "anomalie_count": summary["count"]}
