import unittest

from web.server import parse_services_param


class ServiceParsingTests(unittest.TestCase):
    def test_admin_de_fincas_expands_to_fincas(self):
        services = parse_services_param("Admin de fincas")
        self.assertIn("admin de fincas", services)
        self.assertIn("fincas", services)

    def test_fincas_expands_to_administracion_de_fincas(self):
        services = parse_services_param("fincas")
        self.assertIn("fincas", services)
        # Compat: algunos flujos históricos guardan "Administración de fincas" en vez de "fincas".
        self.assertTrue(
            ("administración de fincas" in services) or ("administracion de fincas" in services)
        )


if __name__ == "__main__":
    unittest.main()

