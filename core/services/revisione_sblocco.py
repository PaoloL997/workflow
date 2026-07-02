"""List and unlock revisions blocked by a client response with no successor."""

from __future__ import annotations

from datetime import date as date_type

from django.db import transaction
from django.db.models import Prefetch

from ..models import Documento, Revisione
from .commesse import serialize_revisione


def _parse_optional_date(value) -> date_type | None:
    if not value:
        return None
    if isinstance(value, date_type):
        return value
    return date_type.fromisoformat(str(value))


def list_revisioni_sbloccabili(job: str) -> list[dict]:
    """Return latest revisions per document that have ext_status and no successor."""
    docs = Documento.objects.filter(testata_id=job).prefetch_related(
        Prefetch(
            "revisioni",
            queryset=Revisione.objects.select_related("ext_status").order_by("rev_no", "pk"),
        )
    )
    result: list[dict] = []
    for doc in docs:
        revs = list(doc.revisioni.all())
        if not revs:
            continue
        latest = max(revs, key=lambda r: (r.rev_no or 0, r.pk))
        if not latest.ext_status_id:
            continue
        ext = latest.ext_status
        result.append(
            {
                "revisione_id": latest.pk,
                "documento_id": doc.pk,
                "vendor_doc": doc.vendor_doc or "",
                "doc_title": doc.doc_title or "",
                "reparto": doc.reparto or "",
                "rev_no": latest.rev_no,
                "rev_let": latest.rev_let or "",
                "ext_status_label": ext.nome if ext else "",
                "ext_status_colore": ext.colore if ext else "",
                "rec_act_date": latest.rec_act_date.isoformat() if latest.rec_act_date else None,
            }
        )
    result.sort(key=lambda x: (x["vendor_doc"], x["rev_no"] or 0))
    return result


@transaction.atomic
def sblocca_revisione(job: str, revisione_id: int, dis_plan_date=None) -> dict:
    """Create the next revision after a locked one (latest with client response)."""
    rev = Revisione.objects.select_related("documento__testata", "ext_status").get(pk=revisione_id)
    doc = rev.documento
    if doc.testata_id != job:
        raise ValueError("Revisione non appartiene a questa commessa.")

    latest = doc.revisioni.order_by("-rev_no", "-pk").first()
    if latest is None or latest.pk != rev.pk:
        raise ValueError("Non è l'ultima revisione del documento.")
    if not rev.ext_status_id:
        raise ValueError("La revisione non ha una risposta cliente.")

    new_rev = Revisione.objects.create(
        documento=doc,
        rev_no=(rev.rev_no or 0) + 1,
        dis_plan_date=_parse_optional_date(dis_plan_date),
        crea_nuova_rev=True,
    )
    return {
        "revisione": serialize_revisione(new_rev),
        "revisione_sbloccata_id": rev.pk,
    }
