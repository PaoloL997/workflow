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
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from src.pdf import genera_planned_docs_pdf, genera_situazione_documenti_pdf, genera_trasmittal_pdf

from .models import (
    Documento,
    IndirSped,
    Permesso,
    Revisione,
    Segnalazione,
    Stabilimento,
    StatoEsterno,
    Testata,
    User,
)
from .permissions import api_write_required
from .services.bc_sync import list_aggiornamenti as list_aggiornamenti_bc
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
    esegui_ricezione,
    fetch_from_bc,
    genera_documenti_da_modelli,
    get_commessa,
    list_cartelle_modelli,
    list_commesse,
    list_documenti,
    list_home_commesse,
    list_indirizzi,
    list_reparti,
    list_revisioni,
    list_situazione,
    list_stati_esterni,
    list_stati_interni,
    pin_commessa,
    request_delete_commessa,
    revisioni_by_doc_for_job,
    risolvi_file_revisione,
    salva_file_link,
    serialize_cartella_modello,
    serialize_documento,
    serialize_indirizzo,
    serialize_revisione,
    serialize_testata,
    unpin_commessa,
    update_commessa,
    update_documento,
    update_indirizzo,
    update_revisione,
    update_stato_esterno,
)
from .services.export_grezzo import build_workbook as build_dati_grezzi_workbook
from .services.export_grezzo import list_tabelle as list_tabelle_grezze
from .services.import_old import importa_commessa_da_access
from .services.notifiche import count_notifiche, list_notifiche, segna_lette
from .services.quality_control_plan import TITOLO as QCP_TITOLO
from .services.quality_control_plan import VENDOR as QCP_VENDOR
from .services.quality_control_plan import (
    create_piano,
    dati_precompilati,
    list_piani,
    serialize_piano,
)
from .services.quality_control_plan import (
    nome_utente as qcp_nome_utente,
)
from .services.revisione_anomalie import (
    audit_commessa,
    audit_commessa_summary,
    classifica_revisione,
    ignora_anomalie_revisione,
    serialize_anomalie_gruppi,
)
from .services.revisione_label import format_revisione_label
from .services.revisione_sblocco import list_revisioni_sbloccabili, sblocca_revisione
from .services.segnalazioni import (
    SegnalazioneClosed,
    SegnalazioneForbidden,
    chiudi_segnalazione,
    create_commento,
    create_segnalazione,
    list_segnalazioni,
    riapri_segnalazione,
    set_voto,
)
from .services.stato_interno import DA_INVIARE_LABEL, stato_interno_label

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
            except IntegrityError:
                error = "Impossibile completare la registrazione. Riprova tra qualche minuto."
            except ValidationError:
                logger.exception("Errore di convalida durante la registrazione di %s", username)
                error = "Errore di convalida durante la registrazione. Riprova."
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
    anomalie_count = audit_commessa_summary(job)["count"]
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
            "anomalie_count": anomalie_count,
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
    return render(
        request,
        "core/archivio_detail.html",
        {
            "testata": testata,
            "aggiornamenti_bc": list_aggiornamenti_bc(job, limit=10),
        },
    )


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
def quality_control_plan_view(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    # Titolo, Vendor, Job n., Data e Prepared by arrivano già col render: così il
    # modal si apre pieno anche mentre la lettura da Business Central è in corso.
    return render(
        request,
        "core/quality_control_plan.html",
        {
            "testata": testata,
            "qcp_titolo": QCP_TITOLO,
            "qcp_vendor": QCP_VENDOR,
            "oggi": _date.today().isoformat(),
            "prepared_by": qcp_nome_utente(request.user),
        },
    )


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
        if request.GET.get("home") in ("1", "true", "True"):
            return JsonResponse({"commesse": list_home_commesse(request.user)})
        q = request.GET.get("q", "").strip() or None
        return JsonResponse({"commesse": list_commesse(q, user=request.user)})
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
@require_http_methods(["POST", "DELETE"])
def commessa_pin_api(request, job):
    try:
        if request.method == "POST":
            data = pin_commessa(request.user, job)
        else:
            data = unpin_commessa(request.user, job)
        return JsonResponse({"ok": True, "data": data})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


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
        if request.user.is_app_admin:
            delete_commessa(job)
        else:
            request_delete_commessa(job, request.user)
        return JsonResponse({"ok": True})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=500)
    except Exception:
        logger.exception('Eliminazione/richiesta eliminazione fallita per commessa "%s".', job)
        return JsonResponse(
            {"error": "Impossibile completare l'operazione di eliminazione."},
            status=500,
        )


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


# ── API: Quality Control Plan ────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def quality_control_plan_prefill_api(request, job):
    """Valori proposti per un nuovo piano.

    Risponde sempre 200 se la commessa esiste: quando Business Central non è
    raggiungibile i suoi campi restano vuoti, il resto è comunque precompilato e
    ``warning`` spiega cosa manca. Un ERP giù non deve impedire di creare.
    """
    try:
        return JsonResponse(dati_precompilati(job, request.user))
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)


@api_login_required
@api_write_required
@require_http_methods(["GET", "POST"])
def quality_control_plan_api(request, job):
    if request.method == "GET":
        try:
            return JsonResponse({"quality_control_plans": list_piani(job)})
        except Testata.DoesNotExist:
            return JsonResponse({"error": "Commessa non trovata."}, status=404)
    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        piano = create_piano(job, data, request.user)
        return JsonResponse({"ok": True, "data": serialize_piano(piano)}, status=201)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValidationError as exc:
        return JsonResponse({"error": exc.message_dict}, status=400)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


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
                    "lettera": s.lettera,
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
                        "lettera": s.lettera,
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


