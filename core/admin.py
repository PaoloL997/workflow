from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from .models import (
    User, Reparto, Testata, IndirSped, Documento, StatoEsterno, Revisione,
    Ticket, TicketNota, Notifica,
)


@admin.register(Reparto)
class RepartoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'acronimo')
    search_fields = ('nome', 'acronimo')


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Profilo', {'fields': ('ruolo', 'reparto')}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Profilo', {'fields': ('email', 'ruolo', 'reparto')}),
    )
    list_display = ('username', 'email', 'ruolo', 'reparto', 'is_active', 'is_staff')
    list_filter = ('is_active', 'is_staff', 'reparto')
    search_fields = ('username', 'email', 'ruolo')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        choices = [('', '— Nessun reparto —')] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by('nome')
        ]
        if 'reparto' in form.base_fields:
            form.base_fields['reparto'].widget = forms.Select(choices=choices)
            form.base_fields['reparto'].required = False
        return form


class IndirSpedInline(admin.TabularInline):
    model = IndirSped
    extra = 0


@admin.register(Testata)
class TestataAdmin(admin.ModelAdmin):
    list_display = ('job', 'client', 'po_no', 'job_detail', 'delivery_date')
    search_fields = ('job', 'client', 'po_no', 'job_detail')
    list_filter = ('rev_let_flag',)
    inlines = [IndirSpedInline]


@admin.register(IndirSped)
class IndirSpedAdmin(admin.ModelAdmin):
    list_display = ('testata', 'consignee', 'city', 'country', 'attn')
    search_fields = ('testata__job', 'consignee', 'city', 'country')
    list_filter = ('country',)


class RevisioneInline(admin.TabularInline):
    model = Revisione
    extra = 0


@admin.register(Documento)
class DocumentoAdmin(admin.ModelAdmin):
    list_display = ('testata', 'item_no', 'doc_title', 'client_doc_no', 'reparto', 'doc_penalty', 'doc_payment')
    search_fields = ('testata__job', 'doc_title', 'client_doc_no', 'vendor_doc')
    list_filter = ('reparto', 'doc_penalty', 'doc_payment', 'rev_gen')
    inlines = [RevisioneInline]


@admin.register(StatoEsterno)
class StatoEsternoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'colore')
    search_fields = ('nome',)


@admin.register(Revisione)
class RevisioneAdmin(admin.ModelAdmin):
    list_display = ('documento', 'rev_no', 'rev_let', 'dis_plan_date', 'dis_act_date', 'int_status', 'ext_status')
    search_fields = ('documento__doc_title', 'documento__testata__job')
    list_filter = ('int_status', 'ext_status')


class TicketNotaInline(admin.TabularInline):
    model = TicketNota
    extra = 0
    readonly_fields = ('created_at',)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'reparto', 'esecutore', 'revisore', 'approvatore', 'created_at')
    list_filter = ('reparto',)
    search_fields = ('reparto', 'esecutore__username', 'revisore__username', 'approvatore__username')
    inlines = [TicketNotaInline]


@admin.register(TicketNota)
class TicketNotaAdmin(admin.ModelAdmin):
    list_display = ('id', 'ticket', 'autore', 'created_at')
    search_fields = ('testo', 'autore__username')
    list_filter = ('ticket',)


@admin.register(Notifica)
class NotificaAdmin(admin.ModelAdmin):
    list_display = ('id', 'destinatario', 'testo', 'letta', 'ticket', 'created_at')
    list_filter = ('letta',)
    search_fields = ('testo', 'destinatario__username')


