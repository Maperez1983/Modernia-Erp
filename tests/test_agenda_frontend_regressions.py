import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web" / "app.js"
SERVER_PY = ROOT / "web" / "server.py"


class AgendaFrontendRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_js = APP_JS.read_text(encoding="utf-8")
        cls.server_py = SERVER_PY.read_text(encoding="utf-8")

    def test_agenda_filters_do_not_fallback_to_all_rows(self):
        render_fn_start = self.app_js.index("const renderCrmAgendaWorkspace = () => {")
        render_fn_end = self.app_js.index("const applyCrmAgendaFilters = (rows = []) => {", render_fn_start)
        render_fn = self.app_js[render_fn_start:render_fn_end]

        self.assertNotIn("filtered = all.slice()", render_fn)
        self.assertNotIn("evita “agenda vacía”", render_fn)

    def test_editing_existing_action_does_not_apply_current_context_relations(self):
        save_start = self.app_js.index("if (actionModalSave) {")
        save_end = self.app_js.index("const conflict = lastAgendaEvents.find", save_start)
        save_block = self.app_js[save_start:save_end]

        self.assertIn("if (!editId) {", save_block)
        self.assertIn('["asesoramiento_id", "inmueble_id", "related_id", "related_tipo"].forEach', save_block)

        relations_pos = save_block.index('["asesoramiento_id", "inmueble_id", "related_id", "related_tipo"].forEach')
        guard_pos = save_block.rfind("if (!editId) {", 0, relations_pos)
        self.assertGreaterEqual(guard_pos, 0)

    def test_all_action_creates_use_scoped_api_post(self):
        self.assertNotIn('fetch("/api/acciones"', self.app_js)
        self.assertIn('apiPost("/api/acciones"', self.app_js)

    def test_cross_service_agenda_reads_use_scope_builder(self):
        self.assertIn("const buildAgendaActionParams = (servicio, extra = {}) => {", self.app_js)
        self.assertIn("resolveAgendaEmpresaIdForService(servicio)", self.app_js)
        self.assertIn('buildAgendaActionParams(servicio, { cliente_id: clienteId })', self.app_js)

    def test_backend_rejects_cross_service_action_mutations(self):
        self.assertIn('payload_service and current_service and payload_service != current_service', self.server_py)
        self.assertIn('"La acción no pertenece al servicio indicado"', self.server_py)
        self.assertIn('"La acción pertenece a otro workspace"', self.server_py)

    def test_admin_role_or_service_keeps_access_to_crm_cards(self):
        self.assertIn("const hasAdminWideAccess = (user) => {", self.app_js)
        self.assertIn('if (isPrivilegedRole(user.rol || "")) return true;', self.app_js)
        self.assertIn('if (isPrivilegedService(user.servicio || "")) return true;', self.app_js)
        self.assertIn("const canAccessSharedHomeModules = (user) => hasAdminWideAccess(user);", self.app_js)
        self.assertIn("if (hasAdminWideAccess(user)) return true;", self.app_js)


if __name__ == "__main__":
    unittest.main()
