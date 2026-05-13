import sqlite3
import unittest

from web.server import fetch_api_usuarios


class ApiUsuariosScopingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE usuarios (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              apellido TEXT,
              usuario TEXT,
              email TEXT,
              servicio TEXT,
              rol TEXT,
              activo INTEGER,
              registro_horario_activo INTEGER
            );
            CREATE TABLE workspace_miembros (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              usuario_id TEXT NOT NULL,
              rol TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )
        self.conn.executemany(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo, registro_horario_activo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("u1", "Ana", "Uno", "ana", "ana@example.com", "inmobiliaria", "", 1, 0),
                ("u2", "Beto", "Dos", "beto", "beto@example.com", "inmobiliaria", "", 1, 0),
                ("u3", "Cris", "Tres", "cris", "cris@example.com", "inmobiliaria", "", 1, 0),
            ],
        )
        self.conn.executemany(
            """
            INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'now', 'now')
            """,
            [
                ("m1", "ws1", "u1", "Miembro"),
                ("m2", "ws1", "u2", "Miembro"),
                ("m3", "ws2", "u3", "Miembro"),
            ],
        )

    def tearDown(self):
        self.conn.close()

    def test_non_privileged_scopes_to_requested_workspace(self):
        session = {"user_id": "u1"}
        rows = fetch_api_usuarios(self.conn, session, workspace_id="ws1", privileged=False)
        ids = sorted([r["id"] for r in rows])
        self.assertEqual(ids, ["u1", "u2"])
        self.assertTrue(all("email" not in r for r in rows))

    def test_non_privileged_without_workspace_id_scopes_to_user_workspaces(self):
        session = {"user_id": "u1"}
        rows = fetch_api_usuarios(self.conn, session, workspace_id="", privileged=False)
        ids = sorted([r["id"] for r in rows])
        self.assertEqual(ids, ["u1", "u2"])
        self.assertTrue(all("email" not in r for r in rows))

    def test_privileged_can_filter_by_workspace_id(self):
        session = {"user_id": "u1"}
        rows = fetch_api_usuarios(self.conn, session, workspace_id="ws1", privileged=True)
        ids = sorted([r["id"] for r in rows])
        self.assertEqual(ids, ["u1", "u2"])
        self.assertTrue(all("email" in r for r in rows))

    def test_privileged_without_workspace_id_returns_global(self):
        session = {"user_id": "u1"}
        rows = fetch_api_usuarios(self.conn, session, workspace_id="", privileged=True)
        ids = sorted([r["id"] for r in rows])
        self.assertEqual(ids, ["u1", "u2"])
        self.assertTrue(all("email" in r for r in rows))


if __name__ == "__main__":
    unittest.main()
