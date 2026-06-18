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

    def test_visible_service_cards_keep_click_and_href_invariants(self):
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn('coreCards.addEventListener("click", (event) => {', app_js)
        self.assertIn("const fallbackNavigate = () => {", app_js)
        self.assertIn('card.dataset.action = "crm-inmo";', app_js)
        self.assertIn('card.dataset.action = "crm-gestoria";', app_js)
        self.assertIn('card.dataset.action = "crm-seguros";', app_js)
        self.assertIn('card.dataset.action = "crm-fin";', app_js)
        self.assertIn('data-action="crm-inmo"', app_js)
        self.assertIn('data-action="crm-gestoria"', app_js)
        self.assertIn('data-action="crm-seguros"', app_js)
        self.assertIn('data-action="crm-fin"', app_js)

    def test_visible_home_cards_match_permission_guards(self):
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("const hasAdminWideAccess = (user) => {", app_js)
        self.assertIn("const canAccessSharedHomeModules = (user) => hasAdminWideAccess(user);", app_js)
        self.assertIn("if (hasAdminWideAccess(user)) return true;", app_js)
        self.assertIn("const isPriv = hasAdminWideAccess(user);", app_js)
        self.assertIn("const canManageWorkspace = Boolean(user && hasAdminWideAccess(user));", app_js)
        self.assertIn('if (!userCanAccessService("inmobiliaria")) return;', app_js)
        self.assertIn('if (!userCanAccessService("gestoria")) return;', app_js)
        self.assertIn('if (!userCanAccessService("seguros")) return;', app_js)
        self.assertIn('if (!userCanAccessService("financiaciones")) return;', app_js)
        self.assertIn("const openWorkspaceQuickAccessFromCompanyCard = (empresaName = \"\") => {", app_js)
        self.assertIn("if (name && openWorkspaceQuickAccessFromCompanyCard(name)) {", app_js)

    def test_workspace_copilot_includes_process_supervisor_feed(self):
        app_js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
        self.assertIn("Chat interno", app_js)
        self.assertIn('id="workspaceInternalCopilotFeed"', app_js)
        self.assertIn('id="workspaceInternalCopilotForm"', app_js)
        self.assertIn('"/api/internal_copilot_chat"', app_js)
        self.assertIn('"/api/internal_copilot_action"', app_js)
        self.assertIn("current_client_id", app_js)
        self.assertIn("current_seguro_id", app_js)
        self.assertIn("current_renta_entry_id", app_js)
        self.assertIn("current_hipoteca_id", app_js)
        self.assertIn("current_factura_id", app_js)
        self.assertIn("current_rrhh_document_id", app_js)
        self.assertIn("current_persona_id", app_js)
        self.assertIn("current_community_id", app_js)
        self.assertIn("renderWorkspaceInternalCopilotFeed", app_js)
        self.assertIn('name="attachment"', app_js)
        self.assertIn("multiple", app_js)
        self.assertIn("Supervisor de procesos", app_js)
        self.assertIn('id="workspaceProcessSupervisorFeed"', app_js)
        self.assertIn('id="workspaceProcessSupervisorHistory"', app_js)
        self.assertIn('data-copilot-process-action', app_js)
        self.assertIn('data-copilot-assistant-action', app_js)
        self.assertIn('"/api/internal_copilot_action"', app_js)
        self.assertIn("bulk_revalidate_processes", app_js)
        self.assertIn("bulk_safe_repair", app_js)
        self.assertIn("bulk_rerun_facturas_ocr", app_js)
        self.assertIn("resolve_domain_safe", app_js)
        self.assertIn("autorreview_domain", app_js)
        self.assertIn("autorreview_global", app_js)
        self.assertIn("start_review_queue", app_js)
        self.assertIn("continue_review_queue", app_js)
        self.assertIn("revalidate_current_and_continue", app_js)
        self.assertIn("post_actions", app_js)
        self.assertIn("refresh_supervisor", app_js)
        self.assertIn("Array.isArray(result?.actions)", app_js)
        self.assertIn("Array.isArray(result?.cards)", app_js)
        self.assertIn('"/api/workspace_process_supervisor_ack"', app_js)
        self.assertIn('"/api/workspace_process_supervisor_action"', app_js)
        self.assertIn("reload_dashboard_block", app_js)
        self.assertIn("reload_records", app_js)
        self.assertIn("refresh_client_summary", app_js)
        self.assertIn("revalidate_process", app_js)
        self.assertIn("state.pendingClienteOpen", app_js)
        self.assertIn("loadGestoriaDashboardDocumentos({ force: true })", app_js)
        self.assertIn("loadGestoriaDashboardContabilidad({ force: true })", app_js)
        self.assertIn("loadGestoriaDashboardGestiones({ force: true })", app_js)
        self.assertIn("loadGestoriaRentaDashboard({ force: true })", app_js)
        self.assertIn("loadGestoriaContabilidad()", app_js)
        self.assertIn("loadGestoriaFact()", app_js)
        self.assertIn("Ficha cliente refrescada", app_js)
        self.assertIn("Proceso validado", app_js)
        self.assertIn("OCR relanzado", app_js)
        self.assertIn("handleProcessSupervisorResponse", app_js)
        self.assertIn("loadWorkspaceProcessSupervisorHistory", app_js)

    def test_gitignore_covers_local_runtime_artifacts(self):
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/*.bak_*", gitignore)
        self.assertIn("*.sqlite-wal", gitignore)
        self.assertIn("__pycache__/", gitignore)


if __name__ == "__main__":
    unittest.main()
