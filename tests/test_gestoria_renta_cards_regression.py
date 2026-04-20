import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GestoriaRentaCardsRegressionTests(unittest.TestCase):
    def test_gestoria_renta_cards_docs_order_by_casts_fecha_to_text(self):
        """
        Regression: en Postgres, `COALESCE(fecha, '')` puede fallar si `fecha` no es TEXT.
        Aseguramos que el ORDER BY en `/api/gestoria_renta_cards` castea `fecha` a TEXT.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("CAST(fecha AS TEXT)", server_py)

    def test_gestoria_renta_cards_docs_where_uses_boolean_false_clause(self):
        """
        Regression: en Postgres, `OR 0` falla (0 no es boolean).
        Usamos `1=0` como condición siempre falsa portable.
        """
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('doc_id_clause = "1=0"', server_py)
        self.assertIn('ref_id_clause = "1=0"', server_py)

    def test_s3_legacy_candidates_include_gestoria_prefix(self):
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('prefixes = ["gestoria", "gestoria_docs", "docs", "renta", "rentas"]', server_py)

    def test_gestoria_docs_api_sanitizes_placeholder_doc_key(self):
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn("_looks_like_placeholder_doc_key", server_py)
        self.assertIn("_is_public_doc_url", server_py)
        self.assertIn("renta_doc_by_doc_id", server_py)
        self.assertIn("renta_doc_by_ref_id", server_py)


if __name__ == "__main__":
    unittest.main()
