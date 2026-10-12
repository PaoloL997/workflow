import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, SimpleTestCase, TestCase, override_settings

from ..models import (
    Permesso,
    PersonaCommessa,
    RuoloPersonaCommessa,
    Stabilimento,
    Testata,
)
from ..services.commesse import (
    create_commessa,
    persone_per_ruolo,
    risolvi_persona_commessa,
)
from ..services.organizzazione_commesse import (
    _dividi_nomi,
    _normalizza_job,
    backfill_persone_commessa,
    leggi_organizzazione_commesse,
    persone_per_job,
    risolvi_persone_libere,
    trova_utente_per_cognome,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User, _costruisci_xlsm_organizzazione, _FakeBusinessCentralSito


class PersonaCommessaTests(TestCase):
    """Vincoli del modello: utente XOR nome libero, più persone per ruolo."""

    def setUp(self):
        self.testata = Testata.objects.create(job="88001")
        self.utente = User.objects.create_user("pc_utente", "pc-utente@b.it", "pw")

    def test_richiede_utente_o_nome_libero(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PersonaCommessa.objects.create(testata=self.testata, ruolo=RuoloPersonaCommessa.PM)

    def test_rifiuta_utente_e_nome_libero_insieme(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PersonaCommessa.objects.create(
                testata=self.testata,
                ruolo=RuoloPersonaCommessa.PM,
                utente=self.utente,
                nome_libero="Mario Rossi",
            )

    def test_piu_persone_stesso_ruolo(self):
        altro = User.objects.create_user("pc_altro", "pc-altro@b.it", "pw")
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PE, utente=self.utente
        )
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PE, utente=altro
        )

        self.assertEqual(
            PersonaCommessa.objects.filter(
                testata=self.testata, ruolo=RuoloPersonaCommessa.PE
            ).count(),
            2,
        )

    def test_cascata_alla_cancellazione_testata(self):
        PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.WE, utente=self.utente
        )

        self.testata.delete()

        self.assertEqual(PersonaCommessa.objects.count(), 0)

    def test_nome_visualizzato(self):
        con_utente = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.QCI, utente=self.utente
        )
        libero = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.QCI, nome_libero="Anna Verdi"
        )

        self.assertEqual(con_utente.nome_visualizzato, self.utente.nome_completo)
        self.assertEqual(libero.nome_visualizzato, "Anna Verdi")

    def test_nome_visualizzato_mostra_nome_e_cognome_non_lo_username(self):
        utente = User.objects.create_user(
            "pc_nome_cognome", "pc-nc@b.it", "pw", first_name="Mario", last_name="Rossi"
        )
        persona = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, utente=utente
        )

        self.assertEqual(persona.nome_visualizzato, "Mario Rossi")


class DividiNomiTests(SimpleTestCase):
    """_dividi_nomi: split di una cella grezza del foglio in singoli nomi."""

    def test_nome_singolo_con_spazio_finale(self):
        self.assertEqual(_dividi_nomi("CAPPELLOTTO "), ["CAPPELLOTTO"])

    def test_split_su_slash(self):
        self.assertEqual(_dividi_nomi("LUCINI / PILONI"), ["LUCINI", "PILONI"])

    def test_split_su_a_capo(self):
        self.assertEqual(_dividi_nomi("LUCINI\nPILONI"), ["LUCINI", "PILONI"])

    def test_scarta_parti_vuote(self):
        self.assertEqual(_dividi_nomi("LUCINI//PILONI"), ["LUCINI", "PILONI"])

    def test_scarta_n_a_case_insensitive(self):
        self.assertEqual(_dividi_nomi("N/A"), [])
        self.assertEqual(_dividi_nomi("n/a"), [])

    def test_valore_vuoto(self):
        self.assertEqual(_dividi_nomi(None), [])
        self.assertEqual(_dividi_nomi(""), [])

    def test_caso_sporco_non_solleva_eccezioni(self):
        # Limite noto: non c'è un modo affidabile di interpretare questo
        # caso, importa che non sollevi eccezioni.
        risultato = _dividi_nomi("BG: IMPALLOMENI \nVI: ")
        self.assertIsInstance(risultato, list)


