import sqlite3
import unittest

from web.server import resolve_workspace_scope_empresa_ids


class WorkspaceScopeEmpresaIdsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE empresas (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              activo INTEGER
            );
            CREATE TABLE workspaces (
              id TEXT PRIMARY KEY,
              nombre TEXT,
              slug TEXT
            );
            CREATE TABLE workspace_companies (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              legacy_empresa_id TEXT,
              nombre TEXT,
              activo INTEGER
            );
            CREATE TABLE workspace_empresas (
              id TEXT PRIMARY KEY,
              workspace_id TEXT NOT NULL,
              empresa_id TEXT NOT NULL
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_includes_explicit_empresa_id_when_workspace_has_no_links(self):
        ids = resolve_workspace_scope_empresa_ids(self.conn, "ws1", empresa_id="e1")
        self.assertEqual(ids, ["e1"])

    def test_prefers_workspace_companies_legacy_ids_and_appends_explicit_empresa_id(self):
        self.conn.execute(
            "INSERT INTO workspace_companies (id, workspace_id, legacy_empresa_id, nombre, activo) VALUES (?,?,?,?,?)",
            ("wc1", "ws1", "e10", "Empresa 10", 1),
        )
        self.conn.execute(
            "INSERT INTO workspace_companies (id, workspace_id, legacy_empresa_id, nombre, activo) VALUES (?,?,?,?,?)",
            ("wc2", "ws1", "e20", "Empresa 20", 1),
        )
        ids = resolve_workspace_scope_empresa_ids(self.conn, "ws1", empresa_id="e1")
        self.assertEqual(ids, ["e10", "e20", "e1"])

    def test_returns_only_workspace_scope_ids_when_empresa_id_not_provided(self):
        self.conn.execute(
            "INSERT INTO workspace_empresas (id, workspace_id, empresa_id) VALUES (?,?,?)",
            ("we1", "ws1", "e30"),
        )
        ids = resolve_workspace_scope_empresa_ids(self.conn, "ws1", empresa_id="")
        self.assertEqual(ids, ["e30"])


if __name__ == "__main__":
    unittest.main()

