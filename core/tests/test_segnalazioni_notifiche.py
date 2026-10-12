import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from ..models import (
    Notifica,
    Permesso,
    Segnalazione,
    SegnalazioneCommento,
    SegnalazioneVoto,
    StatoSegnalazione,
    TipoSegnalazione,
)
from ..services.notifiche import count_notifiche, list_notifiche, segna_lette

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User


class SegnalazioniTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.reader = User.objects.create_user(
            "seg_reader",
            "seg-reader@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Luca",
            last_name="Rossi",
        )
        self.writer = User.objects.create_user(
            "seg_writer",
            "seg-writer@example.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Anna",
            last_name="Bianchi",
        )
        self.admin = User.objects.create_user(
            "seg_admin",
            "seg-admin@example.com",
            "pw",
            permesso=Permesso.ADMIN,
            first_name="Mario",
            last_name="Verdi",
        )
        self.voter = User.objects.create_user(
            "seg_voter",
            "seg-voter@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Piero",
            last_name="Neri",
        )

    def _post(self, url, payload, user=None):
        if user:
            self.client.force_login(user)
        return self.client.post(url, data=json.dumps(payload), content_type="application/json")

    def _create(self, user, tipo="feature", titolo="Titolo", testo="Descrizione"):
        return self._post(
            "/api/segnalazioni/",
            {"tipo": tipo, "titolo": titolo, "testo": testo},
            user=user,
        )

    def test_page_requires_login(self):
        res = self.client.get("/segnalazioni/")
        self.assertEqual(res.status_code, 302)

    def test_page_ok_for_authenticated(self):
        self.client.force_login(self.reader)
        res = self.client.get("/segnalazioni/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Nuova proposta")
        self.assertContains(res, "Tutti i post")
        self.assertContains(res, "I miei post")
        self.assertContains(res, "Top 10 per voti")
        self.assertContains(res, "Nuove funzionalità")
        self.assertContains(res, "Segnalazioni")
        self.assertNotContains(res, "Solo aperti")
        self.assertContains(res, "Post chiusi")

    def test_home_contains_prompt_link(self):
        self.client.force_login(self.reader)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Qualcosa da segnalare?")
        self.assertContains(res, 'href="/segnalazioni/"')

    def test_reading_user_can_create(self):
        res = self._create(self.reader, titolo="Nuova export", testo="Vorrei un export CSV.")
        self.assertEqual(res.status_code, 201)
        data = res.json()["data"]
        self.assertEqual(data["titolo"], "Nuova export")
        self.assertEqual(data["tipo"], TipoSegnalazione.FEATURE)
        self.assertEqual(data["autore_nome"], "Luca Rossi")
        self.assertEqual(data["autore_iniziale"], "L")
        self.assertIsNone(data["autore_avatar"])
        self.assertEqual(data["stato"], StatoSegnalazione.APERTO)
        self.assertEqual(data["score"], 0)
        self.assertEqual(data["mio_voto"], 0)
        self.assertNotIn("voti", data)
        self.assertNotIn("utente", data)

    def test_vote_unique_and_score(self):
        created = self._create(self.reader)
        pk = created.json()["data"]["id"]

        up = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.writer)
        self.assertEqual(up.status_code, 200)
        self.assertEqual(up.json()["data"]["score"], 1)
        self.assertEqual(up.json()["data"]["up"], 1)
        self.assertEqual(up.json()["data"]["mio_voto"], 1)

        again = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.writer)
        self.assertEqual(again.json()["data"]["score"], 1)
        self.assertEqual(SegnalazioneVoto.objects.filter(segnalazione_id=pk).count(), 1)

        down = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": -1}, user=self.voter)
        self.assertEqual(down.json()["data"]["score"], 0)
        self.assertEqual(down.json()["data"]["down"], 1)

        switch = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": -1}, user=self.writer)
        self.assertEqual(switch.json()["data"]["score"], -2)

        clear = self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 0}, user=self.writer)
        self.assertEqual(clear.json()["data"]["mio_voto"], 0)
        self.assertEqual(clear.json()["data"]["score"], -1)

    def test_votes_are_anonymous_in_list(self):
        created = self._create(self.reader, titolo="Voto anonimo")
        pk = created.json()["data"]["id"]
        self._post(f"/api/segnalazioni/{pk}/voto/", {"valore": 1}, user=self.voter)

        self.client.force_login(self.reader)
        res = self.client.get("/api/segnalazioni/")
        self.assertEqual(res.status_code, 200)
        blob = res.content.decode()
        self.assertNotIn("seg_voter", blob)
        self.assertNotIn("Piero Neri", blob)
        item = res.json()["segnalazioni"][0]
        self.assertEqual(item["up"], 1)
        self.assertEqual(item["mio_voto"], 0)
        self.assertNotIn("voti", item)
        for key in item:
            self.assertNotIn("utente", key)

    def test_comment_on_open_and_closed(self):
        pk = self._create(self.reader).json()["data"]["id"]
        comment = self._post(
            f"/api/segnalazioni/{pk}/commenti/",
            {"testo": "Concordo."},
            user=self.writer,
        )
        self.assertEqual(comment.status_code, 201)
        self.assertEqual(comment.json()["data"]["commenti"][0]["autore_nome"], "Anna Bianchi")
        self.assertEqual(SegnalazioneCommento.objects.filter(segnalazione_id=pk).count(), 1)

        close = self._post(f"/api/segnalazioni/{pk}/chiudi/", {}, user=self.admin)
        self.assertEqual(close.status_code, 200)
        self.assertEqual(close.json()["data"]["stato"], StatoSegnalazione.CHIUSO)

        blocked = self._post(
            f"/api/segnalazioni/{pk}/commenti/",
            {"testo": "Troppo tardi."},
            user=self.writer,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("chiuso", blocked.json()["error"].lower())

    def test_non_admin_cannot_close(self):
        pk = self._create(self.reader).json()["data"]["id"]
        res = self._post(f"/api/segnalazioni/{pk}/chiudi/", {}, user=self.writer)
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.json()["error"], "Permesso negato.")
        self.assertEqual(Segnalazione.objects.get(pk=pk).stato, StatoSegnalazione.APERTO)

        res2 = self._post(f"/api/segnalazioni/{pk}/riapri/", {}, user=self.reader)
        self.assertEqual(res2.status_code, 403)

    def test_list_orders_open_before_closed_by_score(self):
        low = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Basso",
            testo="x",
        )
        high = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Alto",
            testo="x",
        )
        closed = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiuso alto",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        SegnalazioneVoto.objects.create(segnalazione=low, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.admin, valore=1)

        self.client.force_login(self.reader)
        titles = [s["titolo"] for s in self.client.get("/api/segnalazioni/").json()["segnalazioni"]]
        self.assertEqual(titles, ["Alto", "Basso"])

    def test_filter_by_tipo(self):
        self._create(self.reader, tipo="feature", titolo="Feat")
        self._create(self.reader, tipo="problema", titolo="Bug")
        self.client.force_login(self.reader)
        feats = self.client.get("/api/segnalazioni/?tipo=feature").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in feats], ["Feat"])
        bugs = self.client.get("/api/segnalazioni/?tipo=problema").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in bugs], ["Bug"])

    def test_filter_by_stato(self):
        self._create(self.reader, titolo="Aperto")
        closed_pk = self._create(self.reader, titolo="Chiuso").json()["data"]["id"]
        self._post(f"/api/segnalazioni/{closed_pk}/chiudi/", {}, user=self.admin)
        self.client.force_login(self.reader)
        default = self.client.get("/api/segnalazioni/").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in default], ["Aperto"])
        aperti = self.client.get("/api/segnalazioni/?stato=aperto").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in aperti], ["Aperto"])
        chiusi = self.client.get("/api/segnalazioni/?stato=chiuso").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in chiusi], ["Chiuso"])

    def test_filter_mine(self):
        self._create(self.reader, titolo="Del reader")
        self._create(self.writer, titolo="Del writer")
        self.client.force_login(self.reader)
        mine = self.client.get("/api/segnalazioni/?mine=1").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in mine], ["Del reader"])
        self.client.force_login(self.writer)
        mine_w = self.client.get("/api/segnalazioni/?mine=1").json()["segnalazioni"]
        self.assertEqual([s["titolo"] for s in mine_w], ["Del writer"])

    def test_top_by_score(self):
        closed = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiuso top",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        mid = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Medio",
            testo="x",
        )
        high = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Alto",
            testo="x",
        )
        Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Zero",
            testo="x",
        )
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=closed, utente=self.admin, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=high, utente=self.voter, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=mid, utente=self.writer, valore=1)

        for i in range(8):
            Segnalazione.objects.create(
                autore=self.reader,
                tipo=TipoSegnalazione.FEATURE,
                titolo=f"Extra {i}",
                testo="x",
            )
        self.client.force_login(self.reader)
        top = self.client.get("/api/segnalazioni/?top=10").json()["segnalazioni"]
        self.assertEqual(len(top), 10)
        self.assertEqual([s["titolo"] for s in top[:2]], ["Alto", "Medio"])
        self.assertNotIn("Chiuso top", [s["titolo"] for s in top])
        self.assertNotIn("Zero", [s["titolo"] for s in top])

    def test_list_ordered_by_created_at_desc(self):
        """L'elenco è cronologico (le più recenti in cima), i voti non contano, i chiusi non compaiono."""
        votata = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Vecchia ma votata",
            testo="x",
        )
        recente = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.PROBLEMA,
            titolo="Recente senza voti",
            testo="x",
        )
        chiusa = Segnalazione.objects.create(
            autore=self.reader,
            tipo=TipoSegnalazione.FEATURE,
            titolo="Chiusa recentissima",
            testo="x",
            stato=StatoSegnalazione.CHIUSO,
        )
        base = timezone.now()
        for s, delta in ((votata, -3), (recente, -1), (chiusa, 0)):
            Segnalazione.objects.filter(pk=s.pk).update(created_at=base + timedelta(hours=delta))
        SegnalazioneVoto.objects.create(segnalazione=votata, utente=self.writer, valore=1)
        SegnalazioneVoto.objects.create(segnalazione=votata, utente=self.voter, valore=1)

        self.client.force_login(self.reader)
        titoli = [s["titolo"] for s in self.client.get("/api/segnalazioni/").json()["segnalazioni"]]
        self.assertEqual(titoli, ["Recente senza voti", "Vecchia ma votata"])

    def test_invalid_list_params(self):
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get("/api/segnalazioni/?tipo=nope").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?stato=nope").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?top=abc").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?top=0").status_code, 400)
        self.assertEqual(self.client.get("/api/segnalazioni/?mine=yes").status_code, 400)


class NotificheTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.autore = User.objects.create_user(
            "notif_autore",
            "notif-autore@example.com",
            "pw",
            permesso=Permesso.READING,
            first_name="Luca",
            last_name="Rossi",
        )
        self.altro = User.objects.create_user(
            "notif_altro",
            "notif-altro@example.com",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Anna",
            last_name="Bianchi",
        )
        self.terzo = User.objects.create_user(
            "notif_terzo",
            "notif-terzo@example.com",
            "pw",
            permesso=Permesso.ADMIN,
            first_name="Mario",
            last_name="Verdi",
        )

    def _crea_segnalazione(self, user, tipo="feature", titolo="Titolo", testo="Descrizione"):
        self.client.force_login(user)
        res = self.client.post(
            "/api/segnalazioni/",
            data=json.dumps({"tipo": tipo, "titolo": titolo, "testo": testo}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        return res.json()["data"]["id"]

    def test_nuova_feature_notifica_tutti_tranne_autore(self):
        self._crea_segnalazione(self.autore, tipo="feature")
        self.assertEqual(Notifica.objects.filter(destinatario=self.autore).count(), 0)
        testi = set(
            Notifica.objects.exclude(destinatario=self.autore).values_list("testo", flat=True)
        )
        self.assertEqual(testi, {"Luca Rossi ha proposto una nuova feature"})
        self.assertEqual(
            set(
                Notifica.objects.values_list("destinatario__username", flat=True),
            ),
            {"notif_altro", "notif_terzo"},
        )

    def test_nuovo_problema_ha_testo_dedicato(self):
        self._crea_segnalazione(self.autore, tipo="problema")
        testi = set(Notifica.objects.values_list("testo", flat=True))
        self.assertEqual(testi, {"Luca Rossi ha evidenziato un problema"})

    def test_utenti_disattivati_non_ricevono_notifiche(self):
        self.terzo.is_active = False
        self.terzo.save(update_fields=["is_active"])
        self._crea_segnalazione(self.autore)
        self.assertEqual(
            list(Notifica.objects.values_list("destinatario__username", flat=True)),
            ["notif_altro"],
        )

    def test_api_elenca_solo_le_proprie_notifiche(self):
        pk = self._crea_segnalazione(self.autore)
        self.client.force_login(self.altro)
        res = self.client.get("/api/notifiche/")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 1)
        item = body["notifiche"][0]
        self.assertEqual(item["testo"], "Luca Rossi ha proposto una nuova feature")
        self.assertEqual(item["segnalazione_id"], pk)
        self.assertEqual(item["tipo"], TipoSegnalazione.FEATURE)
        self.assertIsNotNone(item["created_at"])

        self.client.force_login(self.autore)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 0)

    def test_api_richiede_autenticazione(self):
        self.assertEqual(self.client.get("/api/notifiche/").status_code, 401)
        self.assertEqual(self.client.post("/api/notifiche/lette/").status_code, 401)

    def test_notifica_sparisce_dopo_la_visualizzazione(self):
        self._crea_segnalazione(self.autore)
        self.client.force_login(self.altro)
        ids = [n["id"] for n in self.client.get("/api/notifiche/").json()["notifiche"]]

        lette = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": ids}),
            content_type="application/json",
        )
        self.assertEqual(lette.status_code, 200)
        self.assertEqual(lette.json()["lette"], 1)
        self.assertEqual(lette.json()["count"], 0)
        self.assertEqual(self.client.get("/api/notifiche/").json()["notifiche"], [])
        self.assertIsNotNone(Notifica.objects.get(pk=ids[0]).letta_il)

        # Le notifiche degli altri utenti restano da leggere
        self.client.force_login(self.terzo)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 1)

    def test_lette_senza_ids_marca_tutte(self):
        self._crea_segnalazione(self.autore, titolo="Prima")
        self._crea_segnalazione(self.terzo, titolo="Seconda")
        self.client.force_login(self.altro)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 2)

        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["lette"], 2)
        self.assertEqual(self.client.get("/api/notifiche/").json()["count"], 0)

    def test_lette_marca_solo_gli_id_richiesti(self):
        self._crea_segnalazione(self.autore, titolo="Prima")
        self._crea_segnalazione(self.terzo, titolo="Seconda")
        self.client.force_login(self.altro)
        notifiche = self.client.get("/api/notifiche/").json()["notifiche"]
        self.assertEqual(len(notifiche), 2)

        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": [notifiche[0]["id"]]}),
            content_type="application/json",
        )
        self.assertEqual(res.json()["lette"], 1)
        rimaste = self.client.get("/api/notifiche/").json()["notifiche"]
        self.assertEqual([n["id"] for n in rimaste], [notifiche[1]["id"]])

    def test_lette_rifiuta_payload_non_valido(self):
        self.client.force_login(self.altro)
        bad_type = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": "1"}),
            content_type="application/json",
        )
        self.assertEqual(bad_type.status_code, 400)
        bad_item = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": ["abc"]}),
            content_type="application/json",
        )
        self.assertEqual(bad_item.status_code, 400)
        bad_json = self.client.post(
            "/api/notifiche/lette/",
            data="non-json",
            content_type="application/json",
        )
        self.assertEqual(bad_json.status_code, 400)

    def test_lette_ignora_notifiche_di_altri_utenti(self):
        self._crea_segnalazione(self.autore)
        altrui = Notifica.objects.get(destinatario=self.terzo)
        self.client.force_login(self.altro)
        res = self.client.post(
            "/api/notifiche/lette/",
            data=json.dumps({"ids": [altrui.pk]}),
            content_type="application/json",
        )
        self.assertEqual(res.json()["lette"], 0)
        self.assertIsNone(Notifica.objects.get(pk=altrui.pk).letta_il)

    def test_notifiche_rimosse_con_la_segnalazione(self):
        pk = self._crea_segnalazione(self.autore)
        Segnalazione.objects.filter(pk=pk).delete()
        self.assertEqual(Notifica.objects.count(), 0)

    def test_service_helpers(self):
        self._crea_segnalazione(self.autore)
        self.assertEqual(count_notifiche(self.altro), 1)
        self.assertEqual(len(list_notifiche(self.altro)), 1)
        self.assertEqual(segna_lette(self.altro), 1)
        self.assertEqual(count_notifiche(self.altro), 0)
        self.assertEqual(list_notifiche(self.altro), [])
        with self.assertRaises(ValueError):
            segna_lette(self.terzo, ["x"])

    def _commenta(self, user, pk, testo="Un commento"):
        self.client.force_login(user)
        res = self.client.post(
            f"/api/segnalazioni/{pk}/commenti/",
            data=json.dumps({"testo": testo}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 201)
        return res

    def test_commento_notifica_autore_del_thread(self):
        pk = self._crea_segnalazione(self.autore)
        segna_lette(self.autore)
        segna_lette(self.altro)
        segna_lette(self.terzo)

        self._commenta(self.altro, pk)

        self.assertEqual(count_notifiche(self.autore), 1)
        n = list_notifiche(self.autore)[0]
        self.assertEqual(n["testo"], "Anna Bianchi ha commentato «Titolo»")
        self.assertEqual(n["autore"], "Anna Bianchi")
        self.assertEqual(n["segnalazione_id"], pk)
        # Chi commenta non si auto-notifica e chi non partecipa resta fuori.
        self.assertEqual(count_notifiche(self.altro), 0)
        self.assertEqual(count_notifiche(self.terzo), 0)

    def test_commento_notifica_anche_gli_altri_commentatori(self):
        pk = self._crea_segnalazione(self.autore)
        self._commenta(self.altro, pk, "Primo commento")
        segna_lette(self.autore)
        segna_lette(self.altro)
        segna_lette(self.terzo)

        self._commenta(self.terzo, pk, "Secondo commento")

        self.assertEqual(count_notifiche(self.autore), 1)
        self.assertEqual(count_notifiche(self.altro), 1)
        self.assertEqual(count_notifiche(self.terzo), 0)
        self.assertEqual(
            list_notifiche(self.altro)[0]["testo"],
            "Mario Verdi ha commentato «Titolo»",
        )

    def test_commento_riporta_a_non_letta_la_notifica_del_thread(self):
        pk = self._crea_segnalazione(self.autore)
        segna_lette(self.altro)
        self.assertEqual(count_notifiche(self.altro), 0)

        self._commenta(self.terzo, pk)

        self.assertEqual(count_notifiche(self.altro), 0)
        self._commenta(self.altro, pk, "Rispondo io")
        self.assertEqual(count_notifiche(self.terzo), 1)
        self.assertEqual(
            list_notifiche(self.terzo)[0]["testo"],
            "Anna Bianchi ha commentato «Titolo»",
        )
        # Resta una sola notifica per thread e destinatario.
        self.assertEqual(Notifica.objects.filter(destinatario=self.terzo).count(), 1)

    def test_commento_non_notifica_utenti_disattivati(self):
        pk = self._crea_segnalazione(self.autore)
        self.autore.is_active = False
        self.autore.save(update_fields=["is_active"])
        segna_lette(self.autore)

        self._commenta(self.altro, pk)

        self.assertEqual(count_notifiche(self.autore), 0)

    def test_commento_tronca_i_titoli_lunghi(self):
        titolo = "T" * 200
        pk = self._crea_segnalazione(self.autore, titolo=titolo)
        segna_lette(self.autore)

        self._commenta(self.altro, pk)

        testo = list_notifiche(self.autore)[0]["testo"]
        self.assertTrue(testo.startswith("Anna Bianchi ha commentato «" + "T" * 119))
        self.assertTrue(testo.endswith("…»"))
        self.assertLessEqual(len(testo), 300)

    def test_campanella_visibile_nelle_pagine_autenticate(self):
        self.client.force_login(self.altro)
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="notif-btn"')
        self.assertContains(res, 'id="notif-panel"')
        self.assertContains(res, 'aria-label="Notifiche"')

    def test_campanella_assente_per_anonimi(self):
        res = self.client.get("/login/")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'id="notif-btn"')
