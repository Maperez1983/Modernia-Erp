import sqlite3
import unittest

from web.server import (
    OPENPYXL_AVAILABLE,
    build_hipotecas_firmadas_excel_workbook,
    build_hipoteca_fixed_cost_entries,
    build_hipoteca_accounting_entries,
    collect_gestoria_renta_card_items,
    compute_gestoria_dashboard_segmentacion_trabajos,
    collect_hipotecas_firmadas_export_rows,
    delete_gestoria_contabilidad_record,
    delete_hipoteca_record,
    derive_hipoteca_commissions,
    is_gestoria_dashboard_active_state,
    maybe_promote_study_hipoteca_accounting,
    resolve_hipoteca_contabilidad_link,
    sanitize_renta_entry,
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
              empresa_id TEXT,
              nif TEXT,
              telefono TEXT,
              email TEXT,
              estado TEXT,
              fecha_nacimiento TEXT,
              poblacion TEXT,
              provincia TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE clientes_empresas (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              empresa_id TEXT,
              servicio TEXT,
              estado TEXT,
              fecha_inicio TEXT,
              fecha_fin TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE cliente_gestoria (
              id TEXT PRIMARY KEY,
              cliente_id TEXT,
              tipo_cliente TEXT,
              mod_fiscal INTEGER,
              mod_laboral INTEGER,
              mod_contable INTEGER,
              mod_renta INTEGER,
              mod_registro INTEGER,
              mod_trafico INTEGER,
              mod_puntuales INTEGER,
              renta_detalles TEXT,
              created_at TEXT,
              updated_at TEXT
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
            CREATE TABLE gestoria_docs (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              referencia_tipo TEXT,
              referencia_id TEXT,
              nombre TEXT,
              tipo TEXT,
              fecha TEXT,
              estado TEXT,
              notas TEXT,
              doc_key TEXT,
              doc_url TEXT,
              calidad_ocr TEXT,
              campos_ocr TEXT,
              created_at TEXT,
              updated_at TEXT
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

    def test_collect_signed_export_rows_filters_year_and_non_signed_statuses(self):
        if not OPENPYXL_AVAILABLE:
            self.skipTest("openpyxl no disponible")

        export_conn = sqlite3.connect(":memory:")
        export_conn.row_factory = sqlite3.Row
        export_conn.executescript(
            """
            CREATE TABLE hipotecas (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente TEXT,
              cliente_id TEXT,
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
            CREATE TABLE clientes (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              nif TEXT,
              direccion TEXT,
              telefono TEXT,
              email TEXT,
              created_at TEXT
            );
            INSERT INTO clientes (id, nombre, nif, direccion, telefono, email, created_at)
            VALUES ('c1', 'Cliente Uno', '11111111H', 'Calle Uno', '600000001', 'uno@test.local', '2026-03-25');
            INSERT INTO clientes (id, nombre, nif, direccion, telefono, email, created_at)
            VALUES ('c2', 'Cliente Dos', '22222222J', 'Calle Dos', '600000002', 'dos@test.local', '2026-03-25');
            INSERT INTO clientes (id, nombre, nif, direccion, telefono, email, created_at)
            VALUES ('c3', 'Cliente Tres', '33333333P', 'Calle Tres', '600000003', 'tres@test.local', '2026-03-25');
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, created_at, updated_at
            ) VALUES (
              'h1', 'e1', 'Cliente Uno', 'c1', 'BBVA', 200000, 160000, 80, 40000, 3000,
              'Modernia Norte', '2025-01-10', 'Sí', 'Compra', '2025-02-15', 750, 600, 1650,
              'Inmo Uno', 'Asesor Uno', 'Firmada', 2025, '2026-03-25', '2026-03-25'
            );
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, created_at, updated_at
            ) VALUES (
              'h2', 'e1', 'Cliente Dos', 'c2', 'Santander', 180000, 140000, 77.78, 40000, 2500,
              'Modernia Centro', '2025-03-01', 'Sí', 'Compra', '2025-04-10', 625, 500, 1375,
              'Inmo Dos', 'Asesor Dos', 'Indemnización', 2025, '2026-03-25', '2026-03-25'
            );
            INSERT INTO hipotecas (
              id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje, entrada, comision,
              oficina, fecha_encargo, encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan, comision_modernia,
              inmobiliaria_compra, asesor, estado, anio, created_at, updated_at
            ) VALUES (
              'h3', 'e1', 'Cliente Tres', 'c3', 'CaixaBank', 210000, 170000, 80.95, 40000, 3200,
              'Modernia Sur', '2024-05-01', 'Sí', 'Subrogación', '2024-06-20', 800, 640, 1760,
              'Inmo Tres', 'Asesor Tres', 'Firmado', 2024, '2026-03-25', '2026-03-25'
            );
            """
        )
        try:
            rows_2025 = collect_hipotecas_firmadas_export_rows(export_conn, "e1", "2025")
            self.assertEqual([row["id"] for row in rows_2025], ["h1"])
            self.assertEqual(rows_2025[0]["anio_declarativo"], "2025")
            self.assertEqual(rows_2025[0]["cliente_nif"], "11111111H")

            wb = build_hipotecas_firmadas_excel_workbook(rows_2025, "2025")
            detail = wb["Operaciones firmadas"]
            summary = wb["Resumen declarativo"]

            self.assertEqual(detail["A2"].value, "2025")
            self.assertEqual(detail["C2"].value, "Cliente Uno")
            self.assertEqual(summary["B2"].value, "2025")
            self.assertEqual(summary["B3"].value, 1)
        finally:
            export_conn.close()

    def test_collect_gestoria_renta_card_items_returns_latest_entry_and_preview_doc(self):
        self.conn.execute(
            """
            INSERT INTO clientes (
              id, nombre, empresa_id, nif, telefono, email, estado, fecha_nacimiento, poblacion, provincia, created_at, updated_at
            ) VALUES (
              'c1', 'Ana Renta', 'e1', '12345678A', '600000000', 'ana@example.com', 'Alta', '1985-01-10', 'Malaga',
              'Malaga', '2026-03-25', '2026-03-25'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (
              id, cliente_id, empresa_id, servicio, estado, fecha_inicio, created_at, updated_at
            ) VALUES (
              'ce1', 'c1', 'e1', 'gestoria', 'Alta', '2024-01-01', '2026-03-25', '2026-03-25'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO cliente_gestoria (
              id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
              mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
            ) VALUES (
              'cg1', 'c1', 'Particular', 0, 0, 0, 1, 0, 0, 0, ?, '2026-03-25', '2026-03-25'
            )
            """,
            (
                """
                {"notes":"","entries":[
                  {"id":"r1","ejercicio":"2024","cliente_nombre":"Ana Renta","cliente_nif":"12345678A","presentacion_fecha":"2025-04-01","resultado_declaracion":100.0,"source_files":["uno.pdf"]},
                  {"id":"r2","ejercicio":"2025","cliente_nombre":"Ana Renta","cliente_nif":"12345678A","presentacion_fecha":"2026-04-02","resultado_declaracion":250.0,"source_files":["dos.pdf"]}
                ]}
                """,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id, nombre, tipo, fecha, estado, notas, doc_url, created_at, updated_at
            ) VALUES (
              'd1', 'e1', 'c1', 'renta', 'r2', 'Renta 2025 · Ana.pdf', 'Renta', '2026-04-02', 'Recibido', 'ok',
              '/uploads/rentas/2025/ana.pdf', '2026-03-25', '2026-03-25'
            )
            """
        )
        self.conn.commit()

        rows = collect_gestoria_renta_card_items(self.conn, "e1", q="ana", estado="Alta", limit=10)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cliente_id"], "c1")
        self.assertEqual(rows[0]["renta_latest"]["id"], "r2")
        self.assertEqual(rows[0]["renta_latest"]["ejercicio"], "2025")
        self.assertEqual(rows[0]["doc_count"], 1)
        self.assertEqual(rows[0]["preview_doc"]["doc_url"], "/uploads/rentas/2025/ana.pdf")

    def test_sanitize_renta_entry_discards_outlier_income_and_corrupt_casilla(self):
        sane = sanitize_renta_entry(
            {
                "ingresos_principales_total": 9000000,
                "rendimientos_trabajo_total": 7876.22,
                "rendimientos_actividades_economicas_total": 9000000,
                "rendimientos_capital_inmobiliario_total": None,
                "rendimientos_capital_mobiliario_total": None,
                "casilla_505": 14.64,
                "base_imponible_general": None,
                "base_liquidable_general": None,
                "resultado_declaracion": 1577.18,
            }
        )
        self.assertEqual(sane["ingresos_principales_total"], 7876.22)
        self.assertEqual(sane["rendimientos_trabajo_total"], 7876.22)
        self.assertIsNone(sane["rendimientos_actividades_economicas_total"])
        self.assertIsNone(sane["casilla_505"])
        self.assertEqual(sane["resultado_declaracion"], 1577.18)

    def test_is_gestoria_dashboard_active_state_supports_activo_and_alta(self):
        self.assertTrue(is_gestoria_dashboard_active_state("Activo"))
        self.assertTrue(is_gestoria_dashboard_active_state("Activa"))
        self.assertTrue(is_gestoria_dashboard_active_state("Alta"))
        self.assertFalse(is_gestoria_dashboard_active_state("Pendiente"))
        self.assertFalse(is_gestoria_dashboard_active_state("Baja"))

    def test_compute_gestoria_dashboard_segmentacion_trabajos_counts_categories(self):
        self.conn.executescript(
            """
            CREATE TABLE gestoria_trabajos (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              tipo_categoria TEXT,
              tipo_trabajo TEXT,
              estado TEXT
            );
            INSERT INTO gestoria_trabajos (id, empresa_id, tipo_categoria, tipo_trabajo, estado) VALUES
              ('t1', 'emp-1', 'Herencias', '', 'Pendiente'),
              ('t2', 'emp-1', '', 'Transferencia de vehículo', 'Pendiente'),
              ('t3', 'emp-1', '', 'Expediente administrativo', 'Cerrado'),
              ('t4', 'emp-1', 'Tasaciones', '', 'Hecho'),
              ('t5', 'emp-1', '', 'Renta 2025', 'Pendiente');
            """
        )
        summary = compute_gestoria_dashboard_segmentacion_trabajos(self.conn, ["emp-1"])
        self.assertEqual(summary["herencias_total"], 1)
        self.assertEqual(summary["trafico_total"], 1)
        self.assertEqual(summary["expedientes_total"], 1)
        self.assertEqual(summary["tasaciones_total"], 1)
        self.assertEqual(summary["rentas_total"], 1)
        self.assertEqual(summary["abiertos_total"], 3)


if __name__ == "__main__":
    unittest.main()
