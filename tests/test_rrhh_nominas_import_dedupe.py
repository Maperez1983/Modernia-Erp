import unittest

from web.server import ensure_workspace_core_tables, ensure_workspace_product_tables, get_db, normalize_nif


class RrhhNominasImportDedupeTests(unittest.TestCase):
    def test_dedupe_query_finds_existing(self):
        conn = get_db(":memory:")
        ensure_workspace_core_tables(conn)
        ensure_workspace_product_tables(conn)
        ws = "ws1"
        persona = "p1"
        nif = normalize_nif("Z0068840Y")
        conn.execute(
            """
            INSERT INTO workspace_rrhh_documentos (
              id, workspace_id, empresa_id, persona_id, tipo, nombre, doc_key, doc_url,
              permanente, estado,
              nomina_year, nomina_month, nomina_empleado_nif,
              created_at, updated_at
            ) VALUES (
              'd1', ?, NULL, ?, 'Nómina', 'x.pdf', 'k', 'u',
              1, 'Activo',
              2026, 2, ?,
              datetime('now'), datetime('now')
            )
            """,
            (ws, persona, nif),
        )
        row = conn.execute(
            """
            SELECT id
            FROM workspace_rrhh_documentos
            WHERE workspace_id = ?
              AND persona_id = ?
              AND LOWER(COALESCE(tipo,'')) IN ('nómina','nomina')
              AND COALESCE(nomina_year, 0) = ?
              AND COALESCE(nomina_month, 0) = ?
            LIMIT 1
            """,
            (ws, persona, 2026, 2),
        ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()

