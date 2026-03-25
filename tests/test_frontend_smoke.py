import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"


class FrontendSmokeTests(unittest.TestCase):
    def test_index_loads_frontend_modules(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("ui-foundation.js", html)
        self.assertIn("app-auth.js", html)
        self.assertIn("app-routing.js", html)
        self.assertIn("app.js", html)

    def test_frontend_modules_export_expected_globals(self):
        auth_js = (WEB_DIR / "app-auth.js").read_text(encoding="utf-8")
        routing_js = (WEB_DIR / "app-routing.js").read_text(encoding="utf-8")
        foundation_js = (WEB_DIR / "ui-foundation.js").read_text(encoding="utf-8")
        self.assertIn("window.CRMAppAuth", auth_js)
        self.assertIn("window.CRMAppRouting", routing_js)
        self.assertIn("window.CRMUI", foundation_js)

    def test_bank_branding_does_not_depend_on_remote_clearbit_logos(self):
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("logo.clearbit.com", app_js)

    def test_gitignore_covers_local_runtime_artifacts(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/*.bak_*", gitignore)
        self.assertIn("*.sqlite-wal", gitignore)
        self.assertIn("__pycache__/", gitignore)


if __name__ == "__main__":
    unittest.main()
