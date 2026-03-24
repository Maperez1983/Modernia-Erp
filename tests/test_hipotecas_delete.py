import sqlite3
import unittest

from web.server import delete_hipoteca_record


class HipotecasDeleteTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              banco TEXT,
              precio REAL,
              importe_hipoteca REAL,
              porcentaje REAL,
              entrada REAL,
              comision REAL,
              oficina TEXT,
              fecha_encargo TEXT,
              encargo TEXT,
              tipo_hipoteca TEXT,
              fecha_firma TEXT,
              cesion REAL,
              comision_juan REAL,
              comision_modernia REAL,
              inmobiliaria_compra TEXT,
              asesor TEXT,
              estado TEXT,
              anio INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, estado, anio, created_at, updated_at
            ) VALUES (
              'h1', 'e1', 'Cliente Uno', 'FIRMADA', 2025, '2026-03-24', '2026-03-24'
            )
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_delete_existing_hipoteca(self):
        deleted = delete_hipoteca_record(self.conn, "h1")
        self.assertTrue(deleted)
        count = self.conn.execute("SELECT COUNT(*) FROM hipotecas WHERE id = 'h1'").fetchone()[0]
        self.assertEqual(count, 0)

    def test_delete_missing_hipoteca_returns_false(self):
        deleted = delete_hipoteca_record(self.conn, "missing")
        self.assertFalse(deleted)
        count = self.conn.execute("SELECT COUNT(*) FROM hipotecas").fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
