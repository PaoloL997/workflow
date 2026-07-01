import colorsys
import json
import logging
from datetime import date as _date
from functools import wraps

import openpyxl
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from src.pdf import genera_trasmittal_pdf

from .models import (
    Documento,
    IndirSped,
    Permesso,
    Revisione,
    Stabilimento,
    StatoEsterno,
    Testata,
    User,
)
from .permissions import api_write_required
from .services.commesse import (
    close_commessa,
    create_commessa,
    create_documento,
    create_indirizzo,
    create_revisione,
    create_stato_esterno,
    delete_commessa,
    delete_documento,
    delete_indirizzo,
    delete_revisione,
    delete_stato_esterno,
    esegui_emissione,
    esegui_ricezione,
    fetch_from_bc,
    genera_documenti_da_modelli,
    get_commessa,
    list_cartelle_modelli,
    list_commesse,
    list_documenti,
    list_indirizzi,
    list_reparti,
    list_revisioni,
    list_situazione,
    list_stati_esterni,
    list_stati_interni,
    revisioni_by_doc_for_job,
    risolvi_file_revisione,
    salva_file_link,
    serialize_cartella_modello,
    serialize_documento,
    serialize_indirizzo,
    serialize_revisione,
    serialize_testata,
    update_commessa,
    update_documento,
    update_indirizzo,
    update_revisione,
    update_stato_esterno,
)
from .services.import_old import importa_commessa_da_access

logger = logging.getLogger(__name__)


