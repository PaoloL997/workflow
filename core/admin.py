from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    CartellaModelloDocumento,
    Documento,
    ModelloDocumento,
    Reparto,
    Revisione,
    RevisioneFileLink,
    Stabilimento,
    StatoEsterno,
    Testata,
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
    fieldsets = UserAdmin.fieldsets + (("Profilo", {"fields": ("ruolo", "reparto")}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Profilo", {"fields": ("email", "ruolo", "reparto")}),
    )
    list_display = ("username", "email", "ruolo", "reparto", "is_active", "is_staff")
    list_filter = ("is_active", "is_staff", "reparto")
    search_fields = ("username", "email", "ruolo")

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        choices = [("", "— Nessun reparto —")] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by("nome")
        ]
        if "reparto" in form.base_fields:
            form.base_fields["reparto"].widget = forms.Select(choices=choices)
            form.base_fields["reparto"].required = False
        return form


@admin.register(StatoEsterno)
class StatoEsternoAdmin(admin.ModelAdmin):
    list_display = ("id", "nome", "colore", "crea_nuova_rev")
    search_fields = ("nome",)


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


@admin.register(Testata)
class TestataAdmin(admin.ModelAdmin):
    list_display = (
        "job",
        "client",
        "po_no",
        "delivery_date",
        "time_cli_doc_rev",
        "time_ven_doc_rev",
    )
    search_fields = ("job", "client", "po_no")
    list_filter = ("delivery_date",)


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ("id", "testata", "vendor_doc", "client_doc_no", "doc_title", "reparto")
    search_fields = ("vendor_doc", "client_doc_no", "doc_title", "testata__job")
    list_filter = ("reparto",)
    raw_id_fields = ("testata",)


@admin.register(Revisione)
class RevisioneAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "documento",
        "rev_no",
        "int_status",
        "dis_plan_date",
        "dis_act_date",
        "rec_act_date",
    )
    search_fields = ("documento__vendor_doc", "documento__testata__job")
    list_filter = ("int_status",)
    raw_id_fields = ("documento",)