class NormalizzaJobTests(SimpleTestCase):
    """_normalizza_job: normalizza una cella 'Job no.' al formato Testata.job."""

    def test_stringa(self):
        self.assertEqual(_normalizza_job("22105"), "22105")

    def test_intero(self):
        self.assertEqual(_normalizza_job(22116), "22116")

    def test_float_intero(self):
        self.assertEqual(_normalizza_job(22116.0), "22116")

    def test_prefisso_lettera(self):
        self.assertEqual(_normalizza_job("I23004"), "I23004")

    def test_none(self):
        self.assertEqual(_normalizza_job(None), "")


class LeggiOrganizzazioneCommesseTests(TestCase):
    """leggi_organizzazione_commesse / persone_per_job: lettura del foglio Excel."""

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.xlsm_path = Path(media.name) / "organizzazione.xlsx"

    def _leggi(self, righe):
        _costruisci_xlsm_organizzazione(self.xlsm_path, righe)
        return leggi_organizzazione_commesse(str(self.xlsm_path))

    def test_job_stringa_e_intero(self):
        dati = self._leggi(
            [
                {"Job": "22105", "PM": "CAPPELLOTTO"},
                {"Job": 22116, "PM": "ROSSI"},
            ]
        )
        self.assertEqual(dati["22105"]["pm"], ["CAPPELLOTTO"])
        self.assertEqual(dati["22116"]["pm"], ["ROSSI"])

    def test_job_con_prefisso_lettera(self):
        dati = self._leggi([{"Job": "I23004", "PM": "N/A"}])
        self.assertIn("I23004", dati)
        self.assertEqual(dati["I23004"]["pm"], [])

    def test_ruolo_multiplo_split_su_slash(self):
        dati = self._leggi([{"Job": "23068", "PM": "BORELLI/QUIPPERETTI"}])
        self.assertEqual(dati["23068"]["pm"], ["BORELLI", "QUIPPERETTI"])

    def test_n_a_trattato_come_vuoto(self):
        dati = self._leggi([{"Job": "99001", "QCI": "N/A"}])
        self.assertEqual(dati["99001"]["qci"], [])

    def test_ruolo_vuoto(self):
        dati = self._leggi([{"Job": "99002"}])
        self.assertEqual(dati["99002"], {"pm": [], "pe": [], "we": [], "qci": []})

    def test_righe_con_lo_stesso_job_si_uniscono(self):
        dati = self._leggi(
            [
                {"Job": "23068", "PM": "BORELLI/QUIPPERETTI"},
                {"Job": "23068", "PM": "BORELLI"},
            ]
        )
        # Deduplicato: BORELLI compare una sola volta anche se in entrambe le righe.
        self.assertEqual(dati["23068"]["pm"], ["BORELLI", "QUIPPERETTI"])

    def test_persone_per_job_non_trovato_restituisce_none(self):
        self._leggi([{"Job": "99003", "PM": "ROSSI"}])
        self.assertIsNone(persone_per_job("00000", str(self.xlsm_path)))

    def test_persone_per_job_trovato(self):
        self._leggi([{"Job": "99003", "PM": "ROSSI"}])
        self.assertEqual(persone_per_job("99003", str(self.xlsm_path))["pm"], ["ROSSI"])

    def test_file_non_trovato(self):
        with self.assertRaises(FileNotFoundError):
            leggi_organizzazione_commesse(r"Z:\percorso\che\non\esiste.xlsm")


