import sqlite3
import unittest
from unittest.mock import patch

from web.server import (
    DEFAULT_WORKSPACE_NAME,
    enforce_workspace_membership,
    ensure_usuarios_schema,
    ensure_workspace_core_tables,
    ensure_workspace_product_tables,
    ensure_workspace_persona_for_self,
    normalize_workspace_slug,
)


class WorkspaceMembershipAutoJoinTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_usuarios_schema(self.conn)
        ensure_workspace_core_tables(self.conn)
        ensure_workspace_product_tables(self.conn)
        # Minimal empresas table required by ensure_workspace_persona_for_self() via fetch_workspace_company_ids().
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER DEFAULT 1
            )
            """
        )
        self.conn.execute("INSERT OR IGNORE INTO empresas (id, nombre, activo) VALUES ('e1', 'Modernia', 1)")

        default_slug = normalize_workspace_slug(DEFAULT_WORKSPACE_NAME)
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at)
            VALUES ('ws_default', ?, ?, 'Activo', 'Enterprise', '', datetime('now'), datetime('now'))
            """,
            (DEFAULT_WORKSPACE_NAME, default_slug),
        )
        # Ensure at least one company is attached to the workspace (for persona auto-create).
        self.conn.execute(
            """
            INSERT OR IGNORE INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at)
            VALUES ('we1', 'ws_default', 'e1', 'operativa', datetime('now'), datetime('now'))
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_autojoin_default_workspace_when_member_missing(self):
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at)
            VALUES ('u1', 'Sebastian', 'Lallana', 'SLallana', 'sebas@example.com', 'Inmobiliaria', 'Inmobiliaria', 1, 1, datetime('now'), datetime('now'))
            """
        )
        session = {"token": "t", "user_id": "u1", "rol": "Inmobiliaria", "servicio": "Inmobiliaria", "email": "sebas@example.com"}
        with patch("web.server.WORKSPACE_MEMBERSHIP_ENFORCE", True):
            ok, err = enforce_workspace_membership(self.conn, session, "ws_default")
        self.assertTrue(ok, err)
        count = self.conn.execute(
            "SELECT COUNT(*) AS total FROM workspace_miembros WHERE workspace_id = 'ws_default' AND usuario_id = 'u1'"
        ).fetchone()["total"]
        self.assertEqual(count, 1)

    def test_does_not_autojoin_other_workspace_without_evidence(self):
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at)
            VALUES ('ws_other', 'Cliente X', 'cliente-x', 'Activo', 'Enterprise', '', datetime('now'), datetime('now'))
            """
        )
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at)
            VALUES ('u2', 'Alicia', 'Mostazo', 'AMostazo', 'alicia@example.com', 'Gestoría', 'Gestoría', 1, 1, datetime('now'), datetime('now'))
            """
        )
        session = {"token": "t", "user_id": "u2", "rol": "Gestoría", "servicio": "Gestoría", "email": "alicia@example.com"}
        with patch("web.server.WORKSPACE_MEMBERSHIP_ENFORCE", True):
            ok, err = enforce_workspace_membership(self.conn, session, "ws_other")
        self.assertFalse(ok)
        self.assertEqual(err, "No autorizado")

    def test_autojoin_other_workspace_if_persona_exists(self):
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at)
            VALUES ('ws_other', 'Cliente X', 'cliente-x', 'Activo', 'Enterprise', '', datetime('now'), datetime('now'))
            """
        )
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at)
            VALUES ('u3', 'David', 'Garcia', 'Dgarcia', 'david@example.com', 'Seguros', 'Seguros', 1, 1, datetime('now'), datetime('now'))
            """
        )
        # Existing employee record in ws_other (email match), but user is not yet a member.
        self.conn.execute(
            """
            INSERT INTO workspace_registro_personal (
              id, workspace_id, empresa_id, usuario_id, usuario_manual, source, nombre, email, activo, created_at, updated_at
            ) VALUES (
              'p1', 'ws_other', 'e1', '', 0, 'manual', 'David Garcia', 'david@example.com', 1, datetime('now'), datetime('now')
            )
            """
        )
        session = {"token": "t", "user_id": "u3", "rol": "Seguros", "servicio": "Seguros", "email": "david@example.com", "nombre": "David", "apellido": "Garcia"}
        with patch("web.server.WORKSPACE_MEMBERSHIP_ENFORCE", True):
            ok, err = enforce_workspace_membership(self.conn, session, "ws_other")
        self.assertTrue(ok, err)
        count = self.conn.execute(
            "SELECT COUNT(*) AS total FROM workspace_miembros WHERE workspace_id = 'ws_other' AND usuario_id = 'u3'"
        ).fetchone()["total"]
        self.assertEqual(count, 1)

    def test_ensure_persona_autocreates_when_time_enabled(self):
        self.conn.execute(
            """
            INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at)
            VALUES ('u4', 'Sofia', 'Perez', 'SPerez', 'sofia@example.com', 'Gestoría', 'Gestoría', 1, 1, datetime('now'), datetime('now'))
            """
        )
        session = {"token": "t", "user_id": "u4", "rol": "Gestoría", "servicio": "Gestoría", "email": "sofia@example.com", "nombre": "Sofia", "apellido": "Perez"}
        persona_id = ensure_workspace_persona_for_self(self.conn, "ws_default", session)
        self.assertTrue(persona_id)
        row = self.conn.execute(
            """
            SELECT usuario_id, usuario_manual, empresa_id, activo
            FROM workspace_registro_personal
            WHERE workspace_id = 'ws_default' AND id = ?
            """,
            (persona_id,),
        ).fetchone()
        self.assertEqual(row["usuario_id"], "u4")
        self.assertEqual(int(row["usuario_manual"] or 0), 1)
        self.assertEqual(row["empresa_id"], "e1")
        self.assertEqual(int(row["activo"] or 0), 1)


if __name__ == "__main__":
    unittest.main()
