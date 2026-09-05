from datetime import date as date_type
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Prefetch

from ..models import (
    STATI_INTERNI_CHOICES,
    CartellaModelloDocumento,
    CommessaPin,
    Documento,
    IndirSped,
    Reparto,
    Revisione,
    StatoEsterno,
    Testata,
)
from .stato_esterno_colori import cell_colors

MAX_PINNED_COMMESSE = 8

# ── Serializers ───────────────────────────────────────────────────────────────


def format_revisione_label(rev_no, rev_let, rev_let_flag):
    """Return the revision label based on the archive flag.

    If ``rev_let_flag`` is True, show the letter (fallback to number if empty).
    Otherwise always show the number, ignoring ``rev_let``.
    """
    if rev_let_flag:
        if rev_let:
            return rev_let
        return str(rev_no) if rev_no is not None else ""
    return str(rev_no) if rev_no is not None else ""


def serialize_testata(t, pinned=None):
    data = {
        "id": t.pk,
        "job": t.job,
        "client": t.client,
        "po_no": t.po_no,
        "job_detail": t.job_detail,
        "delivery_date": t.delivery_date.isoformat() if t.delivery_date else None,
        "actual_delivery_date": t.actual_delivery_date.isoformat()
        if t.actual_delivery_date
        else None,
        "delivery_term": t.delivery_term,
        "requisition": t.requisition,
        "time_cli_doc_rev": t.time_cli_doc_rev,
        "time_ven_doc_rev": t.time_ven_doc_rev,
        "rev_let_flag": t.rev_let_flag,
    }
    if pinned is not None:
        data["pinned"] = bool(pinned)
    return data


def serialize_indirizzo(i):
    return {
        "id": i.pk,
        "job": i.testata_id,
        "consignee": i.consignee,
        "address": i.address,
        "zip_code": i.zip_code,
        "city": i.city,
        "country": i.country,
        "attn": i.attn,
        "ph_no": i.ph_no,
    }


# ── Testata CRUD ──────────────────────────────────────────────────────────────


