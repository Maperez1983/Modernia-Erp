import sqlite3
import unittest

from web.server import parse_services_param, service_sql_match_clause


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

    def test_gestoria_service_sql_matches_accented_and_plain_labels(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE clientes_empresas (servicio TEXT)")
        conn.executemany(
            "INSERT INTO clientes_empresas (servicio) VALUES (?)",
            [("Gestoría",), ("gestoria",), ("Seguros",)],
        )
        clause, values = service_sql_match_clause("ce", ["gestoria"])
        rows = conn.execute(
            f"SELECT servicio FROM clientes_empresas ce WHERE {clause} ORDER BY servicio",
            values,
        ).fetchall()
        self.assertEqual([row[0] for row in rows], ["Gestoría", "gestoria"])


if __name__ == "__main__":
    unittest.main()
