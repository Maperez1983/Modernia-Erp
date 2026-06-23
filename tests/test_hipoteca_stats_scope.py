import sys
import types
import unittest
from pathlib import Path

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


class HipotecaStatsScopeTests(unittest.TestCase):
    def test_hipoteca_stats_uses_consistent_alias_for_workspace_scope(self):
        source = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")
        marker = 'if path == "/api/hipoteca_stats":'
        start = source.index(marker)
        end = source.index('if path == "/api/hipoteca_dashboard":', start)
        block = source[start:end]
        self.assertIn('build_service_scope_filter(conn, "hipotecas", "h", workspace_id, empresa_id)', block)
        self.assertIn("SELECT COUNT(*) AS total FROM hipotecas h WHERE {scope_clause}", block)
        self.assertIn("FROM hipotecas h", block)


if __name__ == "__main__":
    unittest.main()
