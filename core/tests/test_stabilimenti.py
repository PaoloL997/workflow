import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import patch

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from ..models import (
    DestinazioneDocumento,
    Documento,
    FirmatarioStabilimento,
    IndirizzoDefaultTrasmittalInterno,
    IndirizzoStabilimento,
    Reparto,
    RuoloFirmatarioStabilimento,
    Stabilimento,
    Testata,
    TipoDestinatarioTransmittalInterno,
    TipoIndirizzoStabilimento,
)
from ..services.recipients_import import (
    importa_destinazioni_commessa,
    importa_destinazioni_tutte_le_commesse,
    leggi_recipients_data,
)
from ..services.trasmittal_interno import (
    imposta_destinazioni,
    indirizzi_default_per_siti,
    indirizzi_per_siti,
    siti_coinvolti,
    siti_del_documento,
)

# ── Shared fixture factory (unit tests only — uses temp dir) ──────────────────
from ._fixtures import User


class UserStabilimentoTest(TestCase):
    def test_stabilimento_optional(self):
        user = User.objects.create_user("stab_none", password="pw")
        self.assertIsNone(user.stabilimento_id)

    def test_stabilimento_assign(self):
        stab = Stabilimento.objects.create(nome="Bergamo")
        user = User.objects.create_user("stab_yes", password="pw", stabilimento=stab)
        self.assertEqual(user.stabilimento.nome, "Bergamo")


class StabilimentoSiglaCodiceBCTests(TestCase):
    """Sigla e codice_bc: unici ma non tutti gli stabilimenti li hanno."""

    def test_sigla_unica(self):
        Stabilimento.objects.create(nome="Uno", sigla="BG")

        with self.assertRaises(IntegrityError), transaction.atomic():
            Stabilimento.objects.create(nome="Due", sigla="BG")

    def test_codice_bc_unico(self):
        Stabilimento.objects.create(nome="Uno", codice_bc=1)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Stabilimento.objects.create(nome="Due", codice_bc=1)

    def test_piu_stabilimenti_con_sigla_e_codice_null_convivono(self):
        # Non tutti gli stabilimenti sono siti costruttivi: NULL è ammesso più volte.
        Stabilimento.objects.create(nome="Milano")
        Stabilimento.objects.create(nome="Roma")

        self.assertEqual(
            set(Stabilimento.objects.values_list("nome", flat=True)), {"Milano", "Roma"}
        )


