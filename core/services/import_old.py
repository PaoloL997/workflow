import logging

import pandas as pd
from django.db import transaction

from ..models import Documento, IndirSped, Reparto, Revisione, StatoEsterno, Testata
from .access_source import fetch_commessa_frames
from .revisione_anomalie import audit_commessa_summary
from .revisioni_cleanup import (
    access_codes_without_nuova_rev,
    drop_orphan_revisioni,
    find_orphan_indices,
)
from .stato_esterno_codes import STATUS_LETTER_MAP
from .stato_interno import stato_interno_effettivo
from .trasmittal_archivio import sync_trasmittal_da_cartella

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "A": {"nome": STATUS_LETTER_MAP["A"], "colore": "#00B050"},
    "I": {"nome": STATUS_LETTER_MAP["I"], "colore": "#D61D09"},
    "C": {"nome": STATUS_LETTER_MAP["C"], "colore": "#D61D09"},
    "F": {"nome": STATUS_LETTER_MAP["F"], "colore": "#FFC000"},
    "Z": {"nome": STATUS_LETTER_MAP["Z"], "colore": "#FFC000"},
    "O": {"nome": STATUS_LETTER_MAP["O"], "colore": "#D61D09"},
    "R": {"nome": STATUS_LETTER_MAP["R"], "colore": "#D61D09"},
    "S": {"nome": STATUS_LETTER_MAP["S"], "colore": "#B8B8B8"},
}

__REPARTO_MAP = {
    1: ["Ufficio Tecnico", "UT"],
    2: ["Project Management", "PM"],
    3: ["Amministrazione", "AM"],
    4: ["Quality Control", "QC"],
}


def _to_date(val):
    if pd.isna(val):
        return None
    if hasattr(val, "date"):
        return val.date()
    return val


def int_status_from_access(dis_act_date, rec_act_date, ext_status=None) -> str:
    """Derive workflow int_status from the Access dispatch/receipt/status data.

    - receipt recorded, or a client response already given → ricevuto
    - dispatch recorded (nothing back yet) → inviato_al_cliente
    - neither → empty (UI: Da inviare / da emettere)
    """
    return stato_interno_effettivo(
        "",
        dis_act_date=dis_act_date,
        rec_act_date=rec_act_date,
        ha_risposta_cliente=bool(ext_status),
    )


def _to_str(val, default=""):
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return str(val).strip()


def _to_int(val):
    try:
        if pd.isna(val):
            return None
    except (TypeError, ValueError):
        pass
    return int(val)


def _to_bool(val):
    try:
        if pd.isna(val):
            return False
    except (TypeError, ValueError):
        pass
    return bool(val)


def _get_reparto_nome(val) -> str:
    """Resolve a numeric reparto ID from the old Access data to a department name.

    Looks up ``__REPARTO_MAP`` and creates the corresponding ``Reparto`` entry
    in the database if it does not exist yet. Returns an empty string for IDs
    not present in the map.
    """
    try:
        reparto_id = int(float(str(val)))
    except (ValueError, TypeError):
        return _to_str(val)

    if reparto_id not in __REPARTO_MAP:
        return ""

    nome, acronimo = __REPARTO_MAP[reparto_id]
    Reparto.objects.get_or_create(nome=nome, defaults={"acronimo": acronimo})
    return nome


def _get_stato_esterno(code):
    if not isinstance(code, str) or code not in _STATUS_MAP:
        return None
    info = _STATUS_MAP[code]
    obj, created = StatoEsterno.objects.get_or_create(
        nome=info["nome"],
        defaults={"colore": info["colore"], "lettera": code},
    )
    if not created and not (obj.lettera or "").strip():
        obj.lettera = code
        obj.save(update_fields=["lettera"])
    return obj


