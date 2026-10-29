"""List and unlock revisions blocked by a client response with no successor."""

from __future__ import annotations

from django.db import transaction
from django.db.models import Prefetch

from ..date_fmt import parse_iso_date
from ..models import Documento, Revisione
from .commesse import serialize_revisione
from .stato_esterno_colori import cell_colors
from .ultima_revisione import ORDINE_CRESCENTE, chiave_ordinamento, ultima_revisione


def list_revisioni_sbloccabili(job: str) -> list[dict]:
    """Return latest revisions per document that have ext_status and no successor."""
    docs = Documento.objects.filter(testata_id=job).prefetch_related(
        Prefetch(
            "revisioni",
            queryset=Revisione.objects.select_related("ext_status").order_by(*ORDINE_CRESCENTE),
        )
    )
    result: list[dict] = []
    for doc in docs:
        revs = list(doc.revisioni.all())
        if not revs:
            continue
        latest = max(revs, key=chiave_ordinamento)
        if not latest.ext_status_id:
            continue
        ext = latest.ext_status
        cella = cell_colors(ext.colore) if ext else {"bg": "", "fg": ""}
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
                "ext_status_bg": cella["bg"],
                "ext_status_fg": cella["fg"],
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

    latest = ultima_revisione(doc)
    if latest is None or latest.pk != rev.pk:
        raise ValueError("Non è l'ultima revisione del documento.")
    if not rev.ext_status_id:
        raise ValueError("La revisione non ha una risposta cliente.")

    new_rev = Revisione.objects.create(
        documento=doc,
        rev_no=(rev.rev_no or 0) + 1,
        dis_plan_date=parse_iso_date(dis_plan_date, strict=True),
        crea_nuova_rev=False,
    )
    return {
        "revisione": serialize_revisione(new_rev),
        "revisione_sbloccata_id": rev.pk,
    }
