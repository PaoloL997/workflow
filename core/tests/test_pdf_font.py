"""Ricerca dei font TrueType Unicode usati dai PDF (``src.pdf``)."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from fpdf import FPDF

from src import pdf as pdf_mod

_ARIAL = ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf")
_LIBERATION = (
    "LiberationSans-Regular.ttf",
    "LiberationSans-Bold.ttf",
    "LiberationSans-Italic.ttf",
    "LiberationSans-BoldItalic.ttf",
)
_DEJAVU = (
    "DejaVuSans.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans-Oblique.ttf",
    "DejaVuSans-BoldOblique.ttf",
)


class TrovaFontUnicodeTest(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rimuovi_tmp)

    def _rimuovi_tmp(self):
        for f in self.tmp.iterdir():
            f.unlink()
        self.tmp.rmdir()

    def _crea(self, *nomi):
        for nome in nomi:
            (self.tmp / nome).touch()

    def test_nessun_font_installato_ripiega_su_helvetica(self):
        with patch.object(pdf_mod, "_FONT_DIRS", (self.tmp, self.tmp / "assente")):
            self.assertIsNone(pdf_mod._trova_font_unicode())
            with patch.object(FPDF, "add_font") as add_font:
                self.assertEqual(pdf_mod._register_unicode_font(FPDF(), "X"), "Helvetica")
            add_font.assert_not_called()

    def test_preferisce_arial_se_presente(self):
        self._crea(*_ARIAL, *_DEJAVU)
        with patch.object(pdf_mod, "_FONT_DIRS", (self.tmp,)):
            paths = pdf_mod._trova_font_unicode()
        self.assertEqual(paths[""], self.tmp / "arial.ttf")
        self.assertEqual(paths["BI"], self.tmp / "arialbi.ttf")

    def test_usa_liberation_sans_quando_arial_manca(self):
        self._crea(*_LIBERATION, *_DEJAVU)
        with patch.object(pdf_mod, "_FONT_DIRS", (self.tmp,)):
            paths = pdf_mod._trova_font_unicode()
        self.assertEqual(paths[""], self.tmp / "LiberationSans-Regular.ttf")

    def test_usa_dejavu_sans_quando_arial_e_liberation_mancano(self):
        self._crea(*_DEJAVU)
        with patch.object(pdf_mod, "_FONT_DIRS", (self.tmp,)):
            paths = pdf_mod._trova_font_unicode()
        self.assertEqual(set(paths), {"", "B", "I", "BI"})
        self.assertEqual(paths["B"], self.tmp / "DejaVuSans-Bold.ttf")

    def test_famiglia_incompleta_viene_scartata(self):
        # Manca il corsivo di Arial: Arial non basta, DejaVu completo vince.
        self._crea("arial.ttf", "arialbd.ttf", *_DEJAVU)
        with patch.object(pdf_mod, "_FONT_DIRS", (self.tmp,)):
            self.assertEqual(pdf_mod._trova_font_unicode()[""], self.tmp / "DejaVuSans.ttf")
            # Con i soli stili richiesti dalla situazione documenti Arial è sufficiente.
            self.assertEqual(
                pdf_mod._trova_font_unicode(styles=("", "B"))[""], self.tmp / "arial.ttf"
            )

    def test_register_registra_tutti_gli_stili_richiesti(self):
        self._crea(*_ARIAL)
        with (
            patch.object(pdf_mod, "_FONT_DIRS", (self.tmp,)),
            patch.object(FPDF, "add_font") as add_font,
        ):
            self.assertEqual(pdf_mod._register_unicode_font(FPDF(), "Fam", styles=("", "B")), "Fam")
        self.assertEqual(
            [c.args for c in add_font.call_args_list],
            [("Fam", "", str(self.tmp / "arial.ttf")), ("Fam", "B", str(self.tmp / "arialbd.ttf"))],
        )


class PdfCaratteriUnicodeTest(SimpleTestCase):
    def test_testo_fuori_latin1_con_font_unicode(self):
        if pdf_mod._trova_font_unicode() is None:
            self.skipTest("Nessun font TrueType Unicode installato su questa macchina")
        doc = FPDF()
        doc.add_page()
        family = pdf_mod._register_unicode_font(doc, "TestUni")
        self.assertNotEqual(family, "Helvetica")
        doc.set_font(family, "", 10)
        # Con Helvetica questi caratteri solleverebbero FPDFUnicodeEncodingException.
        doc.cell(60, 5, "Other recipients… → — €")
        self.assertTrue(doc.output())
