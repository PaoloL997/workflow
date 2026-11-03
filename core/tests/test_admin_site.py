from django.contrib import admin
from django.contrib.auth.models import Permission
from django.test import TestCase

from ..admin_site import GRUPPI_ADMIN, WorkflowAdminSite
from ..models import (
    IndirizzoStabilimento,
    IndirizzoTipoDocumento,
    Permesso,
    Stabilimento,
    TipoIndirizzoStabilimento,
)
from ._fixtures import User


def _gruppi_della_pagina(risposta):
    return [
        (gruppo["name"], [m["object_name"] for m in gruppo["models"]])
        for gruppo in risposta.context["app_list"]
    ]


class GruppiAdminTests(TestCase):
    """L'admin elenca le tabelle per argomento (``core.admin_site.GRUPPI_ADMIN``)."""

    def setUp(self):
        self.root = User.objects.create_superuser("root", "root@example.com", "pw")

    def test_il_sito_admin_e_quello_con_i_gruppi(self):
        self.assertIsInstance(admin.site, WorkflowAdminSite)

    def test_ogni_tabella_registrata_ha_un_gruppo(self):
        # Se fallisce: aggiungere la tabella nuova al gruppo giusto in GRUPPI_ADMIN.
        registrate = {modello._meta.label for modello in admin.site._registry}
        nei_gruppi = [etichetta for _, _, etichette in GRUPPI_ADMIN for etichetta in etichette]

        self.assertEqual(registrate - set(nei_gruppi), set())
        self.assertEqual(
            set(nei_gruppi) - registrate, set(), "tabelle in GRUPPI_ADMIN non registrate"
        )
        self.assertEqual(len(nei_gruppi), len(set(nei_gruppi)), "tabelle in più di un gruppo")

    def test_la_home_mostra_i_gruppi_nell_ordine_configurato(self):
        self.client.force_login(self.root)

        risposta = self.client.get("/admin/")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            [nome for nome, _ in _gruppi_della_pagina(risposta)],
            [nome for _, nome, _ in GRUPPI_ADMIN],
        )
        trasmittal = dict(_gruppi_della_pagina(risposta))["Trasmittal interno"]
        self.assertEqual(
            trasmittal,
            [
                "IndirizzoStabilimento",
                "IndirizzoTipoDocumento",
                "FirmatarioStabilimento",
                "TransmittalInterno",
                "PresaVisioneTransmittalInterno",
            ],
        )

    def test_la_pagina_del_gruppo_mostra_solo_le_sue_tabelle(self):
        self.client.force_login(self.root)

        risposta = self.client.get("/admin/gruppo/trasmittal-interno/")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(
            [nome for nome, _ in _gruppi_della_pagina(risposta)], ["Trasmittal interno"]
        )
        self.assertContains(risposta, 'href="/admin/gruppo/trasmittal-interno/"')

    def test_gruppo_inesistente(self):
        self.client.force_login(self.root)

        self.assertEqual(self.client.get("/admin/gruppo/nessuno/").status_code, 404)

    def test_la_pagina_dell_app_core_resta_disponibile(self):
        self.client.force_login(self.root)

        self.assertEqual(self.client.get("/admin/core/").status_code, 200)

    def test_un_utente_vede_solo_i_gruppi_con_tabelle_permesse(self):
        utente = User.objects.create_user(
            "staff", "staff@example.com", "pw", permesso=Permesso.WRITING
        )
        utente.user_permissions.add(Permission.objects.get(codename="view_documento"))
        self.client.force_login(utente)

        risposta = self.client.get("/admin/")

        self.assertEqual(_gruppi_della_pagina(risposta), [("Commesse e documenti", ["Documento"])])
        self.assertEqual(self.client.get("/admin/gruppo/sistema/").status_code, 404)


class IndirizzoStabilimentoAdminTests(TestCase):
    """Gli indirizzi dei siti si gestiscono dalla loro tabella, non dalla scheda Stabilimento."""

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.indirizzo = IndirizzoStabilimento.objects.create(
            stabilimento=self.bg, email="bg@b.it", tipo=TipoIndirizzoStabilimento.TO
        )

    def test_elenco_con_filtro_per_stabilimento(self):
        risposta = self.client.get(
            f"/admin/core/indirizzostabilimento/?stabilimento__id__exact={self.bg.pk}"
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertContains(risposta, "bg@b.it")

    def test_la_scheda_stabilimento_non_ha_piu_gli_indirizzi(self):
        risposta = self.client.get(f"/admin/core/stabilimento/{self.bg.pk}/change/")

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.context["inline_admin_formsets"], [])


class IndirizzoTipoDocumentoAdminTests(TestCase):
    """Le regole per tipo documento si gestiscono dall'admin, nel gruppo Trasmittal interno."""

    URL_AGGIUNGI = "/admin/core/indirizzotipodocumento/add/"

    def setUp(self):
        self.client.force_login(User.objects.create_superuser("root", "root@example.com", "pw"))

    def _aggiungi(self, codice):
        return self.client.post(
            self.URL_AGGIUNGI,
            {"codice_tipo": codice, "email": "qa@b.it", "tipo": "cc", "attivo": "on"},
        )

    def test_aggiunta_con_codice_in_maiuscolo(self):
        risposta = self._aggiungi("edv")

        self.assertEqual(risposta.status_code, 302)
        self.assertTrue(IndirizzoTipoDocumento.objects.filter(codice_tipo="EDV").exists())

    def test_un_doppione_in_minuscolo_e_un_errore_del_form(self):
        self._aggiungi("EDV")

        risposta = self._aggiungi("edv")

        self.assertEqual(risposta.status_code, 200)
        self.assertTrue(risposta.context["adminform"].form.errors)
        self.assertEqual(IndirizzoTipoDocumento.objects.filter(codice_tipo="EDV").count(), 1)
