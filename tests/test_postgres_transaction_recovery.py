import unittest
from unittest.mock import patch

from web.schema_support import table_columns
from web.server import fetch_workspace_company_ids, get_platform_empresa_id


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RollbackTrackingConn:
    __crm_backend__ = "postgres"

    def __init__(self):
        self.rollback_calls = 0

    def rollback(self):
        self.rollback_calls += 1


class TableColumnsTransactionRecoveryTests(unittest.TestCase):
    def test_table_columns_rolls_back_when_postgres_query_fails(self):
        class Conn(_RollbackTrackingConn):
            def execute(self, sql, params=None):
                if "information_schema.columns" in str(sql):
                    raise RuntimeError("boom")
                raise AssertionError(f"Unexpected SQL: {sql}")

        conn = Conn()
        cols = table_columns(conn, "gestoria")
        self.assertEqual(cols, set())
        self.assertEqual(conn.rollback_calls, 1)


class WorkspaceCompanyIdsTransactionRecoveryTests(unittest.TestCase):
    def test_fetch_workspace_company_ids_rolls_back_before_followup_queries(self):
        class Conn(_RollbackTrackingConn):
            def execute(self, sql, params=None):
                sql_text = " ".join(str(sql).split())
                if "SELECT empresa_id FROM workspace_empresas" in sql_text:
                    if self.rollback_calls == 0:
                        raise AssertionError("fetch_workspace_company_ids continued without rollback")
                    return _FakeResult([("empresa-1",)])
                if "SELECT DISTINCT empresa_id FROM workspace_registro_personal" in sql_text:
                    return _FakeResult([])
                if "SELECT COUNT(*) AS total FROM workspaces" in sql_text:
                    return _FakeResult([(1,)])
                if "SELECT slug, nombre FROM workspaces WHERE id = ? LIMIT 1" in sql_text:
                    return _FakeResult([])
                if "SELECT id FROM empresas WHERE COALESCE(activo, 1) = 1 ORDER BY nombre" in sql_text:
                    return _FakeResult([])
                if "INSERT OR IGNORE INTO workspace_empresas" in sql_text:
                    return _FakeResult([])
                raise AssertionError(f"Unexpected SQL: {sql_text}")

        conn = Conn()

        with patch("web.server.ensure_workspace_core_tables", side_effect=RuntimeError("boom")):
            ids = fetch_workspace_company_ids(conn, "ws-1")

        self.assertEqual(ids, ["empresa-1"])
        self.assertGreaterEqual(conn.rollback_calls, 1)


class PlatformEmpresaIdTransactionRecoveryTests(unittest.TestCase):
    def test_get_platform_empresa_id_rolls_back_before_fallback_lookup(self):
        class Conn(_RollbackTrackingConn):
            def __init__(self):
                super().__init__()
                self.insert_calls = 0

            def execute(self, sql, params=None):
                sql_text = " ".join(str(sql).split())
                if "SELECT value FROM crm_meta" in sql_text:
                    raise RuntimeError("boom")
                if "SELECT id FROM empresas WHERE LOWER(TRIM(nombre)) IN" in sql_text:
                    if self.rollback_calls == 0:
                        raise AssertionError("fallback lookup ran before rollback")
                    return _FakeResult([("empresa-1",)])
                if "INSERT INTO crm_meta" in sql_text:
                    self.insert_calls += 1
                    return _FakeResult([])
                raise AssertionError(f"Unexpected SQL: {sql_text}")

            def commit(self):
                return None

        conn = Conn()

        eid = get_platform_empresa_id(conn)

        self.assertEqual(eid, "empresa-1")
        self.assertGreaterEqual(conn.rollback_calls, 1)
        self.assertEqual(conn.insert_calls, 1)


if __name__ == "__main__":
    unittest.main()
