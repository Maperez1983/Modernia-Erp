import sqlite3
import unittest

from web.server import (
    delete_gestoria_contabilidad_record,
    delete_hipoteca_record,
    sync_hipotecas_contabilidad_entries,
)


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
              cliente_id TEXT,
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
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              created_at TEXT
            );
            CREATE TABLE gestoria_contabilidad (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_ids_json TEXT,
              hipoteca_id TEXT,
              seguro_id TEXT,
              poliza_numero TEXT,
              fecha TEXT,
              concepto TEXT,
              gestion TEXT,
              tipo TEXT,
              importe REAL,
              notas TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE hipotecas_contabilidad_excluidas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              hipoteca_id TEXT NOT NULL,
              fecha TEXT NOT NULL,
              gestion TEXT NOT NULL,
              created_at TEXT NOT NULL,
              UNIQUE (empresa_id, hipoteca_id, fecha, gestion)
            );
            """
        )
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, banco, fecha_firma, comision, cesion, comision_juan, comision_modernia,
              estado, anio, created_at, updated_at
            ) VALUES (
              'h1', 'e1', 'Cliente Uno', 'Banco Test', '2025-02-10', 100.0, 20.0, 20.0, 60.0,
              'FIRMADA', 2025, '2026-03-24', '2026-03-24'
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

    def test_deleted_auto_hipoteca_entry_is_not_recreated_by_sync(self):
        sync_hipotecas_contabilidad_entries(self.conn, "e1", now="2026-03-24T10:00:00+00:00")
        row = self.conn.execute(
            """
            SELECT id
            FROM gestoria_contabilidad
            WHERE hipoteca_id = 'h1' AND fecha = '2025-02-10' AND gestion = 'Comisión cliente'
            """
        ).fetchone()
        self.assertIsNotNone(row)

        deleted = delete_gestoria_contabilidad_record(self.conn, row["id"], now="2026-03-24T10:05:00+00:00")
        self.assertTrue(deleted)

        sync_hipotecas_contabilidad_entries(self.conn, "e1", now="2026-03-24T10:10:00+00:00")

        recreated = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM gestoria_contabilidad
            WHERE hipoteca_id = 'h1' AND fecha = '2025-02-10' AND gestion = 'Comisión cliente'
            """
        ).fetchone()["total"]
        self.assertEqual(recreated, 0)

        exclusion = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM hipotecas_contabilidad_excluidas
            WHERE empresa_id = 'e1' AND hipoteca_id = 'h1' AND fecha = '2025-02-10' AND gestion = 'Comisión cliente'
            """
        ).fetchone()["total"]
        self.assertEqual(exclusion, 1)

    def test_sync_does_not_create_entries_for_non_closed_status_even_with_signature_date(self):
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, banco, fecha_firma, comision, cesion, comision_juan, comision_modernia,
              estado, anio, created_at, updated_at
            ) VALUES (
              'h2', 'e1', 'Cliente Dos', 'Banco Test', '2025-03-12', 90.0, 10.0, 18.0, 62.0,
              'ESTUDIO', 2025, '2026-03-24', '2026-03-24'
            )
            """
        )
        self.conn.commit()

        sync_hipotecas_contabilidad_entries(self.conn, "e1", now="2026-03-24T10:00:00+00:00")

        count = self.conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM gestoria_contabilidad
            WHERE hipoteca_id = 'h2'
            """
        ).fetchone()["total"]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