@transaction.atomic
def importa_commessa_da_access(job: str) -> dict:
    """Read a job from the Access MDB and persist it to the database.

    Raises ValueError if the job already exists or is not found in Access.
    """
    if Testata.objects.filter(job=job).exists():
        raise ValueError(f'La commessa "{job}" esiste già nel database.')

    frames = fetch_commessa_frames(job)
    testata_df = frames["testata"]
    indir_df = frames["indirsped"]
    doc_df = frames["dettaglio"]
    rev_raw = frames["revisioni"]

    if testata_df.empty:
        raise ValueError(f'Commessa "{job}" non trovata nel database Access.')

    # Drop last revisions that are Access placeholders: previous response does
    # not foresee a new revision (crea_nuova_rev=False) and the last row has
    # only DisPlanDate.
    no_nuova_rev_codes = access_codes_without_nuova_rev()
    revisioni_orfane_escluse = len(
        find_orphan_indices(rev_raw, no_nuova_rev_codes=no_nuova_rev_codes)
    )
    rev_df = drop_orphan_revisioni(rev_raw, no_nuova_rev_codes=no_nuova_rev_codes)

    r = testata_df.iloc[0]
    testata = Testata.objects.create(
        job=_to_str(r["Job"]),
        client=_to_str(r["Client"]),
        po_no=_to_str(r["POno"]),
        job_detail=_to_str(r["JobDetail"]),
        delivery_date=_to_date(r["DeliveryDate"]),
        delivery_term=_to_str(r["DeliveryTerm"]),
        requisition=_to_str(r["Requisition"]),
        time_cli_doc_rev=_to_int(r["TimeCliDocRev"]),
        time_ven_doc_rev=_to_int(r["TimeVenDocRev"]),
        rev_let_flag=_to_bool(r["RevLetFlag"]),
    )

    if not indir_df.empty:
        ir = indir_df.iloc[0]
        IndirSped.objects.create(
            testata=testata,
            consignee=_to_str(ir["Consignee"]),
            address=_to_str(ir["Address"]),
            zip_code=_to_str(ir["ZipCode"]),
            city=_to_str(ir["City"]),
            country=_to_str(ir["Country"]),
            attn=_to_str(ir["Attn"]),
            ph_no=_to_str(ir["PhNo"]),
        )

    documenti = []
    for _, d in doc_df.iterrows():
        doc = Documento.objects.create(
            testata=testata,
            item_no=_to_str(d["ItemNo"]),
            vendor_doc=_to_str(d["VendorDoc"]),
            client_doc_no=_to_str(d["ClientDocNo"]),
            contractor_doc_no=_to_str(d.get("ContractorDocNo", "")),
            client_doc_class=_to_str(d["ClientDocClass"]),
            doc_title=_to_str(d["DocTitle"]),
            doc_penalty=_to_bool(d["DocPenalty"]),
            doc_payment=_to_bool(d["DocPayment"]),
            rev_gen=_to_bool(d["RevGen"]),
            reparto=_get_reparto_nome(d["Reparto"]),
            remarks=_to_str(d["Remarks"]),
        )
        documenti.append(doc)

    rev_count = 0
    for doc in documenti:
        doc_revs = rev_df.loc[rev_df["VendorDoc"] == doc.vendor_doc]
        for _, rv in doc_revs.iterrows():
            dis_act_date = _to_date(rv["DisActDate"])
            rec_act_date = _to_date(rv["RecActDate"])
            ext_status = _get_stato_esterno(rv["Status"])
            Revisione.objects.create(
                documento=doc,
                rev_no=_to_int(rv["RevNo"]),
                rev_let=_to_str(rv["RevLet"]),
                dis_plan_date=_to_date(rv["DisPlanDate"]),
                dis_act_date=dis_act_date,
                rec_plan_date=_to_date(rv["RecPlanDate"]),
                rec_act_date=rec_act_date,
                int_status=int_status_from_access(dis_act_date, rec_act_date, ext_status),
                ext_status=ext_status,
            )
            rev_count += 1

    summary = audit_commessa_summary(testata.job)
    job_saved = testata.job

    def _sync_trasmittal():
        try:
            sync_trasmittal_da_cartella(job_saved)
        except Exception:
            logger.exception("Sync transmittal dopo import Access fallito (job=%s)", job_saved)

    transaction.on_commit(_sync_trasmittal)
    return {
        "job": testata.job,
        "documenti": len(documenti),
        "revisioni": rev_count,
        "revisioni_orfane_escluse": revisioni_orfane_escluse,
        "anomalie": summary["count"],
        "anomalie_per_codice": summary["per_codice"],
    }
