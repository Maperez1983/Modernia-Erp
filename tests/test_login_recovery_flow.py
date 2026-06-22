import sqlite3
import unittest

from web.server import (
    ensure_auth_invites_table,
    ensure_usuarios_schema,
    get_login_attempt_count,
    login_recovery_available,
    register_login_attempt,
    request_login_access_recovery,
)


class LoginRecoveryFlowTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        try:
            from web import server
            with server._LOGIN_RATE_LOCK:
                server._LOGIN_RATE_STATE.clear()
        except Exception:
            pass
        ensure_usuarios_schema(self.conn)
        ensure_auth_invites_table(self.conn)
        self.conn.execute("DELETE FROM usuarios WHERE usuario = 'recover.user'")
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
            VALUES ('u1', 'Recover', 'User', 'recover.user', 'recover@example.com', 'Gestoría', 'Lectura', 'pbkdf2_sha256$abc', 1, datetime('now'), datetime('now'))
            """
        )
        self.conn.commit()

    def tearDown(self):
        try:
            from web import server
            with server._LOGIN_RATE_LOCK:
                server._LOGIN_RATE_STATE.clear()
        except Exception:
            pass
        self.conn.close()

    def test_recovery_not_available_before_three_failed_attempts(self):
        register_login_attempt("1.2.3.4", "recover.user", ok=False)
        register_login_attempt("1.2.3.4", "recover.user", ok=False)
        self.assertEqual(get_login_attempt_count("1.2.3.4", "recover.user"), 2)
        self.assertFalse(login_recovery_available("1.2.3.4", "recover.user"))
        result = request_login_access_recovery(self.conn, "recover.user", ip="1.2.3.4", min_attempts=3, base_url="https://crm.example.test")
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("error"), "Recuperación no disponible todavía")

    def test_recovery_generates_invite_after_third_failed_attempt(self):
        for _ in range(3):
            register_login_attempt("1.2.3.4", "recover.user", ok=False)
        self.assertTrue(login_recovery_available("1.2.3.4", "recover.user"))
        result = request_login_access_recovery(self.conn, "recover.user", ip="1.2.3.4", min_attempts=3, base_url="https://crm.example.test")
        self.assertTrue(result["ok"])
        self.assertTrue(result["queued"])
        self.assertIn("/?activar_token=", str(result.get("invite_url") or ""))
        row = self.conn.execute("SELECT COALESCE(password_hash, '') AS ph FROM usuarios WHERE id = 'u1'").fetchone()
        self.assertEqual(str(row["ph"] or ""), "")


if __name__ == "__main__":
    unittest.main()
