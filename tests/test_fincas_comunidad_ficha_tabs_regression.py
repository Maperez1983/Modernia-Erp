import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FincasComunidadFichaTabsRegressionTests(unittest.TestCase):
    def test_app_renders_ficha_button_and_modal(self):
        app_js = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-community-open="${row.id}"', app_js)
        self.assertIn("openWorkspaceFincasCommunityFicha(record)", app_js)

    def test_server_exposes_vecinos_and_documentos_endpoints(self):
        server_py = (ROOT / "web" / "server.py").read_text(encoding="utf-8")
        self.assertIn('if path == "/api/workspace_fincas_vecinos":', server_py)
        self.assertIn('if path == "/api/workspace_fincas_documentos":', server_py)
        self.assertIn('elif parsed.path == "/api/workspace_fincas_vecinos":', server_py)
        self.assertIn('elif parsed.path == "/api/workspace_fincas_documentos":', server_py)


if __name__ == "__main__":
    unittest.main()
