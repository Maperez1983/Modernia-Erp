import sqlite3
import unittest

from web.server import (
    compute_seguros_contabilidad_totals,
    resolve_seguro_contabilidad_link,
    upsert_seguro_comision_contabilidad,
)


class SegurosContabilidadTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              poliza_numero TEXT
            );
            CREATE TABLE gestoria_contabilidad (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              cliente_ids_json TEXT,
              seguro_id TEXT,
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
        self.conn.execute(
            """
            INSERT INTO seguros (id, cliente_id, poliza_numero)
            VALUES ('s1', 'c1', 'POL-001')
            """
        )
        self.now = "2026-03-10T10:00:00+00:00"
        self.seguro = {
            "id": "s1",
            "empresa_id": "e1",
            "cliente_id": "c1",
            "poliza_numero": "POL-001",
            "fecha_efecto": "2026-01-15",
            "comision": 120.5,
        }

    def tearDown(self):
        self.conn.close()

    def test_emision_creates_single_entry_and_updates_amount(self):
        first_id = upsert_seguro_comision_contabilidad(self.conn, self.seguro, self.now, movimiento="emision")
        self.assertTrue(first_id)

        self.seguro["comision"] = 150.0
        second_id = upsert_seguro_comision_contabilidad(self.conn, self.seguro, self.now, movimiento="emision")
        self.assertEqual(first_id, second_id)

        row = self.conn.execute("SELECT * FROM gestoria_contabilidad WHERE id = ?", (first_id,)).fetchone()
        self.assertEqual(row["fecha"], "2026-01-15")
        self.assertEqual(row["gestion"], "Comisión emisión")
        self.assertEqual(row["tipo"], "Ingreso")
        self.assertAlmostEqual(float(row["importe"] or 0), 150.0, places=2)
        self.assertEqual(row["cliente_ids_json"], '["c1"]')

        total = self.conn.execute("SELECT COUNT(*) AS n FROM gestoria_contabilidad").fetchone()["n"]
        self.assertEqual(total, 1)

    def test_renovacion_creates_entry_by_date_and_is_idempotent(self):
        first_id = upsert_seguro_comision_contabilidad(
            self.conn,
            self.seguro,
            self.now,
            movimiento="renovacion",
            fecha="2027-01-15",
        )
        second_id = upsert_seguro_comision_contabilidad(
            self.conn,
            self.seguro,
            self.now,
            movimiento="renovacion",
            fecha="2027-01-15",
        )
        self.assertEqual(first_id, second_id)

        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM gestoria_contabilidad WHERE gestion = 'Comisión renovación'"
        ).fetchone()["n"]
        self.assertEqual(count, 1)

    def test_renovacion_and_emision_are_separate_entries(self):
        emision_id = upsert_seguro_comision_contabilidad(self.conn, self.seguro, self.now, movimiento="emision")
        renovacion_id = upsert_seguro_comision_contabilidad(
            self.conn,
            self.seguro,
            self.now,
            movimiento="renovacion",
            fecha="2027-01-15",
        )
        self.assertNotEqual(emision_id, renovacion_id)

        count = self.conn.execute("SELECT COUNT(*) AS n FROM gestoria_contabilidad").fetchone()["n"]
        self.assertEqual(count, 2)

    def test_resolve_seguro_contabilidad_link_returns_policy_and_client(self):
        poliza_numero, cliente_id = resolve_seguro_contabilidad_link(self.conn, "s1")
        self.assertEqual(poliza_numero, "POL-001")
        self.assertEqual(cliente_id, "c1")

    def test_compute_seguros_contabilidad_totals_parses_text_amounts_and_accents(self):
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad (
              id, empresa_id, cliente_id, fecha, concepto, gestion, tipo, importe, notas
            ) VALUES (
              'm1', 'e1', 'c1', '2026-01-20', 'Liq ene', 'Comisión emisión', 'Ingreso', '17,59 €', ''
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad (
              id, empresa_id, cliente_id, fecha, concepto, gestion, tipo, importe, notas
            ) VALUES (
              'm2', 'e1', 'c1', '2026-01-21', 'Extorno', 'Extorno', 'Gasto', '2,10', ''
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_contabilidad (
              id, empresa_id, cliente_id, fecha, concepto, gestion, tipo, importe, notas
            ) VALUES (
              'm3', 'e1', 'c1', '2026-02-02', 'No seguros', 'Fiscal', 'Ingreso', '999,00', 'otro módulo'
            )
            """
        )
        totals = compute_seguros_contabilidad_totals(self.conn, "e1", year="2026")
        self.assertAlmostEqual(totals["ingresos"], 17.59, places=2)
        self.assertAlmostEqual(totals["gastos"], 2.10, places=2)


if __name__ == "__main__":
    unittest.main()
