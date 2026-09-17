from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AggiornamentoBC,
    CartellaModelloDocumento,
    DestinatarioTransmittalInterno,
    DestinazioneDocumento,
    Documento,
    EsecuzioneSchedulata,
    FirmatarioStabilimento,
    IndirizzoStabilimento,
    ModelloDocumento,
    Notifica,
    Permesso,
    PersonaCommessa,
    Reparto,
    Revisione,
    RevisioneFileLink,
    RigaTransmittalInterno,
    Segnalazione,
    SegnalazioneCommento,
    Stabilimento,
    StatoEsterno,
    Testata,
    Transmittal,
    TransmittalInterno,
    User,
)


class IndirizzoStabilimentoInline(admin.TabularInline):
    model = IndirizzoStabilimento
    extra = 0
    fields = ("email", "tipo", "attivo")


@admin.register(Stabilimento)
class StabilimentoAdmin(admin.ModelAdmin):
    list_display = ("id", "nome", "sigla", "codice_bc")
    search_fields = ("nome", "sigla")
    inlines = [IndirizzoStabilimentoInline]


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


class PersonaCommessaInline(admin.TabularInline):
    model = PersonaCommessa
    extra = 0
    fields = ("ruolo", "utente", "nome_libero")
    raw_id_fields = ("utente",)


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
        "sito_costruttivo",
    )
    search_fields = ("job", "client", "po_no")
    list_filter = ("delivery_date", "sito_costruttivo")
    inlines = [PersonaCommessaInline]


@admin.register(PersonaCommessa)
class PersonaCommessaAdmin(admin.ModelAdmin):
    list_display = ("id", "testata", "ruolo", "utente", "nome_libero")
    # "Utente" vuoto = cognome del foglio non abbinato: da controllare a mano.
    list_filter = ("ruolo", ("utente", admin.EmptyFieldListFilter))
    search_fields = (
        "testata__job",
        "nome_libero",
        "utente__username",
        "utente__first_name",
        "utente__last_name",
    )
    raw_id_fields = ("testata", "utente")


class DestinazioneDocumentoInline(admin.TabularInline):
    model = DestinazioneDocumento
    extra = 0
    fields = ("stabilimento",)


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
    inlines = [DestinazioneDocumentoInline]


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


@admin.register(FirmatarioStabilimento)
class FirmatarioStabilimentoAdmin(admin.ModelAdmin):
    list_display = ("id", "stabilimento", "ruolo", "utente")
    list_filter = ("ruolo", "stabilimento")
    search_fields = ("utente__username", "utente__first_name", "utente__last_name")
    raw_id_fields = ("utente",)


class _SolaLetturaInline:
    """Un inline che si consulta soltanto: niente aggiunte, modifiche o cancellazioni."""

    extra = 0

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RigaTransmittalInternoInline(_SolaLetturaInline, admin.TabularInline):
    model = RigaTransmittalInterno
    fields = (
        "posizione",
        "documento",
        "revisione",
        "copie",
        "tpi",
        "tpi_destinatario",
        "cliente",
        "siti",
        "note",
    )
    filter_horizontal = ("siti",)


class DestinatarioTransmittalInternoInline(_SolaLetturaInline, admin.TabularInline):
    model = DestinatarioTransmittalInterno
    fields = ("email", "tipo", "origine")


@admin.register(TransmittalInterno)
class TransmittalInternoAdmin(admin.ModelAdmin):
    """Sola lettura: l'archivio si scrive da ``crea_trasmittal_interno``, non da qui."""

    list_display = ("nome", "testata", "data", "progressivo", "creato_da", "creato_il")
    list_filter = ("data",)
    search_fields = ("nome", "testata__job")
    readonly_fields = ("testata", "data", "progressivo", "nome", "creato_da", "creato_il", "note")
    inlines = [RigaTransmittalInternoInline, DestinatarioTransmittalInternoInline]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