class CreateCommessaConPersoneTests(TestCase):
    """create_commessa: creazione atomica di Testata + PersonaCommessa."""

    def setUp(self):
        self.utente = User.objects.create_user("cc_utente", "cc-utente@b.it", "pw")

    def _dati(self, job, **extra):
        return {"job": job, "client": "Cliente Test", **extra}

    def test_utente_registrato(self):
        t = create_commessa(self._dati("77001", persone={"pm": [{"utente_id": self.utente.pk}]}))

        riga = PersonaCommessa.objects.get(testata=t, ruolo=RuoloPersonaCommessa.PM)
        self.assertEqual(riga.utente_id, self.utente.pk)
        self.assertEqual(riga.nome_libero, "")

    def test_nome_libero(self):
        t = create_commessa(self._dati("77002", persone={"pe": [{"nome": "Mario Rossi"}]}))

        riga = PersonaCommessa.objects.get(testata=t, ruolo=RuoloPersonaCommessa.PE)
        self.assertIsNone(riga.utente_id)
        self.assertEqual(riga.nome_libero, "Mario Rossi")

    def test_piu_persone_sullo_stesso_ruolo(self):
        altro = User.objects.create_user("cc_altro", "cc-altro@b.it", "pw")
        t = create_commessa(
            self._dati(
                "77003",
                persone={
                    "qci": [{"utente_id": self.utente.pk}, {"utente_id": altro.pk}],
                },
            )
        )

        self.assertEqual(
            PersonaCommessa.objects.filter(testata=t, ruolo=RuoloPersonaCommessa.QCI).count(), 2
        )

    def test_senza_persone_non_crea_righe(self):
        t = create_commessa(self._dati("77004"))

        self.assertEqual(PersonaCommessa.objects.filter(testata=t).count(), 0)

    def test_nome_libero_vuoto_ignorato(self):
        t = create_commessa(self._dati("77005", persone={"we": [{"nome": "   "}]}))

        self.assertEqual(PersonaCommessa.objects.filter(testata=t).count(), 0)

    def test_utente_id_inesistente_solleva_integrity_error(self):
        from django.db import connection

        # Postgres non verifica sempre il vincolo di chiave esterna in modo
        # sincrono dentro un savepoint annidato (quello di TestCase): un
        # check_constraints() esplicito forza a farlo qui, invece di
        # scoprirlo solo al rollback di fine test.
        with self.assertRaises(IntegrityError), transaction.atomic():
            create_commessa(self._dati("77006", persone={"pm": [{"utente_id": 999999}]}))
            connection.check_constraints()

    def test_risolve_sito_costruttivo_da_bc_alla_creazione(self):
        bg = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        fake = _FakeBusinessCentralSito({"77007": "1"})

        with patch("core.services.bc_sync._apri_connessione", return_value=fake):
            with self.captureOnCommitCallbacks(execute=True):
                t = create_commessa(self._dati("77007"))

        t.refresh_from_db()
        self.assertEqual(t.sito_costruttivo_id, bg.pk)

    def test_bc_non_raggiungibile_non_impedisce_la_creazione(self):
        fake = _FakeBusinessCentralSito({}, conn=False)

        with patch("core.services.bc_sync._apri_connessione", return_value=fake):
            with self.captureOnCommitCallbacks(execute=True):
                t = create_commessa(self._dati("77008"))

        self.assertTrue(Testata.objects.filter(job="77008").exists())
        t.refresh_from_db()
        self.assertIsNone(t.sito_costruttivo_id)


