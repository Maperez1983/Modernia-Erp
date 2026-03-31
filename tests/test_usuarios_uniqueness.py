import sqlite3
import unittest

from web.server import fetch_active_users_by_login, normalize_username, _usuarios_conflict_id


class UsuariosUniquenessTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Tabla mínima (sin UNIQUE) para simular DBs legacy con duplicados.
        self.conn.executescript(
            """
            CREATE TABLE usuarios (
              id TEXT PRIMARY KEY,
              nombre TEXT NOT NULL,
              apellido TEXT,
              usuario TEXT,
              email TEXT,
              servicio TEXT,
              rol TEXT,
              registro_horario_activo INTEGER DEFAULT 0,
              password_hash TEXT,
              activo INTEGER DEFAULT 1,
              invite_token TEXT,
              invite_expires_at TEXT,
              invite_sent_at TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_normalize_username_trims_and_collapses_whitespace(self):
        self.assertEqual(normalize_username("  Juan   Pérez  "), "Juan Pérez")

    def test_login_lookup_matches_trimmed_usuario(self):
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo)
            VALUES ('u1', 'Juan', 'Pérez', 'juan  ', 'juan@example.com', 'Gestoría', 'Gestoría', 1)
            """
        )
        matches = fetch_active_users_by_login(self.conn, "juan")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["id"], "u1")

    def test_login_lookup_detects_ambiguous_duplicates(self):
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo)
            VALUES ('u1', 'Ana', 'Uno', 'ANA', 'ana1@example.com', 'RRHH', 'Lectura', 1)
            """
        )
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo)
            VALUES ('u2', 'Ana', 'Dos', 'ana ', 'ana2@example.com', 'RRHH', 'Lectura', 1)
            """
        )
        matches = fetch_active_users_by_login(self.conn, "ana")
        self.assertEqual(len(matches), 2)

    def test_conflict_detection_is_case_insensitive_and_trimmed(self):
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo)
            VALUES ('u1', 'Admin', 'Uno', 'Admin', 'admin@example.com', 'Administración', 'Administrador', 1)
            """
        )
        conflict = _usuarios_conflict_id(self.conn, usuario=" admin ", email="other@example.com")
        self.assertIsNotNone(conflict)
        self.assertEqual(conflict["field"], "usuario")
        self.assertEqual(conflict["id"], "u1")


if __name__ == "__main__":
    unittest.main()

