import sqlite3
import sys
import types
import unittest

try:
    import PIL  # noqa: F401
except Exception:
    if "PIL" not in sys.modules:
        pil_stub = types.ModuleType("PIL")
        pil_stub.Image = object()
        pil_stub.ImageDraw = object()
        pil_stub.ImageEnhance = object()
        pil_stub.ImageFilter = object()
        pil_stub.ImageFont = object()
        pil_stub.ImageOps = object()
        sys.modules["PIL"] = pil_stub

from web.server import admin_force_reset_password_invite, ensure_auth_invites_table, ensure_usuarios_schema


class AdminForceResetInviteTests(unittest.TestCase):
    def test_force_reset_creates_invite_and_clears_password(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            ensure_usuarios_schema(conn)
            ensure_auth_invites_table(conn)
            conn.execute(
                """
                INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
                VALUES ('u1', 'David', 'Garcia', 'DGarcia', 'dgarcia@grupomodernia.es', 'Inmobiliaria', 'Lectura', 'x$y', 1, datetime('now'), datetime('now'))
                """
            )
            conn.commit()
            result = admin_force_reset_password_invite(conn, "DGarcia", ttl_seconds=3600)
            self.assertEqual(result["user_id"], "u1")
            # password_hash debe quedar vacío
            ph = conn.execute("SELECT COALESCE(password_hash,'') AS ph FROM usuarios WHERE id='u1'").fetchone()["ph"]
            self.assertEqual(str(ph or ""), "")
            # debe existir invitación
            token = result["token"]
            row = conn.execute("SELECT token, user_id FROM auth_invites WHERE token = ?", (token,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["user_id"], "u1")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