class PersonePerRuoloTests(TestCase):
    """persone_per_ruolo: persone per ruolo, con lo stato di abbinamento, per l'header."""

    def test_elenca_le_persone_per_ruolo_con_lo_stato_di_abbinamento(self):
        t = Testata.objects.create(job="66001")
        u1 = User.objects.create_user(
            "ppr1", "ppr1@b.it", "pw", first_name="Mario", last_name="Rossi"
        )
        abbinata = PersonaCommessa.objects.create(
            testata=t, ruolo=RuoloPersonaCommessa.PM, utente=u1
        )
        libera = PersonaCommessa.objects.create(
            testata=t, ruolo=RuoloPersonaCommessa.PM, nome_libero="Libero Bianchi"
        )

        risultato = persone_per_ruolo(t)

        self.assertEqual(
            risultato["pm"],
            [
                {"id": abbinata.pk, "nome": "Mario Rossi", "abbinato": True},
                {"id": libera.pk, "nome": "Libero Bianchi", "abbinato": False},
            ],
        )
        self.assertEqual(risultato["pe"], [])
        self.assertEqual(set(risultato), {"pm", "pe", "qci", "we"})


class RisolviPersonaCommessaTests(TestCase):
    """risolvi_persona_commessa: collega manualmente una voce a testo libero a un utente."""

    def setUp(self):
        self.testata = Testata.objects.create(job="66010")
        self.persona = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.WE, nome_libero="Baldelli"
        )
        self.utente = User.objects.create_user("rpc1", "rpc1@b.it", "pw", last_name="Baldelli")

    def test_collega_l_utente_e_svuota_il_nome_libero(self):
        persona = risolvi_persona_commessa(self.persona.pk, self.utente.pk)

        self.assertEqual(persona.utente_id, self.utente.pk)
        self.assertEqual(persona.nome_libero, "")

    def test_persona_inesistente(self):
        with self.assertRaises(PersonaCommessa.DoesNotExist):
            risolvi_persona_commessa(999999, self.utente.pk)

    def test_utente_inesistente(self):
        with self.assertRaises(User.DoesNotExist):
            risolvi_persona_commessa(self.persona.pk, 999999)