class FirmatarioStabilimentoTests(TestCase):
    """Un solo firmatario per stabilimento e ruolo; lo stesso utente può firmare più siti."""

    def setUp(self):
        self.stab = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.altro_stab = Stabilimento.objects.create(nome="Schio", sigla="VI", codice_bc=5)
        self.utente = User.objects.create_user("firmatario", password="pw")

    def test_un_solo_firmatario_per_ruolo_e_stabilimento(self):
        FirmatarioStabilimento.objects.create(
            stabilimento=self.stab,
            ruolo=RuoloFirmatarioStabilimento.PRODUZIONE,
            utente=self.utente,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            FirmatarioStabilimento.objects.create(
                stabilimento=self.stab,
                ruolo=RuoloFirmatarioStabilimento.PRODUZIONE,
                utente=self.utente,
            )

    def test_lo_stesso_utente_firma_per_piu_stabilimenti(self):
        FirmatarioStabilimento.objects.create(
            stabilimento=self.stab,
            ruolo=RuoloFirmatarioStabilimento.QUALITA,
            utente=self.utente,
        )
        FirmatarioStabilimento.objects.create(
            stabilimento=self.altro_stab,
            ruolo=RuoloFirmatarioStabilimento.QUALITA,
            utente=self.utente,
        )

        self.assertEqual(self.utente.firmatario_di.count(), 2)


class MigrazioneSigleCodiciBCTests(TestCase):
    """La migrazione dati 0045 assegna sigla e codice_bc per nome."""

    def _modulo(self):
        import importlib

        return importlib.import_module("core.migrations.0045_popola_sigla_codice_bc_stabilimenti")

    def test_assegna_i_codici_giusti(self):
        for nome in ("Valbrembo", "Albignasego", "Marghera", "Ricengo", "Schio", "Milano"):
            Stabilimento.objects.create(nome=nome)

        self._modulo().popola(django_apps, None)

        attesi = {
            "Valbrembo": ("BG", 1),
            "Albignasego": ("PD", 2),
            "Marghera": ("VE", 3),
            "Ricengo": ("CR", 4),
            "Schio": ("VI", 5),
            "Milano": (None, None),
        }
        for nome, (sigla, codice_bc) in attesi.items():
            stab = Stabilimento.objects.get(nome=nome)
            self.assertEqual((stab.sigla, stab.codice_bc), (sigla, codice_bc))

    def test_reverse_svuota_solo_i_nomi_noti(self):
        Stabilimento.objects.create(nome="Ricengo", sigla="CR", codice_bc=4)
        Stabilimento.objects.create(nome="Altro", sigla="XX", codice_bc=99)

        self._modulo().svuota(django_apps, None)

        self.assertEqual(
            (
                Stabilimento.objects.get(nome="Ricengo").sigla,
                Stabilimento.objects.get(nome="Ricengo").codice_bc,
            ),
            (None, None),
        )
        # Uno stabilimento fuori dall'elenco della migrazione non è toccato.
        altro = Stabilimento.objects.get(nome="Altro")
        self.assertEqual((altro.sigla, altro.codice_bc), ("XX", 99))


class MigrazioneTpiStrutturatoTests(SimpleTestCase):
    """La migrazione dati 0051 converte il vecchio TPI testo libero in (bool, destinatario).

    La forma storica del campo (``tpi_testo``, prima della migrazione) non
    esiste più nel modello corrente: non si può costruire con un
    ``RigaTransmittalInterno`` reale. Le funzioni della migrazione operano
    solo su ``apps.get_model(...).objects.all()`` e ``riga.save(update_fields=...)``,
    quindi bastano dei doppi minimi con quella stessa forma.
    """

    def _modulo(self):
        import importlib

        return importlib.import_module(
            "core.migrations.0051_riga_trasmittal_interno_tpi_strutturato"
        )

    class _RigaFinta:
        def __init__(self, tpi_testo):
            self.tpi_testo = tpi_testo
            self.tpi_destinatario = ""
            self.tpi_bool = False
            self.salvata_con = None

        def save(self, update_fields):
            self.salvata_con = update_fields

    class _AppsFinto:
        def __init__(self, righe):
            self._righe = righe

        def get_model(self, app_label, model_name):
            righe = self._righe

            class _ManagerFinto:
                def all(self):
                    return righe

            return type("RigaTransmittalInternoFinto", (), {"objects": _ManagerFinto()})

    def test_tpi_testo_valorizzato_diventa_tpi_true_col_testo_come_destinatario(self):
        riga = self._RigaFinta(tpi_testo="AI")

        self._modulo().popola_tpi_strutturato(self._AppsFinto([riga]), None)

        self.assertTrue(riga.tpi_bool)
        self.assertEqual(riga.tpi_destinatario, "AI")
        self.assertEqual(riga.salvata_con, ["tpi_destinatario", "tpi_bool"])

    def test_tpi_testo_vuoto_diventa_tpi_false(self):
        riga = self._RigaFinta(tpi_testo="")

        self._modulo().popola_tpi_strutturato(self._AppsFinto([riga]), None)

        self.assertFalse(riga.tpi_bool)
        self.assertEqual(riga.tpi_destinatario, "")

    def test_tpi_testo_solo_spazi_diventa_tpi_false(self):
        riga = self._RigaFinta(tpi_testo="   ")

        self._modulo().popola_tpi_strutturato(self._AppsFinto([riga]), None)

        self.assertFalse(riga.tpi_bool)
        self.assertEqual(riga.tpi_destinatario, "")


class IndirizziPerSitiTests(TestCase):
    """indirizzi_per_siti: TO/CC per un elenco di siti, per il trasmittal interno."""

    def setUp(self):
        self.valbrembo = Stabilimento.objects.create(nome="Valbrembo", codice_bc=1)
        self.albignasego = Stabilimento.objects.create(nome="Albignasego", codice_bc=2)

    def _indirizzo(self, stabilimento, email, tipo, attivo=True):
        return IndirizzoStabilimento.objects.create(
            stabilimento=stabilimento, email=email, tipo=tipo, attivo=attivo
        )

    def test_input_vuoto(self):
        self._indirizzo(self.valbrembo, "a@b.it", TipoIndirizzoStabilimento.TO)

        self.assertEqual(indirizzi_per_siti([]), {"to": [], "cc": []})
        self.assertEqual(indirizzi_per_siti(None), {"to": [], "cc": []})

    def test_codici_inesistenti(self):
        self.assertEqual(indirizzi_per_siti([999]), {"to": [], "cc": []})

    def test_piu_siti_con_indirizzi_sovrapposti(self):
        self._indirizzo(self.valbrembo, "to1@b.it", TipoIndirizzoStabilimento.TO)
        self._indirizzo(self.albignasego, "to2@b.it", TipoIndirizzoStabilimento.TO)
        # Stesso indirizzo su entrambi i siti, maiuscole diverse: un solo TO.
        self._indirizzo(self.valbrembo, "comune@b.it", TipoIndirizzoStabilimento.TO)
        self._indirizzo(self.albignasego, "Comune@B.it", TipoIndirizzoStabilimento.TO)

        risultato = indirizzi_per_siti([1, 2])

        # Deduplica case-insensitive: dei due "comune" ne resta uno solo,
        # qualunque sia la maiuscola/minuscola sopravvissuta.
        self.assertEqual(len(risultato["to"]), 3)
        normalizzati = {e.lower() for e in risultato["to"]}
        self.assertEqual(normalizzati, {"to1@b.it", "to2@b.it", "comune@b.it"})
        self.assertEqual(risultato["cc"], [])

    def test_stesso_indirizzo_in_to_e_cc_compare_solo_in_to(self):
        self._indirizzo(self.valbrembo, "doppio@b.it", TipoIndirizzoStabilimento.TO)
        self._indirizzo(self.albignasego, "DOPPIO@b.it", TipoIndirizzoStabilimento.CC)
        self._indirizzo(self.albignasego, "solo_cc@b.it", TipoIndirizzoStabilimento.CC)

        risultato = indirizzi_per_siti([1, 2])

        self.assertEqual(risultato["to"], ["doppio@b.it"])
        self.assertEqual(risultato["cc"], ["solo_cc@b.it"])

    def test_indirizzi_inattivi_esclusi(self):
        self._indirizzo(self.valbrembo, "attivo@b.it", TipoIndirizzoStabilimento.TO)
        self._indirizzo(self.valbrembo, "inattivo@b.it", TipoIndirizzoStabilimento.TO, attivo=False)

        risultato = indirizzi_per_siti([1])

        self.assertEqual(risultato["to"], ["attivo@b.it"])


class IndirizziDefaultPerSitiTests(TestCase):
    """indirizzi_default_per_siti: TO/CC "sempre in copia" per stabilimento, da admin."""

    def setUp(self):
        self.valbrembo = Stabilimento.objects.create(nome="Valbrembo", codice_bc=1)
        self.albignasego = Stabilimento.objects.create(nome="Albignasego", codice_bc=2)

    def _indirizzo(self, stabilimento, email, tipo, attivo=True):
        return IndirizzoDefaultTrasmittalInterno.objects.create(
            stabilimento=stabilimento, email=email, tipo=tipo, attivo=attivo
        )

    def test_input_vuoto(self):
        self._indirizzo(self.valbrembo, "a@b.it", TipoDestinatarioTransmittalInterno.TO)

        self.assertEqual(indirizzi_default_per_siti([]), {"to": [], "cc": []})
        self.assertEqual(indirizzi_default_per_siti(None), {"to": [], "cc": []})

    def test_sito_senza_indirizzi_default_configurati(self):
        self.assertEqual(indirizzi_default_per_siti([1]), {"to": [], "cc": []})

    def test_solo_il_sito_coinvolto_contribuisce(self):
        self._indirizzo(self.valbrembo, "bg@b.it", TipoDestinatarioTransmittalInterno.CC)
        self._indirizzo(self.albignasego, "pd@b.it", TipoDestinatarioTransmittalInterno.CC)

        risultato = indirizzi_default_per_siti([1])

        self.assertEqual(risultato, {"to": [], "cc": ["bg@b.it"]})

    def test_indirizzo_inattivo_escluso(self):
        self._indirizzo(self.valbrembo, "attivo@b.it", TipoDestinatarioTransmittalInterno.TO)
        self._indirizzo(
            self.valbrembo, "inattivo@b.it", TipoDestinatarioTransmittalInterno.TO, attivo=False
        )

        risultato = indirizzi_default_per_siti([1])

        self.assertEqual(risultato["to"], ["attivo@b.it"])


class DestinazioneDocumentoTests(TestCase):
    """Stabilimenti destinatari della copia cartacea di un documento."""

    def setUp(self):
        self.valbrembo = Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        self.albignasego = Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        self.marghera = Stabilimento.objects.create(nome="Marghera", sigla="VE", codice_bc=3)
        self.milano = Stabilimento.objects.create(nome="Milano")  # senza codice_bc

        testata = Testata.objects.create(job="99001")
        self.doc1 = Documento.objects.create(testata=testata, vendor_doc="99001-DOC1")
        self.doc2 = Documento.objects.create(testata=testata, vendor_doc="99001-DOC2")

    def test_unicita_documento_stabilimento(self):
        DestinazioneDocumento.objects.create(documento=self.doc1, stabilimento=self.valbrembo)

        with self.assertRaises(IntegrityError), transaction.atomic():
            DestinazioneDocumento.objects.create(documento=self.doc1, stabilimento=self.valbrembo)

    def test_clean_rifiuta_uno_stabilimento_senza_codice_bc(self):
        destinazione = DestinazioneDocumento(documento=self.doc1, stabilimento=self.milano)

        with self.assertRaises(ValidationError):
            destinazione.full_clean()

    def test_imposta_destinazioni_sostituisce_e_non_accumula(self):
        imposta_destinazioni(self.doc1, [1, 2])
        self.assertEqual([s.codice_bc for s in siti_del_documento(self.doc1)], [1, 2])

        imposta_destinazioni(self.doc1, [3])

        self.assertEqual([s.codice_bc for s in siti_del_documento(self.doc1)], [3])

    def test_imposta_destinazioni_lista_vuota_azzera(self):
        imposta_destinazioni(self.doc1, [1, 2])

        imposta_destinazioni(self.doc1, [])

        self.assertEqual(siti_del_documento(self.doc1), [])

    def test_siti_del_documento_ordinati_per_codice_bc(self):
        imposta_destinazioni(self.doc1, [3, 1, 2])

        self.assertEqual([s.codice_bc for s in siti_del_documento(self.doc1)], [1, 2, 3])

    def test_siti_coinvolti_deduplica_su_documenti_con_siti_sovrapposti(self):
        imposta_destinazioni(self.doc1, [1, 2])
        imposta_destinazioni(self.doc2, [2, 3])

        risultato = siti_coinvolti([self.doc1, self.doc2])

        self.assertEqual([s.codice_bc for s in risultato], [1, 2, 3])


class ImportDestinazioniUtTests(TestCase):
    """Precompilazione delle destinazioni UT dal vecchio <job>-RecipientsData.txt."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.patcher = patch("django.conf.settings.FILESERVER_JOBS_PATH", self.tmp)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

        Stabilimento.objects.create(nome="Valbrembo", sigla="BG", codice_bc=1)
        Stabilimento.objects.create(nome="Albignasego", sigla="PD", codice_bc=2)
        Stabilimento.objects.create(nome="Marghera", sigla="VE", codice_bc=3)
        Stabilimento.objects.create(nome="Ricengo", sigla="CR", codice_bc=4)
        Stabilimento.objects.create(nome="Schio", sigla="VI", codice_bc=5)

        self.reparto_ut = Reparto.objects.create(nome="Ufficio Tecnico", acronimo="UT")
        self.testata = Testata.objects.create(job="99070")
        self.doc = Documento.objects.create(
            testata=self.testata, vendor_doc="99070-01-ALFA", reparto=self.reparto_ut.nome
        )

    def _scrivi_file(self, job, contenuto):
        cartella = Path(self.tmp) / job / "PROGETTO" / "UT" / "TRANSMITTAL"
        cartella.mkdir(parents=True, exist_ok=True)
        (cartella / f"{job}-RecipientsData.txt").write_text(contenuto, encoding="utf-8")

    # -- leggi_recipients_data --

    def test_file_assente_ritorna_none(self):
        self.assertIsNone(leggi_recipients_data("99070"))

    def test_parsing_righe_valide(self):
        self._scrivi_file("99070", "99070-01-ALFA 11000\n99070-01-BETA 00001\n")

        dati = leggi_recipients_data("99070")

        self.assertEqual(dati, {"99070-01-ALFA": {1, 2}, "99070-01-BETA": {5}})

    def test_righe_malformate_ignorate(self):
        self._scrivi_file(
            "99070",
            "99070-01-ALFA 11000\n"
            "riga senza bitmask\n"
            "99070-01-BETA 999\n"  # non 5 cifre 0/1
            "\n",  # riga vuota
        )

        dati = leggi_recipients_data("99070")

        self.assertEqual(dati, {"99070-01-ALFA": {1, 2}})

    def test_documento_senza_bitmask_ancora_compilato_viene_ignorato_senza_errore(self):
        """Riga con solo il B&R Doc (spazio finale, nessuna cifra): comune nel
        vecchio strumento per un documento mai destinato a nessuno — non è una
        riga malformata."""
        self._scrivi_file(
            "99070",
            "99070-01-ALFA 11000\n"
            "99070-01-BETA \n"  # mai compilata: solo la prima colonna
            "99070-01-GAMMA\n",  # idem, senza nemmeno lo spazio finale
        )

        dati = leggi_recipients_data("99070")

        self.assertEqual(dati, {"99070-01-ALFA": {1, 2}})

    # -- importa_destinazioni_commessa --

    def test_precompila_un_documento_senza_destinazioni(self):
        self._scrivi_file("99070", "99070-01-ALFA 10001\n")

        esito = importa_destinazioni_commessa(self.testata)

        self.assertTrue(esito["trovato"])
        self.assertEqual(esito["precompilati"], ["99070-01-ALFA"])
        self.assertEqual(esito["gia_impostati"], 0)
        self.assertEqual([s.codice_bc for s in siti_del_documento(self.doc)], [1, 5])

    def test_non_tocca_un_documento_gia_impostato(self):
        imposta_destinazioni(self.doc, [3])  # corretto a mano, es. da mcielok
        self._scrivi_file("99070", "99070-01-ALFA 11000\n")  # il vecchio file direbbe altro

        esito = importa_destinazioni_commessa(self.testata)

        self.assertEqual(esito["precompilati"], [])
        self.assertEqual(esito["gia_impostati"], 1)
        self.assertEqual([s.codice_bc for s in siti_del_documento(self.doc)], [3])

    def test_vendor_doc_non_tra_i_documenti_ut_va_in_non_trovati(self):
        self._scrivi_file("99070", "99070-01-ALFA 10000\n99070-01-INESISTENTE 01000\n")

        esito = importa_destinazioni_commessa(self.testata)

        self.assertEqual(esito["non_trovati"], ["99070-01-INESISTENTE"])

    def test_dry_run_non_scrive_nulla(self):
        self._scrivi_file("99070", "99070-01-ALFA 10001\n")

        esito = importa_destinazioni_commessa(self.testata, dry_run=True)

        self.assertEqual(esito["precompilati"], ["99070-01-ALFA"])
        self.assertEqual(siti_del_documento(self.doc), [])

    def test_file_senza_righe_valide_ritorna_trovato_ma_vuoto(self):
        self._scrivi_file("99070", "riga non valida\n")

        esito = importa_destinazioni_commessa(self.testata)

        self.assertTrue(esito["trovato"])
        self.assertEqual(esito["precompilati"], [])

    # -- importa_destinazioni_tutte_le_commesse --

    def test_aggrega_su_piu_commesse_e_salta_quelle_senza_file(self):
        altra = Testata.objects.create(job="99071")
        Documento.objects.create(
            testata=altra, vendor_doc="99071-01-GAMMA", reparto=self.reparto_ut.nome
        )
        self._scrivi_file("99070", "99070-01-ALFA 10001\n")
        # 99071 non ha il file: deve essere solo "controllata", non "con_file".

        report = importa_destinazioni_tutte_le_commesse(jobs=["99070", "99071"])

        self.assertEqual(report["controllate"], 2)
        self.assertEqual(report["con_file"], 1)
        self.assertEqual(report["precompilati"], 1)

    def test_una_commessa_in_errore_non_ferma_le_altre(self):
        altra = Testata.objects.create(job="99071")
        Documento.objects.create(
            testata=altra, vendor_doc="99071-01-GAMMA", reparto=self.reparto_ut.nome
        )
        self._scrivi_file("99070", "99070-01-ALFA 10001\n")
        self._scrivi_file("99071", "99071-01-GAMMA 01000\n")

        with patch(
            "core.services.recipients_import.importa_destinazioni_commessa",
            side_effect=[
                RuntimeError("condivisione irraggiungibile"),
                {
                    "trovato": True,
                    "precompilati": ["99071-01-GAMMA"],
                    "gia_impostati": 0,
                    "non_trovati": [],
                },
            ],
        ):
            report = importa_destinazioni_tutte_le_commesse(jobs=["99070", "99071"])

        self.assertEqual(len(report["errori"]), 1)
        self.assertEqual(report["errori"][0]["job"], "99070")
        self.assertEqual(report["precompilati"], 1)

    def test_esclude_le_commesse_chiuse_di_default(self):
        self.testata.actual_delivery_date = date(2026, 1, 1)
        self.testata.save(update_fields=["actual_delivery_date"])
        self._scrivi_file("99070", "99070-01-ALFA 10001\n")

        report = importa_destinazioni_tutte_le_commesse()

        self.assertEqual(report["controllate"], 0)

        report_tutte = importa_destinazioni_tutte_le_commesse(includi_chiuse=True)

        self.assertEqual(report_tutte["controllate"], 1)
        self.assertEqual(report_tutte["con_file"], 1)
