from functools import wraps

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods
import json
import logging
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

from .models import Testata, IndirSped, Documento, Revisione, StatoEsterno, User
from src.pdf import genera_trasmittal_pdf

logger = logging.getLogger(__name__)

from .services.commesse import (
    list_commesse, get_commessa, create_commessa, update_commessa,
    delete_commessa, fetch_from_bc, serialize_testata,
    list_indirizzi, create_indirizzo, update_indirizzo,
    delete_indirizzo, serialize_indirizzo,
    list_documenti, create_documento, update_documento,
    delete_documento, serialize_documento,
    genera_documenti_da_modelli,
    list_reparti,
    list_stati_interni,
    list_stati_esterni, create_stato_esterno, update_stato_esterno, delete_stato_esterno,
    list_revisioni, create_revisione, update_revisione,
    delete_revisione, serialize_revisione,
    esegui_emissione, esegui_ricezione,
)


def api_login_required(view_func):
    """Decorator that returns 401 JSON for unauthenticated requests instead of redirecting."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Non autenticato.'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


# ── API: Commesse (Testata) ──────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET', 'POST'])
def commesse_api(request):
    if request.method == 'GET':
        q = request.GET.get('q', '').strip() or None
        return JsonResponse({'commesse': list_commesse(q)})
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    try:
        t = create_commessa(data)
        return JsonResponse({'ok': True, 'data': serialize_testata(t)}, status=201)
    except IntegrityError:
        return JsonResponse({'error': 'Una commessa con questo Job esiste già.'}, status=409)
    except ValidationError as exc:
        return JsonResponse({'error': exc.message_dict}, status=422)


@api_login_required
@require_http_methods(['GET', 'PUT', 'DELETE'])
def commessa_api_detail(request, job):
    if request.method == 'GET':
        try:
            t = get_commessa(job)
            return JsonResponse({'data': serialize_testata(t)})
        except Testata.DoesNotExist:
            logger.warning('Commessa "%s" non trovata nel database locale.', job)
            return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    if request.method == 'PUT':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'JSON non valido.'}, status=400)
        try:
            t = update_commessa(job, data)
            return JsonResponse({'ok': True, 'data': serialize_testata(t)})
        except Testata.DoesNotExist:
            return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
        except ValidationError as exc:
            return JsonResponse({'error': exc.message_dict}, status=422)
    try:
        delete_commessa(job)
        return JsonResponse({'ok': True})
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)


@api_login_required
@require_http_methods(['GET'])
def erp_api(request):
    job = request.GET.get('job', '').strip()
    if not job:
        return JsonResponse({'error': 'Parametro job mancante.'}, status=400)
    try:
        data = fetch_from_bc(job)
        if data:
            logger.info('ERP: commessa "%s" trovata — campi restituiti: %s', job, list(data.keys()))
        else:
            logger.warning('ERP: commessa "%s" non trovata in Business Central (risposta vuota).', job)
        return JsonResponse({'data': data})
    except Exception as exc:
        logger.error('ERP: errore durante il recupero della commessa "%s": %s', job, exc)
        return JsonResponse({'data': {}, 'warning': str(exc)})


# ── API: Indirizzi di Spedizione ─────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET', 'POST'])
def indirizzi_api(request, job):
    if request.method == 'GET':
        try:
            return JsonResponse({'indirizzi': list_indirizzi(job)})
        except Testata.DoesNotExist:
            return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    try:
        i = create_indirizzo(job, data)
        return JsonResponse({'ok': True, 'data': serialize_indirizzo(i)}, status=201)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@api_login_required
@require_http_methods(['PATCH', 'DELETE'])
def indirizzo_api_detail(request, pk):
    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'JSON non valido.'}, status=400)
        try:
            i = update_indirizzo(pk, data)
            return JsonResponse({'ok': True, 'data': serialize_indirizzo(i)})
        except IndirSped.DoesNotExist:
            return JsonResponse({'error': 'Indirizzo non trovato.'}, status=404)
        except ValidationError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    try:
        delete_indirizzo(pk)
        return JsonResponse({'ok': True})
    except IndirSped.DoesNotExist:
        return JsonResponse({'error': 'Indirizzo non trovato.'}, status=404)


# ── API: Documenti ───────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET', 'POST'])
def documenti_api(request, job):
    if request.method == 'GET':
        try:
            return JsonResponse({'documenti': list_documenti(job)})
        except Testata.DoesNotExist:
            return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    try:
        d = create_documento(job, data)
        return JsonResponse({'ok': True, 'data': serialize_documento(d)}, status=201)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@api_login_required
@require_http_methods(['PATCH', 'DELETE'])
def documento_api_detail(request, pk):
    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'JSON non valido.'}, status=400)
        try:
            d = update_documento(pk, data)
            return JsonResponse({'ok': True, 'data': serialize_documento(d)})
        except Documento.DoesNotExist:
            return JsonResponse({'error': 'Documento non trovato.'}, status=404)
        except ValidationError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    try:
        delete_documento(pk)
        return JsonResponse({'ok': True})
    except Documento.DoesNotExist:
        return JsonResponse({'error': 'Documento non trovato.'}, status=404)


# ── API: Reparti ────────────────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def reparti_api(request):
    reparti = list_reparti()
    return JsonResponse({'reparti': [{'nome': r} for r in reparti]})


# ── API: Stati Interni / Esterni ─────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def stati_interni_api(request):
    return JsonResponse({'stati': list_stati_interni()})


@api_login_required
@require_http_methods(['GET', 'POST'])
def stati_esterni_api(request):
    if request.method == 'GET':
        return JsonResponse({'stati': list_stati_esterni()})
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    try:
        s = create_stato_esterno(data)
        return JsonResponse({'ok': True, 'data': {'id': s.pk, 'nome': s.nome, 'colore': s.colore}}, status=201)
    except IntegrityError:
        return JsonResponse({'error': 'Esiste già uno stato esterno con questo nome.'}, status=409)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@api_login_required
@require_http_methods(['PATCH', 'DELETE'])
def stato_esterno_api_detail(request, pk):
    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'JSON non valido.'}, status=400)
        try:
            s = update_stato_esterno(pk, data)
            return JsonResponse({'ok': True, 'data': {'id': s.pk, 'nome': s.nome, 'colore': s.colore}})
        except StatoEsterno.DoesNotExist:
            return JsonResponse({'error': 'Stato esterno non trovato.'}, status=404)
        except IntegrityError:
            return JsonResponse({'error': 'Esiste già uno stato esterno con questo nome.'}, status=409)
        except Exception as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    try:
        delete_stato_esterno(pk)
        return JsonResponse({'ok': True})
    except StatoEsterno.DoesNotExist:
        return JsonResponse({'error': 'Stato esterno non trovato.'}, status=404)


# ── API: Emissione ───────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['POST'])
def emissione_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    doc_ids = data.get('doc_ids', [])
    dis_act_date = data.get('dis_act_date', '')
    if not doc_ids or not dis_act_date:
        return JsonResponse({'error': 'Specificare doc_ids e dis_act_date.'}, status=400)
    try:
        updated = esegui_emissione(doc_ids, dis_act_date)
        return JsonResponse({'ok': True, 'updated': updated})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


# ── API: Trasmittal PDF ─────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['POST'])
def trasmittal_pdf_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)

    doc_ids = data.get('doc_ids', [])
    addr_ids = data.get('addr_ids', [])
    date_str = data.get('date', '')
    job = data.get('job', '')

    if not doc_ids or not job:
        return JsonResponse({'error': 'Specificare job e doc_ids.'}, status=400)

    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)

    # Build testata dict
    testata_dict = {
        'job': testata.job,
        'po_no': testata.po_no or '',
        'job_detail': testata.job_detail or '',
        'client': testata.client or '',
    }

    # Build addresses list
    addresses = []
    if addr_ids:
        for addr in IndirSped.objects.filter(pk__in=addr_ids, testata=testata):
            addresses.append({
                'consignee': addr.consignee,
                'address': addr.address,
                'zip_code': addr.zip_code,
                'city': addr.city,
                'country': addr.country,
                'attn': addr.attn,
                'ph_no': addr.ph_no,
            })

    # Build documents list with latest revision info
    documents = []
    for doc in Documento.objects.filter(pk__in=doc_ids, testata=testata).order_by('item_no'):
        rev = doc.revisioni.order_by('-rev_no').first()
        documents.append({
            'job': testata.job,
            'item_no': doc.item_no or '',
            'vendor_doc': doc.vendor_doc or '',
            'doc_title': doc.doc_title or '',
            'rev_no': rev.rev_no if rev else '',
            'rev_let': rev.rev_let if rev else '',
            'rec_plan_date': rev.rec_plan_date.isoformat() if rev and rev.rec_plan_date else '',
        })

    if not date_str:
        from datetime import date as date_type
        date_str = date_type.today().isoformat()

    try:
        pdf_bytes = genera_trasmittal_pdf(testata_dict, addresses, documents, date_str)
    except Exception as exc:
        return JsonResponse({'error': f'Errore generazione PDF: {exc}'}, status=500)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    safe_job = job.replace('"', '')
    response['Content-Disposition'] = f'inline; filename="trasmittal_{safe_job}_{date_str}.pdf"'
    return response


# ── API: Ricezione ───────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['POST'])
def ricezione_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    entries = data.get('entries', [])
    crea_nuova_revisione = bool(data.get('crea_nuova_revisione', False))
    if not entries:
        return JsonResponse({'error': 'Specificare almeno un documento.'}, status=400)
    try:
        result = esegui_ricezione(entries, crea_nuova_revisione)
        return JsonResponse({'ok': True, 'result': result})
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)


# ── API: Revisioni ───────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET', 'POST'])
def revisioni_api(request, doc_pk):
    if request.method == 'GET':
        try:
            return JsonResponse({'revisioni': list_revisioni(doc_pk)})
        except Documento.DoesNotExist:
            return JsonResponse({'error': 'Documento non trovato.'}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON non valido.'}, status=400)
    try:
        r = create_revisione(doc_pk, data)
        return JsonResponse({'ok': True, 'data': serialize_revisione(r)}, status=201)
    except Documento.DoesNotExist:
        return JsonResponse({'error': 'Documento non trovato.'}, status=404)
    except ValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@api_login_required
@require_http_methods(['PATCH', 'DELETE'])
def revisione_api_detail(request, pk):
    if request.method == 'PATCH':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'JSON non valido.'}, status=400)
        try:
            r = update_revisione(pk, data)
            return JsonResponse({'ok': True, 'data': serialize_revisione(r)})
        except Revisione.DoesNotExist:
            return JsonResponse({'error': 'Revisione non trovata.'}, status=404)
        except ValidationError as exc:
            return JsonResponse({'error': str(exc)}, status=400)
    try:
        delete_revisione(pk)
        return JsonResponse({'ok': True})
    except Revisione.DoesNotExist:
        return JsonResponse({'error': 'Revisione non trovata.'}, status=404)


# ── Export: Document list as Excel ───────────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def export_documenti(request, job):
    try:
        documenti = list_documenti(job)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Document List'

    headers = [
        'Item', 'B&R Doc', 'Client Doc N°', 'Client Doc Class',
        'Titolo', 'Reparto', 'Penale', 'Pagamento', 'Note',
    ]
    header_fill = PatternFill(start_color='1C1C1A', end_color='1C1C1A', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=10)

    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for row_idx, d in enumerate(documenti, start=2):
        ws.cell(row=row_idx, column=1, value=d['item_no'])
        ws.cell(row=row_idx, column=2, value=d['vendor_doc'])
        ws.cell(row=row_idx, column=3, value=d['client_doc_no'])
        ws.cell(row=row_idx, column=4, value=d['client_doc_class'])
        ws.cell(row=row_idx, column=5, value=d['doc_title'])
        ws.cell(row=row_idx, column=6, value=d['reparto_label'])
        ws.cell(row=row_idx, column=7, value='Sì' if d['doc_penalty'] else '')
        ws.cell(row=row_idx, column=8, value='Sì' if d['doc_payment'] else '')
        ws.cell(row=row_idx, column=9, value=d['remarks'])

    # Auto-fit column widths
    for col_idx, _ in enumerate(headers, start=1):
        max_len = max(
            (len(str(ws.cell(row=r, column=col_idx).value or '')) for r in range(1, ws.max_row + 1)),
            default=8,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f'{job}_document_list.xlsx'
    response = HttpResponse(
        buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ── Import: Document list from Excel ─────────────────────────────────────────

# Column aliases accepted in the uploaded file (case-insensitive, stripped)
_IMPORT_COL_MAP = {
    'item': 'item_no',
    'item no': 'item_no',
    'item_no': 'item_no',
    'vendor doc': 'vendor_doc',
    'vendor_doc': 'vendor_doc',
    'b&r doc': 'vendor_doc',
    'client doc n°': 'client_doc_no',
    'client doc no': 'client_doc_no',
    'client doc n': 'client_doc_no',
    'client_doc_no': 'client_doc_no',
    'client doc class': 'client_doc_class',
    'client_doc_class': 'client_doc_class',
    'titolo': 'doc_title',
    'titolo documento': 'doc_title',
    'doc title': 'doc_title',
    'doc_title': 'doc_title',
    'reparto': 'reparto_name',
    'penale': 'doc_penalty',
    'doc penalty': 'doc_penalty',
    'doc_penalty': 'doc_penalty',
    'pagamento': 'doc_payment',
    'doc payment': 'doc_payment',
    'doc_payment': 'doc_payment',
    'rev generale': 'rev_gen',
    'rev. generale': 'rev_gen',
    'rev_gen': 'rev_gen',
    'note': 'remarks',
    'remarks': 'remarks',
}

_BOOL_TRUE = {'sì', 'si', 'yes', '1', 'true', 'x', 'vero'}


def _parse_bool(val):
    return str(val).strip().lower() in _BOOL_TRUE


@api_login_required
@require_http_methods(['POST'])
def genera_documenti_da_modelli_api(request, job):
    try:
        creati, saltati = genera_documenti_da_modelli(job)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)
    return JsonResponse({
        'ok': True,
        'created': len(creati),
        'skipped': saltati,
        'documenti': [serialize_documento(d) for d in creati],
    })


@api_login_required
@require_http_methods(['POST'])
def import_documenti_excel(request, job):
    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({'error': 'Commessa non trovata.'}, status=404)

    f = request.FILES.get('file')
    if not f:
        return JsonResponse({'error': 'Nessun file caricato.'}, status=400)

    try:
        wb = openpyxl.load_workbook(f, data_only=True)
    except Exception:
        return JsonResponse({'error': 'File Excel non valido o corrotto.'}, status=400)

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return JsonResponse({'error': 'Il file è vuoto.'}, status=400)

    # Map header row → field names
    header_row = [str(c).strip().lower() if c is not None else '' for c in rows[0]]
    col_map = {}  # col_index → field name
    for idx, h in enumerate(header_row):
        field = _IMPORT_COL_MAP.get(h)
        if field:
            col_map[idx] = field

    if not col_map:
        return JsonResponse({'error': 'Nessuna colonna riconosciuta. Verifica le intestazioni.'}, status=400)

    # Build valid reparti set from User.reparto
    valid_reparti = set(
        r.lower() for r in list_reparti()
    )

    created = []
    errors = []
    for row_num, row in enumerate(rows[1:], start=2):
        if all(c is None or str(c).strip() == '' for c in row):
            continue  # skip blank rows
        data = {}
        for col_idx, field in col_map.items():
            val = row[col_idx] if col_idx < len(row) else None
            data[field] = val

        reparto_str = ''
        if 'reparto_name' in data:
            name = str(data.pop('reparto_name') or '').strip()
            if name:
                if name.lower() in valid_reparti:
                    reparto_str = name
                else:
                    errors.append(f'Riga {row_num}: reparto "{name}" non trovato, ignorato.')

        try:
            doc = Documento.objects.create(
                testata=testata,
                item_no=str(data.get('item_no') or '').strip(),
                vendor_doc=str(data.get('vendor_doc') or '').strip(),
                client_doc_no=str(data.get('client_doc_no') or '').strip(),
                client_doc_class=str(data.get('client_doc_class') or '').strip(),
                doc_title=str(data.get('doc_title') or '').strip(),
                doc_penalty=_parse_bool(data.get('doc_penalty', '')),
                doc_payment=_parse_bool(data.get('doc_payment', '')),
                rev_gen=_parse_bool(data.get('rev_gen', '')),
                reparto=reparto_str,
                remarks=str(data.get('remarks') or '').strip(),
            )
            Revisione.objects.create(documento=doc, rev_no=0)
            created.append(doc.pk)
        except Exception as exc:
            errors.append(f'Riga {row_num}: {exc}')

    return JsonResponse({'created': len(created), 'errors': errors})


# ── API: Ticket ──────────────────────────────────────────────────────────────

from .services.tickets import (
    list_tickets, get_ticket, create_ticket, update_ticket, delete_ticket,
    transition_revisione, list_revisioni_da_emettere,
    list_note, create_nota,
    list_notifiche, count_non_lette, mark_as_read, mark_all_as_read,
    serialize_ticket,
    count_revisioni_da_emettere_per_reparto, count_tickets_attivi_per_reparto,
    get_user_overview,
)


@api_login_required
@require_http_methods(['GET', 'POST'])
def tickets_api(request):
    if request.method == 'GET':
        reparto = request.GET.get('reparto', '')
        concluso_param = request.GET.get('concluso', '')
        commessa = request.GET.get('commessa', '')
        concluso = None
        if concluso_param == '1':
            concluso = True
        elif concluso_param == '0':
            concluso = False
        data = list_tickets(
            reparto=reparto or None,
            concluso=concluso,
            commessa=commessa or None,
        )
        return JsonResponse(data, safe=False)
    else:
        try:
            body = json.loads(request.body)
            t = create_ticket(body, request.user)
            return JsonResponse(serialize_ticket(t), status=201)
        except (KeyError, ValueError, ValidationError) as e:
            return JsonResponse({'error': str(e)}, status=400)


@api_login_required
@require_http_methods(['GET', 'PUT', 'DELETE'])
def ticket_api_detail(request, pk):
    try:
        if request.method == 'GET':
            t = get_ticket(pk)
            return JsonResponse(serialize_ticket(t))
        elif request.method == 'PUT':
            body = json.loads(request.body)
            t = update_ticket(pk, body)
            t = get_ticket(pk)
            return JsonResponse(serialize_ticket(t))
        else:
            delete_ticket(pk)
            return JsonResponse({'ok': True})
    except Exception as e:
        status = 404 if 'does not exist' in str(e) else 400
        return JsonResponse({'error': str(e)}, status=status)


@api_login_required
@require_http_methods(['POST'])
def revisione_transition_api(request, pk):
    """Per-revisione workflow transition. Body: {action, nota?}."""
    try:
        body = json.loads(request.body)
        action = body.get('action', '')
        nota = body.get('nota', '')
        ticket, _rev = transition_revisione(pk, action, request.user, nota_testo=nota or None)
        return JsonResponse(serialize_ticket(ticket))
    except PermissionError as e:
        return JsonResponse({'error': str(e)}, status=403)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=404)


@api_login_required
@require_http_methods(['GET'])
def revisioni_da_emettere_api(request):
    reparto = request.GET.get('reparto', '')
    commessa = request.GET.get('commessa', '')
    data = list_revisioni_da_emettere(
        reparto=reparto or None,
        commessa=commessa or None,
    )
    return JsonResponse(data, safe=False)


@api_login_required
@require_http_methods(['GET'])
def ticket_counts_api(request):
    """Returns badge counts for the sidebar: pending revisions + active tickets per reparto."""
    return JsonResponse({
        'da_emettere': count_revisioni_da_emettere_per_reparto(),
        'attivi': count_tickets_attivi_per_reparto(),
    })


# ── API: Ticket Notes ────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET', 'POST'])
def ticket_note_api(request, pk):
    if request.method == 'GET':
        return JsonResponse(list_note(pk), safe=False)
    else:
        try:
            body = json.loads(request.body)
            testo = body.get('testo', '').strip()
            if not testo:
                return JsonResponse({'error': 'Testo obbligatorio.'}, status=400)
            from .services.tickets import serialize_nota
            n = create_nota(pk, request.user, testo)
            return JsonResponse(serialize_nota(n), status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


# ── API: Notifiche ───────────────────────────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def notifiche_api(request):
    solo_non_lette = request.GET.get('non_lette', '') == '1'
    data = list_notifiche(request.user, solo_non_lette=solo_non_lette)
    count = count_non_lette(request.user)
    return JsonResponse({'notifiche': data, 'non_lette_count': count})


@api_login_required
@require_http_methods(['POST'])
def notifica_leggi_api(request, pk):
    mark_as_read(pk, request.user)
    return JsonResponse({'ok': True})


@api_login_required
@require_http_methods(['POST'])
def notifiche_leggi_tutte_api(request):
    mark_all_as_read(request.user)
    return JsonResponse({'ok': True})


# ── API: Overview (user dashboard) ───────────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def overview_api(request):
    data = get_user_overview(request.user)
    return JsonResponse(data)


# ── API: Users (for ticket assignment) ───────────────────────────────────────

@api_login_required
@require_http_methods(['GET'])
def users_api(request):
    """Return list of active users for ticket assignment dropdowns."""
    users = User.objects.filter(is_active=True).order_by('last_name', 'first_name', 'username')
    data = [
        {'id': u.pk, 'username': u.username, 'nome_completo': u.nome_completo, 'reparto': u.reparto}
        for u in users
    ]
    return JsonResponse(data, safe=False)