class BackfillPersoneCommessaTests(TestCase):
    """backfill_persone_commessa e il comando che lo espone."""

    def setUp(self):
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.xlsm_path = Path(media.name) / "organizzazione.xlsx"
        _costruisci_xlsm_organizzazione(
            self.xlsm_path,
            [
                {"Job": "55001", "PM": "ROSSI", "PE": "BIANCHI"},
                {"Job": "55002", "PM": "VERDI"},
            ],
        )
        patcher = override_settings(ORGANIZZAZIONE_COMMESSE_XLSM_PATH=str(self.xlsm_path))
        patcher.enable()
        self.addCleanup(patcher.disable)

        self.t1 = Testata.objects.create(job="55001")
        self.t2 = Testata.objects.create(job="55002")
        self.t3 = Testata.objects.create(job="55003")  # non nel foglio

    def test_crea_persone_per_commesse_esistenti(self):
        report = backfill_persone_commessa()

        self.assertEqual(sorted(report["aggiornate"]), ["55001", "55002"])
        self.assertEqual(report["non_trovate"], ["55003"])
        self.assertEqual(
            set(self.t1.persone.values_list("ruolo", "nome_libero")),
            {("pm", "ROSSI"), ("pe", "BIANCHI")},
        )

    def test_salta_ruolo_gia_popolato(self):
        PersonaCommessa.objects.create(
            testata=self.t1, ruolo=RuoloPersonaCommessa.PM, nome_libero="Già corretto"
        )

        report = backfill_persone_commessa()

        # PM non toccato (era già popolato); PE viene comunque riempito.
        pm = list(self.t1.persone.filter(ruolo="pm").values_list("nome_libero", flat=True))
        self.assertEqual(pm, ["Già corretto"])
        self.assertTrue(self.t1.persone.filter(ruolo="pe", nome_libero="BIANCHI").exists())
        self.assertEqual(report["ruoli_saltati"], 1)

    def test_rieseguibile_senza_duplicare(self):
        backfill_persone_commessa()
        prima = PersonaCommessa.objects.count()

        backfill_persone_commessa()

        self.assertEqual(PersonaCommessa.objects.count(), prima)

    def test_dry_run_non_scrive(self):
        report = backfill_persone_commessa(dry_run=True)

        self.assertEqual(PersonaCommessa.objects.count(), 0)
        self.assertEqual(sorted(report["aggiornate"]), ["55001", "55002"])

    def test_jobs_limita_il_backfill(self):
        backfill_persone_commessa(jobs=["55001"])

        self.assertTrue(self.t1.persone.exists())
        self.assertFalse(self.t2.persone.exists())

    def test_comando_job_singolo(self):
        out = io.StringIO()
        call_command("backfill_persone_commessa", "--job=55001", stdout=out)

        self.assertTrue(self.t1.persone.exists())
        self.assertFalse(self.t2.persone.exists())
        self.assertIn("55001", out.getvalue())

    def test_comando_job_non_trovato_in_workflow(self):
        err = io.StringIO()
        call_command("backfill_persone_commessa", "--job=00000", stderr=err)

        self.assertIn("non trovata", err.getvalue())

    def test_comando_dry_run(self):
        out = io.StringIO()
        call_command("backfill_persone_commessa", "--dry-run", stdout=out)

        self.assertEqual(PersonaCommessa.objects.count(), 0)
        self.assertIn("dry-run", out.getvalue())

    def test_abbina_un_cognome_a_un_utente_registrato(self):
        rossi = User.objects.create_user(
            "bpc_rossi", "bpc-rossi@b.it", "pw", first_name="Mario", last_name="Rossi"
        )

        backfill_persone_commessa()

        pm = self.t1.persone.get(ruolo="pm")
        self.assertEqual(pm.utente_id, rossi.pk)
        self.assertEqual(pm.nome_libero, "")
        # BIANCHI non ha un utente corrispondente: resta testo libero.
        pe = self.t1.persone.get(ruolo="pe")
        self.assertIsNone(pe.utente_id)
        self.assertEqual(pe.nome_libero, "BIANCHI")

    def test_da_risolvere_elenca_i_cognomi_non_abbinati(self):
        report = backfill_persone_commessa()

        self.assertEqual(
            {(v["job"], v["ruolo"], v["nome"]) for v in report["da_risolvere"]},
            {("55001", "pm", "ROSSI"), ("55001", "pe", "BIANCHI"), ("55002", "pm", "VERDI")},
        )

    def test_comando_segnala_da_risolvere(self):
        out = io.StringIO()
        call_command("backfill_persone_commessa", stdout=out)

        self.assertIn("Da risolvere", out.getvalue())
        self.assertIn("ROSSI", out.getvalue())

    def test_comando_risolvi_esistenti(self):
        backfill_persone_commessa()  # crea le righe a testo libero
        rossi = User.objects.create_user(
            "bpc_rossi2", "bpc-rossi2@b.it", "pw", first_name="Mario", last_name="Rossi"
        )

        out = io.StringIO()
        call_command("backfill_persone_commessa", "--risolvi-esistenti", stdout=out)

        pm = self.t1.persone.get(ruolo="pm")
        self.assertEqual(pm.utente_id, rossi.pk)
        self.assertIn("ROSSI", out.getvalue())


class TrovaUtentePerCognomeTests(TestCase):
    """trova_utente_per_cognome: abbinamento cognome -> utente registrato."""

    def test_una_sola_corrispondenza(self):
        u = User.objects.create_user("tup1", "tup1@b.it", "pw", last_name="Rossi")

        self.assertEqual(trova_utente_per_cognome("Rossi"), u)

    def test_case_insensitive(self):
        u = User.objects.create_user("tup2", "tup2@b.it", "pw", last_name="Rossi")

        self.assertEqual(trova_utente_per_cognome("ROSSI"), u)

    def test_nessuna_corrispondenza(self):
        self.assertIsNone(trova_utente_per_cognome("Sconosciuto"))

    def test_piu_corrispondenze_troppo_ambiguo(self):
        User.objects.create_user("tup3", "tup3@b.it", "pw", last_name="Rossi")
        User.objects.create_user("tup4", "tup4@b.it", "pw", last_name="Rossi")

        self.assertIsNone(trova_utente_per_cognome("Rossi"))


