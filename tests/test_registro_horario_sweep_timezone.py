import sqlite3
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime

from web.server import (
    build_workspace_time_csv,
    build_workspace_time_xml,
    count_protected_workspace_time_entries,
    fetch_protected_workspace_time_persona_ids,
    find_duplicate_open_time_entry,
    workspace_time_retention_cutoff_date,
    workspace_time_company_allowed,
)


class RegistroHorarioSweepTimezoneTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE workspace_registro_personal (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              nombre TEXT NOT NULL,
              horas_pactadas_dia REAL,
              alert_missing_checkin INTEGER NOT NULL DEFAULT 1,
              alert_missing_checkout INTEGER NOT NULL DEFAULT 1,
              alert_notify_worker INTEGER NOT NULL DEFAULT 1,
              alert_notify_admin INTEGER NOT NULL DEFAULT 1,
              alert_admin_contact TEXT,
              alert_last_sent TEXT,
              activo INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE workspace_registro_alerts (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              persona_id TEXT,
              alert_missing_checkin INTEGER NOT NULL DEFAULT 1,
              alert_missing_checkout INTEGER NOT NULL DEFAULT 1,
              notify_worker INTEGER NOT NULL DEFAULT 1,
              notify_admin INTEGER NOT NULL DEFAULT 1,
              admin_contact TEXT,
              schedule TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE workspace_registro_notifications (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              persona_id TEXT,
              channel TEXT NOT NULL,
              payload TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE workspace_registro_horario (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT,
              persona_id TEXT,
              fecha TEXT,
              hora_inicio TEXT,
              hora_fin TEXT
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_missing_checkin_uses_app_now_when_now_is_none(self):
        from web import server as srv

        fixed_now = datetime(2026, 4, 1, 11, 0, 0)
        original_app_now = srv.app_now
        try:
            srv.app_now = lambda: fixed_now
            self.conn.execute(
                """
                INSERT INTO workspace_registro_personal (
                  id, workspace_id, empresa_id, nombre, horas_pactadas_dia,
                  alert_missing_checkin, alert_missing_checkout, alert_notify_worker, alert_notify_admin,
                  alert_admin_contact, alert_last_sent, activo, created_at, updated_at
                ) VALUES (
                  'p1', 'w1', 'e1', 'Irene', 8,
                  1, 1, 1, 1,
                  'admin@example.com', '', 1, '2026-04-01 00:00:00', '2026-04-01 00:00:00'
                )
                """
            )
            created = srv.run_workspace_time_missing_sweep(self.conn, "w1")
            # A las 11:00 (schedule por defecto 10:00) debe avisar de falta de entrada.
            self.assertIn("worker_missing_checkin", created)
            self.assertIn("admin_missing_checkin", created)
            # Segunda pasada el mismo día no debe duplicar.
            created2 = srv.run_workspace_time_missing_sweep(self.conn, "w1")
            self.assertEqual(created2, [])
        finally:
            srv.app_now = original_app_now

    def test_duplicate_open_entry_detects_edit_conflicts(self):
        self.conn.execute(
            """
            INSERT INTO workspace_registro_horario (
              id, workspace_id, empresa_id, persona_id, fecha, hora_inicio, hora_fin
            ) VALUES
              ('r1', 'w1', 'e1', 'p1', '2026-04-01', '09:00', NULL),
              ('r2', 'w1', 'e1', 'p1', '2026-04-01', '10:00', '12:00')
            """
        )
        row = find_duplicate_open_time_entry(
            self.conn,
            "w1",
            "e1",
            "2026-04-01",
            persona_id="p1",
            exclude_id="r2",
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], "r1")
        self.assertIsNone(
            find_duplicate_open_time_entry(
                self.conn,
                "w1",
                "e1",
                "2026-04-01",
                persona_id="p1",
                exclude_id="r1",
            )
        )

    def test_workspace_time_company_allowed_rejects_foreign_company(self):
        from web.server import ensure_workspace_core_tables

        ensure_workspace_core_tables(self.conn)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER DEFAULT 1
            )
            """
        )
        self.conn.execute("INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at) VALUES ('w1','W1','w1','Activo','Enterprise','',datetime('now'),datetime('now'))")
        self.conn.execute("INSERT INTO empresas (id, nombre, activo) VALUES ('e1','Empresa 1',1)")
        self.conn.execute("INSERT INTO empresas (id, nombre, activo) VALUES ('e2','Empresa 2',1)")
        self.conn.execute("INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at) VALUES ('we1','w1','e1','operativa',datetime('now'),datetime('now'))")
        self.assertTrue(workspace_time_company_allowed(self.conn, "w1", "e1"))
        self.assertFalse(workspace_time_company_allowed(self.conn, "w1", "e2"))

    def test_retention_cutoff_keeps_four_year_window(self):
        self.assertEqual(workspace_time_retention_cutoff_date(datetime(2026, 5, 29, 12, 0, 0)), "2022-05-29")

    def test_retention_helpers_protect_recent_and_unknown_dates(self):
        self.conn.execute(
            """
            INSERT INTO workspace_registro_horario (
              id, workspace_id, empresa_id, persona_id, fecha, hora_inicio, hora_fin
            ) VALUES
              ('recent', 'w1', 'e1', 'p1', ?, '09:00', '17:00'),
              ('old', 'w1', 'e1', 'p2', '2001-01-01', '09:00', '17:00'),
              ('unknown', 'w1', 'e1', 'p3', '', '09:00', '17:00')
            """,
            (workspace_time_retention_cutoff_date(),),
        )
        self.assertEqual(count_protected_workspace_time_entries(self.conn, "w1"), 2)
        self.assertEqual(count_protected_workspace_time_entries(self.conn, "w1", persona_id="p2"), 0)
        self.assertEqual(fetch_protected_workspace_time_persona_ids(self.conn, "w1"), {"p1", "p3"})

    def test_time_csv_includes_compliance_metadata_columns(self):
        csv_text = build_workspace_time_csv(
            [
                {
                    "empresa_id": "e1",
                    "empresa_nombre": "Empresa",
                    "persona_id": "p1",
                    "persona_nombre": "Irene",
                    "fecha": "2026-04-01",
                    "hora_inicio": "09:00",
                    "hora_fin": "17:00",
                    "minutos_trabajados": 480,
                }
            ]
        ).decode("utf-8-sig")
        self.assertIn("timezone", csv_text.splitlines()[0])
        self.assertIn("retention_years", csv_text.splitlines()[0])
        self.assertIn("art. 34.9 Estatuto de los Trabajadores", csv_text)

    def test_time_xml_includes_compliance_metadata(self):
        xml_bytes = build_workspace_time_xml([], persona_name="Irene", company_name="Empresa", month="2026-04")
        root = ET.fromstring(xml_bytes)
        self.assertEqual(root.attrib.get("timezone"), "Europe/Madrid")
        self.assertEqual(root.attrib.get("retention_years"), "4")
        self.assertEqual(root.attrib.get("legal_basis"), "art. 34.9 Estatuto de los Trabajadores")


if __name__ == "__main__":
    unittest.main()
