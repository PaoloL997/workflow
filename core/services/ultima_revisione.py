"""Qual è l'ultima revisione di un documento: una regola sola per tutto il codice.

``Revisione.rev_no`` può essere NULL (import dal vecchio Access). PostgreSQL
mette i NULL per primi in un ordinamento decrescente, quindi un semplice
``order_by("-rev_no")`` sceglie proprio la revisione senza numero come
"ultima", mentre un ordinamento in Python con ``rev_no or 0`` la tratta come
la revisione 0: due risposte diverse per lo stesso documento, e l'emissione
scrive la data su una revisione mentre lo sblocco ne guarda un'altra.

Qui la regola è unica, in SQL e in Python: una revisione senza numero viene
prima di tutte le altre; a parità di numero vince la più recente (``pk``).
"""

from __future__ import annotations

from django.db.models import F

from ..models import Revisione

# Da usare in ``order_by(*...)``: stessa regola di ``chiave_ordinamento``.
ORDINE_CRESCENTE = (F("rev_no").asc(nulls_first=True), "pk")
ORDINE_DECRESCENTE = (F("rev_no").desc(nulls_last=True), "-pk")


def chiave_ordinamento(revisione):
    """Chiave per ``sorted``/``max`` sulle revisioni: NULL prima, poi numero, poi pk."""
    return (revisione.rev_no is not None, revisione.rev_no or 0, revisione.pk)


def _prefetchate(documento):
    """Le revisioni già caricate da ``prefetch_related("revisioni")``, o ``None``."""
    cache = getattr(documento, "_prefetched_objects_cache", None) or {}
    return cache.get("revisioni")


def ultima_revisione(documento):
    """Ultima revisione del documento, ``None`` se non ne ha.

    Con le revisioni già prefetchate non fa nessuna query: così un elenco di
    documenti costa un numero fisso di query, non due per documento.
    """
    prefetchate = _prefetchate(documento)
    if prefetchate is not None:
        return max(prefetchate, key=chiave_ordinamento, default=None)
    return documento.revisioni.select_related("ext_status").order_by(*ORDINE_DECRESCENTE).first()


def ultima_revisione_per_documento_id(documento_id):
    """Come ``ultima_revisione`` a partire dall'id, quando il documento non è a portata di mano."""
    return Revisione.objects.filter(documento_id=documento_id).order_by(*ORDINE_DECRESCENTE).first()


def revisione_zero(documento):
    """La revisione 0 del documento (la prima pianificata), ``None`` se manca."""
    prefetchate = _prefetchate(documento)
    if prefetchate is not None:
        return min((r for r in prefetchate if r.rev_no == 0), key=lambda r: r.pk, default=None)
    return documento.revisioni.filter(rev_no=0).order_by("pk").first()