def _normalize_doc_id_cols(data):
    doc_id_cols = data.get("doc_id_cols")
    if not isinstance(doc_id_cols, list):
        doc_id_mode = data.get("doc_id_mode", "all")
        if doc_id_mode == "both":
            doc_id_mode = "all"
        if doc_id_mode == "all":
            doc_id_cols = ["client", "vendor", "contractor"]
        elif doc_id_mode in ("vendor", "client", "contractor"):
            doc_id_cols = [doc_id_mode]
        else:
            doc_id_cols = ["client", "vendor", "contractor"]
    return [c for c in doc_id_cols if c in ("vendor", "client", "contractor")]


def _trasmittal_addresses(testata, addr_ids):
    addresses = []
    if not addr_ids:
        return addresses
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
    return addresses


def _trasmittal_documents(testata, doc_ids):
    documents = []
    for doc in Documento.objects.filter(pk__in=doc_ids, testata=testata).order_by("item_no"):
        rev = doc.revisioni.order_by("-rev_no").first()
        documents.append(
            {
                "item_no": doc.item_no or "",
                "vendor_doc": doc.vendor_doc or "",
                "client_doc_no": doc.client_doc_no or "",
                "contractor_doc_no": doc.contractor_doc_no or "",
                "doc_title": doc.doc_title or "",
                "rev_no": rev.rev_no if rev else "",
                # Lettera o numero secondo il flag di archivio (vedi revisione_label).
                "rev_label": format_revisione_label(
                    rev.rev_no if rev else None,
                    rev.rev_let if rev else "",
                    testata.rev_let_flag,
                )
                if rev
                else "",
                "dis_plan_date": rev.dis_plan_date.isoformat()
                if (rev and rev.dis_plan_date)
                else None,
            }
        )
    return documents


def _generate_trasmittal_pdf_bytes(request, testata, data, date_str, doc_ids):
    testata_dict = {
        "job": testata.job,
        "po_no": testata.po_no or "",
        "job_detail": testata.job_detail or "",
        "client": testata.client or "",
        "time_cli_doc_rev": testata.time_cli_doc_rev,
    }
    user = request.user
    signer_name = (getattr(user, "nome_completo", None) or user.get_full_name() or "").strip()
    if not signer_name:
        signer_name = (user.get_username() or "").strip()
    signer_role = (getattr(user, "ruolo", None) or "").strip()
    return genera_trasmittal_pdf(
        testata_dict,
        _trasmittal_addresses(testata, data.get("addr_ids") or []),
        _trasmittal_documents(testata, doc_ids),
        date_str,
        our_ref=data.get("our_ref") or "",
        city=data.get("city") or "",
        delivery_mode=data.get("delivery_mode") or "attached",
        brevi_manu_name=data.get("brevi_manu_name") or "",
        doc_id_cols=_normalize_doc_id_cols(data),
        signer_name=signer_name,
        signer_role=signer_role,
    )


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

    job = (data.get("job") or "").strip()
    if not job:
        job = (
            Documento.objects.filter(pk=doc_ids[0]).values_list("testata_id", flat=True).first()
            or ""
        )
    if not job:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    from .services.trasmittal_archivio import emetti_e_archivia

    try:
        pdf_bytes = _generate_trasmittal_pdf_bytes(request, testata, data, dis_act_date, doc_ids)
        result = emetti_e_archivia(job, doc_ids, dis_act_date, pdf_bytes)
        return JsonResponse({"ok": True, **result})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except OSError as exc:
        logger.error("Errore salvataggio PDF transmittal job=%s: %s", job, exc)
        return JsonResponse(
            {"error": f"Impossibile salvare il transmittal su disco: {exc}"}, status=500
        )
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
    date_str = data.get("date", "")
    job = data.get("job", "")

    if not doc_ids or not job:
        return JsonResponse({"error": "Specificare job e doc_ids."}, status=400)

    try:
        testata = Testata.objects.get(job=job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    if not date_str:
        from datetime import date as date_type

        date_str = date_type.today().isoformat()

    try:
        pdf_bytes = _generate_trasmittal_pdf_bytes(request, testata, data, date_str, doc_ids)
    except Exception as exc:
        return JsonResponse({"error": f"Errore generazione PDF: {exc}"}, status=500)

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    safe_job = job.replace('"', "")
    response["Content-Disposition"] = f'inline; filename="trasmittal_{safe_job}_{date_str}.pdf"'
    return response


# ── API: Storico transmittal ─────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def trasmittal_storico_api(request, job):
    """List issued transmittals for a job from the database table."""
    from .services.trasmittal_archivio import (
        cartella_trasmittal_canonica,
        formato_nome_file,
        lista_storico,
        sync_trasmittal_da_cartella,
        trasmittal_in_da_spedire,
    )

    try:
        get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    forza = request.GET.get("sync") in ("1", "true", "yes")
    try:
        sync_trasmittal_da_cartella(job, solo_se_vuota=not forza)
        items = lista_storico(job)
    except Exception as e:
        logger.error("Errore elenco transmittal job=%s: %s", job, e)
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse(
        {
            "items": items,
            "cartella": str(cartella_trasmittal_canonica(job)),
            "formato": formato_nome_file(job),
            "in_da_spedire": trasmittal_in_da_spedire(job),
        }
    )


@api_login_required
@require_http_methods(["GET"])
def trasmittal_prossimo_api(request, job):
    """Return the next transmittal number/code and destination path for a job."""
    from .services.trasmittal_archivio import percorso_previsto, prossimo_numero

    try:
        get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    try:
        numero = prossimo_numero(job)
    except Exception as e:
        logger.error("Errore prossimo transmittal job=%s: %s", job, e)
        return JsonResponse({"error": str(e)}, status=500)
    dest = percorso_previsto(job, numero)
    return JsonResponse({"numero": numero, "codice": f"{job}-{numero}", "percorso": str(dest)})


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def trasmittal_annulla_api(request, job, trasmittal_id):
    """Undo the latest app-issued transmittal for a job."""
    from .services.trasmittal_archivio import TrasmittalAnnullaError, annulla_trasmittal

    try:
        get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    try:
        annulla_trasmittal(job, trasmittal_id)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except FileNotFoundError:
        return JsonResponse({"error": "Transmittal non trovato."}, status=404)
    except TrasmittalAnnullaError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    except Exception as e:
        logger.error("Errore annulla transmittal job=%s id=%s: %s", job, trasmittal_id, e)
        return JsonResponse({"error": str(e)}, status=500)
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["GET"])
def trasmittal_file_serve(request, job, trasmittal_id):
    """Serve a transmittal PDF from the archive (same pipeline as revision files)."""
    from .services.trasmittal_archivio import percorso_trasmittal

    try:
        get_commessa(job)
    except Testata.DoesNotExist:
        raise Http404
    try:
        file_path = percorso_trasmittal(job, trasmittal_id)
    except PermissionError:
        return HttpResponseForbidden("Percorso non autorizzato.")
    except FileNotFoundError:
        raise Http404
    if not file_path.is_file():
        raise Http404
    return FileResponse(
        open(file_path, "rb"),
        content_type="application/pdf",
        as_attachment=False,
        filename=file_path.name,
    )


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
        "Contractor Doc N°",
        "Client Doc Class",
        "Title",
        "Department",
        "Penalty",
        "Payment",
        "Notes",
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
        ws.cell(row=row_idx, column=4, value=d["contractor_doc_no"])
        ws.cell(row=row_idx, column=5, value=d["client_doc_class"])
        ws.cell(row=row_idx, column=6, value=d["doc_title"])
        ws.cell(row=row_idx, column=7, value=d["reparto_label"])
        ws.cell(row=row_idx, column=8, value="Yes" if d["doc_penalty"] else "")
        ws.cell(row=row_idx, column=9, value="Yes" if d["doc_payment"] else "")
        ws.cell(row=row_idx, column=10, value=d["remarks"])

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


