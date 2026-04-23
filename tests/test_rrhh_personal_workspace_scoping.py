import sqlite3
import unittest

from web.server import (
    ensure_usuarios_schema,
    ensure_workspace_core_tables,
    ensure_workspace_product_tables,
    fetch_workspace_personal,
)


class WorkspacePersonalScopingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        ensure_usuarios_schema(self.conn)
        ensure_workspace_core_tables(self.conn)
        ensure_workspace_product_tables(self.conn)
        # Minimal empresas table required for joins used by fetch_workspace_personal.
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
        self.conn.execute("INSERT OR IGNORE INTO empresas (id, nombre, activo) VALUES ('e2', 'Otro', 1)")

        # Workspaces + company links.
        self.conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at) VALUES ('ws1','WS1','ws1','Activo','Enterprise','',datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO workspaces (id, nombre, slug, estado, plan, descripcion, created_at, updated_at) VALUES ('ws2','WS2','ws2','Activo','Enterprise','',datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at) VALUES ('we1','ws1','e1','operativa',datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at) VALUES ('we2','ws2','e2','operativa',datetime('now'),datetime('now'))"
        )

        # Users + memberships.
        self.conn.execute(
            "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at) VALUES ('u1','Ana','Perez','aperez','ana@example.com','RRHH','RRHH',1,1,datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, registro_horario_activo, activo, created_at, updated_at) VALUES ('u2','Beto','Lopez','blopez','beto@example.com','RRHH','RRHH',1,1,datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, updated_at) VALUES ('m1','ws1','u1','User',datetime('now'),datetime('now'))"
        )
        self.conn.execute(
            "INSERT INTO workspace_miembros (id, workspace_id, usuario_id, rol, created_at, updated_at) VALUES ('m2','ws2','u2','User',datetime('now'),datetime('now'))"
        )

        # Personal in ws1:
        # - linked to u1 (member) -> visible
        self.conn.execute(
            """
            INSERT INTO workspace_registro_personal (
              id, workspace_id, empresa_id, empresa_manual, usuario_id, usuario_manual, source, nombre, email, activo, created_at, updated_at
            ) VALUES ('p_ok','ws1','e1',1,'u1',1,'manual','Ana Perez','ana@example.com',1,datetime('now'),datetime('now'))
            """
        )
        # - manual worker without usuario_id -> visible
        self.conn.execute(
            """
            INSERT INTO workspace_registro_personal (
              id, workspace_id, empresa_id, empresa_manual, usuario_id, usuario_manual, source, nombre, email, activo, created_at, updated_at
            ) VALUES ('p_manual','ws1','e1',1,NULL,0,'manual','Manual','manual@example.com',1,datetime('now'),datetime('now'))
            """
        )
        # - wrongly linked to u2 (not member of ws1) -> must be hidden
        self.conn.execute(
            """
            INSERT INTO workspace_registro_personal (
              id, workspace_id, empresa_id, empresa_manual, usuario_id, usuario_manual, source, nombre, email, activo, created_at, updated_at
            ) VALUES ('p_leak','ws1','e1',1,'u2',1,'manual','Leak','leak@example.com',1,datetime('now'),datetime('now'))
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_fetch_workspace_personal_hides_non_member_user_links(self):
        rows = fetch_workspace_personal(self.conn, "ws1", only_active=True, limit=50)["rows"]
        ids = {row["id"] for row in rows}
        self.assertIn("p_ok", ids)
        self.assertIn("p_manual", ids)
        self.assertNotIn("p_leak", ids)


if __name__ == "__main__":
    unittest.main()

