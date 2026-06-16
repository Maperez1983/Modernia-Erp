import sys
import types
import unittest

if "PIL" not in sys.modules:
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageEnhance = object()
    pil_stub.ImageFilter = object()
    pil_stub.ImageFont = object()
    pil_stub.ImageOps = object()
    sys.modules["PIL"] = pil_stub

from web.server import normalize_service_key


class NormalizeServiceKeyTests(unittest.TestCase):
    def test_maps_long_fincas_labels(self):
        self.assertEqual(normalize_service_key("Fincas Velazquez"), "fincas")
        self.assertEqual(normalize_service_key("Administración de fincas - Velazquez"), "fincas")
        self.assertEqual(normalize_service_key("Admin de fincas · Velazquez"), "fincas")

    def test_maps_long_financiaciones_labels(self):
        self.assertEqual(normalize_service_key("Financiaciones Modernia"), "financiaciones")
        self.assertEqual(normalize_service_key("Hipotecas Modernia"), "financiaciones")
        self.assertEqual(normalize_service_key("LCCI Hipotecas"), "financiaciones")

    def test_maps_other_service_keywords(self):
        self.assertEqual(normalize_service_key("Gestoría - Renta"), "gestoria")
        self.assertEqual(normalize_service_key("Seguros Hogar"), "seguros")
        self.assertEqual(normalize_service_key("Inmobiliaria Ventas"), "inmobiliaria")


if __name__ == "__main__":
    unittest.main()
