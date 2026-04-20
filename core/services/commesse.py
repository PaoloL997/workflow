from ..models import Testata, IndirSped, Documento, Revisione, StatoEsterno, User, Reparto, STATI_INTERNI_CHOICES
from datetime import timedelta, date as date_type


# ── Serializers ───────────────────────────────────────────────────────────────

def serialize_testata(t):
    return {
        'id': t.pk,
        'job': t.job,
        'vb_job': t.vb_job,
        'client': t.client,
        'po_no': t.po_no,
        'job_detail': t.job_detail,
        'delivery_date': t.delivery_date.isoformat() if t.delivery_date else None,
        'delivery_term': t.delivery_term,
        'requisition': t.requisition,
        'time_cli_doc_rev': t.time_cli_doc_rev,
        'time_ven_doc_rev': t.time_ven_doc_rev,
        'rev_let_flag': t.rev_let_flag,
        'transm_flag': t.transm_flag,
    }


def serialize_indirizzo(i):
    return {
        'id': i.pk,
        'job': i.testata_id,
        'consignee': i.consignee,
        'address': i.address,
        'zip_code': i.zip_code,
        'city': i.city,
        'country': i.country,
        'attn': i.attn,
        'ph_no': i.ph_no,
    }


# ── Testata CRUD ──────────────────────────────────────────────────────────────

def list_commesse(q=None):
    qs = Testata.objects.all().order_by('-pk')
    if q:
        qs = qs.filter(job__icontains=q) | qs.filter(client__icontains=q)
    return [serialize_testata(t) for t in qs]


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


def delete_commessa(job):
    t = Testata.objects.get(job=job)
    t.delete()


# ── ERP fetch ─────────────────────────────────────────────────────────────────

def fetch_from_bc(job):
    from src.erp.business_central import BusinessCentral
    bc = BusinessCentral()
    try:
        ana = bc.get_commessa_anagrafica(job)
        com = bc.get_commessa_commerciale(job)
    finally:
        bc.close()

    result = {}
    if ana is not None and not ana.empty:
        row = ana.iloc[0]
        result['job'] = row.get('commessa', '')
        result['job_detail'] = row.get('descrizione', '')
        result['client'] = row.get('cliente', '')
    if com is not None and not com.empty:
        row = com.iloc[0]
        result['po_no'] = row.get('po_cliente', '')
        result['delivery_date'] = row.get('data_consegna', None)
    return result


# ── IndirSped CRUD ────────────────────────────────────────────────────────────

def list_indirizzi(job):
    t = Testata.objects.get(job=job)
    return [serialize_indirizzo(i) for i in t.indirizzi_spedizione.order_by('pk')]


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
    'job', 'vb_job', 'client', 'po_no', 'job_detail',
    'delivery_date', 'delivery_term', 'requisition',
    'time_cli_doc_rev', 'time_ven_doc_rev',
    'rev_let_flag', 'transm_flag',
}

_INDIRIZZO_FIELDS = {
    'consignee', 'address', 'zip_code', 'city',
    'country', 'attn', 'ph_no',
}


def _clean_testata_fields(data):
    return {k: v for k, v in data.items() if k in _TESTATA_FIELDS}


def _clean_indirizzo_fields(data):
    return {k: v for k, v in data.items() if k in _INDIRIZZO_FIELDS}


# ── Reparto helpers ───────────────────────────────────────────────────────────

def list_reparti():
    """Return reparto names from the Reparto table."""
    return list(Reparto.objects.values_list('nome', flat=True))


# ── Documento CRUD ───────────────────────────────────────────────────────────────────────────────
def serialize_documento(d):
    label_map = dict(STATI_INTERNI_CHOICES)
    latest_rev = d.revisioni.order_by('-rev_no', '-pk').first()
    latest_int_status = latest_rev.int_status if latest_rev else ''
    latest_int_status_label = label_map.get(latest_int_status, latest_int_status) if latest_int_status else ''
    return {
        'id': d.pk,
        'job': d.testata_id,
        'item_no': d.item_no,
        'vendor_doc': d.vendor_doc,
        'client_doc_no': d.client_doc_no,
        'client_doc_class': d.client_doc_class,
        'doc_title': d.doc_title,
        'doc_penalty': d.doc_penalty,
        'doc_payment': d.doc_payment,
        'rev_gen': d.rev_gen,
        'reparto': d.reparto,
        'reparto_label': d.reparto,
        'remarks': d.remarks,
        'latest_int_status': latest_int_status,
        'latest_int_status_label': latest_int_status_label,
    }


def list_documenti(job):
    t = Testata.objects.get(job=job)
    return [serialize_documento(d) for d in t.documenti.order_by('pk')]