class RisolviPersoneLibereTests(TestCase):
    """risolvi_persone_libere: ri-abbina le PersonaCommessa già a testo libero."""

    def setUp(self):
        self.testata = Testata.objects.create(job="55010")
        self.non_abbinata = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PM, nome_libero="Rossi"
        )
        self.senza_utente = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.PE, nome_libero="Sconosciuto"
        )

    def test_risolve_quando_un_utente_ora_esiste(self):
        rossi = User.objects.create_user("rpl1", "rpl1@b.it", "pw", last_name="Rossi")

        report = risolvi_persone_libere()

        self.non_abbinata.refresh_from_db()
        self.assertEqual(self.non_abbinata.utente_id, rossi.pk)
        self.assertEqual(self.non_abbinata.nome_libero, "")
        self.assertEqual(
            {(v["job"], v["ruolo"], v["nome"]) for v in report["risolte"]},
            {("55010", "pm", "Rossi")},
        )

    def test_lascia_intatte_quelle_ancora_senza_corrispondenza(self):
        User.objects.create_user("rpl2", "rpl2@b.it", "pw", last_name="Rossi")

        report = risolvi_persone_libere()

        self.senza_utente.refresh_from_db()
        self.assertIsNone(self.senza_utente.utente_id)
        self.assertEqual(self.senza_utente.nome_libero, "Sconosciuto")
        self.assertEqual(
            {(v["job"], v["ruolo"], v["nome"]) for v in report["non_risolte"]},
            {("55010", "pe", "Sconosciuto")},
        )

    def test_dry_run_non_scrive(self):
        User.objects.create_user("rpl3", "rpl3@b.it", "pw", last_name="Rossi")

        risolvi_persone_libere(dry_run=True)

        self.non_abbinata.refresh_from_db()
        self.assertIsNone(self.non_abbinata.utente_id)
        self.assertEqual(self.non_abbinata.nome_libero, "Rossi")

    def test_jobs_limita_la_ricerca(self):
        User.objects.create_user("rpl4", "rpl4@b.it", "pw", last_name="Rossi")
        altra_testata = Testata.objects.create(job="55011")
        PersonaCommessa.objects.create(
            testata=altra_testata, ruolo=RuoloPersonaCommessa.PM, nome_libero="Rossi"
        )

        risolvi_persone_libere(jobs=["55011"])

        self.non_abbinata.refresh_from_db()
        self.assertIsNone(self.non_abbinata.utente_id)
        altra = PersonaCommessa.objects.get(testata=altra_testata)
        self.assertIsNotNone(altra.utente_id)


class UtentiCercaApiTests(TestCase):
    """GET /api/utenti/cerca/: autocomplete per PM/PE/QCI/WE."""

    def setUp(self):
        self.client = Client()
        self.utente = User.objects.create_user(
            "uca_utente",
            "uca@b.it",
            "pw",
            permesso=Permesso.WRITING,
            first_name="Mario",
            last_name="Rossi",
        )
        self.client.force_login(self.utente)
        User.objects.create_user(
            "uca_bianchi",
            "uca-bianchi@b.it",
            "pw",
            first_name="Anna",
            last_name="Bianchi",
        )
        User.objects.create_user(
            "uca_inattivo",
            "uca-inattivo@b.it",
            "pw",
            first_name="Fuori",
            last_name="Servizio",
            is_active=False,
        )

    def test_richiede_login(self):
        self.client.logout()
        risposta = self.client.get("/api/utenti/cerca/?q=Rossi")
        self.assertNotEqual(risposta.status_code, 200)

    def test_cerca_per_cognome(self):
        risposta = self.client.get("/api/utenti/cerca/?q=Rossi")
        utenti = risposta.json()["utenti"]
        self.assertEqual([u["username"] for u in utenti], ["uca_utente"])

    def test_cerca_per_username(self):
        risposta = self.client.get("/api/utenti/cerca/?q=uca_bianchi")
        utenti = risposta.json()["utenti"]
        self.assertEqual([u["username"] for u in utenti], ["uca_bianchi"])

    def test_meno_di_due_caratteri_restituisce_vuoto(self):
        risposta = self.client.get("/api/utenti/cerca/?q=R")
        self.assertEqual(risposta.json()["utenti"], [])

    def test_esclude_utenti_non_attivi(self):
        risposta = self.client.get("/api/utenti/cerca/?q=Servizio")
        self.assertEqual(risposta.json()["utenti"], [])

    def test_limita_a_dieci_risultati(self):
        for i in range(15):
            User.objects.create_user(f"uca_molti{i}", f"uca-molti{i}@b.it", "pw", last_name="Molti")
        risposta = self.client.get("/api/utenti/cerca/?q=Molti")
        self.assertEqual(len(risposta.json()["utenti"]), 10)


