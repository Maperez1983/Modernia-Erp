import sqlite3
import unittest

import web.server as server


class SegurosKpisVencen30DateParsingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              compania TEXT,
              estado TEXT,
              estado_poliza TEXT,
              poliza_numero TEXT
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_ddmmyyyy_vencimiento_is_counted_in_range(self):
        # En el entorno de tests puede existir DATABASE_URL; forzamos modo SQLite
        # para que las expresiones usen GLOB/SUBSTR en vez de regex (~).
        server.db_is_postgres_enabled = lambda: False

        # 2026-06-01 está dentro de 30 días desde 2026-05-02.
        self.conn.execute(
            """
            INSERT INTO seguros (id, empresa_id, fecha_efecto, fecha_vencimiento, compania, estado, estado_poliza, poliza_numero)
            VALUES ('s1', 'e1', '01/06/2025', '01/06/2026', 'REALE', 'En vigor', '', 'P-1')
            """
        )
        in_vigor_expr = server.in_vigor_policy_filter("s")
        fecha_efecto_date = server.seguro_date_sql("fecha_efecto", "s")
        fecha_venc_raw_date = server.seguro_date_sql("fecha_vencimiento", "s")
        fecha_venc_expr = (
            f"COALESCE({fecha_venc_raw_date}, "
            f"CASE WHEN {fecha_efecto_date} IS NOT NULL THEN DATE({fecha_efecto_date}, '+1 year') ELSE NULL END)"
        )
        count = self.conn.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM seguros s
            WHERE s.empresa_id = 'e1'
              AND {in_vigor_expr}
              AND {fecha_venc_expr} IS NOT NULL
              AND DATE({fecha_venc_expr}) BETWEEN DATE('2026-05-02') AND DATE('2026-05-02','+30 days')
            """
        ).fetchone()["total"]
        self.assertEqual(int(count), 1)


if __name__ == "__main__":
    unittest.main()

