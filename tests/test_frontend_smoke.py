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

    def test_standalone_login_fallback_yields_to_app_auth(self):
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (window.__APP_JS_LOADED && window.CRMAppAuth)", html)
        guard_pos = html.index("if (window.__APP_JS_LOADED && window.CRMAppAuth)")
        prevent_pos = html.index("event.preventDefault();", guard_pos)
        self.assertLess(guard_pos, prevent_pos)

    def test_login_sets_role_route_before_app_init(self):
        auth_js = (WEB_DIR / "app-auth.js").read_text(encoding="utf-8")
        route_pos = auth_js.index('params.set("holding", "1");')
        init_pos = auth_js.index("await deps.init();", route_pos)
        self.assertLess(route_pos, init_pos)
        self.assertIn('localStorage.getItem("crm.currentWorkspaceId")', auth_js)

    def test_gitignore_covers_local_runtime_artifacts(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/*.bak_*", gitignore)
        self.assertIn("*.sqlite-wal", gitignore)
        self.assertIn("__pycache__/", gitignore)


if __name__ == "__main__":
    unittest.main()