# ── Export: Emissione / Ricezione ────────────────────────────────────────────


_EMISSIONE_EXCLUDE_STATUSES = frozenset({"inviato_al_cliente", "ricevuto"})

_XLSX_THIN = Border(
    left=Side(style="thin", color="B9B9B9"),
    right=Side(style="thin", color="B9B9B9"),
    top=Side(style="thin", color="B9B9B9"),
    bottom=Side(style="thin", color="B9B9B9"),
)
_XLSX_HEADER_FONT = Font(bold=True, color="000000", size=10)
_XLSX_HEADER_FILL = PatternFill(start_color="F5F5F5", end_color="F5F5F5", fill_type="solid")
_XLSX_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
_XLSX_CELL_ALIGN = Alignment(horizontal="left", vertical="center")
_XLSX_CENTER_ALIGN = Alignment(horizontal="center", vertical="center")
_XLSX_WRAP_ALIGN = Alignment(horizontal="left", vertical="center", wrap_text=True)
_XLSX_OVERDUE_FONT = Font(bold=True, color="B40000", size=10)

# Content-driven width caps. Compact cols ignore long headers (headers wrap).
_XLSX_COMPACT_COLS = frozenset(
    {
        "Item",
        "Rev.",
        "Department",
        "Penalty",
        "Payment",
    }
)
_XLSX_DATE_COLS = frozenset(
    {
        "Planned date",
        "Planned return date",
        "Emission date",
        "Planned send",
        "Actual send",
        "Planned receipt",
        "Actual receipt",
        "Submission date",
        "Receipt date",
        "Dispatch",
        "Received",
    }
)


def _is_export_date_overdue(raw) -> bool:
    if not raw:
        return False
    day = str(raw).strip()[:10]
    if len(day) < 10:
        return False
    return day < _date.today().isoformat()


def _style_xlsx_header_row(ws, headers):
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = _XLSX_HEADER_FONT
        cell.fill = _XLSX_HEADER_FILL
        cell.alignment = _XLSX_HEADER_ALIGN
        cell.border = _XLSX_THIN


def _style_xlsx_header_cell(cell):
    cell.font = _XLSX_HEADER_FONT
    cell.fill = _XLSX_HEADER_FILL
    cell.alignment = _XLSX_HEADER_ALIGN
    cell.border = _XLSX_THIN


def _style_xlsx_data_cell(cell, *, overdue=False, center=False, wrap=False):
    cell.border = _XLSX_THIN
    if center:
        cell.alignment = _XLSX_CENTER_ALIGN
    elif wrap:
        cell.alignment = _XLSX_WRAP_ALIGN
    else:
        cell.alignment = _XLSX_CELL_ALIGN
    if overdue:
        cell.font = _XLSX_OVERDUE_FONT


def _xlsx_content_max_len(ws, col_idx: int, *, data_start_row: int = 2) -> int:
    if ws.max_row < data_start_row:
        return 0
    return max(
        (
            len(str(ws.cell(row=r, column=col_idx).value or ""))
            for r in range(data_start_row, ws.max_row + 1)
        ),
        default=0,
    )


