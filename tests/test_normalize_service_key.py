import unittest

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

