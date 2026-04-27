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

    def test_extracts_casillas_map(self):
        text = "MODELO 100\n0432 21.624,24\n0670 -518,61\n0505 21.624,24\n"
        out = _parse_renta_pdf_fields(text)
        casillas = out.get("casillas") or {}
        self.assertEqual(casillas.get("0432"), 21624.24)
        self.assertEqual(casillas.get("0505"), 21624.24)
        self.assertEqual(casillas.get("0670"), -518.61)

    def test_extracts_casilla_505_with_ocr_letter_o(self):
        text = "MODELO 100\n12.345,67 [o505]\n"
        out = _parse_renta_pdf_fields(text)
        self.assertAlmostEqual(out.get("casilla_505") or 0.0, 12345.67, places=2)

    def test_extracts_base_imponible_and_resultado(self):
        text = "MODELO 100\n0432 21.624,24\n0670 -518,61\n"
        out = _parse_renta_pdf_fields(text)
        self.assertAlmostEqual(out.get("base_imponible_general") or 0.0, 21624.24, places=2)
        self.assertAlmostEqual(out.get("resultado_declaracion") or 0.0, -518.61, places=2)