def _xlsx_wrapped_line_count(text, col_width: float) -> int:
    """Rough number of wrapped lines for Excel row-height estimation."""
    chars_per_line = max(int(col_width * 0.95), 8)
    total = 0
    for part in str(text or "").splitlines() or [""]:
        total += max(1, (len(part) + chars_per_line - 1) // chars_per_line)
    return max(1, total)


def _autosize_xlsx_columns(ws, headers, *, data_start_row: int = 2):
    """Size columns from cell content (not padded by long headers)."""
    title_col = None
    title_width = 40.0

    for col_idx, header in enumerate(headers, start=1):
        content_len = _xlsx_content_max_len(ws, col_idx, data_start_row=data_start_row)
        letter = get_column_letter(col_idx)

        if header == "Title":
            # Prefer reading the full title: wide + wrap; raise row height below.
            width = float(max(36, min(content_len + 2, 90)))
            title_col = col_idx
            title_width = width
        elif header in _XLSX_COMPACT_COLS:
            # Acronyms / flags: fit content, keep narrow (header wraps).
            width = float(max(5, min(max(content_len + 1, 5), 10)))
        elif header in _XLSX_DATE_COLS:
            width = float(max(11, min(max(content_len + 1, 11), 14)))
        elif header in ("Internal status", "Client response"):
            width = float(max(12, min(max(content_len + 2, 12), 24)))
        elif header in ("B&R Doc", "Client Doc N°", "Contractor Doc N°", "Client Doc Class"):
            width = float(max(10, min(max(content_len + 2, 10), 28)))
        else:
            width = float(max(10, min(max(content_len + 2, len(header)), 32)))

        ws.column_dimensions[letter].width = width

    if title_col is None or ws.max_row < data_start_row:
        return

    # Expand row height so wrapped titles are not clipped vertically.
    for r in range(data_start_row, ws.max_row + 1):
        text = ws.cell(row=r, column=title_col).value
        lines = _xlsx_wrapped_line_count(text, title_width)
        if lines > 1:
            ws.row_dimensions[r].height = min(14.5 * lines, 75)


def _xlsx_response(wb, filename: str) -> HttpResponse:
    from io import BytesIO

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response["Pragma"] = "no-cache"
    return response


def _pdf_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response["Pragma"] = "no-cache"
    return response


def _export_format(request, default="xlsx"):
    fmt = (request.GET.get("format") or default).strip().lower()
    return fmt if fmt in ("xlsx", "pdf") else default


_EMISSIONE_PDF_COLUMNS = [
    ("Item", "item_no", False),
    ("B&R Doc", "vendor_doc", False),
    ("Rev.", "latest_rev_display", False),
    ("Client Doc N°", "client_doc_no", False),
    ("Contractor Doc N°", "contractor_doc_no", False),
    ("Client Doc Class", "client_doc_class", False),
    ("Title", "doc_title", False),
    ("Planned date", "latest_dis_plan_date", True),
]

_RICEZIONE_PDF_COLUMNS = [
    ("Item", "item_no", False),
    ("B&R Doc", "vendor_doc", False),
    ("Rev.", "latest_rev_display", False),
    ("Client Doc N°", "client_doc_no", False),
    ("Contractor Doc N°", "contractor_doc_no", False),
    ("Client Doc Class", "client_doc_class", False),
    ("Title", "doc_title", False),
    ("Emission date", "latest_dis_act_date", True),
    ("Planned return date", "latest_rec_plan_date", True),
]


def _sort_docs_by_date(docs, date_key):
    """Ascending by ISO date; empty dates last (matches UI defaultSort)."""

    def _key(d):
        raw = d.get(date_key)
        if not raw:
            return (1, "")
        return (0, str(raw)[:10])

    return sorted(docs, key=_key)


def _export_planned_docs_xlsx(
    job,
    docs,
    *,
    sheet_title,
    date_header,
    date_key,
    filename,
    include_rev=False,
    emission_date_header=None,
    emission_date_key="latest_dis_act_date",
):
    """Build an Excel export for emissione/ricezione document lists."""
    from .date_fmt import format_display_date

    docs = _sort_docs_by_date(docs, date_key)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_title

    headers = [
        "Item",
        "B&R Doc",
    ]
    if include_rev:
        headers.append("Rev.")
    headers.extend(
        [
            "Client Doc N°",
            "Contractor Doc N°",
            "Client Doc Class",
            "Title",
        ]
    )
    if emission_date_header:
        headers.append(emission_date_header)
    headers.append(date_header)

    _style_xlsx_header_row(ws, headers)
    ws.row_dimensions[1].height = 22

    for row_idx, d in enumerate(docs, start=2):
        col = 1
        cells_meta = []  # (value, overdue, center)

        cells_meta.append((d.get("item_no") or "", False, True))
        cells_meta.append((d.get("vendor_doc") or "", False, False))
        if include_rev:
            rev = d.get("latest_rev_display") or ""
            if rev == "\u2014":
                rev = ""
            cells_meta.append((rev, False, True))
        cells_meta.append((d.get("client_doc_no") or "", False, False))
        cells_meta.append((d.get("contractor_doc_no") or "", False, False))
        cells_meta.append((d.get("client_doc_class") or "", False, True))
        cells_meta.append((d.get("doc_title") or "", False, False))
        if emission_date_header:
            raw_em = d.get(emission_date_key)
            cells_meta.append((format_display_date(raw_em) if raw_em else "", False, True))
        raw_plan = d.get(date_key)
        plan_text = format_display_date(raw_plan) if raw_plan else ""
        cells_meta.append((plan_text, _is_export_date_overdue(raw_plan) and bool(plan_text), True))

        for value, overdue, center in cells_meta:
            cell = ws.cell(row=row_idx, column=col, value=value)
            wrap = headers[col - 1] == "Title"
            _style_xlsx_data_cell(cell, overdue=overdue, center=center, wrap=wrap)
            col += 1

    _autosize_xlsx_columns(ws, headers)

    safe_job = job.replace(" ", "_")
    # ``filename`` may be a ready name or a template with ``{job}``.
    out_name = filename.format(job=safe_job) if "{job}" in filename else filename
    return _xlsx_response(wb, out_name)


@api_login_required
@require_http_methods(["GET"])
def export_emissione(request, job):
    """Export documents eligible for emission as Excel or PDF."""
    try:
        testata = get_commessa(job)
        documenti = list_documenti(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    docs = [d for d in documenti if d.get("latest_int_status") not in _EMISSIONE_EXCLUDE_STATUSES]
    docs = _sort_docs_by_date(docs, "latest_dis_plan_date")
    fmt = _export_format(request, default="xlsx")
    safe_job = job.replace(" ", "_")
    today = _date.today()
    date_part = f"{today.day:02d}_{today.month:02d}_{today.year}"
    base_name = f"{safe_job}_to_be_issued_{date_part}"
    if fmt == "pdf":
        pdf_bytes = genera_planned_docs_pdf(
            serialize_testata(testata),
            docs,
            columns=_EMISSIONE_PDF_COLUMNS,
            include_status=False,
            omit_empty_columns=True,
        )
        return _pdf_response(pdf_bytes, f"{base_name}.pdf")
    return _export_planned_docs_xlsx(
        job,
        docs,
        sheet_title="Emissione",
        date_header="Planned date",
        date_key="latest_dis_plan_date",
        filename=f"{base_name}.xlsx",
        include_rev=True,
    )


@api_login_required
@require_http_methods(["GET"])
def export_ricezione(request, job):
    """Export documents awaiting reception as Excel or PDF."""
    try:
        testata = get_commessa(job)
        documenti = list_documenti(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    docs = [d for d in documenti if d.get("latest_int_status") == "inviato_al_cliente"]
    docs = _sort_docs_by_date(docs, "latest_rec_plan_date")
    fmt = _export_format(request, default="xlsx")
    safe_job = job.replace(" ", "_")
    today = _date.today()
    date_part = f"{today.day:02d}_{today.month:02d}_{today.year}"
    base_name = f"{safe_job}_to_be_received_{date_part}"
    if fmt == "pdf":
        pdf_bytes = genera_planned_docs_pdf(
            serialize_testata(testata),
            docs,
            columns=_RICEZIONE_PDF_COLUMNS,
            include_status=False,
            omit_empty_columns=True,
        )
        return _pdf_response(pdf_bytes, f"{base_name}.pdf")
    return _export_planned_docs_xlsx(
        job,
        docs,
        sheet_title="Ricezione",
        date_header="Planned return date",
        date_key="latest_rec_plan_date",
        filename=f"{base_name}.xlsx",
        include_rev=True,
        emission_date_header="Emission date",
        emission_date_key="latest_dis_act_date",
    )


# ── Export: Situazione documenti ─────────────────────────────────────────────


def _export_situazione_xlsx(job, payload, *, vista):
    """Flat Excel for situazione with Planning/Actual grouped date headers."""
    from .date_fmt import format_display_date

    docs = payload.get("documenti") or []
    rev_map = payload.get("revisioni_by_doc") or {}
    rev_let_flag = bool(payload.get("rev_let_flag"))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Situazione"

    # Leaf headers (row 2 for date groups) — used for sizing/rules.
    leaf_headers = [
        "Item",
        "B&R Doc",
        "Client Doc N°",
        "Contractor Doc N°",
        "Client Doc Class",
        "Title",
        "Department",
        "Penalty",
        "Payment",
        "Rev.",
        "Submission date",
        "Receipt date",
        "Dispatch",
        "Received",
        "Internal status",
        "Client response",
    ]
    plan_start, plan_end = 11, 12
    act_start, act_end = 13, 14

    # Row 1–2 headers: fixed cols span both rows; Planning/Actual group dates.
    for col_idx, label in enumerate(leaf_headers, start=1):
        if plan_start <= col_idx <= plan_end or act_start <= col_idx <= act_end:
            continue
        ws.merge_cells(start_row=1, start_column=col_idx, end_row=2, end_column=col_idx)
        cell = ws.cell(row=1, column=col_idx, value=label)
        _style_xlsx_header_cell(cell)
        _style_xlsx_header_cell(ws.cell(row=2, column=col_idx))

    ws.merge_cells(start_row=1, start_column=plan_start, end_row=1, end_column=plan_end)
    ws.merge_cells(start_row=1, start_column=act_start, end_row=1, end_column=act_end)
    plan_cell = ws.cell(row=1, column=plan_start, value="Planning")
    act_cell = ws.cell(row=1, column=act_start, value="Actual")
    _style_xlsx_header_cell(plan_cell)
    _style_xlsx_header_cell(act_cell)
    _style_xlsx_header_cell(ws.cell(row=1, column=plan_end))
    _style_xlsx_header_cell(ws.cell(row=1, column=act_end))

    for col_idx in range(plan_start, act_end + 1):
        cell = ws.cell(row=2, column=col_idx, value=leaf_headers[col_idx - 1])
        _style_xlsx_header_cell(cell)

    ws.row_dimensions[1].height = 20
    ws.row_dimensions[2].height = 20

    # Columns that use centered alignment (others left-aligned).
    _CENTER_COLS = {1, 5, 8, 9, 10, 11, 12, 13, 14}
    _TITLE_COL = leaf_headers.index("Title") + 1

    def _rev_label(rev):
        if not rev:
            return ""
        return format_revisione_label(rev.get("rev_no"), rev.get("rev_let"), rev_let_flag)

    def _int_status_label(rev):
        # Match UI getIntStatusMeta: effective status, empty → "Da inviare"
        if not rev:
            return DA_INVIARE_LABEL
        label = (rev.get("int_status_eff_label") or "").strip()
        if label:
            return label
        return stato_interno_label(rev.get("int_status"))

    row_idx = 3
    for d in docs:
        revs = rev_map.get(d["id"]) or rev_map.get(str(d["id"])) or []
        revs = sorted(revs, key=lambda r: (r.get("rev_no") is None, r.get("rev_no") or 0))
        if vista == "verticale" and revs:
            rows = revs
        elif revs:
            rows = [revs[-1]]
        else:
            rows = [None]
        for rev in rows:
            dis_plan = rev.get("dis_plan_date") if rev else None
            rec_plan = rev.get("rec_plan_date") if rev else None
            values = [
                d.get("item_no") or "",
                d.get("vendor_doc") or "",
                d.get("client_doc_no") or "",
                d.get("contractor_doc_no") or "",
                d.get("client_doc_class") or "",
                d.get("doc_title") or "",
                d.get("reparto_acronimo") or d.get("reparto_label") or "",
                "Yes" if d.get("doc_penalty") else "",
                "Yes" if d.get("doc_payment") else "",
                _rev_label(rev),
                format_display_date(dis_plan) if dis_plan else "",
                format_display_date(rec_plan) if rec_plan else "",
                format_display_date(rev.get("dis_act_date"))
                if rev and rev.get("dis_act_date")
                else "",
                format_display_date(rev.get("rec_act_date"))
                if rev and rev.get("rec_act_date")
                else "",
                _int_status_label(rev),
                (rev.get("ext_status_label") or "") if rev else "",
            ]
            for col_idx, value in enumerate(values, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                _style_xlsx_data_cell(
                    cell,
                    overdue=False,
                    center=col_idx in _CENTER_COLS,
                    wrap=col_idx == _TITLE_COL,
                )
            row_idx += 1

    _autosize_xlsx_columns(ws, leaf_headers, data_start_row=3)
    ws.freeze_panes = "A3"

    safe_job = job.replace(" ", "_")
    return _xlsx_response(wb, f"situazione_documenti_{vista}_{safe_job}.xlsx")


@login_required
@require_http_methods(["GET"])
def export_situazione(request, job):
    """Export situazione documenti as PDF (with header) or Excel (no header)."""
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)

    vista = request.GET.get("vista", "orizzontale")
    if vista not in ("orizzontale", "verticale"):
        vista = "orizzontale"

    payload = list_situazione(job)
    fmt = _export_format(request, default="pdf")
    if fmt == "xlsx":
        return _export_situazione_xlsx(job, payload, vista=vista)

    pdf_bytes = genera_situazione_documenti_pdf(
        serialize_testata(testata),
        documenti=payload.get("documenti") or [],
        revisioni_by_doc=payload.get("revisioni_by_doc") or {},
        rev_let_flag=bool(payload.get("rev_let_flag")),
        vista=vista,
    )
    today = _date.today()
    date_part = f"{today.day:02d}_{today.month:02d}_{today.year}"
    safe_job = job.replace(" ", "_")
    filename = f"{safe_job}_document_status_{date_part}.pdf"
    return _pdf_response(pdf_bytes, filename)


# ── Import: Document list from Excel ─────────────────────────────────────────

# Ordered column headers for the downloadable import template.
_DOCUMENTI_IMPORT_HEADERS = [
    "Item",
    "B&R Doc",
    "Client Doc N°",
    "Contractor Doc N°",
    "Client Doc Class",
    "Document title",
    "Department",
    "Penalty",
    "Payment",
    "General rev.",
    "Planned send date (Rev. 0)",
    "Notes",
]

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
    "contractor doc n°": "contractor_doc_no",
    "contractor doc no": "contractor_doc_no",
    "contractor doc n": "contractor_doc_no",
    "contractor_doc_no": "contractor_doc_no",
    "client doc class": "client_doc_class",
    "client_doc_class": "client_doc_class",
    "titolo": "doc_title",
    "titolo documento": "doc_title",
    "document title": "doc_title",
    "doc title": "doc_title",
    "doc_title": "doc_title",
    "reparto": "reparto_name",
    "department": "reparto_name",
    "penale": "doc_penalty",
    "penalty": "doc_penalty",
    "doc penalty": "doc_penalty",
    "doc_penalty": "doc_penalty",
    "pagamento": "doc_payment",
    "payment": "doc_payment",
    "doc payment": "doc_payment",
    "doc_payment": "doc_payment",
    "rev generale": "rev_gen",
    "rev. generale": "rev_gen",
    "general rev.": "rev_gen",
    "general rev": "rev_gen",
    "rev_gen": "rev_gen",
    "data invio prevista (rev. 0)": "dis_plan_date_rev0",
    "data invio prevista": "dis_plan_date_rev0",
    "data prima emissione": "dis_plan_date_rev0",
    "planned send date (rev. 0)": "dis_plan_date_rev0",
    "planned send date": "dis_plan_date_rev0",
    "dis_plan_date": "dis_plan_date_rev0",
    "dis_plan_date_rev0": "dis_plan_date_rev0",
    "note": "remarks",
    "notes": "remarks",
    "remarks": "remarks",
}

_BOOL_TRUE = {"sì", "si", "yes", "1", "true", "x", "vero"}


def _parse_bool(val):
    return str(val).strip().lower() in _BOOL_TRUE


def _parse_import_date(val):
    """Parse a date value from an Excel cell.

    Accepts openpyxl native date/datetime objects, ISO strings (YYYY-MM-DD),
    and Italian-format strings (DD/MM/YYYY). Returns a date or None.
    """
    import datetime as _dt

    if val is None or str(val).strip() == "":
        return None, None
    if isinstance(val, _dt.datetime):
        return val.date(), None
    if isinstance(val, _dt.date):
        return val, None
    s = str(val).strip()
    try:
        return _dt.date.fromisoformat(s), None
    except ValueError:
        pass
    # Fallback: DD/MM/YYYY
    try:
        return _dt.datetime.strptime(s, "%d/%m/%Y").date(), None
    except ValueError:
        pass
    return None, f'data non riconosciuta: "{s}" (usa formato YYYY-MM-DD o GG/MM/AAAA)'


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

        dis_plan = None
        if "dis_plan_date_rev0" in data:
            dis_plan, date_err = _parse_import_date(data.get("dis_plan_date_rev0"))
            if date_err:
                errors.append(f"Riga {row_num}: {date_err}, data ignorata.")

        try:
            doc = Documento.objects.create(
                testata=testata,
                item_no=str(data.get("item_no") or "").strip(),
                vendor_doc=str(data.get("vendor_doc") or "").strip(),
                client_doc_no=str(data.get("client_doc_no") or "").strip(),
                contractor_doc_no=str(data.get("contractor_doc_no") or "").strip(),
                client_doc_class=str(data.get("client_doc_class") or "").strip(),
                doc_title=str(data.get("doc_title") or "").strip(),
                doc_penalty=_parse_bool(data.get("doc_penalty", "")),
                doc_payment=_parse_bool(data.get("doc_payment", "")),
                rev_gen=_parse_bool(data.get("rev_gen", "")),
                reparto=reparto_str,
                remarks=str(data.get("remarks") or "").strip(),
            )
            rev0 = Revisione.objects.create(documento=doc, rev_no=0)
            if dis_plan is not None:
                rev0.dis_plan_date = dis_plan
                rev0.save(update_fields=["dis_plan_date"])
            created.append(doc.pk)
        except Exception as exc:
            errors.append(f"Riga {row_num}: {exc}")

    return JsonResponse({"created": len(created), "errors": errors})


# ── Template: Import document list ───────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def import_documenti_template(request):
    """Download a pre-formatted Excel template for document list import."""
    from io import BytesIO

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Template Lista Documenti"

    header_fill = PatternFill(start_color="1C1C1A", end_color="1C1C1A", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=10)

    for col_idx, h in enumerate(_DOCUMENTI_IMPORT_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Column widths: wider for free-text columns
    _col_widths = {
        1: 10,  # Item
        2: 22,  # B&R Doc
        3: 22,  # Client Doc N°
        4: 22,  # Contractor Doc N°
        5: 22,  # Client Doc Class
        6: 45,  # Document title
        7: 18,  # Department
        8: 10,  # Penalty
        9: 12,  # Payment
        10: 14,  # General rev.
        11: 28,  # Planned send date (Rev. 0)
        12: 35,  # Notes
    }
    for col_idx, width in _col_widths.items():
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Apply date format to the date column
    date_col_idx = _DOCUMENTI_IMPORT_HEADERS.index("Planned send date (Rev. 0)") + 1
    for row in range(2, 102):  # pre-format 100 data rows
        ws.cell(row=row, column=date_col_idx).number_format = "D MMM YYYY"

    # Department: dropdown with system departments at download time
    reparto_col_idx = _DOCUMENTI_IMPORT_HEADERS.index("Department") + 1
    reparto_col_letter = get_column_letter(reparto_col_idx)
    reparti = list_reparti()
    if reparti:
        ws_reparti = wb.create_sheet("_Reparti")
        for row_idx, nome in enumerate(reparti, start=1):
            ws_reparti.cell(row=row_idx, column=1, value=nome)
        ws_reparti.sheet_state = "hidden"
        last_reparto_row = len(reparti)
        dv = DataValidation(
            type="list",
            formula1=f"='_Reparti'!$A$1:$A${last_reparto_row}",
            allow_blank=True,
        )
        dv.error = "Select a department from the list."
        dv.errorTitle = "Invalid department"
        dv.prompt = "Choose a department present in the system."
        dv.promptTitle = "Department"
        ws.add_data_validation(dv)
        dv.add(f"{reparto_col_letter}2:{reparto_col_letter}101")

    # Freeze the header row
    ws.freeze_panes = "A2"

    # Row height for header
    ws.row_dimensions[1].height = 20

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    response = HttpResponse(
        buf.read(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = 'attachment; filename="template_lista_documenti.xlsx"'
    return response


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


# ── API: Anomalie revisioni ───────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def commessa_anomalie_api(request, job):
    try:
        testata = get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    anomalies = audit_commessa(job)
    gruppi = serialize_anomalie_gruppi(job, anomalies)
    return JsonResponse(
        {
            "count": len(gruppi),
            "anomalie_totali": len(anomalies),
            "gruppi": gruppi,
            "time_cli_doc_rev": testata.time_cli_doc_rev,
        }
    )


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def commessa_anomalie_risolvi_api(request, job):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)

    revisione_id = data.get("revisione_id")
    bucket = (data.get("bucket") or "").strip()
    if not revisione_id or not bucket:
        return JsonResponse({"error": "Specificare revisione_id e bucket."}, status=400)

    try:
        get_commessa(job)
        result = classifica_revisione(job, int(revisione_id), bucket, data)
        summary = audit_commessa_summary(job)
        return JsonResponse({"ok": True, **result, "anomalie_count": summary["count"]})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def commessa_anomalie_ignora_api(request, job):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)

    revisione_id = data.get("revisione_id")
    if not revisione_id:
        return JsonResponse({"error": "Specificare revisione_id."}, status=400)

    try:
        get_commessa(job)
        result = ignora_anomalie_revisione(job, int(revisione_id))
        return JsonResponse({"ok": True, **result})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


# ── API: Sblocco revisioni ───────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def commessa_revisioni_sbloccabili_api(request, job):
    try:
        get_commessa(job)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    revisioni = list_revisioni_sbloccabili(job)
    return JsonResponse({"count": len(revisioni), "revisioni": revisioni})


@api_login_required
@api_write_required
@require_http_methods(["POST"])
def commessa_revisione_sblocca_api(request, job):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"error": "JSON non valido."}, status=400)

    revisione_id = data.get("revisione_id")
    if not revisione_id:
        return JsonResponse({"error": "Specificare revisione_id."}, status=400)

    try:
        get_commessa(job)
        result = sblocca_revisione(job, int(revisione_id), data.get("dis_plan_date"))
        remaining = list_revisioni_sbloccabili(job)
        return JsonResponse({"ok": True, **result, "count": len(remaining)})
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except Revisione.DoesNotExist:
        return JsonResponse({"error": "Revisione non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


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


# ── HTML + API: Segnalazioni ─────────────────────────────────────────────────


def _json_body(request):
    try:
        return json.loads(request.body)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


@login_required
def segnalazioni_view(request):
    return render(request, "core/segnalazioni.html", {})


@api_login_required
@require_http_methods(["GET", "POST"])
def segnalazioni_api(request):
    if request.method == "GET":
        tipo = (request.GET.get("tipo") or "").strip() or None
        stato = (request.GET.get("stato") or "").strip() or None
        mine_raw = (request.GET.get("mine") or "").strip()
        top_raw = (request.GET.get("top") or "").strip() or None
        if mine_raw and mine_raw not in ("0", "1"):
            return JsonResponse({"error": "Parametro mine non valido."}, status=400)
        try:
            return JsonResponse(
                {
                    "segnalazioni": list_segnalazioni(
                        request.user,
                        tipo=tipo,
                        stato=stato,
                        mine=mine_raw == "1",
                        top=top_raw,
                    )
                }
            )
        except ValueError as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        item = create_segnalazione(
            request.user,
            data.get("tipo"),
            data.get("titolo"),
            data.get("testo"),
        )
        return JsonResponse({"ok": True, "data": item}, status=201)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@require_http_methods(["POST"])
def segnalazione_voto_api(request, pk):
    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        item = set_voto(request.user, pk, data.get("valore"))
        return JsonResponse({"ok": True, "data": item})
    except Segnalazione.DoesNotExist:
        return JsonResponse({"error": "Segnalazione non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@require_http_methods(["POST"])
def segnalazione_commenti_api(request, pk):
    data = _json_body(request)
    if data is None:
        return JsonResponse({"error": "JSON non valido."}, status=400)
    try:
        item = create_commento(request.user, pk, data.get("testo"))
        return JsonResponse({"ok": True, "data": item}, status=201)
    except Segnalazione.DoesNotExist:
        return JsonResponse({"error": "Segnalazione non trovata."}, status=404)
    except SegnalazioneClosed as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@api_login_required
@require_http_methods(["POST"])
def segnalazione_chiudi_api(request, pk):
    try:
        item = chiudi_segnalazione(request.user, pk)
        return JsonResponse({"ok": True, "data": item})
    except Segnalazione.DoesNotExist:
        return JsonResponse({"error": "Segnalazione non trovata."}, status=404)
    except SegnalazioneForbidden:
        return JsonResponse({"error": "Permesso negato."}, status=403)


@api_login_required
@require_http_methods(["POST"])
def segnalazione_riapri_api(request, pk):
    try:
        item = riapri_segnalazione(request.user, pk)
        return JsonResponse({"ok": True, "data": item})
    except Segnalazione.DoesNotExist:
        return JsonResponse({"error": "Segnalazione non trovata."}, status=404)
    except SegnalazioneForbidden:
        return JsonResponse({"error": "Permesso negato."}, status=403)


# ── API: Notifiche ───────────────────────────────────────────────────────────


@api_login_required
@require_http_methods(["GET"])
def notifiche_api(request):
    notifiche = list_notifiche(request.user)
    return JsonResponse({"notifiche": notifiche, "count": len(notifiche)})


@api_login_required
@require_http_methods(["POST"])
def notifiche_lette_api(request):
    data = {} if not request.body else _json_body(request)
    if not isinstance(data, dict):
        return JsonResponse({"error": "JSON non valido."}, status=400)
    ids = data.get("ids")
    if ids is not None and not isinstance(ids, list):
        return JsonResponse({"error": "Elenco notifiche non valido."}, status=400)
    try:
        lette = segna_lette(request.user, ids)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"ok": True, "lette": lette, "count": count_notifiche(request.user)})


# ── HTML + Export: Dati grezzi ───────────────────────────────────────────────


@login_required
def scarica_view(request):
    return render(request, "core/scarica.html", {"tabelle": list_tabelle_grezze()})


@api_login_required
@require_http_methods(["GET"])
def export_dati_grezzi(request, job):
    """Excel con un foglio per ciascuna tabella grezza richiesta della commessa."""
    keys = []
    for raw in request.GET.getlist("tabelle"):
        keys.extend(raw.split(","))
    try:
        wb = build_dati_grezzi_workbook(job, keys)
    except Testata.DoesNotExist:
        return JsonResponse({"error": "Commessa non trovata."}, status=404)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    today = _date.today()
    date_part = f"{today.day:02d}_{today.month:02d}_{today.year}"
    filename = f"{job.replace(' ', '_')}_dati_grezzi_{date_part}.xlsx"
    return _xlsx_response(wb, filename)
