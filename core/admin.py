from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms
from .models import User, Reparto, StatoEsterno, ModelloDocumento


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


@admin.register(StatoEsterno)
class StatoEsternoAdmin(admin.ModelAdmin):
    list_display = ('id', 'nome', 'colore')
    search_fields = ('nome',)


@admin.register(ModelloDocumento)
class ModelloDocumentoAdmin(admin.ModelAdmin):
    list_display = ('doc_title', 'item_no', 'codice_fisso', 'reparto')
    search_fields = ('doc_title', 'item_no', 'codice_fisso', 'reparto')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        choices = [('', '— Nessun reparto —')] + [
            (r.nome, r.nome) for r in Reparto.objects.order_by('nome')
        ]
        if 'reparto' in form.base_fields:
            form.base_fields['reparto'].widget = forms.Select(choices=choices)
            form.base_fields['reparto'].required = False
        return form


