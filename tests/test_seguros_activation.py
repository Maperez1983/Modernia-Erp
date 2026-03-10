import sqlite3
import unittest

from web.server import seguros_sync_activation_action


class SegurosActivationActionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              servicio TEXT,
              cliente_id TEXT,
              inmueble_id TEXT,
              cliente_nombre TEXT,
              fecha TEXT,
              hora TEXT,
              tipo TEXT,
              responsable TEXT,
              estado TEXT,
              notas TEXT,
              recordatorio_min INTEGER,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )
        self.now = "2026-03-10T10:00:00+00:00"

    def tearDown(self):
        self.conn.close()

    def test_creates_pending_activation_action_for_future_effect(self):
        row = {
            "id": "s1",
            "empresa_id": "e1",
            "cliente_id": "c1",
            "fecha_efecto": "2026-05-01",
            "estado": "Contratada",
            "tomador": "Cliente Uno",
            "poliza_numero": "POL-100",
        }
        seguros_sync_activation_action(self.conn, row, self.now)
        action = self.conn.execute(
            "SELECT tipo, estado, fecha, notas FROM acciones WHERE servicio = 'Seguros' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(action)
        self.assertEqual(action["tipo"], "Activar póliza")
        self.assertEqual(action["estado"], "Pendiente")
        self.assertEqual(action["fecha"], "2026-05-01")
        self.assertIn("s1", action["notas"] or "")

    def test_marks_activation_action_done_when_policy_is_in_force(self):
        self.conn.execute(
            """
            INSERT INTO acciones (
              id, empresa_id, servicio, cliente_id, cliente_nombre, fecha, tipo, estado, notas, created_at, updated_at
            ) VALUES (
              'a1', 'e1', 'Seguros', 'c1', 'Cliente Uno', '2026-05-01', 'Activar póliza', 'Pendiente',
              'Activar póliza por entrada en vigor. Poliza ID: s1', '2026-03-10', '2026-03-10'
            )
            """
        )
        row = {
            "id": "s1",
            "empresa_id": "e1",
            "cliente_id": "c1",
            "fecha_efecto": "2026-05-01",
            "estado": "En vigor",
            "tomador": "Cliente Uno",
            "poliza_numero": "POL-100",
        }
        seguros_sync_activation_action(self.conn, row, self.now)
        action = self.conn.execute("SELECT estado FROM acciones WHERE id = 'a1'").fetchone()
        self.assertEqual(action["estado"], "Hecho")


if __name__ == "__main__":
    unittest.main()
