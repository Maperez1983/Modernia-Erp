import sqlite3
import unittest
from datetime import datetime, timedelta

from web.server import upsert_seguro_comision_contabilidad


class SegurosContabilidadSyncTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              estado TEXT,
              estado_poliza TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              poliza_numero TEXT,
              comision TEXT
            );

            CREATE TABLE gestoria_contabilidad (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_ids_json TEXT,
              seguro_id TEXT,
              hipoteca_id TEXT,
              poliza_numero TEXT,
              fecha TEXT,
              concepto TEXT,
              gestion TEXT,
              tipo TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_upserts_when_estado_is_contratado_but_dates_make_it_en_vigor(self):
        today = datetime.now().date()
        fecha_efecto = (today - timedelta(days=30)).isoformat()
        self.conn.execute(
            """
            INSERT INTO seguros (id, empresa_id, cliente_id, estado, estado_poliza, fecha_efecto, fecha_vencimiento, poliza_numero, comision)
            VALUES ('s1', 'e1', 'c1', 'Contratado', 'activa', ?, '', '', '123,45')
            """,
            (fecha_efecto,),
        )
        row = self.conn.execute("SELECT * FROM seguros WHERE id = 's1'").fetchone()
        cont_id = upsert_seguro_comision_contabilidad(self.conn, row, now="2026-04-08T10:00:00Z", movimiento="emision")
        self.assertTrue(cont_id)
        saved = self.conn.execute("SELECT * FROM gestoria_contabilidad WHERE seguro_id = 's1'").fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(saved["empresa_id"], "e1")
        self.assertEqual(saved["cliente_id"], "c1")
        self.assertEqual(saved["tipo"], "Ingreso")

    def test_skips_when_fecha_efecto_is_in_future(self):
        today = datetime.now().date()
        fecha_efecto = (today + timedelta(days=30)).isoformat()
        self.conn.execute(
            """
            INSERT INTO seguros (id, empresa_id, cliente_id, estado, estado_poliza, fecha_efecto, fecha_vencimiento, poliza_numero, comision)
            VALUES ('s2', 'e1', 'c1', 'Contratado', 'activa', ?, '', '', '200')
            """,
            (fecha_efecto,),
        )
        row = self.conn.execute("SELECT * FROM seguros WHERE id = 's2'").fetchone()
        cont_id = upsert_seguro_comision_contabilidad(self.conn, row, now="2026-04-08T10:00:00Z", movimiento="emision")
        self.assertIsNone(cont_id)
        saved = self.conn.execute("SELECT COUNT(*) AS n FROM gestoria_contabilidad WHERE seguro_id = 's2'").fetchone()
        self.assertEqual(saved["n"], 0)


if __name__ == "__main__":
    unittest.main()

