import unittest

from scripts.import_rentas_2024_to_crm import (
    looks_like_nif,
    normalize_nif_candidate,
    parse_date_ddmmyyyy,
    parse_money,
)


class RentasOcrNormalizationTests(unittest.TestCase):
    def test_normalize_nif_dni(self):
        self.assertEqual(normalize_nif_candidate("12345678Z"), "12345678Z")
        self.assertTrue(looks_like_nif("12345678Z"))

    def test_normalize_nif_cif_keeps_prefix(self):
        # OCR: "O" -> "0" pero el prefijo CIF "B" debe mantenerse.
        self.assertEqual(normalize_nif_candidate("B12O4567B"), "B1204567B")
        self.assertTrue(looks_like_nif("B12O4567B"))

    def test_parse_date_handles_ocr_confusions(self):
        self.assertEqual(parse_date_ddmmyyyy("0I/0S/2O26"), "2026-05-01")

    def test_parse_money_handles_ocr_confusions(self):
        self.assertEqual(parse_money("1.OOO,00"), 1000.0)
        self.assertEqual(parse_money("52B,10"), 528.1)


if __name__ == "__main__":
    unittest.main()

