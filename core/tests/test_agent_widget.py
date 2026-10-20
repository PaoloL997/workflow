from django.test import Client, TestCase

from ..models import Permesso
from ._fixtures import User

TOGGLE = "core/partials/agent_toggle.html"
PANEL = "core/partials/agent_panel.html"


class AgentWidgetTemplateTests(TestCase):
    """Pulsante e pannello dell'assistente: accanto al pulsante del tema, solo dopo il login."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            "agent_reader", "agent-reader@example.com", "pw", permesso=Permesso.READING
        )

    def _assert_widget(self, res):
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, TOGGLE)
        self.assertTemplateUsed(res, PANEL)
        self.assertContains(res, 'id="agent-toggle-btn"', count=1)
        self.assertContains(res, 'aria-label="Apri assistente"')
        self.assertContains(res, 'id="agent-panel"', count=1)
        self.assertContains(res, "core/agent_widget.css")

    def test_pagina_col_toggle_del_tema_ha_pulsante_e_pannello(self):
        self.client.force_login(self.user)
        res = self.client.get("/segnalazioni/")

        self.assertTemplateUsed(res, "core/partials/theme_toggle.html")
        self._assert_widget(res)

    def test_home_ha_pulsante_e_pannello(self):
        self.client.force_login(self.user)

        self._assert_widget(self.client.get("/"))

    def test_login_anonimo_non_ha_pulsante_ne_pannello(self):
        res = self.client.get("/login/")

        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "core/partials/theme_toggle.html")
        self.assertTemplateNotUsed(res, TOGGLE)
        self.assertTemplateNotUsed(res, PANEL)
        self.assertNotContains(res, 'id="agent-toggle-btn"')
        self.assertNotContains(res, 'id="agent-panel"')
        self.assertNotContains(res, "agent_widget.css")

    def test_reset_password_non_ha_il_pulsante_anche_dopo_il_login(self):
        self.client.force_login(self.user)
        res = self.client.get("/password-reset/")

        self.assertEqual(res.status_code, 200)
        self.assertTemplateNotUsed(res, TOGGLE)
        self.assertNotContains(res, 'id="agent-toggle-btn"')
