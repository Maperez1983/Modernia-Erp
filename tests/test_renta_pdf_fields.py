import unittest


from web.server import _parse_renta_pdf_fields


class RentaPdfFieldsTests(unittest.TestCase):
    def test_extracts_casilla_505_when_code_before_amount(self):
        text = "MODELO 100\n0505 12.345,67\n"
        out = _parse_renta_pdf_fields(text)
        self.assertAlmostEqual(out.get("casilla_505") or 0.0, 12345.67, places=2)

    def test_extracts_casilla_505_when_code_without_leading_zero(self):
        text = "MODELO 100\n12.345,67 505\n"
        out = _parse_renta_pdf_fields(text)
        self.assertAlmostEqual(out.get("casilla_505") or 0.0, 12345.67, places=2)

