import io

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from ..models import Documento, Permesso, Testata
from ._fixtures import User


def _xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(
        "docs.xlsx",
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


class ImportDocumentiExcelTest(TestCase):
    def setUp(self):
        self.client = Client()
        user = User.objects.create_user(
            "imp_user", "imp@example.com", "pw", permesso=Permesso.WRITING
        )
        self.client.force_login(user)
        self.testata = Testata.objects.create(job="IMP-01", client="C")
        self.url = f"/api/commesse/{self.testata.job}/import-excel/"

    def test_valore_troppo_lungo_riporta_messaggio_di_validazione(self):
        res = self.client.post(
            self.url,
            {"file": _xlsx([["Item", "Document title"], ["1", "x" * 301], ["2", "ok"]])},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["created"], 1)
        self.assertEqual(len(data["errors"]), 1)
        self.assertIn("Riga 2:", data["errors"][0])
        self.assertIn("300", data["errors"][0])
        self.assertEqual(Documento.objects.filter(testata=self.testata).count(), 1)
