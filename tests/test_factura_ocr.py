import unittest

from web.server import build_invoice_asiento, parse_invoice_text


class FacturaOcrTests(unittest.TestCase):
    def test_parse_invoice_basic_amounts(self):
        text = """
        FACTURA Nº F-2026/14
        Fecha: 05/03/2026
        Proveedor: Servicios Málaga SL
        NIF: B12345678
        Base imponible: 100,00
        IVA 21%: 21,00
        Total factura: 121,00
        """
        parsed = parse_invoice_text(text)
        self.assertEqual(parsed["numero"], "F-2026/14")
        self.assertEqual(parsed["fecha"], "2026-03-05")
        self.assertEqual(parsed["nif"], "B12345678")
        self.assertAlmostEqual(parsed["base_imponible"], 100.0)
        self.assertAlmostEqual(parsed["cuota_iva"], 21.0)
        self.assertAlmostEqual(parsed["total"], 121.0)

    def test_build_asiento_compra_balances(self):
        parsed = {
            "tipo": "compra",
            "base_imponible": 100.0,
            "cuota_iva": 21.0,
            "cuota_irpf": 0.0,
            "total": 121.0,
            "descripcion": "Factura prueba",
            "iva_pct": 21.0,
        }
        lines, debe, haber = build_invoice_asiento(parsed, "400")
        self.assertEqual(len(lines), 3)
        self.assertAlmostEqual(debe, 121.0)
        self.assertAlmostEqual(haber, 121.0)


if __name__ == "__main__":
    unittest.main()

