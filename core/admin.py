from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AggiornamentoBC,
    AttivitaQCP,
    CartellaModelloDocumento,
    Documento,
    EsecuzioneSchedulata,
    ModelloDocumento,
    Notifica,
    Permesso,
    QualityControlPlan,
    QualityControlPlanAgency,
    QualityControlPlanCode,
    QualityControlPlanItem,
    QualityControlPlanSignature,
    QualityControlPlanSpec,
    Reparto,
    Revisione,
    RevisioneFileLink,
    Segnalazione,
    SegnalazioneCommento,
    Stabilimento,
    StatoEsterno,
    Testata,
    Transmittal,
    User,
)
from .services.quality_control_plan import sincronizza_punti


@admin.register(Stabilimento)
class StabilimentoAdmin(admin.ModelAdmin):
    list_display = ("id", "nome")
    search_fields = ("nome",)


@admin.register(Reparto)
class RepartoAdmin(admin.ModelAdmin):
    list_display = ("id", "nome", "acronimo")
    search_fields = ("nome", "acronimo")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Profilo", {"fields": ("ruolo", "reparto", "stabilimento", "firma")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Profilo", {"fields": ("email", "ruolo", "reparto", "stabilimento")}),
        ("Permessi", {"fields": ("permesso",)}),
    )
    list_display = (
        "username",
        "email",
        "permesso",
        "ruolo",
        "reparto",
        "stabilimento",
        "is_active",
    )
    list_filter = ("permesso", "is_active", "reparto", "stabilimento")
    search_fields = ("username", "email", "ruolo")
    readonly_fields = ("is_staff",)

    def get_fieldsets(self, request, obj=None):
        fieldsets = []
        for title, options in super().get_fieldsets(request, obj):
            if title == "Permissions":
                fields = tuple(f for f in options["fields"] if f != "is_staff")
                if fields:
                    fieldsets.append((title, {**options, "fields": fields}))
            else:
                fieldsets.append((title, options))
        fieldsets.append(("Permessi app", {"fields": ("permesso", "is_staff")}))
        return tuple(fieldsets)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        choices = [("", "— Nessun reparto —")] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by("nome")
        ]
        if "reparto" in form.base_fields:
            form.base_fields["reparto"].widget = forms.Select(choices=choices)
            form.base_fields["reparto"].required = False
        if "permesso" in form.base_fields:
            form.base_fields["permesso"].initial = Permesso.READING
        return form


@admin.register(StatoEsterno)
class StatoEsternoAdmin(admin.ModelAdmin):
    list_display = ("id", "lettera", "nome", "colore", "crea_nuova_rev")
    search_fields = ("nome", "lettera")
    fields = ("nome", "lettera", "colore", "crea_nuova_rev")


class ModelloDocumentoInline(admin.TabularInline):
    model = ModelloDocumento
    extra = 1
    fields = ("doc_title", "item_no", "codice_fisso", "reparto")

    def get_formset(self, request, obj=None, **kwargs):
        formset = super().get_formset(request, obj, **kwargs)
        choices = [("", "— Nessun reparto —")] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by("nome")
        ]
        if "reparto" in formset.form.base_fields:
            formset.form.base_fields["reparto"].widget = forms.Select(choices=choices)
            formset.form.base_fields["reparto"].required = False
        return formset


@admin.register(CartellaModelloDocumento)
class CartellaModelloDocumentoAdmin(admin.ModelAdmin):
    list_display = ("nome", "modelli_count")
    search_fields = ("nome", "descrizione")
    inlines = [ModelloDocumentoInline]

    @admin.display(description="Modelli")
    def modelli_count(self, obj):
        return obj.modelli.count()


