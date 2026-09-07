from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AggiornamentoBC,
    CartellaModelloDocumento,
    Documento,
    EsecuzioneSchedulata,
    ModelloDocumento,
    Notifica,
    Permesso,
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
        ("Profilo", {"fields": ("ruolo", "reparto", "stabilimento")}),
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
            kwargs["queryset"] = Revisione.objects.select_related("documento").order_by(
                "documento__testata_id", "documento__vendor_doc", "rev_no", "pk"
            )
            field = super().formfield_for_manytomany(db_field, request, **kwargs)

            def label(rev):
                rev_label = f"Rev {rev.rev_no}" if rev.rev_no is not None else "Rev"
                if rev.rev_let:
                    rev_label += rev.rev_let
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
        "int_status",
        "ext_status",
        "dis_plan_date",
        "dis_act_date",
        "rec_act_date",
    )
    search_fields = ("documento__vendor_doc", "documento__testata__job")
    list_filter = ("int_status",)
    raw_id_fields = ("documento",)


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
