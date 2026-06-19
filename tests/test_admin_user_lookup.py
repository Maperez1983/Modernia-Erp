import sqlite3
import sys
import types
import unittest

try:
    import PIL  # noqa: F401
except Exception:
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageEnhance = object()
    pil_stub.ImageFilter = object()
    pil_stub.ImageFont = object()
    pil_stub.ImageOps = object()
    sys.modules.setdefault("PIL", pil_stub)

from web.auth_security import hash_password
from web.server import admin_lookup_users_by_login, ensure_usuarios_schema


class AdminUserLookupTests(unittest.TestCase):
    def test_pbkdf2_password_scheme_is_reported(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_usuarios_schema(conn)
        conn.execute(
            """
            INSERT INTO usuarios (
                id, nombre, apellido, usuario, email, servicio, rol, activo, password_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, datetime('now'), datetime('now'))
            """,
            (
                "u1",
                "Admin",
                "Lookup",
                "lookup.user",
                "lookup@example.com",
                "Administración",
                "Administrador",
                hash_password("Modernia2026"),
            ),
        )
        conn.commit()

        items = admin_lookup_users_by_login(conn, "lookup.user")

        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["has_password"])
        self.assertEqual(items[0]["password_scheme"], "pbkdf2_sha256")


if __name__ == "__main__":
    unittest.main()
