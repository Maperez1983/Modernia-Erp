import unittest
from io import BytesIO


class TestFincasBankExtractImport(unittest.TestCase):
    def test_parse_csv_basic(self):
        from web.server import parse_fincas_bank_extract

        raw = (
            "FECHA OPERACION;CONCEPTO;IMPORTE;SALDO\n"
            "18/05/2026;Cargo de GENERAL ELEVADORES XXI, S.L.;-193,60;23278,59\n"
            "15/05/2026;Abono de MONICA;70,00;23653,69\n"
        ).encode("utf-8")
        rows = parse_fincas_bank_extract(raw, filename="extracto.csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fecha"], "2026-05-18")
        self.assertAlmostEqual(float(rows[0]["importe"]), -193.6, places=2)
        self.assertEqual(rows[1]["fecha"], "2026-05-15")
        self.assertAlmostEqual(float(rows[1]["importe"]), 70.0, places=2)

    def test_parse_xlsx_basic(self):
        from openpyxl import Workbook
        from web.server import parse_fincas_bank_extract

        wb = Workbook()
        ws = wb.active
        ws.title = "sheet1"
        ws.append(["FECHA OPERACION", "CONCEPTO", "IMPORTE", "SALDO"])
        ws.append(["18/5/2026", "Cargo de GENERAL ELEVADORES XXI, S.L.", -193.6, 23278.59])
        ws.append(["15/5/2026", "Abono de MONICA", 70, 23653.69])
        buf = BytesIO()
        wb.save(buf)
        rows = parse_fincas_bank_extract(buf.getvalue(), filename="extracto.xlsx")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["fecha"], "2026-05-18")
        self.assertAlmostEqual(float(rows[0]["importe"]), -193.6, places=2)

