import sqlite3
import unittest

from web.server import workspace_actor_is_privileged


class PrivilegeRefreshTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE usuarios (
              id TEXT PRIMARY KEY,
              rol TEXT,
              servicio TEXT,
              activo INTEGER DEFAULT 1
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_refreshes_privilege_from_db_when_session_is_stale(self):
        self.conn.execute(
            "INSERT INTO usuarios (id, rol, servicio, activo) VALUES ('u1', 'Administrador', '', 1)"
        )
        session = {"token": "t", "user_id": "u1", "rol": "", "servicio": ""}
        self.assertTrue(workspace_actor_is_privileged(self.conn, session))

    def test_denies_when_db_user_is_inactive(self):
        self.conn.execute(
            "INSERT INTO usuarios (id, rol, servicio, activo) VALUES ('u1', 'Administrador', '', 0)"
        )
        session = {"token": "t", "user_id": "u1", "rol": "", "servicio": ""}
        self.assertFalse(workspace_actor_is_privileged(self.conn, session))


if __name__ == "__main__":
    unittest.main()

