import sqlite3
import unittest
from datetime import datetime, timezone

from web.server import (
    _parse_iso_dt_utc,
    close_actions_for_related,
    ensure_action_for_related,
    fetch_workspace_fincas_incidencias_for_comunidad,
    fetch_workspace_fincas_proveedores_for_comunidad,
    fetch_workspace_presupuesto_share,
    fetch_workspace_presupuesto_templates,
)


class ServerF821RegressionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              servicio TEXT NOT NULL,
              cliente_id TEXT,
              cliente_nombre TEXT,
              fecha TEXT,
              asunto TEXT,
              tipo TEXT,
              responsable TEXT,
              estado TEXT,
              notas TEXT,
              related_id TEXT,
              related_tipo TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT
            );
            CREATE TABLE workspace_fincas_comunidades (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              nombre TEXT
            );
            CREATE TABLE workspace_fincas_incidencias (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              comunidad_id TEXT,
              titulo TEXT,
              descripcion TEXT,
              prioridad TEXT,
              estado TEXT,
              proveedor TEXT,
              proveedor_id TEXT,
              responsable TEXT,
              fecha_apertura TEXT,
              fecha_cierre TEXT,
              coste_estimado REAL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE workspace_fincas_proveedores (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              comunidad_id TEXT,
              empresa_id TEXT,
              nombre TEXT,
              tipo_servicio TEXT,
              telefono TEXT,
              email TEXT,
              estado TEXT,
              tarifa_mensual REAL,
              notas TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE workspace_presupuesto_shares (
              token TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              presupuesto_id TEXT NOT NULL,
              expires_at TEXT,
              last_access_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        self.now = "2026-07-13T12:00:00+00:00"

    def tearDown(self):
        self.conn.close()

    def test_parse_iso_dt_utc_normalizes_naive_iso(self):
        parsed = _parse_iso_dt_utc("2026-07-13T12:34:56")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-07-13T12:34:56+00:00")

    def test_ensure_and_close_actions_for_related(self):
        action_id = ensure_action_for_related(
            self.conn,
            empresa_id="e1",
            servicio="Seguros",
            related_tipo="seguros_recibo",
            related_id="rec-1",
            tipo="Impago recibo",
            fecha="2026-07-14",
            cliente_id="c1",
            cliente_nombre="Cliente Uno",
            notas="Estado: impagado.",
            now=self.now,
        )
        self.assertTrue(action_id)
        again_id = ensure_action_for_related(
            self.conn,
            empresa_id="e1",
            servicio="Seguros",
            related_tipo="seguros_recibo",
            related_id="rec-1",
            tipo="Impago recibo",
            fecha="2026-07-15",
            cliente_id="c1",
            cliente_nombre="Cliente Uno",
            notas="Estado: impagado.",
            now=self.now,
        )
        self.assertEqual(action_id, again_id)
        rows = self.conn.execute("SELECT * FROM acciones").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["estado"], "Pendiente")
        self.assertEqual(rows[0]["fecha"], "2026-07-15")
        close_actions_for_related(
            self.conn,
            empresa_id="e1",
            servicio="Seguros",
            related_tipo="seguros_recibo",
            related_id="rec-1",
            now=self.now,
        )
        closed = self.conn.execute("SELECT estado FROM acciones WHERE id = ?", (action_id,)).fetchone()
        self.assertEqual(closed["estado"], "Hecho")

    def test_fincas_helpers_filter_by_comunidad(self):
        self.conn.executemany(
            """
            INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre)
            VALUES (?, ?, ?)
            """,
            [
                ("c1", "ws1", "Comunidad Norte"),
                ("c2", "ws1", "Comunidad Sur"),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO workspace_fincas_incidencias (
              id, workspace_id, comunidad_id, titulo, descripcion, prioridad, estado,
              proveedor, proveedor_id, responsable, fecha_apertura, fecha_cierre, coste_estimado, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("i1", "ws1", "c1", "Fuga", "Revisar bajante", "Alta", "Abierta", "", None, "Ana", "2026-07-01", None, 120.0, self.now, self.now),
                ("i2", "ws1", "c2", "Luz", "Cambiar portal", "Media", "Abierta", "", None, "Luis", "2026-07-02", None, 80.0, self.now, self.now),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO empresas (id, nombre)
            VALUES (?, ?)
            """,
            [("emp1", "Proveedor Uno")],
        )
        self.conn.executemany(
            """
            INSERT INTO workspace_fincas_proveedores (
              id, workspace_id, comunidad_id, empresa_id, nombre, tipo_servicio, telefono, email, estado,
              tarifa_mensual, notas, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("p1", "ws1", "c1", "emp1", "Proveedor Uno", "Mantenimiento", "111", "a@example.com", "Activo", 10.0, "", self.now, self.now),
                ("p2", "ws1", "c2", "emp1", "Proveedor Dos", "Limpieza", "222", "b@example.com", "Activo", 20.0, "", self.now, self.now),
            ],
        )
        incidencias = fetch_workspace_fincas_incidencias_for_comunidad(self.conn, "ws1", comunidad_id="c1")
        proveedores = fetch_workspace_fincas_proveedores_for_comunidad(self.conn, "ws1", comunidad_id="c1")
        self.assertEqual([row["id"] for row in incidencias["rows"]], ["i1"])
        self.assertEqual([row["id"] for row in proveedores["rows"]], ["p1"])

    def test_presupuesto_share_and_templates_helpers(self):
        self.conn.execute(
            """
            INSERT INTO workspace_presupuesto_shares (
              token, workspace_id, presupuesto_id, expires_at, last_access_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("share-1", "ws1", "pres-1", "2026-07-20T00:00:00+00:00", None, self.now, self.now),
        )
        share = fetch_workspace_presupuesto_share(self.conn, "share-1")
        self.assertIsNotNone(share)
        self.assertEqual(share["presupuesto_id"], "pres-1")
        templates = fetch_workspace_presupuesto_templates(self.conn, "ws1", servicio="Fincas", limit=2)
        self.assertEqual(templates["workspace_id"], "ws1")
        self.assertEqual(templates["servicio"], "fincas")
        keys = [item["key"] for item in templates["templates"]]
        self.assertEqual(keys, ["fincas_calculado", "fincas_completo"])

