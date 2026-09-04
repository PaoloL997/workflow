"""Raw per-job data export: one Excel sheet per database table.

Sheets hold the tables essentially as stored (model column names, no formatting
beyond the bold header row); only the revisions sheet joins in the identifiers
of its document and the letter of the client answer.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from operator import attrgetter

import openpyxl
from django.utils import timezone
from openpyxl.styles import Font

from ..models import Documento, IndirSped, Revisione, Testata


@dataclass(frozen=True)
class TabellaGrezza:
    """An exportable table for a single job.

    Attributes:
        key: Identifier used in the export request.
        label: Shown in the UI and used as the Excel sheet title.
        model: Django model the columns are derived from.
        queryset: Callable that returns the rows to export for a given job.
        colonne: Explicit (header, getter) pairs; when empty every concrete
            model field is exported, in declaration order.
    """

    key: str
    label: str
    model: type
    queryset: Callable
    colonne: tuple = ()

    @property
    def _pairs(self):
        if self.colonne:
            return self.colonne
        return tuple((f.attname, attrgetter(f.attname)) for f in self.model._meta.concrete_fields)

    @property
    def headers(self):
        return [header for header, _ in self._pairs]

    def rows(self, job):
        getters = [getter for _, getter in self._pairs]
        return [[_cell(getter(obj)) for getter in getters] for obj in self.queryset(job)]


def _lettera_stato(revisione):
    """Letter of the client answer (e.g. "A"), empty when there is none."""
    return revisione.ext_status.lettera if revisione.ext_status_id else ""


# Le revisioni portano gli identificativi del documento a cui appartengono:
# gli id tecnici e il flag interno "ignora anomalie" non servono a chi legge.
REVISIONI_COLONNE = (
    ("client_doc_no", attrgetter("documento.client_doc_no")),
    ("client_doc_class", attrgetter("documento.client_doc_class")),
    ("contractor_doc_no", attrgetter("documento.contractor_doc_no")),
    ("vendor_doc", attrgetter("documento.vendor_doc")),
    ("item_no", attrgetter("documento.item_no")),
    ("rev_no", attrgetter("rev_no")),
    ("rev_let", attrgetter("rev_let")),
    ("dis_plan_date", attrgetter("dis_plan_date")),
    ("dis_act_date", attrgetter("dis_act_date")),
    ("rec_plan_date", attrgetter("rec_plan_date")),
    ("rec_act_date", attrgetter("rec_act_date")),
    ("int_status", attrgetter("int_status")),
    ("ext_status", _lettera_stato),
    ("crea_nuova_rev", attrgetter("crea_nuova_rev")),
)


TABELLE = (
    TabellaGrezza(
        "testate",
        "Commessa",
        Testata,
        lambda job: Testata.objects.filter(job=job),
    ),
    TabellaGrezza(
        "indirizzi_spedizione",
        "Indirizzi spedizione",
        IndirSped,
        lambda job: IndirSped.objects.filter(testata_id=job).order_by("pk"),
    ),
    TabellaGrezza(
        "documenti",
        "Documenti",
        Documento,
        lambda job: Documento.objects.filter(testata_id=job).order_by("pk"),
    ),
    TabellaGrezza(
        "revisioni",
        "Revisioni",
        Revisione,
        lambda job: (
            Revisione.objects.filter(documento__testata_id=job)
            .select_related("documento", "ext_status")
            .order_by("documento_id", "pk")
        ),
        colonne=REVISIONI_COLONNE,
    ),
)

TABELLE_BY_KEY = {t.key: t for t in TABELLE}


def list_tabelle():
    """The exportable tables, in display order."""
    return [{"key": t.key, "label": t.label} for t in TABELLE]


def _cell(value):
    """Excel-ready value: naive datetimes, everything else untouched."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return value.replace(tzinfo=None)
    if value is None or isinstance(value, date | bool | int | float | str):
        return value
    return str(value)


def resolve_tabelle(keys):
    """Turn the requested keys into tables, in canonical order.

    Args:
        keys: Iterable of table keys picked by the user.

    Returns:
        The list of TabellaGrezza to export.

    Raises:
        ValueError: If no table was selected or a key is unknown.
    """
    richieste = {str(k).strip() for k in (keys or []) if str(k).strip()}
    if not richieste:
        raise ValueError("Seleziona almeno una tabella da scaricare.")
    sconosciute = sorted(richieste - set(TABELLE_BY_KEY))
    if sconosciute:
        raise ValueError(f"Tabella non riconosciuta: {', '.join(sconosciute)}.")
    return [t for t in TABELLE if t.key in richieste]


def build_workbook(job, keys):
    """Build the workbook with one sheet per requested table.

    Args:
        job: Job number whose data is exported.
        keys: Keys of the tables to include.

    Returns:
        The openpyxl Workbook with the requested sheets.

    Raises:
        Testata.DoesNotExist: If the job does not exist.
        ValueError: If the table selection is not valid.
    """
    tabelle = resolve_tabelle(keys)
    if not Testata.objects.filter(job=job).exists():
        raise Testata.DoesNotExist(job)

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    header_font = Font(bold=True)

    for tabella in tabelle:
        ws = wb.create_sheet(title=tabella.label[:31])
        ws.append(tabella.headers)
        for cell in ws[1]:
            cell.font = header_font
        for row in tabella.rows(job):
            ws.append(row)

    return wb
