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

from web.server import (
    classify_login_access_issue,
    classify_post_login_scope_issue,
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

    def test_classify_login_access_issue_detects_missing_membership(self):
        issue = classify_login_access_issue(self.conn, "recover.user")
        self.assertEqual(issue.get("reason"), "missing_membership")

    def test_classify_login_access_issue_detects_inactive_user(self):
        self.conn.execute("UPDATE usuarios SET activo = 0 WHERE id = 'u1'")
        self.conn.commit()
        issue = classify_login_access_issue(self.conn, "recover.user")
        self.assertEqual(issue.get("reason"), "inactive_user")

    def test_classify_login_access_issue_detects_password_not_initialized(self):
        self.conn.execute("UPDATE usuarios SET password_hash = NULL WHERE id = 'u1'")
        self.conn.commit()
        issue = classify_login_access_issue(self.conn, "recover.user")
        self.assertEqual(issue.get("reason"), "password_not_initialized")

    def test_classify_post_login_scope_issue_detects_no_workspace_membership(self):
        issue = classify_post_login_scope_issue(
            self.conn,
            {"user_id": "u1", "usuario": "recover.user", "servicio": "Gestoría", "rol": "Lectura"},
        )
        self.assertEqual(issue.get("reason"), "no_workspace_membership")

    def test_classify_post_login_scope_issue_detects_no_service_scope(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              slug TEXT,
              estado TEXT,
              plan TEXT,
              kind TEXT,
              descripcion TEXT,
              logo_url TEXT,
              primary_color TEXT,
              accent_color TEXT
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspaces (id, nombre) VALUES ('ws1', 'Workspace 1')"
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workspace_miembros (
              id TEXT PRIMARY KEY,
              workspace_id TEXT,
              usuario_id TEXT,
              rol TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        self.conn.execute(
            "INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol) VALUES ('m1', 'ws1', 'u1', 'Miembro')"
        )
        self.conn.commit()
        issue = classify_post_login_scope_issue(
            self.conn,
            {"user_id": "u1", "usuario": "recover.user", "servicio": "", "rol": "Lectura"},
        )
        self.assertEqual(issue.get("reason"), "no_service_scope")


if __name__ == "__main__":
    unittest.main()