@admin.register(ModelloDocumento)
class ModelloDocumentoAdmin(admin.ModelAdmin):
    list_display = ("doc_title", "cartella", "item_no", "codice_fisso", "reparto")
    list_filter = ("cartella",)
    search_fields = ("doc_title", "item_no", "codice_fisso", "reparto", "cartella__nome")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        choices = [("", "— Nessun reparto —")] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by("nome")
        ]
        if "reparto" in form.base_fields:
            form.base_fields["reparto"].widget = forms.Select(choices=choices)
            form.base_fields["reparto"].required = False
        return form


@admin.register(RevisioneFileLink)
class RevisioneFileLinkAdmin(admin.ModelAdmin):
    list_display = ("id", "revisione", "percorso", "created_at", "updated_at")
    search_fields = ("percorso", "revisione__documento__vendor_doc")
    raw_id_fields = ("revisione",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(Transmittal)
class TransmittalAdmin(admin.ModelAdmin):
    list_display = ("id", "testata", "numero", "data_emissione")
    list_filter = ("data_emissione",)
    search_fields = ("testata__job",)
    raw_id_fields = ("testata",)
    filter_horizontal = ("revisioni",)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "revisioni":
            kwargs["queryset"] = Revisione.objects.select_related("documento__testata").order_by(
                "documento__testata_id", "documento__vendor_doc", "rev_no", "pk"
            )
            field = super().formfield_for_manytomany(db_field, request, **kwargs)

            def label(rev):
                etichetta = rev.etichetta()
                rev_label = f"Rev {etichetta}" if etichetta else "Rev"
                vendor = rev.documento.vendor_doc or f"doc {rev.documento_id}"
                return f"#{rev.pk} — {vendor} {rev_label}"

            field.label_from_instance = label
            return field
        return super().formfield_for_manytomany(db_field, request, **kwargs)


@admin.register(Testata)
class TestataAdmin(admin.ModelAdmin):
    list_display = (
        "job",
        "client",
        "po_no",
        "delivery_date",
        "actual_delivery_date",
        "time_cli_doc_rev",
        "time_ven_doc_rev",
    )
    search_fields = ("job", "client", "po_no")
    list_filter = ("delivery_date",)


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "testata",
        "vendor_doc",
        "client_doc_no",
        "contractor_doc_no",
        "doc_title",
        "reparto",
    )
    search_fields = (
        "vendor_doc",
        "client_doc_no",
        "contractor_doc_no",
        "doc_title",
        "testata__job",
    )
    list_filter = ("reparto",)
    raw_id_fields = ("testata",)


@admin.register(Revisione)
class RevisioneAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "documento",
        "rev_no",
        "etichetta",
        "int_status",
        "ext_status",
        "dis_plan_date",
        "dis_act_date",
        "rec_act_date",
    )
    search_fields = ("documento__vendor_doc", "documento__testata__job")
    list_filter = ("int_status",)
    raw_id_fields = ("documento",)
    list_select_related = ("documento__testata",)

    @admin.display(description="Rev. mostrata")
    def etichetta(self, obj):
        return obj.etichetta()


class SegnalazioneCommentoInline(admin.TabularInline):
    model = SegnalazioneCommento
    extra = 0
    readonly_fields = ("autore", "testo", "created_at")
    can_delete = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Segnalazione)
class SegnalazioneAdmin(admin.ModelAdmin):
    list_display = ("id", "titolo", "tipo", "stato", "autore", "created_at")
    list_filter = ("tipo", "stato")
    search_fields = (
        "titolo",
        "testo",
        "autore__username",
        "autore__first_name",
        "autore__last_name",
    )
    readonly_fields = ("autore", "created_at", "chiuso_da", "chiuso_il")
    raw_id_fields = ("autore", "chiuso_da")
    inlines = [SegnalazioneCommentoInline]


@admin.register(Notifica)
class NotificaAdmin(admin.ModelAdmin):
    list_display = ("id", "destinatario", "testo", "created_at", "letta_il")
    list_filter = ("letta_il",)
    search_fields = (
        "testo",
        "destinatario__username",
        "destinatario__first_name",
        "destinatario__last_name",
    )
    readonly_fields = ("destinatario", "segnalazione", "testo", "created_at", "letta_il")
    raw_id_fields = ("destinatario", "segnalazione")

    def has_add_permission(self, request):
        return False


