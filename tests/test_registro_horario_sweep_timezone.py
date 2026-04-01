import sqlite3
import unittest
from datetime import datetime


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


if __name__ == "__main__":
    unittest.main()