def api_login_required(view_func):
    """Decorator that returns 401 JSON for unauthenticated requests instead of redirecting."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Non autenticato."}, status=401)
        return view_func(request, *args, **kwargs)

    return wrapper


# ── HTML: Auth ───────────────────────────────────────────────────────────────


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(request.GET.get("next", "home"))
        error = "Credenziali non valide. Riprova."
    return render(request, "core/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("login")


def register_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        password1 = request.POST.get("password1", "")
        password2 = request.POST.get("password2", "")
        if not username or not email or not password1:
            error = "Username, email e password sono obbligatori."
        elif password1 != password2:
            error = "Le password non coincidono."
        elif len(password1) < 8:
            error = "La password deve essere di almeno 8 caratteri."
        elif not email.lower().endswith("@brembanarolle.com"):
            error = "È necessario usare un'email con dominio @brembanarolle.com."
        elif User.objects.filter(username=username).exists():
            error = "Username già in uso."
        elif User.objects.filter(email=email).exists():
            error = "Email già registrata."
        else:
            try:
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password1,
                    first_name=first_name,
                    last_name=last_name,
                    permesso=Permesso.READING,
                )
                login(request, user)
                return redirect("home")
            except Exception:
                error = "Errore durante la registrazione. Riprova."
    return render(request, "core/register.html", {"error": error})


# ── HTML: Home ───────────────────────────────────────────────────────────────


@login_required
def commesse_list_view(request):
    return render(request, "core/commesse_list.html", {})


@login_required
def commessa_detail_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    archivio_completo = (
        testata.time_cli_doc_rev is not None and testata.time_ven_doc_rev is not None
    )
    indirizzi_all = list_indirizzi(job)
    STATI_EMESSI = ("inviato_al_cliente", "ricevuto")
    documenti_all = list_documenti(job) if archivio_completo else []
    emissione_count = sum(1 for d in documenti_all if d["latest_int_status"] not in STATI_EMESSI)
    ricezione_count = sum(
        1 for d in documenti_all if d["latest_int_status"] == "inviato_al_cliente"
    )
    situazione_totale = len(documenti_all)
    situazione_emessi = sum(
        1 for d in documenti_all if d["latest_int_status"] in ("inviato_al_cliente", "ricevuto")
    )
    situazione_ricevuti = sum(1 for d in documenti_all if d["latest_int_status"] == "ricevuto")
    # Documenti preview: first 4, assign cycling color class
    _TILE_COLORS = ["tile-c0", "tile-c1", "tile-c2", "tile-c3", "tile-c4"]
    for i, d in enumerate(documenti_all):
        d["tile_color"] = _TILE_COLORS[i % len(_TILE_COLORS)]
    documenti_preview = documenti_all[:7]
    documenti_extra = max(0, len(documenti_all) - 7)

    # Deadline previews for emissione / ricezione cards
    def _urgency(delta):
        if delta is None:
            return "urg-none", "—"
        if delta < -1:
            return "urg-danger", f"{abs(delta)}gg fa"
        if delta == -1:
            return "urg-danger", "Ieri"
        if delta == 0:
            return "urg-today", "Oggi"
        if delta == 1:
            return "urg-urgent", "Domani"
        if delta <= 3:
            return "urg-soon", f"{delta}gg"
        if delta <= 7:
            return "urg-week", f"{delta}gg"
        return "urg-ok", f"{delta}gg"

    _today = _date.today()

    def _enrich(d, date_key):
        raw = d.get(date_key)
        delta = (_date.fromisoformat(raw) - _today).days if raw else None
        urg, label = _urgency(delta)
        return {
            **d,
            "days_label": label,
            "urg_class": urg,
            "_sort": delta if delta is not None else 99999,
        }

    _emissione_all = sorted(
        [
            _enrich(d, "latest_dis_plan_date")
            for d in documenti_all
            if d["latest_int_status"] not in STATI_EMESSI
        ],
        key=lambda x: x["_sort"],
    )
    emissione_preview = _emissione_all[:4]
    emissione_extra = max(0, len(_emissione_all) - 4)

    _ricezione_all = sorted(
        [
            _enrich(d, "latest_rec_plan_date")
            for d in documenti_all
            if d["latest_int_status"] == "inviato_al_cliente"
        ],
        key=lambda x: x["_sort"],
    )
    ricezione_preview = _ricezione_all[:4]
    ricezione_extra = max(0, len(_ricezione_all) - 4)

    return render(
        request,
        "core/commessa_detail.html",
        {
            "testata": testata,
            "archivio_completo": archivio_completo,
            "indirizzi_preview": indirizzi_all[:2],
            "indirizzi_count": len(indirizzi_all),
            "emissione_count": emissione_count,
            "ricezione_count": ricezione_count,
            "situazione_totale": situazione_totale,
            "situazione_emessi": situazione_emessi,
            "situazione_ricevuti": situazione_ricevuti,
            "documenti_preview": documenti_preview,
            "documenti_extra": documenti_extra,
            "emissione_preview": emissione_preview,
            "emissione_extra": emissione_extra,
            "ricezione_preview": ricezione_preview,
            "ricezione_extra": ricezione_extra,
        },
    )


@login_required
def documenti_list_view(request, job):
    from django.http import Http404

    from .services.fileserver import get_jobs_root

    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    reparti = list_reparti()
    commessa_folder = str(get_jobs_root() / job)
    return render(
        request,
        "core/documenti_list.html",
        {
            "testata": testata,
            "reparti": reparti,
            "commessa_folder": commessa_folder,
        },
    )


@login_required
def archivio_detail_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    return render(request, "core/archivio_detail.html", {"testata": testata})


@login_required
def emissione_detail_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    return render(request, "core/emissione_detail.html", {"testata": testata})


@login_required
def ricezione_detail_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    return render(request, "core/ricezione_detail.html", {"testata": testata})


@login_required
def situazione_detail_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    from .services.fileserver import get_jobs_root

    commessa_folder = str(get_jobs_root() / job)
    return render(
        request,
        "core/situazione_detail.html",
        {"testata": testata, "commessa_folder": commessa_folder},
    )


@login_required
def home_view(request):
    return render(request, "core/home.html", {})


# ── API: Commesse (Testata) ──────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def commesse_api(request):
    if request.method == "GET":
        q = request.GET.get("q", "").strip() or None
        return JsonResponse({"commesse": list_commesse(q)})
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        t = create_commessa(data)
        return JsonResponse({"ok": True, "data": serialize_testata(t)}, status=201)
    except IntegrityError:
        return JsonResponse({"error": "Una commessa con questo Job esiste già."}, status=409)
    except ValidationError as exc:
        return JsonResponse({"error": exc.message_dict}, status=422)


@api_login_required
@api_write_required
@require_http_methods(["GET", "PUT", "DELETE"])
def commessa_api_detail(request, job):
    if request.method == "GET":
        try:
            t = get_commessa(job)
            return JsonResponse({"data": serialize_testata(t)})
        except Testata.DoesNotExist:
            logger.warning('Commessa "%s" non trovata nel database locale.', job)
            return JsonResponse({"error": "Commessa non trovata."}, status=404)
    if request.method == "PUT":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON non valido."}, status=400)
        try:
            t = update_commessa(job, data)
            return JsonResponse({"ok": True, "data": serialize_testata(t)})
        except Testata.DoesNotExist:
            return JsonResponse({"error": "Commessa non trovata."}, status=404)
        except ValidationError as exc:
            return JsonResponse({"error": exc.message_dict}, status=422)
    try:
        delete_commessa(job)
        return JsonResponse({"ok": True})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def commessa_close_api(request, job):
    try:
        t = close_commessa(job)
        return JsonResponse({"ok": True, "data": serialize_testata(t)})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)


@api_login_required
@require_http_methods(["GET"])
def erp_api(request):
    job = request.GET.get("job", "").strip()
    if not job:
        return JsonResponse({"error": "Parametro job mancante."}, status=400)
    try:
        data = fetch_from_bc(job)
        if data:
            logger.info('ERP: commessa "%s" trovata — campi restituiti: %s', job, list(data.keys()))
        else:
            logger.warning(
                'ERP: commessa "%s" non trovata in Business Central (risposta vuota).', job
            )
        return JsonResponse({"data": data})
    except Exception as exc:
        logger.error('ERP: errore durante il recupero della commessa "%s": %s', job, exc)
        return JsonResponse({"data": {}, "warning": str(exc)})


# ── API: Indirizzi di Spedizione ─────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def indirizzi_api(request, job):
    if request.method == "GET":
        try:
            return JsonResponse({"indirizzi": list_indirizzi(job)})
        except Testata.DoesNotExist:
            return JsonResponse({"error": "Commessa non trovata."}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        i = create_indirizzo(job, data)
        return JsonResponse({"ok": True, "data": serialize_indirizzo(i)}, status=201)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@api_write_required
@require_http_methods(["PATCH", "DELETE"])
def indirizzo_api_detail(request, pk):
    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON non valido."}, status=400)
        try:
            i = update_indirizzo(pk, data)
            return JsonResponse({"ok": True, "data": serialize_indirizzo(i)})
        except IndirSped.DoesNotExist:
            return JsonResponse({"error": "Indirizzo non trovato."}, status=404)
        except ValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    try:
        delete_indirizzo(pk)
        return JsonResponse({"ok": True})
    except IndirSped.DoesNotExist:
        return JsonResponse({"error": "Indirizzo non trovato."}, status=404)


# ── API: Documenti ───────────────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def documenti_api(request, job):
    if request.method == "GET":
        try:
            payload = {"documenti": list_documenti(job)}
            if request.GET.get("include_revisioni"):
                payload["revisioni_by_doc"] = revisioni_by_doc_for_job(job)
            return JsonResponse(payload)
        except Testata.DoesNotExist:
            return JsonResponse({"error": "Commessa non trovata."}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        d = create_documento(job, data)
        return JsonResponse({"ok": True, "data": serialize_documento(d)}, status=201)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@require_http_methods(["GET"])
def situazione_api(request, job):
    try:
        return JsonResponse(list_situazione(job))
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)


@api_login_required
@api_write_required
@require_http_methods(["GET", "PATCH", "DELETE"])
def documento_api_detail(request, pk):
    if request.method == "GET":
        try:
            d = Documento.objects.get(pk=pk)
            return JsonResponse(serialize_documento(d))
        except Documento.DoesNotExist:
            return JsonResponse({"error": "Documento non trovato."}, status=404)
    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON non valido."}, status=400)
        try:
            d = update_documento(pk, data)
            return JsonResponse({"ok": True, "data": serialize_documento(d)})
        except Documento.DoesNotExist:
            return JsonResponse({"error": "Documento non trovato."}, status=404)
        except ValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    try:
        delete_documento(pk)
        return JsonResponse({"ok": True})
    except Documento.DoesNotExist:
        return JsonResponse({"error": "Documento non trovato."}, status=404)


# ── API: Reparti ────────────────────────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def reparti_api(request):
    reparti = list_reparti()
    return JsonResponse({"reparti": [{"nome": r} for r in reparti]})


# ── API: Stati Interni / Esterni ─────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def stati_interni_api(request):
    return JsonResponse({"stati": list_stati_interni()})


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def stati_esterni_api(request):
    if request.method == "GET":
        return JsonResponse({"stati": list_stati_esterni()})
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        s = create_stato_esterno(data)
        return JsonResponse(
            {
                "ok": True,
                "data": {
                    "id": s.pk,
                    "nome": s.nome,
                    "colore": s.colore,
                    "crea_nuova_rev": s.crea_nuova_rev,
                },
            },
            status=201,
        )
    except IntegrityError:
        return JsonResponse({"error": "Esiste già uno stato esterno con questo nome."}, status=409)
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@api_write_required
@require_http_methods(["PATCH", "DELETE"])
def stato_esterno_api_detail(request, pk):
    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON non valido."}, status=400)
        try:
            s = update_stato_esterno(pk, data)
            return JsonResponse(
                {
                    "ok": True,
                    "data": {
                        "id": s.pk,
                        "nome": s.nome,
                        "colore": s.colore,
                        "crea_nuova_rev": s.crea_nuova_rev,
                    },
                }
            )
        except StatoEsterno.DoesNotExist:
            return JsonResponse({"error": "Stato esterno non trovato."}, status=404)
        except IntegrityError:
            return JsonResponse(
                {"error": "Esiste già uno stato esterno con questo nome."}, status=409
            )
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    try:
        delete_stato_esterno(pk)
        return JsonResponse({"ok": True})
    except StatoEsterno.DoesNotExist:
        return JsonResponse({"error": "Stato esterno non trovato."}, status=404)


# ── API: Emissione ───────────────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def emissione_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    doc_ids = data.get("doc_ids", [])
    dis_act_date = data.get("dis_act_date", "")
    if not doc_ids or not dis_act_date:
        return JsonResponse({"error": "Specificare doc_ids e dis_act_date."}, status=400)
    try:
        updated = esegui_emissione(doc_ids, dis_act_date)
        return JsonResponse({"ok": True, "updated": updated})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


# ── API: Stabilimenti ────────────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def stabilimenti_api(request):
    items = list(Stabilimento.objects.values("id", "nome"))
    return JsonResponse({"stabilimenti": items})


# ── API: Trasmittal PDF ─────────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def trasmittal_pdf_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)

    doc_ids = data.get("doc_ids", [])
    addr_ids = data.get("addr_ids", [])
    date_str = data.get("date", "")
    job = data.get("job", "")
    our_ref = data.get("our_ref", "")
    city = data.get("city", "")
    delivery_mode = data.get("delivery_mode", "attached")
    brevi_manu_name = data.get("brevi_manu_name", "")
    doc_id_mode = data.get("doc_id_mode", "both")
    if doc_id_mode not in ("vendor", "client", "both"):
        doc_id_mode = "both"

    if not doc_ids or not job:
        return JsonResponse({"error": "Specificare job e doc_ids."}, status=400)

    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    # Build testata dict
    testata_dict = {
        "job": testata.job,
        "po_no": testata.po_no or "",
        "job_detail": testata.job_detail or "",
        "client": testata.client or "",
        "time_cli_doc_rev": testata.time_cli_doc_rev,
    }

    # Build addresses list
    addresses = []
    if addr_ids:
        for addr in IndirSped.objects.filter(pk__in=addr_ids, testata=testata):
            addresses.append(
                {
                    "consignee": addr.consignee,
                    "address": addr.address,
                    "zip_code": addr.zip_code,
                    "city": addr.city,
                    "country": addr.country,
                    "attn": addr.attn,
                    "ph_no": addr.ph_no,
                }
            )

    # Build documents list with latest revision info
    documents = []
    for doc in Documento.objects.filter(pk__in=doc_ids, testata=testata).order_by("item_no"):
        rev = doc.revisioni.order_by("-rev_no").first()
        documents.append(
            {
                "item_no": doc.item_no or "",
                "vendor_doc": doc.vendor_doc or "",
                "client_doc_no": doc.client_doc_no or "",
                "doc_title": doc.doc_title or "",
                "rev_no": rev.rev_no if rev else "",
            }
        )

    if not date_str:
        from datetime import date as date_type

        date_str = date_type.today().isoformat()

    try:
        pdf_bytes = genera_trasmittal_pdf(
            testata_dict,
            addresses,
            documents,
            date_str,
            our_ref=our_ref,
            city=city,
            delivery_mode=delivery_mode,
            brevi_manu_name=brevi_manu_name,
            doc_id_mode=doc_id_mode,
        )
    except Exception as exc:
        return JsonResponse({"error": f"Errore generazione PDF: {exc}"}, status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    safe_job = job.replace('"', "")
    response["Content-Disposition"] = f'inline; filename="trasmittal_{safe_job}_{date_str}.pdf"'
    return response


# ── API: Ricezione ───────────────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def ricezione_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    entries = data.get("entries", [])
    crea_nuova_revisione = bool(data.get("crea_nuova_revisione", False))
    if not entries:
        return JsonResponse({"error": "Specificare almeno un documento."}, status=400)
    try:
        result = esegui_ricezione(entries, crea_nuova_revisione)
        return JsonResponse({"ok": True, "result": result})
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)


# ── API: Revisioni ───────────────────────────────────────────────────────────


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def revisioni_api(request, doc_pk):
    if request.method == "GET":
        try:
            return JsonResponse({"revisioni": list_revisioni(doc_pk)})
        except Documento.DoesNotExist:
            return JsonResponse({"error": "Documento non trovato."}, status=404)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        r = create_revisione(doc_pk, data)
        return JsonResponse({"ok": True, "data": serialize_revisione(r)}, status=201)
    except Documento.DoesNotExist:
        return JsonResponse({"error": "Documento non trovato."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@api_write_required
@require_http_methods(["PATCH", "DELETE"])
def revisione_api_detail(request, pk):
    if request.method == "PATCH":
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "JSON non valido."}, status=400)
        try:
            r = update_revisione(pk, data)
            return JsonResponse({"ok": True, "data": serialize_revisione(r)})
        except Revisione.DoesNotExist:
            return JsonResponse({"error": "Revisione non trovata."}, status=404)
        except ValidationError as exc:
            return JsonResponse({"error": str(exc)}, status=400)
    try:
        delete_revisione(pk)
        return JsonResponse({"ok": True})
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)


# ── Export: Document list as Excel ───────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def export_documenti(request, job):
    try:
        documenti = list_documenti(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Document List"

    headers = [
        "Item",
        "B&R Doc",
        "Client Doc N°",
        "Client Doc Class",
        "Titolo",
        "Reparto",
        "Penale",
        "Pagamento",
        "Note",
    ]
    header_fill = PatternFill(start_color="1C1C1A", end_color="1C1C1A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=10)

    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for row_idx, d in enumerate(documenti, start=2):
        ws.cell(row=row_idx, column=1, value=d["item_no"])
        ws.cell(row=row_idx, column=2, value=d["vendor_doc"])
        ws.cell(row=row_idx, column=3, value=d["client_doc_no"])
        ws.cell(row=row_idx, column=4, value=d["client_doc_class"])
        ws.cell(row=row_idx, column=5, value=d["doc_title"])
        ws.cell(row=row_idx, column=6, value=d["reparto_label"])
        ws.cell(row=row_idx, column=7, value="Sì" if d["doc_penalty"] else "")
        ws.cell(row=row_idx, column=8, value="Sì" if d["doc_payment"] else "")
        ws.cell(row=row_idx, column=9, value=d["remarks"])

    # Auto-fit column widths
    for col_idx, _ in enumerate(headers, start=1):
        max_len = max(
            (
                len(str(ws.cell(row=r, column=col_idx).value or ""))
                for r in range(1, ws.max_row + 1)
            ),
            default=8,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

    from io import BytesIO

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"{job}_document_list.xlsx"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Export: Situazione documenti ─────────────────────────────────────────────


def _hsl_hex(h_deg: float, s_pct: float, l_pct: float) -> str:
    """Convert a CSS HSL color to a 6-char RRGGBB hex string for openpyxl.

    Args:
        h_deg: Hue in degrees (0–360).
        s_pct: Saturation as a percentage (0–100).
        l_pct: Lightness as a percentage (0–100).

    Returns:
        Upper-case 6-character hex string, e.g. ``"C8E1F9"``.
    """
    r, g, b = colorsys.hls_to_rgb(h_deg / 360, l_pct / 100, s_pct / 100)
    return f"{int(r * 255):02X}{int(g * 255):02X}{int(b * 255):02X}"


# Light-mode badge palette from situazione_detail.html, mapped to (bg_hex, fg_hex).
# Used to apply matching colors in the Excel export.
_INT_STATUS_COLORS: dict[str, tuple[str, str]] = {
    "da_iniziare": (_hsl_hex(220, 14, 90), _hsl_hex(220, 10, 40)),
    "in_lavorazione": (_hsl_hex(210, 80, 88), _hsl_hex(210, 80, 30)),
    "in_revisione": (_hsl_hex(42, 80, 88), _hsl_hex(42, 60, 30)),
    "in_approvazione": (_hsl_hex(30, 80, 88), _hsl_hex(30, 60, 30)),
    "da_emettere": (_hsl_hex(270, 60, 88), _hsl_hex(270, 50, 35)),
    "inviato_al_cliente": (_hsl_hex(46, 92, 88), _hsl_hex(46, 70, 30)),
    "ricevuto": (_hsl_hex(145, 55, 88), _hsl_hex(145, 45, 28)),
}


@login_required
@require_http_methods(["GET"])
def export_situazione(request, job):
    """Export the situazione documenti as an Excel file.

    Supports two layouts via the ``vista`` query parameter:

    - ``verticale`` (default): one row per document × revision, with all
      status columns.
    - ``orizzontale``: one row per document, with date columns grouped by
      revision index.

    Args:
        request: The HTTP request. Optional ``?vista=orizzontale`` param.
        job: The commessa job identifier.

    Returns:
        HttpResponse: An xlsx attachment, or a 404 JSON response if the
        commessa does not exist.
    """
    try:
        documenti = list_documenti(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    vista = request.GET.get("vista", "verticale")

    revs_by_doc = revisioni_by_doc_for_job(job)

    def fmt(d):
        """Format an ISO date string as DD/MM/YYYY, or return empty string."""
        if not d:
            return ""
        try:
            y, m, day = str(d).split("-")
            return f"{day}/{m}/{y}"
        except ValueError:
            return str(d)

    header_fill = PatternFill(start_color="1C1C1A", end_color="1C1C1A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=10)
    header_align = Alignment(horizontal="center", vertical="center")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Situazione"

    if vista == "orizzontale":
        max_revs = max((len(revs_by_doc.get(d["id"], [])) for d in documenti), default=1)
        fixed_labels = [
            "Item",
            "B&R Doc",
            "Client Doc No",
            "Client Doc Class",
            "Descrizione",
            "Reparto",
        ]
        sub_labels = ["Inv. prev.", "Inv. eff.", "Ric. prev.", "Ric. eff."]
        n_fixed = len(fixed_labels)
        total_cols = n_fixed + max_revs * 4

        # ── Row 1: fixed column headers (merged over rows 1–2) + "Rev. X" group headers ──
        for col_idx, label in enumerate(fixed_labels, start=1):
            cell = ws.cell(row=1, column=col_idx, value=label)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            ws.merge_cells(start_row=1, start_column=col_idx, end_row=2, end_column=col_idx)

        for i in range(max_revs):
            rev_start = n_fixed + 1 + i * 4
            cell = ws.cell(row=1, column=rev_start, value=f"Rev. {i}")
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align
            ws.merge_cells(start_row=1, start_column=rev_start, end_row=1, end_column=rev_start + 3)

        # ── Row 2: sub-labels under each revision group ──
        sub_font = Font(bold=True, color="FFFFFF", size=9)
        for i in range(max_revs):
            for j, sub in enumerate(sub_labels):
                cell = ws.cell(row=2, column=n_fixed + 1 + i * 4 + j, value=sub)
                cell.font = sub_font
                cell.fill = header_fill
                cell.alignment = header_align

        # ── Data rows (start at row 3) ──
        for row_idx, d in enumerate(documenti, start=3):
            revs = revs_by_doc.get(d["id"], [])
            for col_idx, val in enumerate(
                [
                    d["item_no"],
                    d["vendor_doc"],
                    d["client_doc_no"],
                    d["client_doc_class"],
                    d["doc_title"],
                    d["reparto_acronimo"] or d["reparto_label"],
                ],
                start=1,
            ):
                ws.cell(row=row_idx, column=col_idx, value=val)
            for i in range(max_revs):
                r = revs[i] if i < len(revs) else None
                for j, val in enumerate(
                    [
                        fmt(r["dis_plan_date"]) if r else "",
                        fmt(r["dis_act_date"]) if r else "",
                        fmt(r["rec_plan_date"]) if r else "",
                        fmt(r["rec_act_date"]) if r else "",
                    ]
                ):
                    ws.cell(row=row_idx, column=n_fixed + 1 + i * 4 + j, value=val)

    else:  # verticale (default)
        headers = [
            "Item",
            "B&R Doc",
            "Client Doc No",
            "Client Doc Class",
            "Titolo",
            "Reparto",
            "Penale",
            "Pagamento",
            "Rev.",
            "Inv. previsto",
            "Inv. effettivo",
            "Ric. previsto",
            "Ric. effettivo",
            "Stato interno",
            "Risposta cliente",
        ]
        for col_idx, h in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        row_idx = 2
        for d in documenti:
            revs = revs_by_doc.get(d["id"], [])
            if not revs:
                # One row with no revision data
                ws.cell(row=row_idx, column=1, value=d["item_no"])
                ws.cell(row=row_idx, column=2, value=d["vendor_doc"])
                ws.cell(row=row_idx, column=3, value=d["client_doc_no"])
                ws.cell(row=row_idx, column=4, value=d["client_doc_class"])
                ws.cell(row=row_idx, column=5, value=d["doc_title"])
                ws.cell(row=row_idx, column=6, value=d["reparto_acronimo"] or d["reparto_label"])
                ws.cell(row=row_idx, column=7, value="Sì" if d["doc_penalty"] else "No")
                ws.cell(row=row_idx, column=8, value="Sì" if d["doc_payment"] else "No")
                row_idx += 1
                continue
            for r in revs:
                rev_label = (
                    (r["rev_let"] or "")
                    if r["rev_let"]
                    else str(r["rev_no"] if r["rev_no"] is not None else "")
                )
                int_label = r["int_status_label"] or ""
                ws.cell(row=row_idx, column=1, value=d["item_no"])
                ws.cell(row=row_idx, column=2, value=d["vendor_doc"])
                ws.cell(row=row_idx, column=3, value=d["client_doc_no"])
                ws.cell(row=row_idx, column=4, value=d["client_doc_class"])
                ws.cell(row=row_idx, column=5, value=d["doc_title"])
                ws.cell(row=row_idx, column=6, value=d["reparto_acronimo"] or d["reparto_label"])
                ws.cell(row=row_idx, column=7, value="Sì" if d["doc_penalty"] else "No")
                ws.cell(row=row_idx, column=8, value="Sì" if d["doc_payment"] else "No")
                ws.cell(row=row_idx, column=9, value=rev_label)
                ws.cell(row=row_idx, column=10, value=fmt(r["dis_plan_date"]))
                ws.cell(row=row_idx, column=11, value=fmt(r["dis_act_date"]))
                ws.cell(row=row_idx, column=12, value=fmt(r["rec_plan_date"]))
                ws.cell(row=row_idx, column=13, value=fmt(r["rec_act_date"]))
                # Stato interno — colored badge
                int_cell = ws.cell(row=row_idx, column=14, value=int_label)
                int_colors = _INT_STATUS_COLORS.get(r["int_status"] or "")
                if int_colors:
                    int_cell.fill = PatternFill(
                        start_color=int_colors[0], end_color=int_colors[0], fill_type="solid"
                    )
                    int_cell.font = Font(color=int_colors[1], size=9, bold=True)
                    int_cell.alignment = Alignment(horizontal="center", vertical="center")
                # Risposta cliente — colored using the stored hex from the DB
                ext_label = r["ext_status_label"] or ""
                ext_cell = ws.cell(row=row_idx, column=15, value=ext_label)
                if ext_label:
                    raw_color = (r.get("ext_status_colore") or "").lstrip("#")
                    if len(raw_color) == 6:
                        ext_cell.fill = PatternFill(
                            start_color=raw_color, end_color=raw_color, fill_type="solid"
                        )
                        ext_cell.font = Font(color="FFFFFF", size=9, bold=True)
                        ext_cell.alignment = Alignment(horizontal="center", vertical="center")
                row_idx += 1

        total_cols = 15

    # Auto-fit column widths (scan all rows; merged-range non-origin cells have None value)
    for col_idx in range(1, total_cols + 1):
        max_len = max(
            (
                len(str(ws.cell(row=r, column=col_idx).value or ""))
                for r in range(1, ws.max_row + 1)
            ),
            default=8,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(max_len + 4, 50)

    from io import BytesIO

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    safe_job = job.replace(" ", "_")
    filename = f"situazione_{safe_job}.xlsx"
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Import: Document list from Excel ─────────────────────────────────────────

# Column aliases accepted in the uploaded file (case-insensitive, stripped)
_IMPORT_COL_MAP = {
    "item": "item_no",
    "item no": "item_no",
    "item_no": "item_no",
    "vendor doc": "vendor_doc",
    "vendor_doc": "vendor_doc",
    "b&r doc": "vendor_doc",
    "client doc n°": "client_doc_no",
    "client doc no": "client_doc_no",
    "client doc n": "client_doc_no",
    "client_doc_no": "client_doc_no",
    "client doc class": "client_doc_class",
    "client_doc_class": "client_doc_class",
    "titolo": "doc_title",
    "titolo documento": "doc_title",
    "doc title": "doc_title",
    "doc_title": "doc_title",
    "reparto": "reparto_name",
    "penale": "doc_penalty",
    "doc penalty": "doc_penalty",
    "doc_penalty": "doc_penalty",
    "pagamento": "doc_payment",
    "doc payment": "doc_payment",
    "doc_payment": "doc_payment",
    "rev generale": "rev_gen",
    "rev. generale": "rev_gen",
    "rev_gen": "rev_gen",
    "note": "remarks",
    "remarks": "remarks",
}

_BOOL_TRUE = {"sì", "si", "yes", "1", "true", "x", "vero"}


def _parse_bool(val):
    return str(val).strip().lower() in _BOOL_TRUE


@api_login_required
@require_http_methods(["GET"])
def cartelle_modelli_api(request):
    cartelle = list_cartelle_modelli()
    return JsonResponse({"data": [serialize_cartella_modello(c) for c in cartelle]})


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def genera_documenti_da_modelli_api(request, job):
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "JSON non valido."}, status=400)
    cartella_id = body.get("cartella_id")
    if not cartella_id:
        return JsonResponse({"error": "Cartella modelli non specificata."}, status=400)
    try:
        creati, saltati = genera_documenti_da_modelli(job, cartella_id)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=404)
    return JsonResponse(
        {
            "ok": True,
            "created": len(creati),
            "skipped": saltati,
            "documenti": [serialize_documento(d) for d in creati],
        }
    )


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def import_documenti_excel(request, job):
    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"error": "Nessun file caricato."}, status=400)

    try:
        wb = openpyxl.load_workbook(f, data_only=True)
    except Exception:
        return JsonResponse({"error": "File Excel non valido o corrotto."}, status=400)

    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return JsonResponse({"error": "Il file è vuoto."}, status=400)

    # Map header row → field names
    header_row = [str(c).strip().lower() if c is not None else "" for c in rows[0]]
    col_map = {}  # col_index → field name
    for idx, h in enumerate(header_row):
        field = _IMPORT_COL_MAP.get(h)
        if field:
            col_map[idx] = field

    if not col_map:
        return JsonResponse(
            {"error": "Nessuna colonna riconosciuta. Verifica le intestazioni."}, status=400
        )

    # Build valid reparti set from User.reparto
    valid_reparti = set(r.lower() for r in list_reparti())

    created = []
    errors = []
    for row_num, row in enumerate(rows[1:], start=2):
        if all(c is None or str(c).strip() == "" for c in row):
            continue  # skip blank rows
        data = {}
        for col_idx, field in col_map.items():
            val = row[col_idx] if col_idx < len(row) else None
            data[field] = val

        reparto_str = ""
        if "reparto_name" in data:
            name = str(data.pop("reparto_name") or "").strip()
            if name:
                if name.lower() in valid_reparti:
                    reparto_str = name
                else:
                    errors.append(f'Riga {row_num}: reparto "{name}" non trovato, ignorato.')

        try:
            doc = Documento.objects.create(
                testata=testata,
                item_no=str(data.get("item_no") or "").strip(),
                vendor_doc=str(data.get("vendor_doc") or "").strip(),
                client_doc_no=str(data.get("client_doc_no") or "").strip(),
                client_doc_class=str(data.get("client_doc_class") or "").strip(),
                doc_title=str(data.get("doc_title") or "").strip(),
                doc_penalty=_parse_bool(data.get("doc_penalty", "")),
                doc_payment=_parse_bool(data.get("doc_payment", "")),
                rev_gen=_parse_bool(data.get("rev_gen", "")),
                reparto=reparto_str,
                remarks=str(data.get("remarks") or "").strip(),
            )
            Revisione.objects.create(documento=doc, rev_no=0)
            created.append(doc.pk)
        except Exception as exc:
            errors.append(f"Riga {row_num}: {exc}")

    return JsonResponse({"created": len(created), "errors": errors})


# ── API: File revisione ───────────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def revisione_file_api(request, pk):
    """Resolve the filesystem file path for a revision.

    Tries automatic resolution first (base path / RICEVUTI), then falls back
    to the stored manual link.

    Returns:
        JSON with ``status`` (``found`` | ``multiple`` | ``manual_linked`` |
        ``not_found``) and ``files`` list.
    """
    try:
        result = risolvi_file_revisione(pk)
        return JsonResponse(result)
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)
    except Exception as e:
        logger.error("Errore risoluzione file revisione %s: %s", pk, e)
        return JsonResponse({"error": str(e)}, status=500)


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def revisione_file_link_api(request, pk):
    """Save a manual file link for a revision.

    Request body: ``{"percorso": "Z:\\\\JOBS\\\\..."}``

    Returns:
        JSON with the saved ``percorso``.
    """
    try:
        data = json.loads(request.body)
        percorso = (data.get("percorso") or "").strip()
        if not percorso:
            return JsonResponse({"error": "Percorso mancante."}, status=400)
        link = salva_file_link(pk, percorso)
        return JsonResponse({"percorso": link.percorso})
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except Exception as e:
        logger.error("Errore salvataggio link file revisione %s: %s", pk, e)
        return JsonResponse({"error": str(e)}, status=500)


@api_login_required
@require_http_methods(["GET"])
def fileserver_browse_api(request):
    """List the contents of a directory on the fileserver.

    Query parameter ``path`` (optional): absolute path to list. Defaults to
    the JOBS root. Restricted to paths within the JOBS root for security.

    Returns:
        JSON with ``percorso_corrente``, ``percorso_padre`` (or ``null`` at
        root), and ``entries`` list.
    """
    from .services.fileserver import lista_directory

    path = request.GET.get("path", "").strip() or None
    try:
        result = lista_directory(path)
        dirs = [e for e in result["entries"] if e["tipo"] == "cartella"]
        files = [e for e in result["entries"] if e["tipo"] == "file"]
        return JsonResponse(
            {
                "percorso": result["percorso_corrente"],
                "parent": result["percorso_padre"],
                "dirs": [{"nome": d["nome"], "percorso": d["percorso"]} for d in dirs],
                "files": [
                    {"nome": f["nome"], "percorso": f["percorso"], "estensione": f["estensione"]}
                    for f in files
                ],
            }
        )
    except PermissionError as e:
        return JsonResponse({"error": str(e)}, status=403)
    except FileNotFoundError as e:
        return JsonResponse({"error": str(e)}, status=404)
    except Exception as e:
        logger.error("Errore browse fileserver path=%s: %s", path, e)
        return JsonResponse({"error": str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def revisione_file_serve(request, pk):
    """Serve a revision file directly from the fileserver.

    Accepts an optional ``percorso`` query parameter to select a specific file
    (needed when multiple candidates exist). If omitted the file is resolved
    automatically via ``risolvi_file_revisione``.

    All file types are served as attachments, triggering a download prompt
    so the OS opens the file with the default application.

    Args:
        pk: Primary key of the ``Revisione`` to serve.

    Returns:
        FileResponse with the file content.

    Raises:
        Http404: If the revision does not exist, no file is resolved, or the
            resolved path does not point to an existing file.
        HttpResponseForbidden: If the requested path is outside the JOBS root.
    """
    from pathlib import Path

    from .services.fileserver import get_jobs_root

    _CONTENT_TYPES = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls": "application/vnd.ms-excel",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
    }

    # Determine which file path to serve
    percorso_param = request.GET.get("percorso", "").strip()
    if percorso_param:
        file_path = Path(percorso_param)
        # Security: must stay within the JOBS root
        try:
            file_path.resolve().relative_to(get_jobs_root().resolve())
        except ValueError:
            return HttpResponseForbidden("Percorso non autorizzato.")
    else:
        try:
            result = risolvi_file_revisione(pk)
        except Revisione.DoesNotExist:
            raise Http404
        if result["status"] not in ("found", "manual_linked") or not result["files"]:
            raise Http404
        file_path = Path(result["files"][0]["percorso"])

    if not file_path.is_file():
        raise Http404

    ext = file_path.suffix.lower().lstrip(".")
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

    return FileResponse(
        open(file_path, "rb"),
        content_type=content_type,
        as_attachment=False,
        filename=file_path.name,
    )


# ── HTML: Profilo utente ─────────────────────────────────────────────────────


@login_required
def profilo_view(request):
    user = request.user
    errors = {}
    success = None

    if request.method == "POST":
        action = request.POST.get("action", "update_profile")

        if action == "change_password":
            old_pw = request.POST.get("old_password", "")
            new_pw1 = request.POST.get("new_password1", "")
            new_pw2 = request.POST.get("new_password2", "")
            if not user.check_password(old_pw):
                errors["password"] = "La password attuale non è corretta."
            elif not new_pw1:
                errors["password"] = "Inserisci la nuova password."
            elif new_pw1 != new_pw2:
                errors["password"] = "Le nuove password non coincidono."
            elif len(new_pw1) < 8:
                errors["password"] = "La password deve essere di almeno 8 caratteri."
            else:
                user.set_password(new_pw1)
                user.save()
                update_session_auth_hash(request, user)
                success = "password"
        else:
            first_name = request.POST.get("first_name", "").strip()
            last_name = request.POST.get("last_name", "").strip()
            email = request.POST.get("email", "").strip()
            ruolo = request.POST.get("ruolo", "").strip()
            reparto = request.POST.get("reparto", "").strip()

            if not email:
                errors["email"] = "L'email è obbligatoria."
            elif User.objects.filter(email=email).exclude(pk=user.pk).exists():
                errors["email"] = "Email già utilizzata da un altro account."

            if not errors:
                user.first_name = first_name
                user.last_name = last_name
                user.email = email
                user.ruolo = ruolo
                user.reparto = reparto

                avatar_file = request.FILES.get("avatar")
                if avatar_file:
                    if user.avatar:
                        user.avatar.delete(save=False)
                    user.avatar = avatar_file

                user.save()
                return redirect("home")

    reparti = list_reparti()
    return render(
        request,
        "core/profilo.html",
        {
            "errors": errors,
            "success": success,
            "reparti": reparti,
        },
    )


# ── HTML: Import from old Access database ────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def import_from_old_view(request):
    return render(request, "core/import_from_old.html")


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def import_from_old_api(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)

    job = (data.get("job") or "").strip()
    if not job:
        return JsonResponse({"error": "Specificare il numero di commessa."}, status=400)

    try:
        result = importa_commessa_da_access(job)
        return JsonResponse({"ok": True, **result})
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except Exception as exc:
        logger.exception("Errore importazione da Access, job=%s", job)
        return JsonResponse({"error": f"Errore durante l'importazione: {exc}"}, status=500)