@admin.register(EsecuzioneSchedulata)
class EsecuzioneSchedulataAdmin(admin.ModelAdmin):
    list_display = ("nome", "ultima_esecuzione", "esito")
    readonly_fields = ("nome", "ultima_esecuzione", "esito")

    def has_add_permission(self, request):
        return False


@admin.register(AggiornamentoBC)
class AggiornamentoBCAdmin(admin.ModelAdmin):
    list_display = ("id", "testata", "campo", "valore_precedente", "valore_nuovo", "created_at")
    list_filter = ("campo",)
    search_fields = ("testata__job", "valore_precedente", "valore_nuovo")
    readonly_fields = ("testata", "campo", "valore_precedente", "valore_nuovo", "created_at")
    raw_id_fields = ("testata",)

    def has_add_permission(self, request):
        return False


class QualityControlPlanItemInline(admin.TabularInline):
    model = QualityControlPlanItem
    extra = 0
    fields = ("item_no", "descrizione", "ordine")
    ordering = ("ordine", "id")


class _QualityControlPlanListaInline(admin.TabularInline):
    extra = 0
    ordering = ("ordine", "id")


class QualityControlPlanCodeInline(_QualityControlPlanListaInline):
    model = QualityControlPlanCode
    fields = ("codice", "ordine")


class QualityControlPlanSpecInline(_QualityControlPlanListaInline):
    model = QualityControlPlanSpec
    fields = ("spec", "ordine")


class QualityControlPlanAgencyInline(_QualityControlPlanListaInline):
    model = QualityControlPlanAgency
    fields = ("nome", "ordine")


@admin.register(QualityControlPlan)
class QualityControlPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "testata", "doc_no", "project", "owner", "data", "prepared_by")
    search_fields = ("testata__job", "doc_no", "project", "owner", "purchaser")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("testata", "prepared_by_user")
    inlines = (
        QualityControlPlanItemInline,
        QualityControlPlanCodeInline,
        QualityControlPlanSpecInline,
        QualityControlPlanAgencyInline,
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # Gli enti si modificano qui, negli inline: gli step già inseriti devono
        # avere un punto per ogni ente, e nessuno per gli enti tolti.
        sincronizza_punti(form.instance)


@admin.register(QualityControlPlanSignature)
class QualityControlPlanSignatureAdmin(admin.ModelAdmin):
    """Le firme si consultano soltanto: sono append-only.

    Si registrano e si annullano dalla pagina del piano, con autore, data e
    motivo; qui non si aggiungono, non si cambiano e non si cancellano.
    """

    list_display = ("id", "punto", "utente", "esito", "firmato_il", "annullata_il")
    list_filter = ("esito",)
    search_fields = ("utente__username", "utente__last_name", "note", "motivo_annullo")
    list_select_related = ("punto", "utente")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttivitaQCP)
class AttivitaQCPAdmin(admin.ModelAdmin):
    """Il catalogo si mantiene da qui, senza deploy.

    Un'attività non si cancella mai: si disattiva. La cancellazione è tolta del
    tutto (anche come azione di massa), così un piano che la usa non perde il
    riferimento.
    """

    list_display = ("codice", "capitolo", "divisione", "tipo", "attivo")
    list_filter = ("capitolo", "divisione", "tipo", "attivo")
    search_fields = ("codice", "descrizione")
    ordering = ("ordine", "id")
    actions = ("attiva", "disattiva")

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Attiva le attività selezionate")
    def attiva(self, request, queryset):
        queryset.update(attivo=True)

    @admin.action(description="Disattiva le attività selezionate")
    def disattiva(self, request, queryset):
        queryset.update(attivo=False)
