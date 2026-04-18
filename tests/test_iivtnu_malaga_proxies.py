import sqlite3
import unittest

import web.server as server


class IivtnuMalagaProxySeedTests(unittest.TestCase):
    def test_seed_malaga_fills_missing_years_with_proxy(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        server.ensure_iivtnu_schema(conn)

        prev_postal = server._IIVTNU_POSTAL_CACHE
        prev_tipo = server._IIVTNU_TIPO_GRAVAMEN_MALAGA_CACHE
        try:
            server._IIVTNU_POSTAL_CACHE = {
                "cp_to": {},
                "ine_to": {
                    "29016": "Árchez",
                    "29024": "Benalauría",
                    "29067": "Málaga",
                },
                "prov_to": {
                    "29016": "Málaga",
                    "29024": "Málaga",
                    "29067": "Málaga",
                },
            }
            server._IIVTNU_TIPO_GRAVAMEN_MALAGA_CACHE = {
                "years": {
                    "2024": {
                        "29024": 30.0,
                        "29067": 29.0,
                    },
                    "2025": {
                        "29016": 30.0,
                        "29067": 29.0,
                    },
                },
                "source": {
                    "2024": {"label": "OTA 2024", "url": "https://ota.example/2024.xlsx"},
                    "2025": {"label": "OTA 2025", "url": "https://ota.example/2025.xlsx"},
                },
            }

            server._iivtnu_seed_malaga(conn, now_iso="2026-01-01T00:00:00+00:00")

            # 2025 missing 29024 -> debe coger 2024 como proxy
            row_2025 = conn.execute(
                """
                SELECT tipo_gravamen_pct, source_label
                FROM iivtnu_param_sets
                WHERE municipio_ine = '29024' AND vigente_desde = '2025-01-01' AND vigente_hasta = '2025-12-31'
                """,
            ).fetchone()
            self.assertIsNotNone(row_2025)
            self.assertAlmostEqual(float(row_2025["tipo_gravamen_pct"]), 30.0, places=6)
            self.assertIn("proxy para 2025", str(row_2025["source_label"]))

            # 2024 missing 29016 -> debe coger 2025 como proxy
            row_2024 = conn.execute(
                """
                SELECT tipo_gravamen_pct, source_label
                FROM iivtnu_param_sets
                WHERE municipio_ine = '29016' AND vigente_desde = '2024-01-01' AND vigente_hasta = '2024-12-31'
                """,
            ).fetchone()
            self.assertIsNotNone(row_2024)
            self.assertAlmostEqual(float(row_2024["tipo_gravamen_pct"]), 30.0, places=6)
            self.assertIn("proxy para 2024", str(row_2024["source_label"]))
        finally:
            server._IIVTNU_POSTAL_CACHE = prev_postal
            server._IIVTNU_TIPO_GRAVAMEN_MALAGA_CACHE = prev_tipo

