import sqlite3
import unittest

from web.server import (
    apply_fin_action_workflow,
    convert_fin_asesoramiento_to_hipoteca,
    ensure_fin_followup_action,
    validate_fin_action_result,
)


class FinWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE asesoramientos_financiacion (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              origen TEXT,
              inmueble_id TEXT,
              accion_origen_id TEXT,
              inmobiliaria_asesor TEXT,
              asesor TEXT,
              fecha TEXT,
              estado TEXT,
              cliente1_id TEXT,
              cliente1_nombre TEXT,
              cliente1_dni TEXT,
              cliente1_telefono TEXT,
              cliente1_email TEXT,
              cliente1_fecha_nacimiento TEXT,
              cliente1_estado_civil TEXT,
              cliente1_regimen TEXT,
              cliente1_hijos TEXT,
              cliente1_profesion TEXT,
              cliente1_tipo_contrato TEXT,
              cliente1_tiempo_contrato TEXT,
              cliente1_ingresos REAL,
              cliente1_patrimonio TEXT,
              cliente1_prestamos TEXT,
              cliente1_prestamo_activo TEXT,
              cliente1_prestamo_entidad TEXT,
              cliente1_prestamo_resto REAL,
              cliente2_id TEXT,
              cliente2_nombre TEXT,
              cliente2_dni TEXT,
              cliente2_telefono TEXT,
              cliente2_email TEXT,
              cliente2_fecha_nacimiento TEXT,
              cliente2_estado_civil TEXT,
              cliente2_regimen TEXT,
              cliente2_hijos TEXT,
              cliente2_profesion TEXT,
              cliente2_tipo_contrato TEXT,
              cliente2_tiempo_contrato TEXT,
              cliente2_ingresos REAL,
              cliente2_patrimonio TEXT,
              cliente2_prestamos TEXT,
              cliente2_prestamo_activo TEXT,
              cliente2_prestamo_entidad TEXT,
              cliente2_prestamo_resto REAL,
              ingresos_conjuntos REAL,
              entidades_financieras TEXT,
              avalistas TEXT,
              aportacion_cv REAL,
              notas TEXT,
              notas_ocr TEXT,
              calidad_ocr TEXT,
              campos_ocr TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              servicio TEXT NOT NULL,
              cliente_id TEXT,
              inmueble_id TEXT,
              asesoramiento_id TEXT,
              cliente_nombre TEXT,
              fecha TEXT,
              hora TEXT,
              tipo TEXT,
              responsable TEXT,
              estado TEXT,
              resultado_cierre TEXT,
              estado_siguiente TEXT,
              documento_tipo TEXT,
              importe_propuesta REAL,
              notas TEXT,
              recordatorio_min INTEGER,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
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
            """
        )
        self.conn.execute(
            """
            INSERT INTO asesoramientos_financiacion (
              id, empresa_id, fecha, estado, cliente1_id, cliente1_nombre, cliente1_ingresos,
              ingresos_conjuntos, asesor, inmobiliaria_asesor, created_at, updated_at
            ) VALUES (
              'a1', 'e1', '2026-03-20', 'Lead', 'c1', 'Cliente Uno', 1800, 1800,
              'Asesor Demo', 'Inmo Demo', '2026-03-20', '2026-03-20'
            )
            """
        )
        self.now = "2026-03-28T10:00:00+00:00"

    def tearDown(self):
        self.conn.close()

    def test_validate_fin_action_result_requires_result_when_closed(self):
        self.assertEqual(
            validate_fin_action_result("Primera llamada", "Hecho", ""),
            "La tarea financiera debe cerrarse con un resultado",
        )
        self.assertIsNone(validate_fin_action_result("Primera llamada", "Pendiente", ""))

    def test_apply_fin_action_workflow_advances_to_asesoramiento_and_creates_followup(self):
        self.conn.execute(
            """
            INSERT INTO acciones (
              id, empresa_id, servicio, cliente_id, asesoramiento_id, cliente_nombre,
              fecha, tipo, responsable, estado, resultado_cierre, created_at, updated_at
            ) VALUES (
              'ac1', 'e1', 'financiaciones', 'c1', 'a1', 'Cliente Uno',
              '2026-03-28', 'Primera llamada', 'Asesor Demo', 'Hecho', 'Cita concertada', '2026-03-28', '2026-03-28'
            )
            """
        )
        action = self.conn.execute("SELECT * FROM acciones WHERE id = 'ac1'").fetchone()
        result = apply_fin_action_workflow(self.conn, "e1", action, self.now)
        self.assertEqual(result, "Asesoramiento")
        row = self.conn.execute("SELECT estado FROM asesoramientos_financiacion WHERE id = 'a1'").fetchone()
        self.assertEqual(row["estado"], "Asesoramiento")
        followup = self.conn.execute(
            "SELECT tipo, estado FROM acciones WHERE asesoramiento_id = 'a1' AND id != 'ac1'"
        ).fetchone()
        self.assertIsNotNone(followup)
        self.assertEqual(followup["tipo"], "Reunión de asesoramiento")
        self.assertEqual(followup["estado"], "Pendiente")

    def test_apply_fin_action_workflow_converts_on_signed_firma(self):
        self.conn.execute(
            "UPDATE asesoramientos_financiacion SET estado = 'Firma' WHERE id = 'a1'"
        )
        self.conn.execute(
            """
            INSERT INTO acciones (
              id, empresa_id, servicio, cliente_id, asesoramiento_id, cliente_nombre,
              fecha, tipo, responsable, estado, resultado_cierre, created_at, updated_at
            ) VALUES (
              'ac2', 'e1', 'financiaciones', 'c1', 'a1', 'Cliente Uno',
              '2026-03-28', 'Firma hipoteca', 'Asesor Demo', 'Hecho', 'Firmada', '2026-03-28', '2026-03-28'
            )
            """
        )
        action = self.conn.execute("SELECT * FROM acciones WHERE id = 'ac2'").fetchone()
        result = apply_fin_action_workflow(self.conn, "e1", action, self.now)
        self.assertEqual(result, "Convertido")
        hipoteca = self.conn.execute("SELECT cliente_id, asesor FROM hipotecas LIMIT 1").fetchone()
        self.assertIsNotNone(hipoteca)
        self.assertEqual(hipoteca["cliente_id"], "c1")
        self.assertEqual(hipoteca["asesor"], "Asesor Demo")
        asesoramiento = self.conn.execute(
            "SELECT estado FROM asesoramientos_financiacion WHERE id = 'a1'"
        ).fetchone()
        self.assertEqual(asesoramiento["estado"], "Convertido")

    def test_convert_fin_asesoramiento_to_hipoteca_is_idempotent(self):
        row = self.conn.execute("SELECT * FROM asesoramientos_financiacion WHERE id = 'a1'").fetchone()
        first = convert_fin_asesoramiento_to_hipoteca(self.conn, "e1", row, self.now)
        second = convert_fin_asesoramiento_to_hipoteca(self.conn, "e1", row, self.now)
        self.assertEqual(first, second)
        total = self.conn.execute("SELECT COUNT(*) AS total FROM hipotecas").fetchone()["total"]
        self.assertEqual(total, 1)

    def test_convert_fin_asesoramiento_to_hipoteca_is_idempotent_without_cliente1_id(self):
        self.conn.execute(
            """
            INSERT INTO asesoramientos_financiacion (
              id, empresa_id, fecha, estado, cliente1_id, cliente1_nombre, notas_ocr, asesor,
              inmobiliaria_asesor, created_at, updated_at
            ) VALUES (
              'a2', 'e1', '2026-03-21', 'Lead', NULL, 'Cliente Dos', '', 'Asesor Demo',
              'Inmo Demo', '2026-03-21', '2026-03-21'
            )
            """
        )
        row = self.conn.execute("SELECT * FROM asesoramientos_financiacion WHERE id = 'a2'").fetchone()
        first = convert_fin_asesoramiento_to_hipoteca(self.conn, "e1", row, self.now)
        second = convert_fin_asesoramiento_to_hipoteca(self.conn, "e1", row, self.now)
        self.assertEqual(first, second)
        total = self.conn.execute(
            "SELECT COUNT(*) AS total FROM hipotecas WHERE cliente = 'Cliente Dos'"
        ).fetchone()["total"]
        self.assertEqual(total, 1)

    def test_ensure_fin_followup_action_avoids_duplicates(self):
        first = ensure_fin_followup_action(
            self.conn,
            "e1",
            "a1",
            "c1",
            "Cliente Uno",
            "Asesor Demo",
            "Seguimiento bancario",
            "Revisar banco",
            self.now,
        )
        second = ensure_fin_followup_action(
            self.conn,
            "e1",
            "a1",
            "c1",
            "Cliente Uno",
            "Asesor Demo",
            "Seguimiento bancario",
            "Revisar banco",
            self.now,
        )
        self.assertEqual(first, second)
        total = self.conn.execute(
            "SELECT COUNT(*) AS total FROM acciones WHERE asesoramiento_id = 'a1' AND tipo = 'Seguimiento bancario'"
        ).fetchone()["total"]
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
