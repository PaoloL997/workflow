import json
import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from ..models import (
    Documento,
    FirmatarioStabilimento,
    IndirizzoStabilimento,
    Permesso,
    PersonaCommessa,
    Reparto,
    Revisione,
    RuoloFirmatarioStabilimento,
    RuoloPersonaCommessa,
    Stabilimento,
    Testata,
    TipoIndirizzoStabilimento,
    TransmittalInterno,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User


class TrasmittalInternoEndToEndTests(TestCase):
    """End-to-end: percorre il flusso utente del trasmittal interno con i dati
    reali del vecchio strumento Excel/VBA (anagrafiche, indirizzi, firmatari)
    e confronta il risultato con il comportamento atteso di quello strumento.

    Trova divergenze, non le corregge (vedi il report consegnato con la PR).
    Nessun invio di posta reale: solo il backend locmem di Django (mai
    sostituito in questa classe), fileserver su una directory temporanea,
    nessun accesso a Business Central.
    """

    def setUp(self):
        self.client = Client()

        # Garanzia esplicita: mai un backend email reale in questi test.
        from django.core.mail import get_connection

        self.assertIn("locmem", type(get_connection()).__module__)

        self.jobs_root = tempfile.TemporaryDirectory()
        self.addCleanup(self.jobs_root.cleanup)
        fs_patch = override_settings(FILESERVER_JOBS_PATH=self.jobs_root.name)
        fs_patch.enable()
        self.addCleanup(fs_patch.disable)

        # ── Stabilimenti ──
        self.bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.pd = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        self.ve = Stabilimento.objects.create(nome="Marghera", sigla="VE", codice_bc=3)
        self.cr = Stabilimento.objects.create(nome="Ricengo", sigla="CR", codice_bc=4)
        self.vi = Stabilimento.objects.create(nome="Schio", sigla="VI", codice_bc=5)
        self.milano = Stabilimento.objects.create(nome="Milano")  # nessun codice sito

        # ── Indirizzi TO/CC per sito (dati del vecchio strumento) ──
        _TO = {
            self.bg: ["fdamiani", "locatellim"],
            self.pd: ["egomiero", "mtoniolo", "dgiunchi", "dgigante"],
            self.ve: ["egomiero", "mtoniolo", "dgiunchi", "dgigante"],  # identici a PD
            self.cr: ["epaparazzo", "msolazzo", "mmaggi", "fcorradini", "poro"],
            self.vi: ["mgasparini", "anovella", "thossain"],
        }
        _CC = {
            self.bg: ["dpasserini", "quality", "mcheccolin", "fbaldin", "mcarminati", "mpersoneni"],
            self.pd: ["dpasserini", "lterrassan", "mgalli", "asandona"],
            self.ve: ["dpasserini", "psaccarola", "mgalli", "asandona"],
            self.cr: ["dpasserini", "egritti", "rlucini", "egalbiati"],
            self.vi: ["dpasserini", "lferracin", "aottoboni", "apunturieri"],
        }
        for stabilimento, nomi in _TO.items():
            for nome in nomi:
                IndirizzoStabilimento.objects.create(
                    stabilimento=stabilimento,
                    email=f"{nome}@brembanarolle.com",
                    tipo=TipoIndirizzoStabilimento.TO,
                )
        for stabilimento, nomi in _CC.items():
            for nome in nomi:
                IndirizzoStabilimento.objects.create(
                    stabilimento=stabilimento,
                    email=f"{nome}@brembanarolle.com",
                    tipo=TipoIndirizzoStabilimento.CC,
                )

        # ── Firmatari Produzione/Qualità per sito ──
        def _utente_firmatario(nome):
            return User.objects.create_user(nome.lower(), f"{nome.lower()}@brembanarolle.com", "pw")

        self.firmatari_utenti = {
            nome: _utente_firmatario(nome)
            for nome in (
                "MLocatelli",
                "FBaldin",
                "DGiunchi",
                "MGalli",
                "POro",
                "RLucini",
                "THossain",
                "AOttoboni",
            )
        }
        _FIRMATARI = {
            self.bg: ("MLocatelli", "FBaldin"),
            self.pd: ("DGiunchi", "MGalli"),
            self.ve: ("DGiunchi", "MGalli"),  # stessi di PD
            self.cr: ("POro", "RLucini"),
            self.vi: ("THossain", "AOttoboni"),
        }
        for stabilimento, (produzione, qualita) in _FIRMATARI.items():
            FirmatarioStabilimento.objects.create(
                stabilimento=stabilimento,
                ruolo=RuoloFirmatarioStabilimento.PRODUZIONE,
                utente=self.firmatari_utenti[produzione],
            )
            FirmatarioStabilimento.objects.create(
                stabilimento=stabilimento,
                ruolo=RuoloFirmatarioStabilimento.QUALITA,
                utente=self.firmatari_utenti[qualita],
            )
        # Nessun firmatario ha un'immagine di firma caricata (punto 9): il
        # campo firma resta vuoto per tutti, di proposito.

        # ── Commessa e documenti UT ──
        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99090", sito_costruttivo=self.bg)

        from core.services.fileserver import get_base_path

        base = get_base_path(self.testata.job, "UT")
        base.mkdir(parents=True)

        self.doc_a = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99090-01-DWGA",
            doc_title="Documento A",
            reparto="Ufficio Tecnico",
        )
        self.doc_b = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99090-01-DWGB",
            doc_title="Documento B",
            reparto="Ufficio Tecnico",
        )
        self.doc_c = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99090-01-ESH1",  # pattern SHn: ?????-??-ESH*
            doc_title="Documento C (SHn)",
            reparto="Ufficio Tecnico",
        )
        self.doc_d = Documento.objects.create(
            testata=self.testata,
            vendor_doc="99090-01-DWGD",
            doc_title="Documento D",
            reparto="Ufficio Tecnico",
        )
        for doc in (self.doc_a, self.doc_b, self.doc_c, self.doc_d):
            Revisione.objects.create(documento=doc, rev_no=0)
        for doc in (self.doc_a, self.doc_b, self.doc_c):  # DOC-D: file mancante di proposito
            (base / f"{doc.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-fake")

        # ── PM/PE/QCI ──
        self.pm_utente = User.objects.create_user(
            "mtoniolo", "mtoniolo@brembanarolle.com", "pw", first_name="Mauro", last_name="Toniolo"
        )
        self.pe_utente = User.objects.create_user(
            "e2e_pe", "pe.nuovo@brembanarolle.com", "pw", first_name="Paolo", last_name="Erre"
        )
        self.qci_utente = User.objects.create_user(
            "e2e_qci", "qci.nuovo@brembanarolle.com", "pw", first_name="Quinto", last_name="Ci"
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, utente=self.pm_utente
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PE, utente=self.pe_utente
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.QCI, utente=self.qci_utente
        )

        self.writer = User.objects.create_user(
            "e2e_writer",
            "e2e-writer@b.it",
            "pw",
            permesso=Permesso.WRITING,
            trasmittal_interno_writer=True,
        )
        self.client.force_login(self.writer)

        # ── Percorso 1-3: dalla pagina commessa alla griglia destinazioni,
        #    tutto attraverso il test client (mai chiamate dirette ai servizi) ──
        self._imposta_destinazioni(self.doc_a, [self.pd.codice_bc, self.ve.codice_bc])
        self._imposta_destinazioni(self.doc_b, [self.bg.codice_bc])
        self._imposta_destinazioni(self.doc_c, [self.bg.codice_bc])
        # DOC-D: nessuna destinazione, di proposito.

    # ── Helper: navigazione del flusso via test client ──────────────────────

    def _url(self, path):
        return f"/api/commesse/{self.testata.job}/trasmittal-interno/{path}"

    def _imposta_destinazioni(self, documento, codici_bc):
        risposta = self.client.post(
            self._url(f"documenti/{documento.pk}/destinazioni/"),
            data=json.dumps({"codici_bc": codici_bc}),
            content_type="application/json",
        )
        self.assertEqual(risposta.status_code, 200, risposta.content)
        return risposta.json()

    def _riga(self, documento, **overrides):
        base = {
            "documento_id": documento.pk,
            "revisione": "0",
            "copie": 2,
            "tpi": False,
            "note": "",
            "cliente": True,
        }
        base.update(overrides)
        return base

    def _anteprima(self, righe, note=""):
        risposta = self.client.post(
            self._url("anteprima/"),
            data=json.dumps({"righe": righe, "note": note}),
            content_type="application/json",
        )
        self.assertEqual(risposta.status_code, 200, risposta.content)
        return risposta.json()

    def _emetti(self, righe, note="", destinatari=None):
        payload = {"righe": righe, "note": note}
        if destinatari is not None:
            payload["destinatari"] = destinatari
        risposta = self.client.post(
            self._url("emetti/"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        return risposta

    def _righe_abcd(self, con_c=True):
        righe = [self._riga(self.doc_a, cliente=True), self._riga(self.doc_b, cliente=False)]
        if con_c:
            righe.append(self._riga(self.doc_c, cliente=True))
        return righe

    # ── Percorso: card della commessa e pagina dedicata ─────────────────────

    def test_01_card_sbloccata_e_pagina_raggiungibile(self):
        pagina_commessa = self.client.get(f"/commesse/{self.testata.job}/")
        self.assertEqual(pagina_commessa.status_code, 200)
        self.assertNotContains(pagina_commessa, 'class="section-card section-card-locked"')
        self.assertContains(pagina_commessa, f"/commesse/{self.testata.job}/trasmittal-interno/")

        pagina_trasmittal = self.client.get(f"/commesse/{self.testata.job}/trasmittal-interno/")
        self.assertEqual(pagina_trasmittal.status_code, 200)

    # ── Punto 19: Milano non è selezionabile come destinazione ──────────────

    def test_02_milano_non_selezionabile_come_destinazione(self):
        risposta = self.client.get(self._url("destinazioni/"))
        sigle = [s["sigla"] for s in risposta.json()["stabilimenti"]]
        self.assertNotIn(None, sigle)
        self.assertEqual(sorted(sigle), ["BG", "CR", "PD", "VE", "VI"])

    # ── Punto 14: documento senza file segnalato in selezione, non blocca ───

    def test_03_doc_d_segnalato_in_selezione_gli_altri_selezionabili(self):
        risposta = self.client.get(self._url("selezione/"))
        stati = {d["id"]: d for d in risposta.json()["documenti"]}

        for doc in (self.doc_a, self.doc_b, self.doc_c):
            self.assertTrue(stati[doc.pk]["selezionabile"], stati[doc.pk])

        self.assertFalse(stati[self.doc_d.pk]["selezionabile"])
        self.assertEqual(stati[self.doc_d.pk]["motivo"], "Nessun file trovato sul fileserver.")

    def test_03b_lettera_si_crea_senza_doc_d_nonostante_la_sua_presenza_in_elenco(self):
        risposta = self._emetti(self._righe_abcd())
        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertTrue(risposta.json()["ok"])

    # ── Punti 1-2-3: dedup TO/CC su PD+VE+BG (indirizzi identici per PD/VE) ──

    def test_04_to_pd_ve_compaiono_una_volta_ciascuno(self):
        anteprima = self._anteprima(self._righe_abcd())
        to = [d["email"] for d in anteprima["destinatari"] if d["tipo"] == "to"]
        for nome in ("egomiero", "mtoniolo", "dgiunchi", "dgigante"):
            email = f"{nome}@brembanarolle.com"
            self.assertEqual(to.count(email), 1, f"{email}: atteso 1, trovato {to.count(email)}")

    def test_05_dpasserini_una_volta_sola_nonostante_tre_siti(self):
        anteprima = self._anteprima(self._righe_abcd())
        emails = [d["email"] for d in anteprima["destinatari"]]
        self.assertEqual(emails.count("dpasserini@brembanarolle.com"), 1)

    def test_06_mgalli_asandona_una_volta_ciascuno(self):
        anteprima = self._anteprima(self._righe_abcd())
        emails = [d["email"] for d in anteprima["destinatari"]]
        self.assertEqual(emails.count("mgalli@brembanarolle.com"), 1)
        self.assertEqual(emails.count("asandona@brembanarolle.com"), 1)

    # ── Punto 4: PM già in TO di PD → una sola occorrenza, in TO ────────────

    def test_07_pm_mtoniolo_una_sola_occorrenza_in_to(self):
        anteprima = self._anteprima(self._righe_abcd())
        occorrenze = [
            d for d in anteprima["destinatari"] if d["email"] == "mtoniolo@brembanarolle.com"
        ]
        self.assertEqual(len(occorrenze), 1)
        self.assertEqual(occorrenze[0]["tipo"], "to")

    # ── Punto 5: un indirizzo in TO e in CC resta solo in TO ─────────────────
    # I dati di partenza dati dal task, applicati alla lettera BG+PD+VE, non
    # producono di per sé una collisione TO/CC (i nominativi TO e CC dei tre
    # siti coinvolti sono tutti distinti — vedi il report). Verifico quindi
    # la regola con un caso sintetico minimo, sullo stesso sito BG già in
    # gioco, aggiungendo un indirizzo apposta presente sia in TO che in CC.

    def test_08_indirizzo_in_to_e_in_cc_resta_solo_in_to(self):
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg,
            email="doppio@brembanarolle.com",
            tipo=TipoIndirizzoStabilimento.CC,
        )
        IndirizzoStabilimento.objects.create(
            stabilimento=self.bg,
            email="doppio@brembanarolle.com",
            tipo=TipoIndirizzoStabilimento.TO,
        )
        anteprima = self._anteprima(self._righe_abcd())
        occorrenze = [
            d for d in anteprima["destinatari"] if d["email"] == "doppio@brembanarolle.com"
        ]
        self.assertEqual(len(occorrenze), 1)
        self.assertEqual(occorrenze[0]["tipo"], "to")

    # ── Punto 6: DOC-C (SHn) → export@ in CC; rimosso, sparisce ──────────────

    def test_09_export_presente_con_doc_c_assente_senza(self):
        anteprima_con_c = self._anteprima(self._righe_abcd(con_c=True))
        emails_con_c = [d["email"] for d in anteprima_con_c["destinatari"]]
        self.assertIn("export@brembanarolle.com", emails_con_c)

        anteprima_senza_c = self._anteprima(self._righe_abcd(con_c=False))
        emails_senza_c = [d["email"] for d in anteprima_senza_c["destinatari"]]
        self.assertNotIn("export@brembanarolle.com", emails_senza_c)

    # ── Punto 7: PM/PE/QCI non valorizzati → lettera creata comunque ────────

    def test_10_lettera_creata_senza_pm_pe_qci_valorizzati(self):
        altra = Testata.objects.create(job="99091", sito_costruttivo=self.bg)
        doc = Documento.objects.create(
            testata=altra, vendor_doc="99091-01-DWGX", reparto="Ufficio Tecnico"
        )
        Revisione.objects.create(documento=doc, rev_no=0)
        from core.services.fileserver import get_base_path

        base = get_base_path(altra.job, "UT")
        base.mkdir(parents=True)
        (base / f"{doc.vendor_doc} Rev A.pdf").write_bytes(b"%PDF-fake")
        self.client.post(
            f"/api/commesse/{altra.job}/trasmittal-interno/documenti/{doc.pk}/destinazioni/",
            data=json.dumps({"codici_bc": [self.bg.codice_bc]}),
            content_type="application/json",
        )

        risposta = self.client.post(
            f"/api/commesse/{altra.job}/trasmittal-interno/emetti/",
            data=json.dumps(
                {"righe": [{"documento_id": doc.pk, "revisione": "0", "cliente": True}]}
            ),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200, risposta.content)
        self.assertTrue(risposta.json()["ok"])

    # ── Punto 8: firmatari PD+VE deduplicati (DGiunchi/MGalli comuni) ───────
    # Nessuna libreria di estrazione testo da PDF è disponibile in questo
    # ambiente (fitz non installato — vedi il fallimento preesistente in
    # SituazioneApiTestCase): verifico quindi la stessa funzione di dedup
    # usata da genera_trasmittal_interno_pdf direttamente sui siti reali
    # della lettera, non analizzando i byte del PDF.

    def test_11_firmatari_pd_ve_deduplicati_per_ruolo(self):
        from src.pdf import _firmatari_per_ruolo

        siti = [self.pd, self.ve]
        produzione = _firmatari_per_ruolo(siti, RuoloFirmatarioStabilimento.PRODUZIONE)
        qualita = _firmatari_per_ruolo(siti, RuoloFirmatarioStabilimento.QUALITA)

        self.assertEqual([f.utente_id for f in produzione], [self.firmatari_utenti["DGiunchi"].pk])
        self.assertEqual([f.utente_id for f in qualita], [self.firmatari_utenti["MGalli"].pk])

    # ── Punto 9: firmatario senza immagine → PDF generato comunque ──────────

    def test_12_pdf_generato_senza_immagini_di_firma(self):
        for firmatario in self.firmatari_utenti.values():
            self.assertFalse(firmatario.firma)

        risposta = self.client.post(
            self._url("anteprima/pdf/"),
            data=json.dumps({"righe": self._righe_abcd()}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta["Content-Type"], "application/pdf")
        self.assertTrue(risposta.content.startswith(b"%PDF"))
        self.assertGreater(len(risposta.content), 1000)

    # ── Punto 10: nome file e percorso ───────────────────────────────────────

    def test_13_nome_file_pdf_e_percorso(self):
        risposta = self._emetti(self._righe_abcd())
        corpo = risposta.json()
        self.assertTrue(corpo["pdf"]["ok"])
        percorso = Path(corpo["pdf"]["percorso"])
        oggi = timezone.localdate().isoformat()
        self.assertEqual(percorso.name, f"99090_{oggi}_E1.pdf")
        self.assertIn(str(Path("99090") / "Progetto" / "UT" / "Transmittal"), str(percorso))
        self.assertTrue(percorso.is_file())

    # ── Punto 11: progressivo giornaliero, reset il giorno dopo ─────────────

    def test_14_progressivo_giornaliero_e_reset_il_giorno_dopo(self):
        giorno1 = date(2026, 9, 15)  # martedì
        giorno2 = date(2026, 9, 16)

        with patch("core.services.trasmittal_interno.timezone.localdate", return_value=giorno1):
            prima = self._emetti(self._righe_abcd()).json()
            seconda = self._emetti([self._riga(self.doc_b, cliente=False)]).json()
        with patch("core.services.trasmittal_interno.timezone.localdate", return_value=giorno2):
            terza = self._emetti([self._riga(self.doc_c, cliente=True)]).json()

        self.assertTrue(prima["nome"].endswith("_E1"))
        self.assertTrue(seconda["nome"].endswith("_E2"))
        self.assertTrue(terza["nome"].endswith("_E1"))

    # ── Punto 12: data di distribuzione (venerdì → lunedì, altrimenti dopo) ──
    # La data di distribuzione mostrata all'utente riflette data_impegno()
    # (giorno lavorativo successivo, lunedì se venerdì), non la data di
    # emissione: verifico che generare il PDF invochi davvero data_impegno.

    def test_15_data_impegno_e_invocata_generando_il_pdf(self):
        from core.services.trasmittal_interno import data_impegno
        from src.pdf import genera_trasmittal_interno_pdf

        venerdi = date(2026, 9, 18)
        self.assertEqual(data_impegno(venerdi), date(2026, 9, 21))  # lunedì, per DataImpegnoTests

        with patch("core.services.trasmittal_interno.timezone.localdate", return_value=venerdi):
            esito = self._emetti(self._righe_abcd()).json()
        trasmittal = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        self.assertEqual(trasmittal.data, venerdi)

        with patch(
            "core.services.trasmittal_interno.data_impegno", side_effect=data_impegno
        ) as mock_impegno:
            genera_trasmittal_interno_pdf(trasmittal)

        self.assertTrue(
            mock_impegno.called,
            "data_impegno() non è invocata generando il PDF: la colonna DATE di "
            "'PAPER COPIES DISTRIBUTION' mostrerebbe la data di emissione invece "
            "del giorno lavorativo successivo (lunedì se venerdì).",
        )

    # ── Punti 15-16: oggetto e corpo dell'email ──────────────────────────────

    def test_16_oggetto_email_formato_atteso(self):
        esito = self._emetti(self._righe_abcd()).json()
        self.assertEqual(len(mail.outbox), 1)
        atteso = f"DOCUMENT TRANSMITTAL [Form MQ 7.5-04 Rev.0]: {esito['nome']}"
        self.assertEqual(mail.outbox[0].subject, atteso)

    def test_17_corpo_email_contiene_le_righe_e_il_percorso(self):
        esito = self._emetti(self._righe_abcd()).json()
        self.assertEqual(len(mail.outbox), 1)
        corpo = mail.outbox[0].body
        for doc in (self.doc_a, self.doc_b, self.doc_c):
            self.assertIn(doc.vendor_doc, corpo)
        # Non solo i documenti: anche gli altri valori di riga, come nel PDF.
        self.assertIn("YES", corpo)  # CLIENT di doc_a/doc_c
        self.assertIn("NO", corpo)  # CLIENT di doc_b
        self.assertIn(esito["pdf"]["percorso"], corpo)

    # ── Punto 17: destinatari modificati in anteprima → usati e registrati ──

    def test_18_destinatari_modificati_in_anteprima_usati_e_registrati(self):
        confermati = [
            {"email": "destinatario.scelto@brembanarolle.com", "tipo": "to", "origine": "manuale"},
        ]
        risposta = self._emetti(self._righe_abcd(), destinatari=confermati)
        esito = risposta.json()

        self.assertEqual(mail.outbox[0].to, ["destinatario.scelto@brembanarolle.com"])
        trasmittal = TransmittalInterno.objects.get(pk=esito["trasmittal_id"])
        registrati = list(trasmittal.destinatari.values_list("email", "tipo"))
        self.assertEqual(registrati, [("destinatario.scelto@brembanarolle.com", "to")])

    # ── Punto 18: il PDF non è allegato, solo linkato nel corpo ─────────────

    def test_19_pdf_non_allegato_alla_email(self):
        esito = self._emetti(self._righe_abcd()).json()
        self.assertEqual(len(mail.outbox[0].attachments), 0)
        self.assertIn(esito["pdf"]["percorso"], mail.outbox[0].body)

    # ── Punto 13: DOC-B (CLIENT NO) non in DCC; DOC-A/DOC-C sì ──────────────

    def test_20_doc_b_escluso_dal_dcc_doc_a_e_c_inclusi(self):
        esito = self._emetti(self._righe_abcd())
        corpo = esito.json()
        copiati = {c["vendor_doc"] for c in corpo["dcc"]["copiati"]}

        self.assertIn(self.doc_a.vendor_doc, copiati)
        self.assertIn(self.doc_c.vendor_doc, copiati)
        self.assertNotIn(self.doc_b.vendor_doc, copiati)

        cartella = Path(corpo["dcc"]["cartella"])
        nomi_file = [p.name for p in cartella.iterdir()]
        self.assertTrue(any(self.doc_a.vendor_doc in n for n in nomi_file))
        self.assertTrue(any(self.doc_c.vendor_doc in n for n in nomi_file))
        self.assertFalse(any(self.doc_b.vendor_doc in n for n in nomi_file))

    # ── Punto 20: modificare le destinazioni dopo l'emissione non cambia lo
    #    snapshot della lettera già emessa ────────────────────────────────

    def test_21_destinazioni_modificate_dopo_emissione_non_toccano_lo_snapshot(self):
        esito = self._emetti(self._righe_abcd())
        trasmittal = TransmittalInterno.objects.get(pk=esito.json()["trasmittal_id"])
        riga_a = trasmittal.righe.get(documento=self.doc_a)
        siti_originali = sorted(s.sigla for s in riga_a.siti.all())
        self.assertEqual(siti_originali, ["PD", "VE"])

        self._imposta_destinazioni(self.doc_a, [self.bg.codice_bc])

        riga_a.refresh_from_db()
        siti_dopo_modifica = sorted(s.sigla for s in riga_a.siti.all())
        self.assertEqual(siti_dopo_modifica, ["PD", "VE"])  # invariato: snapshot

        # Le destinazioni "vive" del documento, invece, sono cambiate davvero.
        risposta = self.client.get(self._url("destinazioni/"))
        doc_a_live = next(d for d in risposta.json()["documenti"] if d["id"] == self.doc_a.pk)
        self.assertEqual(doc_a_live["codici_bc"], [self.bg.codice_bc])

    # ── Punto 21: annullamento libera PDF, cartella DCC e progressivo ──────

    def test_22_annullamento_rimuove_pdf_cartella_dcc_e_libera_il_progressivo(self):
        esito = self._emetti(self._righe_abcd())
        corpo = esito.json()
        pdf_path = Path(corpo["pdf"]["percorso"])
        cartella_dcc = Path(corpo["dcc"]["cartella"])
        self.assertTrue(pdf_path.is_file())
        self.assertTrue(cartella_dcc.is_dir())

        risposta = self.client.post(self._url(f"lettere/{corpo['trasmittal_id']}/annulla/"))

        self.assertEqual(risposta.status_code, 200, risposta.content)
        annulla_corpo = risposta.json()
        self.assertTrue(annulla_corpo["pdf_rimosso"])
        self.assertTrue(annulla_corpo["cartella_dcc_rimossa"])
        self.assertFalse(pdf_path.exists())
        self.assertFalse(cartella_dcc.exists())
        self.assertFalse(TransmittalInterno.objects.filter(pk=corpo["trasmittal_id"]).exists())

        rifatto = self._emetti([self._riga(self.doc_b, cliente=False)]).json()
        self.assertTrue(rifatto["nome"].endswith("_E1"))  # progressivo liberato, non E2