class PersonaCommessaRisolviApiTests(TestCase):
    """POST /api/persone-commessa/<pk>/risolvi/: collega a mano un nome libero a un utente."""

    def setUp(self):
        self.client = Client()
        self.utente_scrittura = User.objects.create_user(
            "pcr_scrittura", "pcr-scrittura@b.it", "pw", permesso=Permesso.WRITING
        )
        self.utente_lettura = User.objects.create_user(
            "pcr_lettura", "pcr-lettura@b.it", "pw", permesso=Permesso.READING
        )
        self.candidato = User.objects.create_user(
            "pcr_candidato", "pcr-candidato@b.it", "pw", last_name="Baldelli"
        )
        self.testata = Testata.objects.create(job="66020")
        self.persona = PersonaCommessa.objects.create(
            testata=self.testata, ruolo=RuoloPersonaCommessa.WE, nome_libero="Baldelli"
        )

    def _risolvi(self, persona_id, utente_id):
        return self.client.post(
            f"/api/persone-commessa/{persona_id}/risolvi/",
            data=json.dumps({"utente_id": utente_id}),
            content_type="application/json",
        )

    def test_richiede_login(self):
        risposta = self._risolvi(self.persona.pk, self.candidato.pk)
        self.assertNotEqual(risposta.status_code, 200)

    def test_richiede_permesso_di_scrittura(self):
        self.client.force_login(self.utente_lettura)

        risposta = self._risolvi(self.persona.pk, self.candidato.pk)

        self.assertEqual(risposta.status_code, 403)
        self.persona.refresh_from_db()
        self.assertIsNone(self.persona.utente_id)

    def test_collega_l_utente(self):
        self.client.force_login(self.utente_scrittura)

        risposta = self._risolvi(self.persona.pk, self.candidato.pk)

        self.assertEqual(risposta.status_code, 200)
        self.assertEqual(risposta.json()["nome"], self.candidato.nome_completo)
        self.persona.refresh_from_db()
        self.assertEqual(self.persona.utente_id, self.candidato.pk)
        self.assertEqual(self.persona.nome_libero, "")

    def test_persona_inesistente(self):
        self.client.force_login(self.utente_scrittura)

        risposta = self._risolvi(999999, self.candidato.pk)

        self.assertEqual(risposta.status_code, 404)

    def test_utente_inesistente(self):
        self.client.force_login(self.utente_scrittura)

        risposta = self._risolvi(self.persona.pk, 999999)

        self.assertEqual(risposta.status_code, 404)

    def test_utente_id_mancante(self):
        self.client.force_login(self.utente_scrittura)

        risposta = self.client.post(
            f"/api/persone-commessa/{self.persona.pk}/risolvi/",
            data=json.dumps({}),
            content_type="application/json",
        )

        self.assertEqual(risposta.status_code, 400)
