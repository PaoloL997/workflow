"""Configurazione dell'app admin, al posto di ``django.contrib.admin`` in INSTALLED_APPS.

Sta in un modulo suo e non in ``core.apps``: con due ``AppConfig`` in quel
modulo Django non saprebbe più quale usare per l'app ``core``.
"""

from django.contrib.admin.apps import AdminConfig


class WorkflowAdminConfig(AdminConfig):
    """L'admin di Django con le tabelle raggruppate per argomento (vedi ``core.admin_site``)."""

    default_site = "core.admin_site.WorkflowAdminSite"
