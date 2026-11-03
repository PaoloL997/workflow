"""Sito admin con le tabelle raggruppate per argomento invece che per app.

Django elenca le tabelle per app, e qui sono quasi tutte in ``core``: un
unico elenco alfabetico che cresce a ogni modello nuovo. ``GRUPPI_ADMIN``
le divide in sezioni, nell'ordine in cui vanno mostrate; ogni sezione ha
la sua pagina (``admin/gruppo/<slug>/``), come quella di un'app.

Una tabella registrata ma assente da ``GRUPPI_ADMIN`` finisce in
``GRUPPO_ALTRO``, così non sparisce; un test fallisce finché non le si
assegna un gruppo.
"""

from django.contrib import admin
from django.http import Http404
from django.template.response import TemplateResponse
from django.urls import path, reverse

# (slug, nome, tabelle come "app_label.NomeModello"), nell'ordine di pagina.
GRUPPI_ADMIN = (
    (
        "commesse",
        "Commesse e documenti",
        (
            "core.Testata",
            "core.PersonaCommessa",
            "core.Documento",
            "core.Revisione",
            "core.RevisioneFileLink",
            "core.Transmittal",
        ),
    ),
    (
        "trasmittal-interno",
        "Trasmittal interno",
        (
            # Configurazione prima, storico delle lettere dopo.
            "core.IndirizzoStabilimento",
            "core.FirmatarioStabilimento",
            "core.TransmittalInterno",
            "core.PresaVisioneTransmittalInterno",
        ),
    ),
    (
        "anagrafiche",
        "Anagrafiche",
        (
            "core.Stabilimento",
            "core.Reparto",
            "core.StatoEsterno",
            "core.CartellaModelloDocumento",
            "core.ModelloDocumento",
        ),
    ),
    (
        "utenti",
        "Utenti e accessi",
        ("core.User", "auth.Group", "core.ApiToken"),
    ),
    (
        "segnalazioni",
        "Segnalazioni e notifiche",
        ("core.Segnalazione", "core.Notifica"),
    ),
    (
        "sistema",
        "Sistema",
        ("core.EsecuzioneSchedulata", "core.AggiornamentoBC"),
    ),
)

GRUPPO_ALTRO = ("altro", "Altro")


class WorkflowAdminSite(admin.AdminSite):
    def get_urls(self):
        return [
            path(
                "gruppo/<slug:slug>/",
                self.admin_view(self.gruppo_index),
                name="gruppo_admin",
            ),
            *super().get_urls(),
        ]

    def _gruppi(self, request):
        """Le tabelle visibili a chi chiede, divise per ``GRUPPI_ADMIN``.

        Parte da ``_build_app_dict``, quindi valgono i permessi di Django:
        una tabella che l'utente non può vedere non compare, e un gruppo
        rimasto vuoto non viene restituito.
        """
        tabelle = {
            modello["model"]._meta.label: modello
            for app in self._build_app_dict(request).values()
            for modello in app["models"]
        }
        gruppi = []
        for slug, nome, etichette in GRUPPI_ADMIN:
            modelli = [tabelle.pop(etichetta) for etichetta in etichette if etichetta in tabelle]
            gruppi.append((slug, nome, modelli))
        altri = sorted(tabelle.values(), key=lambda modello: modello["name"])
        gruppi.append((*GRUPPO_ALTRO, altri))

        return [
            {
                "name": nome,
                "app_label": slug,
                "app_url": reverse(
                    f"{self.name}:gruppo_admin", kwargs={"slug": slug}, current_app=self.name
                ),
                "has_module_perms": True,
                "models": modelli,
            }
            for slug, nome, modelli in gruppi
            if modelli
        ]

    def get_app_list(self, request, app_label=None):
        # La pagina di una singola app (es. /admin/core/) resta quella di Django.
        if app_label is not None:
            return super().get_app_list(request, app_label)
        return self._gruppi(request)

    def gruppo_index(self, request, slug, extra_context=None):
        """Pagina di un gruppo: come quella di un'app, con le sole tabelle del gruppo."""
        gruppo = [voce for voce in self._gruppi(request) if voce["app_label"] == slug]
        if not gruppo:
            raise Http404("La pagina richiesta non esiste.")

        context = {
            **self.each_context(request),
            "title": gruppo[0]["name"],
            "subtitle": None,
            "app_list": gruppo,
            "app_label": slug,
            **(extra_context or {}),
        }
        request.current_app = self.name
        return TemplateResponse(request, "admin/app_index.html", context)
