import sqlite3
import unittest

from web.server import (
    build_hipoteca_fixed_cost_entries,
    build_hipoteca_accounting_entries,
    delete_gestoria_contabilidad_record,
    delete_hipoteca_record,
    derive_hipoteca_commissions,
    maybe_promote_study_hipoteca_accounting,
    resolve_hipoteca_contabilidad_link,
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

    def test_sync_creates_only_expected_auto_entries(self):
        sync_hipotecas_contabilidad_entries(self.conn, "e1", now="2026-03-24T10:00:00+00:00")

        rows = self.conn.execute(
            """
            SELECT gestion, tipo, importe
            FROM gestoria_contabilidad
            WHERE hipoteca_id = 'h1'
            ORDER BY gestion
            """
        ).fetchall()
        gestiones = [row["gestion"] for row in rows]

        self.assertEqual(
            gestiones,
            ["Cesión Juan", "Cesión a inmobiliarias", "Comisión cliente"],
        )
        self.assertNotIn("Cesión banco", gestiones)

        totals = {row["gestion"]: row["importe"] for row in rows}
        self.assertEqual(totals["Comisión cliente"], 100.0)
        self.assertEqual(totals["Cesión Juan"], 20.0)
        self.assertEqual(totals["Cesión a inmobiliarias"], 20.0)

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

    def test_derive_hipoteca_commissions_applies_bonus_office(self):
        split = derive_hipoteca_commissions(100.0, "Modernia Norte")
        self.assertEqual(split["comision_juan"], 20.0)
        self.assertEqual(split["cesion"], 25.0)
        self.assertEqual(split["comision_modernia"], 55.0)

    def test_build_hipoteca_accounting_entries_does_not_autogenerate_cesion_banco(self):
        row = self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone()
        entries = build_hipoteca_accounting_entries(dict(row))
        gestiones = {item["gestion"] for item in entries}
        self.assertNotIn("Cesión banco", gestiones)
        self.assertIn("Comisión cliente", gestiones)
        self.assertIn("Cesión Juan", gestiones)
        self.assertIn("Cesión a inmobiliarias", gestiones)

    def test_build_hipoteca_accounting_entries_skips_cesion_costs_for_particulares(self):
        row = dict(self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone())
        row["oficina"] = "PARTICULARES"
        entries = build_hipoteca_accounting_entries(row)

        self.assertEqual([item["gestion"] for item in entries], ["Comisión cliente"])

    def test_build_hipoteca_accounting_entries_derives_missing_split_from_total(self):
        row = dict(self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone())
        row["oficina"] = "CASA AXARQUIA"
        row["comision"] = 2500.0
        row["comision_juan"] = None
        row["comision_modernia"] = None
        row["cesion"] = None

        entries = build_hipoteca_accounting_entries(row)
        totals = {item["gestion"]: item["importe"] for item in entries}

        self.assertEqual(totals["Comisión cliente"], 2500.0)
        self.assertEqual(totals["Cesión Juan"], 500.0)
        self.assertEqual(totals["Cesión a inmobiliarias"], 500.0)

    def test_build_hipoteca_accounting_entries_uses_fecha_encargo_for_indemnizacion_without_signature(self):
        row = dict(self.conn.execute("SELECT * FROM hipotecas WHERE id = 'h1'").fetchone())
        row["estado"] = "INDEMNIZACIÓN"
        row["fecha_firma"] = ""
        row["fecha_encargo"] = "2025-01-15"

        entries = build_hipoteca_accounting_entries(row)

        self.assertTrue(entries)
        self.assertTrue(all(item["fecha"] == "2025-01-15" for item in entries))

    def test_build_hipoteca_fixed_cost_entries_generates_monthly_and_annual_costs(self):
        entries = build_hipoteca_fixed_cost_entries(now="2025-10-15T10:00:00+00:00")

        self.assertEqual(len(entries), 38)
        self.assertEqual(entries[0]["gestion"], "Nómina Juan")
        self.assertEqual(entries[0]["fecha"], "2024-05-01")
        self.assertEqual(entries[1]["gestion"], "Gestoría")
        self.assertIn(
            ("2024-10-01", "Seguro anual", 502.26),
            {(item["fecha"], item["gestion"], item["importe"]) for item in entries},
        )
        self.assertIn(
            ("2025-10-01", "Seguro anual", 502.26),
            {(item["fecha"], item["gestion"], item["importe"]) for item in entries},
        )

    def test_promoting_study_hipoteca_creates_auto_indemnizacion_entries(self):
        self.conn.execute(
            """
            INSERT INTO hipotecas (
              id, empresa_id, cliente, banco, fecha_encargo, comision, cesion, comision_juan, comision_modernia,
              estado, anio, created_at, updated_at
            ) VALUES (
              'h2', 'e1', 'Cliente Dos', 'Banco Dos', '2025-03-12', 90.0, 18.0, 18.0, 54.0,
              'ESTUDIO', 2025, '2026-03-24', '2026-03-24'
            )
            """
        )
        self.conn.commit()

        changed = maybe_promote_study_hipoteca_accounting(
            self.conn,
            "e1",
            "h2",
            {"fecha": "2025-03-18", "tipo": "Ingreso", "gestion": "Comisión cliente"},
            now="2026-03-24T10:00:00+00:00",
        )

        self.assertTrue(changed)
        row = self.conn.execute("SELECT estado, fecha_firma FROM hipotecas WHERE id = 'h2'").fetchone()
        self.assertEqual(row["estado"], "INDEMNIZACIÓN")
        self.assertEqual(row["fecha_firma"], "2025-03-18")

        entries = self.conn.execute(
            """
            SELECT gestion, tipo, importe
            FROM gestoria_contabilidad
            WHERE hipoteca_id = 'h2'
            ORDER BY gestion
            """
        ).fetchall()
        self.assertEqual([item["gestion"] for item in entries], ["Cesión Juan", "Cesión a inmobiliarias", "Comisión cliente"])

    def test_resolve_hipoteca_contabilidad_link_supports_legacy_schema_without_cliente_id(self):
        legacy = sqlite3.connect(":memory:")
        legacy.row_factory = sqlite3.Row
        legacy.executescript(
            """
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              banco TEXT,
              fecha_firma TEXT
            );
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              created_at TEXT
            );
            INSERT INTO hipotecas (id, empresa_id, cliente, banco, fecha_firma)
            VALUES ('h1', 'e1', 'Cliente Uno', 'Banco Test', '2025-02-10');
            INSERT INTO clientes (id, nombre, created_at)
            VALUES ('c1', 'Cliente Uno', '2026-03-24');
            """
        )
        try:
            link = resolve_hipoteca_contabilidad_link(legacy, "h1")
        finally:
            legacy.close()

        self.assertEqual(link["cliente"], "Cliente Uno")
        self.assertEqual(link["banco"], "Banco Test")
        self.assertEqual(link["fecha_firma"], "2025-02-10")
        self.assertEqual(link["cliente_id"], "c1")


if __name__ == "__main__":
    unittest.main()