def create_documento(job, data):
    t = Testata.objects.get(job=job)
    d = Documento(testata=t, **_clean_documento_fields(data))
    d.full_clean()
    d.save()
    Revisione.objects.create(documento=d, rev_no=0)
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
    return d


def delete_documento(pk):
    Documento.objects.get(pk=pk).delete()


_DOCUMENTO_FIELDS = {
    'item_no', 'vendor_doc', 'client_doc_no', 'client_doc_class',
    'doc_title', 'doc_penalty', 'doc_payment', 'rev_gen',
    'reparto', 'remarks',
}


def _clean_documento_fields(data):
    return {k: v for k, v in data.items() if k in _DOCUMENTO_FIELDS}


# ── StatoEsterno ─────────────────────────────────────────────────────────────

def list_stati_interni():
    """Return hardcoded internal status choices."""
    from ..models import STATI_INTERNI_CHOICES
    return [{'id': k, 'nome': v} for k, v in STATI_INTERNI_CHOICES]


def list_stati_esterni():
    return [{'id': s.pk, 'nome': s.nome, 'colore': s.colore} for s in StatoEsterno.objects.all()]


def create_stato_esterno(data):
    s = StatoEsterno(nome=data.get('nome', '').strip(), colore=data.get('colore', '').strip())
    s.full_clean()
    s.save()
    return s


def update_stato_esterno(pk, data):
    s = StatoEsterno.objects.get(pk=pk)
    if 'nome' in data:
        s.nome = data['nome'].strip()
    if 'colore' in data:
        s.colore = data['colore'].strip()
    s.full_clean()
    s.save()
    return s


def delete_stato_esterno(pk):
    StatoEsterno.objects.get(pk=pk).delete()


# ── Revisione CRUD ───────────────────────────────────────────────────────────

def serialize_revisione(r):
    int_status_label = ''
    if r.int_status:
        from ..models import STATI_INTERNI_CHOICES
        label_map = dict(STATI_INTERNI_CHOICES)
        int_status_label = label_map.get(r.int_status, r.int_status)
    return {
        'id': r.pk,
        'documento_id': r.documento_id,
        'rev_no': r.rev_no,
        'rev_let': r.rev_let,
        'dis_plan_date': r.dis_plan_date.isoformat() if r.dis_plan_date else None,
        'dis_act_date': r.dis_act_date.isoformat() if r.dis_act_date else None,
        'rec_plan_date': r.rec_plan_date.isoformat() if r.rec_plan_date else None,
        'rec_act_date': r.rec_act_date.isoformat() if r.rec_act_date else None,
        'int_status': r.int_status,
        'int_status_label': int_status_label,
        'ext_status': r.ext_status_id,
        'ext_status_label': r.ext_status.nome if r.ext_status else '',
        'ext_status_colore': r.ext_status.colore if r.ext_status else '',
        'crea_nuova_rev': r.crea_nuova_rev,
        'note_rientro': r.note_rientro,
    }


def list_revisioni(doc_pk):
    d = Documento.objects.get(pk=doc_pk)
    return [serialize_revisione(r) for r in d.revisioni.select_related('ext_status').order_by('rev_no')]


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
    'rev_no', 'rev_let',
    'dis_plan_date', 'dis_act_date',
    'rec_plan_date', 'rec_act_date',
    'int_status', 'ext_status',
    'crea_nuova_rev', 'note_rientro',
}


def _clean_revisione_fields(data):
    cleaned = {}
    for k, v in data.items():
        if k in _REVISIONE_FIELDS:
            if k == 'ext_status':
                cleaned[k + '_id'] = v if v else None
            elif k == 'int_status':
                cleaned[k] = v or ''
            elif k.endswith('_date') and v == '':
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
        doc = Documento.objects.select_related('testata').get(pk=doc_id)
        rev = doc.revisioni.order_by('-rev_no').first()
        if rev is None:
            rev = Revisione.objects.create(documento=doc, rev_no=0)

        rev.dis_act_date = dis_act_date
        rev.int_status = 'inviato_al_cliente'

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
        doc_id = entry.get('doc_id')
        rec_act_date_raw = entry.get('rec_act_date', '')
        ext_status_id = entry.get('ext_status_id') or None
        crea_rev = bool(entry.get('crea_nuova_revisione', crea_nuova_revisione))

        if not doc_id or not rec_act_date_raw:
            continue

        if isinstance(rec_act_date_raw, str):
            rec_act_date = date_type.fromisoformat(rec_act_date_raw)
        else:
            rec_act_date = rec_act_date_raw

        doc = Documento.objects.select_related('testata').get(pk=doc_id)
        rev = doc.revisioni.order_by('-rev_no').first()
        if rev is None:
            continue

        rev.rec_act_date = rec_act_date
        rev.ext_status_id = ext_status_id
        rev.int_status = 'ricevuto'
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