def _pinned_jobs_for_user(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    return list(
        CommessaPin.objects.filter(user=user)
        .order_by("pinned_at")
        .values_list("testata_id", flat=True)
    )


def list_commesse(q=None, user=None):
    qs = Testata.objects.all().order_by("-pk")
    if q:
        qs = qs.filter(job__icontains=q) | qs.filter(client__icontains=q)
    pinned_jobs = _pinned_jobs_for_user(user)
    pinned_set = set(pinned_jobs)
    items = [serialize_testata(t, pinned=t.job in pinned_set) for t in qs]
    if pinned_jobs:
        order = {job: i for i, job in enumerate(pinned_jobs)}
        items.sort(key=lambda c: (0 if c["pinned"] else 1, order.get(c["job"], 0), -c["id"]))
    return items


def list_home_commesse(user, limit=MAX_PINNED_COMMESSE):
    pinned_jobs = _pinned_jobs_for_user(user)
    pinned_testate = {t.job: t for t in Testata.objects.filter(job__in=pinned_jobs)}
    result = []
    for job in pinned_jobs[:limit]:
        t = pinned_testate.get(job)
        if t is not None:
            result.append(serialize_testata(t, pinned=True))
    if len(result) >= limit:
        return result[:limit]
    pinned_set = set(pinned_jobs)
    remaining = limit - len(result)
    for t in Testata.objects.exclude(job__in=pinned_set).order_by("-pk")[:remaining]:
        result.append(serialize_testata(t, pinned=False))
    return result


def pin_commessa(user, job):
    t = Testata.objects.get(job=job)
    if CommessaPin.objects.filter(user=user, testata=t).exists():
        return serialize_testata(t, pinned=True)
    if CommessaPin.objects.filter(user=user).count() >= MAX_PINNED_COMMESSE:
        raise ValueError(f"Puoi pinnare al massimo {MAX_PINNED_COMMESSE} commesse.")
    CommessaPin.objects.create(user=user, testata=t)
    return serialize_testata(t, pinned=True)


def unpin_commessa(user, job):
    t = Testata.objects.get(job=job)
    CommessaPin.objects.filter(user=user, testata=t).delete()
    return serialize_testata(t, pinned=False)


def get_commessa(job):
    return Testata.objects.get(job=job)


def create_commessa(data):
    t = Testata(**_clean_testata_fields(data))
    t.full_clean()
    t.save()
    return t


def update_commessa(job, data):
    t = Testata.objects.get(job=job)
    for k, v in _clean_testata_fields(data).items():
        setattr(t, k, v)
    t.full_clean()
    t.save()
    return t


def request_delete_commessa(job, user):
    """Invia una mail di richiesta eliminazione; non cancella la commessa."""
    t = Testata.objects.get(job=job)
    recipients = list(getattr(settings, "COMMESSA_DELETE_REQUEST_RECIPIENTS", []) or [])
    if not recipients:
        raise ValueError("Nessun destinatario configurato per le richieste di eliminazione.")

    requester = getattr(user, "nome_completo", None) or user.get_username()
    subject = f"Richiesta eliminazione commessa {t.job}"
    body = f"Utente {requester} ha richiesto l'eliminazione della commessa {t.job}."
    if t.job_detail:
        body += f"\nDescrizione: {t.job_detail}"

    send_mail(
        subject=subject,
        message=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=False,
    )
    return t


@transaction.atomic
def delete_commessa(job):
    t = Testata.objects.get(job=job)
    t.delete()


def close_commessa(job):
    t = Testata.objects.get(job=job)
    if t.actual_delivery_date is not None:
        raise ValueError("Commessa già chiusa.")
    t.actual_delivery_date = date_type.today()
    t.save(update_fields=["actual_delivery_date"])
    return t


# ── ERP fetch ─────────────────────────────────────────────────────────────────


def fetch_from_bc(job, bc=None):
    """Dati della commessa letti da Business Central.

    Args:
        job: Numero commessa da cercare in BC.
        bc: Connettore già aperto da riusare (utile per il controllo
            giornaliero su molte commesse). Se omesso ne viene aperto e chiuso
            uno dedicato.

    Returns:
        Dict con i campi trovati (vuoto se la commessa non esiste in BC).
    """
    connessione_propria = bc is None
    if connessione_propria:
        from src.erp.business_central import BusinessCentral

        bc = BusinessCentral()
    try:
        ana = bc.get_commessa_anagrafica(job)
        com = bc.get_commessa_commerciale(job)
    finally:
        if connessione_propria:
            bc.close()

    result = {}
    if ana is not None and not ana.empty:
        row = ana.iloc[0]
        result["job"] = row.get("commessa", "")
        result["job_detail"] = row.get("descrizione", "")
        result["client"] = row.get("cliente", "")
    if com is not None and not com.empty:
        row = com.iloc[0]
        result["po_no"] = row.get("po_cliente", "")
        result["delivery_date"] = row.get("data_consegna", None)
    return result


# ── IndirSped CRUD ────────────────────────────────────────────────────────────


def list_indirizzi(job):
    t = Testata.objects.get(job=job)
    return [serialize_indirizzo(i) for i in t.indirizzi_spedizione.order_by("pk")]


def create_indirizzo(job, data):
    t = Testata.objects.get(job=job)
    i = IndirSped(testata=t, **_clean_indirizzo_fields(data))
    i.full_clean()
    i.save()
    return i


def update_indirizzo(pk, data):
    i = IndirSped.objects.get(pk=pk)
    for k, v in _clean_indirizzo_fields(data).items():
        setattr(i, k, v)
    i.full_clean()
    i.save()
    return i


def delete_indirizzo(pk):
    IndirSped.objects.get(pk=pk).delete()


# ── Helpers ───────────────────────────────────────────────────────────────────

_TESTATA_FIELDS = {
    "job",
    "client",
    "po_no",
    "job_detail",
    "delivery_date",
    "delivery_term",
    "requisition",
    "time_cli_doc_rev",
    "time_ven_doc_rev",
    "rev_let_flag",
}

_INDIRIZZO_FIELDS = {
    "consignee",
    "address",
    "zip_code",
    "city",
    "country",
    "attn",
    "ph_no",
}


def _clean_testata_fields(data):
    return {k: v for k, v in data.items() if k in _TESTATA_FIELDS}


def _clean_indirizzo_fields(data):
    return {k: v for k, v in data.items() if k in _INDIRIZZO_FIELDS}


def _parse_date(value):
    """Parse an ISO date string (YYYY-MM-DD) or return None for empty/null values."""
    if not value:
        return None
    if isinstance(value, date_type):
        return value
    try:
        return date_type.fromisoformat(str(value))
    except ValueError:
        return None


# ── Reparto helpers ───────────────────────────────────────────────────────────


def list_reparti():
    """Return reparto names from the Reparto table."""
    return list(Reparto.objects.values_list("nome", flat=True))


# ── Documento CRUD ───────────────────────────────────────────────────────────────────────────────
def serialize_documento(d, reparto_acronimi=None, rev_let_flag=None):
    label_map = dict(STATI_INTERNI_CHOICES)
    latest_rev = d.revisioni.select_related("ext_status").order_by("-rev_no", "-pk").first()
    rev0 = d.revisioni.filter(rev_no=0).first()
    latest_int_status = latest_rev.int_status if latest_rev else ""
    latest_int_status_label = (
        label_map.get(latest_int_status, latest_int_status) if latest_int_status else ""
    )
    if rev_let_flag is None:
        rev_let_flag = d.testata.rev_let_flag
    reparto_acronimo = ""
    if d.reparto:
        if reparto_acronimi is not None:
            reparto_acronimo = reparto_acronimi.get(d.reparto, d.reparto)
        else:
            obj = Reparto.objects.filter(nome=d.reparto).first()
            reparto_acronimo = obj.acronimo if (obj and obj.acronimo) else d.reparto
    return {
        "id": d.pk,
        "job": d.testata_id,
        "item_no": d.item_no,
        "vendor_doc": d.vendor_doc,
        "client_doc_no": d.client_doc_no,
        "contractor_doc_no": d.contractor_doc_no,
        "client_doc_class": d.client_doc_class,
        "doc_title": d.doc_title,
        "doc_penalty": d.doc_penalty,
        "doc_payment": d.doc_payment,
        "rev_gen": d.rev_gen,
        "reparto": d.reparto,
        "reparto_label": d.reparto,
        "reparto_acronimo": reparto_acronimo,
        "remarks": d.remarks,
        "dis_plan_date_rev0": rev0.dis_plan_date.isoformat()
        if (rev0 and rev0.dis_plan_date)
        else None,
        "latest_rev_id": latest_rev.pk if latest_rev else None,
        "latest_rev_no": latest_rev.rev_no if latest_rev else None,
        "latest_rev_let": latest_rev.rev_let if latest_rev else "",
        "latest_int_status": latest_int_status,
        "latest_int_status_label": latest_int_status_label,
        "latest_ext_status": latest_rev.ext_status_id if latest_rev else None,
        "latest_ext_status_label": latest_rev.ext_status.nome
        if (latest_rev and latest_rev.ext_status)
        else "",
        "latest_ext_status_colore": latest_rev.ext_status.colore
        if (latest_rev and latest_rev.ext_status)
        else "",
        "latest_dis_plan_date": latest_rev.dis_plan_date.isoformat()
        if (latest_rev and latest_rev.dis_plan_date)
        else None,
        "latest_dis_act_date": latest_rev.dis_act_date.isoformat()
        if (latest_rev and latest_rev.dis_act_date)
        else None,
        "latest_rec_plan_date": latest_rev.rec_plan_date.isoformat()
        if (latest_rev and latest_rev.rec_plan_date)
        else None,
        "latest_rec_act_date": latest_rev.rec_act_date.isoformat()
        if (latest_rev and latest_rev.rec_act_date)
        else None,
        "latest_rev_display": (
            format_revisione_label(latest_rev.rev_no, latest_rev.rev_let, rev_let_flag)
            if latest_rev
            else "—"
        )
        or "—",
    }


def list_documenti(job):
    t = Testata.objects.get(job=job)
    reparto_acronimi = dict(Reparto.objects.values_list("nome", "acronimo"))
    docs = t.documenti.prefetch_related(
        Prefetch(
            "revisioni",
            queryset=Revisione.objects.select_related("ext_status").order_by("rev_no"),
        )
    ).order_by("pk")
    return [serialize_documento(d, reparto_acronimi, rev_let_flag=t.rev_let_flag) for d in docs]


def revisioni_by_doc_for_job(job: str) -> dict[int, list[dict]]:
    """Return all revisions for a commessa, grouped by document id."""
    revs_by_doc: dict[int, list[dict]] = {}
    revisioni_qs = (
        Revisione.objects.filter(documento__testata_id=job)
        .select_related("ext_status")
        .order_by("documento_id", "rev_no")
    )
    for r in revisioni_qs:
        revs_by_doc.setdefault(r.documento_id, []).append(serialize_revisione(r))
    return revs_by_doc


def list_situazione(job: str) -> dict:
    """Return documenti and revisioni for situazione views in a single payload."""
    t = Testata.objects.get(job=job)
    return {
        "documenti": list_documenti(job),
        "revisioni_by_doc": revisioni_by_doc_for_job(job),
        "rev_let_flag": t.rev_let_flag,
    }


def create_documento(job, data):
    t = Testata.objects.get(job=job)
    d = Documento(testata=t, **_clean_documento_fields(data))
    d.full_clean()
    d.save()
    rev0 = Revisione.objects.create(documento=d, rev_no=0)
    dis_plan = _parse_date(data.get("dis_plan_date_rev0"))
    if dis_plan is not None:
        rev0.dis_plan_date = dis_plan
        rev0.save(update_fields=["dis_plan_date"])
    return d


def update_documento(pk, data):
    d = Documento.objects.get(pk=pk)
    had_reparto = bool(d.reparto)
    for k, v in _clean_documento_fields(data).items():
        setattr(d, k, v)
    d.full_clean()
    d.save()
    # If reparto was just set and no revision exists yet, create rev 0
    if d.reparto and not had_reparto and not d.revisioni.exists():
        Revisione.objects.create(documento=d, rev_no=0)
    if "dis_plan_date_rev0" in data:
        dis_plan = _parse_date(data["dis_plan_date_rev0"])
        rev0 = d.revisioni.filter(rev_no=0).first()
        if rev0 is not None:
            rev0.dis_plan_date = dis_plan
            rev0.save(update_fields=["dis_plan_date"])
    return d


def delete_documento(pk):
    Documento.objects.get(pk=pk).delete()


@transaction.atomic
def genera_documenti_da_modelli(job, cartella_id):
    """Crea un Documento per ciascun ModelloDocumento della cartella indicata.
    Se vendor_doc è già presente nella commessa, il modello viene saltato.
    Restituisce (creati, saltati)."""
    t = Testata.objects.get(job=job)
    try:
        cartella = CartellaModelloDocumento.objects.get(pk=cartella_id)
    except CartellaModelloDocumento.DoesNotExist:
        raise ValueError("Cartella modelli non trovata.")
    modelli = list(cartella.modelli.all())
    if not modelli:
        return [], 0
    existing_vendor = set(v for v in t.documenti.values_list("vendor_doc", flat=True) if v)
    creati = []
    saltati = 0
    for m in modelli:
        vendor = m.vendor_doc_for(job)
        if vendor in existing_vendor:
            saltati += 1
            continue
        d = Documento.objects.create(
            testata=t,
            doc_title=m.doc_title,
            item_no=m.item_no,
            vendor_doc=vendor,
            reparto=m.reparto,
        )
        Revisione.objects.create(documento=d, rev_no=0)
        creati.append(d)
    return creati, saltati


def list_cartelle_modelli():
    return CartellaModelloDocumento.objects.prefetch_related("modelli").order_by("nome")


def serialize_cartella_modello(c):
    modelli = list(c.modelli.all())
    return {
        "id": c.pk,
        "nome": c.nome,
        "descrizione": c.descrizione,
        "modelli": [
            {
                "id": m.pk,
                "doc_title": m.doc_title,
                "item_no": m.item_no,
                "codice_fisso": m.codice_fisso,
                "reparto": m.reparto,
            }
            for m in modelli
        ],
        "modelli_count": len(modelli),
    }


_DOCUMENTO_FIELDS = {
    "item_no",
    "vendor_doc",
    "client_doc_no",
    "contractor_doc_no",
    "client_doc_class",
    "doc_title",
    "doc_penalty",
    "doc_payment",
    "rev_gen",
    "reparto",
    "remarks",
}


def _clean_documento_fields(data):
    return {k: v for k, v in data.items() if k in _DOCUMENTO_FIELDS}


# ── StatoEsterno ─────────────────────────────────────────────────────────────


def list_stati_interni():
    """Return hardcoded internal status choices."""
    from ..models import STATI_INTERNI_CHOICES

    return [{"id": k, "nome": v} for k, v in STATI_INTERNI_CHOICES]


def list_stati_esterni():
    return [
        {
            "id": s.pk,
            "nome": s.nome,
            "lettera": s.lettera,
            "colore": s.colore,
            "crea_nuova_rev": s.crea_nuova_rev,
        }
        for s in StatoEsterno.objects.all()
    ]


def create_stato_esterno(data):
    s = StatoEsterno(
        nome=data.get("nome", "").strip(),
        lettera=(data.get("lettera") or "").strip().upper()[:2],
        colore=data.get("colore", "").strip(),
    )
    if "crea_nuova_rev" in data:
        s.crea_nuova_rev = bool(data["crea_nuova_rev"])
    s.full_clean()
    s.save()
    return s


def update_stato_esterno(pk, data):
    s = StatoEsterno.objects.get(pk=pk)
    if "nome" in data:
        s.nome = data["nome"].strip()
    if "lettera" in data:
        s.lettera = (data.get("lettera") or "").strip().upper()[:2]
    if "colore" in data:
        s.colore = data["colore"].strip()
    if "crea_nuova_rev" in data:
        s.crea_nuova_rev = bool(data["crea_nuova_rev"])
    s.full_clean()
    s.save()
    return s


def delete_stato_esterno(pk):
    StatoEsterno.objects.get(pk=pk).delete()


# ── Revisione CRUD ───────────────────────────────────────────────────────────


def serialize_revisione(r):
    int_status_label = ""
    if r.int_status:
        from ..models import STATI_INTERNI_CHOICES

        label_map = dict(STATI_INTERNI_CHOICES)
        int_status_label = label_map.get(r.int_status, r.int_status)
    # Colori pronti per le celle: fondo uguale al colore dello stato, testo
    # bianco o nero scelto per contrasto (vedi stato_esterno_colori).
    cella = cell_colors(r.ext_status.colore) if r.ext_status else {"bg": "", "fg": ""}
    return {
        "id": r.pk,
        "documento_id": r.documento_id,
        "rev_no": r.rev_no,
        "rev_let": r.rev_let,
        "dis_plan_date": r.dis_plan_date.isoformat() if r.dis_plan_date else None,
        "dis_act_date": r.dis_act_date.isoformat() if r.dis_act_date else None,
        "rec_plan_date": r.rec_plan_date.isoformat() if r.rec_plan_date else None,
        "rec_act_date": r.rec_act_date.isoformat() if r.rec_act_date else None,
        "int_status": r.int_status,
        "int_status_label": int_status_label,
        "ext_status": r.ext_status_id,
        "ext_status_label": r.ext_status.nome if r.ext_status else "",
        "ext_status_lettera": r.ext_status.lettera if r.ext_status else "",
        "ext_status_colore": r.ext_status.colore if r.ext_status else "",
        "ext_status_bg": cella["bg"],
        "ext_status_fg": cella["fg"],
        "crea_nuova_rev": r.crea_nuova_rev,
    }


def list_revisioni(doc_pk):
    d = Documento.objects.get(pk=doc_pk)
    return [
        serialize_revisione(r) for r in d.revisioni.select_related("ext_status").order_by("rev_no")
    ]


def create_revisione(doc_pk, data):
    d = Documento.objects.get(pk=doc_pk)
    r = Revisione(documento=d, **_clean_revisione_fields(data))
    r.full_clean()
    r.save()
    return r


def update_revisione(pk, data):
    r = Revisione.objects.get(pk=pk)
    for k, v in _clean_revisione_fields(data).items():
        setattr(r, k, v)
    r.full_clean()
    r.save()
    return r


def delete_revisione(pk):
    Revisione.objects.get(pk=pk).delete()


_REVISIONE_FIELDS = {
    "rev_no",
    "rev_let",
    "dis_plan_date",
    "dis_act_date",
    "rec_plan_date",
    "rec_act_date",
    "int_status",
    "ext_status",
    "crea_nuova_rev",
}


def _clean_revisione_fields(data):
    cleaned = {}
    for k, v in data.items():
        if k in _REVISIONE_FIELDS:
            if k == "ext_status":
                cleaned[k + "_id"] = v if v else None
            elif k == "int_status":
                cleaned[k] = v or ""
            elif k.endswith("_date") and v == "":
                cleaned[k] = None
            else:
                cleaned[k] = v
    return cleaned


# ── Emissione ────────────────────────────────────────────────────────────────


def esegui_emissione(doc_ids, dis_act_date):
    """
    For each document in doc_ids, update its current (latest) revision:
    - set DisActDate
    - compute RecPlanDate = DisActDate + TimeCliDocRev
    - set IntStatus = 'inviato_al_cliente'
    Returns the list of updated revision dicts.
    """
    if isinstance(dis_act_date, str):
        dis_act_date = date_type.fromisoformat(dis_act_date)

    updated = []

    for doc_id in doc_ids:
        doc = Documento.objects.select_related("testata").get(pk=doc_id)
        rev = doc.revisioni.order_by("-rev_no").first()
        if rev is None:
            rev = Revisione.objects.create(documento=doc, rev_no=0)

        rev.dis_act_date = dis_act_date
        rev.int_status = "inviato_al_cliente"

        time_cli = doc.testata.time_cli_doc_rev
        if time_cli:
            rev.rec_plan_date = dis_act_date + timedelta(days=time_cli)
        else:
            rev.rec_plan_date = None

        rev.save()
        updated.append(serialize_revisione(rev))

    return updated


# ── Ricezione ────────────────────────────────────────────────────────────────


def esegui_ricezione(entries, crea_nuova_revisione=False):
    """
    entries: list of {doc_id, rec_act_date, ext_status_id, crea_nuova_revisione (optional)}
    crea_nuova_revisione: bool — global default, overridden per entry if specified.
    Returns list of updated/created revision dicts.
    """
    result = []
    for entry in entries:
        doc_id = entry.get("doc_id")
        rec_act_date_raw = entry.get("rec_act_date", "")
        ext_status_id = entry.get("ext_status_id") or None
        crea_rev = bool(entry.get("crea_nuova_revisione", crea_nuova_revisione))

        if not doc_id or not rec_act_date_raw:
            continue

        if isinstance(rec_act_date_raw, str):
            rec_act_date = date_type.fromisoformat(rec_act_date_raw)
        else:
            rec_act_date = rec_act_date_raw

        doc = Documento.objects.select_related("testata").get(pk=doc_id)
        rev = doc.revisioni.order_by("-rev_no").first()
        if rev is None:
            continue

        rev.rec_act_date = rec_act_date
        rev.ext_status_id = ext_status_id
        rev.int_status = "ricevuto"
        rev.save()
        result.append(serialize_revisione(rev))

        if crea_rev:
            next_rev_no = (rev.rev_no or 0) + 1
            time_ven = doc.testata.time_ven_doc_rev
            dis_plan = rec_act_date + timedelta(days=time_ven) if time_ven else None
            new_rev = Revisione.objects.create(
                documento=doc,
                rev_no=next_rev_no,
                dis_plan_date=dis_plan,
                crea_nuova_rev=True,
            )
            result.append(serialize_revisione(new_rev))

    return result


# ── File resolution ───────────────────────────────────────────────────────────


def risolvi_file_revisione(revisione_id: int) -> dict:
    """Attempt to auto-resolve the filesystem path for a revision's file.

    Resolution order:
    1. Return the manual link if one has been saved in ``RevisioneFileLink``.
    2. If ``rec_act_date`` is set → look in ``RICEVUTI/{date}/``.
    3. Else if ``dis_act_date`` is set → look in the base path.
    4. Otherwise return ``not_found``.

    Matching rule: the filename must start with ``Documento.vendor_doc``
    (case-insensitive).

    Args:
        revisione_id: Primary key of the ``Revisione`` to resolve.

    Returns:
        Dict with keys:
            - ``status``: ``"found"``, ``"multiple"``, ``"manual_linked"``,
              or ``"not_found"``.
            - ``files``: list of dicts (``percorso``, ``nome``, ``estensione``).

    Raises:
        Revisione.DoesNotExist: If no revision matches ``revisione_id``.
    """
    from pathlib import Path as _Path

    from ..models import Reparto, RevisioneFileLink
    from .fileserver import get_base_path, get_ricevuti_path, trova_file

    rev = Revisione.objects.select_related("documento__testata").get(pk=revisione_id)
    doc = rev.documento
    vendor_doc = doc.vendor_doc.strip()

    # 1. Check manual link first
    try:
        link = RevisioneFileLink.objects.get(revisione=rev)
        percorso = link.percorso
        return {
            "status": "manual_linked",
            "files": [
                {
                    "percorso": percorso,
                    "nome": _Path(percorso).name,
                    "estensione": _Path(percorso).suffix.lstrip(".").lower(),
                }
            ],
        }
    except RevisioneFileLink.DoesNotExist:
        pass

    if not vendor_doc:
        return {"status": "not_found", "files": []}

    # 2. Resolve reparto acronimo
    reparto_obj = Reparto.objects.filter(nome=doc.reparto).first()
    if not reparto_obj or not reparto_obj.acronimo:
        return {"status": "not_found", "files": []}
    reparto_acronimo = reparto_obj.acronimo
    commessa = doc.testata.job

    # 3. Determine directory to scan
    if rev.rec_act_date:
        data_str = rev.rec_act_date.strftime("%Y-%m-%d")
        directory = get_ricevuti_path(commessa, reparto_acronimo, data_str)
    elif rev.dis_act_date:
        directory = get_base_path(commessa, reparto_acronimo)
    else:
        return {"status": "not_found", "files": []}

    files = trova_file(directory, vendor_doc)

    if not files:
        return {"status": "not_found", "files": []}
    if len(files) == 1:
        return {"status": "found", "files": files}
    return {"status": "multiple", "files": files}


def salva_file_link(revisione_id: int, percorso: str) -> object:
    """Create or update the manual file link for a revision.

    Args:
        revisione_id: Primary key of the ``Revisione``.
        percorso: Full filesystem path to the file. Must be inside FILESERVER_JOBS_PATH.

    Returns:
        The saved ``RevisioneFileLink`` instance.

    Raises:
        Revisione.DoesNotExist: If no revision matches ``revisione_id``.
        PermissionError: If the path is outside the JOBS root.
    """
    from pathlib import Path

    from ..models import RevisioneFileLink
    from .fileserver import get_jobs_root

    rev = Revisione.objects.get(pk=revisione_id)
    percorso_clean = percorso.strip()
    try:
        Path(percorso_clean).resolve().relative_to(get_jobs_root().resolve())
    except ValueError:
        raise PermissionError("Percorso non autorizzato: fuori dalla cartella JOBS.")
    link, _ = RevisioneFileLink.objects.update_or_create(
        revisione=rev,
        defaults={"percorso": percorso_clean},
    )
    return link
