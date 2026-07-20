import json
import shutil
import subprocess
import unittest
from pathlib import Path
from textwrap import dedent, indent


ROOT = Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def extract_segment(start_marker: str, end_marker: str) -> str:
    start = APP_SOURCE.index(start_marker)
    end = APP_SOURCE.index(end_marker, start)
    return APP_SOURCE[start:end]


def run_node_script(script: str) -> None:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node no está disponible")
    subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)


def make_factory_script(
    segment: str,
    param_names: list[str],
    return_names: list[str],
    prelude: str,
    body: str,
) -> str:
    factory_source = segment + "\nreturn { " + ", ".join(return_names) + " };"
    factory_params = ", ".join(json.dumps(name) for name in param_names)
    factory_args = ", ".join(param_names)
    factory_call = f"factory({factory_args})" if factory_args else "factory()"
    return dedent(
        f"""
        const assert = require("assert");
        const factory = new Function({factory_params}{", " if factory_params else ""}{json.dumps(factory_source)});
        {prelude}
        const api = {factory_call};
        (async () => {{
        {indent(body, "  ")}
        }})().catch((err) => {{
          console.error(err);
          process.exit(1);
        }});
        """
    )


class FrontendInmoScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const resolveInmoClienteLinkScope =",
            "const createCrmCaptacionQuick = async",
        )
        cls.param_names = [
            "state",
            "resolveEmpresaById",
            "resolveLegacyEmpresaId",
            "resolveCrmInmoEmpresa",
            "getStoredServiceCompanyId",
            "getWorkspaceDefaultCompanyIdForServiceKey",
            "resolveInmoScopeParams",
            "isTenantWorkspaceMode",
            "randomId",
            "fetch",
            "postJsonWithDbRetry",
        ]
        cls.return_names = ["resolveInmoClienteLinkScope", "createCrmClienteQuick"]

    def _run(self, prelude: str, body: str) -> None:
        script = make_factory_script(self.segment, self.param_names, self.return_names, prelude, body)
        run_node_script(script)

    def test_flow_preserves_explicit_workspace_and_company(self):
        self._run(
            dedent(
                """
                const state = {
                  currentWorkspaceId: "ws-1",
                  currentWorkspaceCompanyId: "emp-other",
                  currentWorkspaceCompanyWsId: "ws-other",
                  crmInmoEmpresaId: "",
                };
                const companies = new Map([
                  ["emp-1", { id: "emp-1", legacy_empresa_id: "emp-1", nombre: "Inmo Activa" }],
                  ["emp-other", { id: "emp-other", legacy_empresa_id: "emp-other", nombre: "Gestoría Global" }],
                ]);
                const resolveEmpresaById = (id) => companies.get(String(id || "").trim()) || null;
                const resolveLegacyEmpresaId = (empresa) => String((empresa && (empresa.legacy_empresa_id || empresa.id)) || "").trim();
                const resolveCrmInmoEmpresa = () => companies.get("emp-1");
                const getStoredServiceCompanyId = () => "";
                const getWorkspaceDefaultCompanyIdForServiceKey = () => "";
                const resolveInmoScopeParams = () => ({ workspace_id: "ws-1", empresa_id: "emp-1" });
                const isTenantWorkspaceMode = () => false;
                const randomId = () => "client-1";
                globalThis.SERVICE_COMPANY_MAP = { Inmobiliaria: "Inmo Activa" };
                globalThis.getWorkspaceCompanyById = (id) => companies.get(String(id || "").trim()) || null;
                const fetchCalls = [];
                const fetch = async (url, options) => {
                  fetchCalls.push([url, options]);
                  return {
                    status: 200,
                    json: async () => ({ id: "client-1" }),
                  };
                };
                const linkCalls = [];
                const postJsonWithDbRetry = async (url, payload) => {
                  linkCalls.push([url, payload]);
                  return { ok: true };
                };
                """
            ),
            dedent(
                """
                const { resolveInmoClienteLinkScope, createCrmClienteQuick } = api;
                assert.deepStrictEqual(resolveInmoClienteLinkScope(resolveInmoScopeParams()), {
                  workspace_id: "ws-1",
                  empresa_id: "emp-1",
                });
                const clienteId = await createCrmClienteQuick({ nombre: "Cliente Demo" });
                assert.strictEqual(clienteId, "client-1");
                assert.strictEqual(fetchCalls.length, 1);
                assert.strictEqual(fetchCalls[0][0], "/api/clientes");
                assert.strictEqual(linkCalls.length, 1);
                const [url, payload] = linkCalls[0];
                assert.strictEqual(url, "/api/clientes_link");
                assert.strictEqual(payload.workspace_id, "ws-1");
                assert.strictEqual(payload.empresa_id, "emp-1");
                assert.strictEqual(payload.servicio, "Inmobiliaria");
                assert.ok(payload.empresa_id);
                """
            ),
        )

    def test_scope_helper_prefers_inmo_company_over_other_active_company(self):
        self._run(
            dedent(
                """
                const state = {
                  currentWorkspaceId: "ws-1",
                  currentWorkspaceCompanyId: "emp-other",
                  currentWorkspaceCompanyWsId: "ws-other",
                  crmInmoEmpresaId: "",
                };
                const companies = new Map([
                  ["emp-inmo", { id: "emp-inmo", legacy_empresa_id: "emp-inmo", nombre: "Inmo Activa" }],
                  ["emp-other", { id: "emp-other", legacy_empresa_id: "emp-other", nombre: "Gestoría Global" }],
                ]);
                const resolveEmpresaById = (id) => companies.get(String(id || "").trim()) || null;
                const resolveLegacyEmpresaId = (empresa) => String((empresa && (empresa.legacy_empresa_id || empresa.id)) || "").trim();
                const resolveCrmInmoEmpresa = () => companies.get("emp-inmo");
                const getStoredServiceCompanyId = () => "";
                const getWorkspaceDefaultCompanyIdForServiceKey = () => "";
                const resolveInmoScopeParams = () => ({ workspace_id: "ws-1" });
                const isTenantWorkspaceMode = () => false;
                const randomId = () => "client-1";
                globalThis.SERVICE_COMPANY_MAP = { Inmobiliaria: "Inmo Activa" };
                globalThis.getWorkspaceCompanyById = (id) => companies.get(String(id || "").trim()) || null;
                const fetchCalls = [];
                const fetch = async (url, options) => {
                  fetchCalls.push([url, options]);
                  return {
                    status: 200,
                    json: async () => ({ id: "client-1" }),
                  };
                };
                const linkCalls = [];
                const postJsonWithDbRetry = async (url, payload) => {
                  linkCalls.push([url, payload]);
                  return { ok: true };
                };
                """
            ),
            dedent(
                """
                const { resolveInmoClienteLinkScope, createCrmClienteQuick } = api;
                assert.deepStrictEqual(resolveInmoClienteLinkScope(resolveInmoScopeParams()), {
                  workspace_id: "ws-1",
                  empresa_id: "emp-inmo",
                });
                await createCrmClienteQuick({ nombre: "Cliente Demo" });
                assert.strictEqual(fetchCalls.length, 1);
                assert.strictEqual(linkCalls.length, 1);
                const payload = linkCalls[0][1];
                assert.strictEqual(payload.workspace_id, "ws-1");
                assert.strictEqual(payload.empresa_id, "emp-inmo");
                assert.notStrictEqual(payload.empresa_id, "emp-other");
                """
            ),
        )

    def test_scope_helper_returns_null_without_resolvable_company(self):
        self._run(
            dedent(
                """
                const state = {
                  currentWorkspaceId: "ws-1",
                  currentWorkspaceCompanyId: "",
                  currentWorkspaceCompanyWsId: "",
                  crmInmoEmpresaId: "",
                };
                const resolveEmpresaById = () => null;
                const resolveLegacyEmpresaId = (empresa) => String((empresa && (empresa.legacy_empresa_id || empresa.id)) || "").trim();
                const resolveCrmInmoEmpresa = () => null;
                const getStoredServiceCompanyId = () => "";
                const getWorkspaceDefaultCompanyIdForServiceKey = () => "";
                const resolveInmoScopeParams = () => ({ workspace_id: "ws-1" });
                const isTenantWorkspaceMode = () => false;
                const randomId = () => "client-1";
                globalThis.SERVICE_COMPANY_MAP = { Inmobiliaria: "Inmo Activa" };
                globalThis.getWorkspaceCompanyById = () => null;
                const fetchCalls = [];
                const fetch = async (url, options) => {
                  fetchCalls.push([url, options]);
                  return {
                    status: 200,
                    json: async () => ({ id: "client-1" }),
                  };
                };
                const linkCalls = [];
                const postJsonWithDbRetry = async (url, payload) => {
                  linkCalls.push([url, payload]);
                  return { ok: true };
                };
                """
            ),
            dedent(
                """
                const { resolveInmoClienteLinkScope, createCrmClienteQuick } = api;
                assert.strictEqual(resolveInmoClienteLinkScope(resolveInmoScopeParams()), null);
                await assert.rejects(
                  () => createCrmClienteQuick({ nombre: "Cliente Demo" }),
                  /No se pudo resolver la empresa Inmobiliaria activa\\./
                );
                assert.strictEqual(fetchCalls.length, 0);
                assert.strictEqual(linkCalls.length, 0);
                """
            ),
        )

    def test_scope_helper_does_not_use_other_service_company(self):
        self._run(
            dedent(
                """
                const state = {
                  currentWorkspaceId: "ws-1",
                  currentWorkspaceCompanyId: "emp-other",
                  currentWorkspaceCompanyWsId: "ws-other",
                  crmInmoEmpresaId: "",
                };
                const companies = new Map([
                  ["emp-other", { id: "emp-other", legacy_empresa_id: "emp-other", nombre: "Gestoría Global" }],
                ]);
                const resolveEmpresaById = (id) => companies.get(String(id || "").trim()) || null;
                const resolveLegacyEmpresaId = (empresa) => String((empresa && (empresa.legacy_empresa_id || empresa.id)) || "").trim();
                const resolveCrmInmoEmpresa = () => null;
                const getStoredServiceCompanyId = () => "";
                const getWorkspaceDefaultCompanyIdForServiceKey = () => "";
                const resolveInmoScopeParams = () => ({ workspace_id: "ws-1" });
                const isTenantWorkspaceMode = () => false;
                const randomId = () => "client-1";
                globalThis.SERVICE_COMPANY_MAP = { Inmobiliaria: "Inmo Activa" };
                globalThis.getWorkspaceCompanyById = (id) => companies.get(String(id || "").trim()) || null;
                const fetchCalls = [];
                const fetch = async (url, options) => {
                  fetchCalls.push([url, options]);
                  return {
                    status: 200,
                    json: async () => ({ id: "client-1" }),
                  };
                };
                const linkCalls = [];
                const postJsonWithDbRetry = async (url, payload) => {
                  linkCalls.push([url, payload]);
                  return { ok: true };
                };
                """
            ),
            dedent(
                """
                const { resolveInmoClienteLinkScope, createCrmClienteQuick } = api;
                assert.strictEqual(resolveInmoClienteLinkScope(resolveInmoScopeParams()), null);
                await assert.rejects(
                  () => createCrmClienteQuick({ nombre: "Cliente Demo" }),
                  /No se pudo resolver la empresa Inmobiliaria activa\\./
                );
                assert.strictEqual(fetchCalls.length, 0);
                assert.strictEqual(linkCalls.length, 0);
                """
            ),
        )


class HipotecaFichaResetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const resetHipotecaFichaFormState =",
            "const fetchHipotecaRowById = async",
        )
        cls.return_names = ["resetHipotecaFichaFormState"]

    def _run(self, body: str) -> None:
        script = make_factory_script(self.segment, [], self.return_names, "", body)
        run_node_script(script)

    def test_reset_clears_disabled_controls(self):
        self._run(
            dedent(
                """
                const controls = [
                  { tagName: "INPUT", type: "text", value: "cliente viejo", disabled: true },
                  { tagName: "INPUT", type: "checkbox", checked: true, value: "on", disabled: true },
                  { tagName: "SELECT", value: "old-option", disabled: true },
                  { tagName: "TEXTAREA", value: "observaciones antiguas", disabled: true },
                ];
                const form = {
                  querySelectorAll: () => controls,
                };
                const panel = {
                  querySelector: (selector) => (selector === "#hipotecaFichaForm" ? form : null),
                };
                const { resetHipotecaFichaFormState } = api;
                resetHipotecaFichaFormState(panel);
                assert.strictEqual(controls[0].value, "");
                assert.strictEqual(controls[1].checked, false);
                assert.strictEqual(controls[2].value, "");
                assert.strictEqual(controls[3].value, "");
                """
            ),
        )


class HipotecaBdtCardMetricsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const getHipotecaFieldValue =",
            "const renderHipotecaBdtTable =",
        )
        cls.return_names = ["renderHipotecaBdtCards"]

    def _run(self, body: str, prelude: str = "") -> None:
        script = make_factory_script(self.segment, [], self.return_names, prelude, body)
        run_node_script(script)

    def test_cards_show_signature_date_and_elapsed_days(self):
        self._run(
            body=dedent(
                """
                const { renderHipotecaBdtCards } = api;
                const columns = [
                  "id",
                  "cliente",
                  "banco",
                  "oficina",
                  "importe_hipoteca",
                  "comision",
                  "fecha_encargo",
                  "fecha_firma",
                  "hipoteca_detalle_json",
                ];
                const rows = [[
                  "h1",
                  "Cliente Demo",
                  "Banco Demo",
                  "Oficina Centro",
                  150000,
                  1800,
                  "2026-06-15",
                  "2026-06-20",
                  "{}",
                ]];
                renderHipotecaBdtCards({ columns, rows });
                const text = flattenText(hipotecaBdtTable);
                assert.ok(text.includes("Fecha firma"));
                assert.ok(text.includes("20/06/2026"));
                assert.ok(text.includes("Días encargo→firma"));
                assert.ok(text.includes("5 días"));
                """
            ),
            prelude=dedent(
                """
                class FakeNode {
                  constructor(tag = "div") {
                    this.tagName = String(tag || "div").toUpperCase();
                    this.children = [];
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.textContent = "";
                    this.innerHTML = "";
                    this.attributes = {};
                    this.classList = {
                      add() {},
                      remove() {},
                      toggle() {},
                    };
                  }
                  get childElementCount() {
                    return this.children.length;
                  }
                  appendChild(child) {
                    this.children.push(child);
                    return child;
                  }
                  addEventListener() {}
                  setAttribute(name, value) {
                    this.attributes[name] = String(value);
                  }
                  replaceWith(node) {
                    this.replacedWith = node;
                  }
                  querySelector() {
                    return null;
                  }
                  querySelectorAll() {
                    return [];
                  }
                  closest() {
                    return null;
                  }
                }
                const flattenText = (node) => {
                  const pieces = [];
                  const walk = (current) => {
                    if (current === null || current === undefined) return;
                    if (typeof current === "string") {
                      const text = String(current).trim();
                      if (text) pieces.push(text);
                      return;
                    }
                    const text = String(current.textContent || "").trim();
                    if (text) pieces.push(text);
                    if (Array.isArray(current.children)) current.children.forEach(walk);
                  };
                  walk(node);
                  return pieces.join(" ");
                };
                const document = {
                  createElement: (tag) => new FakeNode(tag),
                };
                const hipotecaBdtTable = new FakeNode("div");
                const resolveHipotecaBankBrand = () => ({
                  logo: "",
                  displayName: "Banco Demo",
                  short: "BD",
                  color: "#123024",
                });
                const openHipotecaFicha = () => {};
                const deleteHipoteca = async () => ({ ok: true });
                const loadHipotecaBdt = () => {};
                const loadFinCrm = () => {};
                const loadHipotecaDashboard = () => {};
                const loadHomeHipotecaStats = async () => ({ ok: true });
                const renderCompanyCards = () => {};
                const safeParseJsonObject = () => ({});
                const getNestedValue = () => "";
                const normalizePrestatariaSource = () => "none";
                const normalizeSimple = (value) => String(value || "").trim().toLowerCase();
                const toNumber = (value) => Number(value);
                const formatEurosCompact = (value) => `${Number(value || 0).toFixed(2)} €`;
                const formatPercent = (value) => `${Number(value || 0).toFixed(2)} %`;
                """
            ),
        )


class HipotecaBdtListadoPrintPopupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const openHipotecaBdtListadoPrint = async (popup = null) => {",
            "const renderHipotecaBdtFromCache = () => {",
        )
        cls.return_names = ["openHipotecaBdtListadoPrint"]

    def _run(self, body: str, prelude: str = "") -> None:
        script = make_factory_script(self.segment, [], self.return_names, prelude, body)
        run_node_script(script)

    def test_print_listado_uses_preopened_popup_when_available(self):
        self._run(
            body=dedent(
                """
                const { openHipotecaBdtListadoPrint } = api;
                const popup = {
                  closed: false,
                  location: { href: "about:blank" },
                  focus() {
                    this.focused = true;
                  },
                  close() {
                    this.closed = true;
                  },
                };
                const result = await openHipotecaBdtListadoPrint(popup);
                assert.strictEqual(result, true);
                assert.strictEqual(writeCalls.length, 1);
                assert.strictEqual(writeCalls[0].popup, popup);
                assert.strictEqual(writeCalls[0].payload.title, "Listado de hipotecas");
                assert.strictEqual(writeCalls[0].payload.html, "<div>PDF de prueba</div>");
                assert.strictEqual(popup.focused, true);
                assert.strictEqual(popup.closed, false);
                assert.strictEqual(openFallbackCalls.length, 0);
                """
            ),
            prelude=dedent(
                """
                const writeCalls = [];
                const openFallbackCalls = [];
                const state = globalThis.state = {
                  hipotecaBdtCache: {
                    data: {
                      columns: ["id", "cliente", "banco", "fecha_firma", "importe_hipoteca", "comision"],
                      rows: [["h1", "Cliente Demo", "Banco Demo", "2026-06-20", 150000, 1800]],
                      filters: { year: "2026", estado: "Firmada", order: "desc" },
                    },
                  },
                };
                globalThis.loadHipotecaBdt = async () => {
                  throw new Error("loadHipotecaBdt no debería ejecutarse con caché disponible");
                };
                globalThis.getHipotecaBdtListadoFilters = () => ({
                  query: "",
                  year: "2026",
                  estado: "Firmada",
                  order: "desc",
                });
                globalThis.filterHipotecaBdtRows = (rows, columns, query, filters, options) => {
                  assert.strictEqual(query, "");
                  assert.strictEqual(filters.year, "2026");
                  assert.strictEqual(filters.estado, "Firmada");
                  assert.strictEqual(options.limit, Infinity);
                  return {
                    filtered: rows,
                    filters,
                  };
                };
                globalThis.buildHipotecaListadoPrintHtml = () => "<div>PDF de prueba</div>";
                globalThis.writeCrmPrintWindow = (popup, payload) => {
                  writeCalls.push({ popup, payload });
                  return true;
                };
                globalThis.openCrmPrintWindow = (...args) => {
                  openFallbackCalls.push(args);
                  throw new Error("fallback no esperado");
                };
                """
            ),
        )


class HipotecaBdtDisplayNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const getHipotecaFieldValue =",
            "const renderHipotecaBdtTable =",
        )
        cls.return_names = ["getHipotecaDisplayName"]

    def _run(self, body: str, prelude: str = "") -> None:
        script = make_factory_script(self.segment, [], self.return_names, prelude, body)
        run_node_script(script)

    def test_display_name_prefers_cliente_inmueble_json_in_print_listado(self):
        self._run(
            body=dedent(
                """
                const { getHipotecaDisplayName } = api;
                const columns = [
                  "id",
                  "cliente",
                  "cliente_inmueble_json",
                  "banco",
                  "importe_hipoteca",
                  "comision",
                  "fecha_firma",
                ];
                const jsonRow = [
                  "h1",
                  "",
                  JSON.stringify({
                    prestataria: {
                      p1: { nombre: "Cliente JSON" },
                    },
                  }),
                  "Banco Demo",
                  150000,
                  1800,
                  "2026-06-20",
                ];
                assert.strictEqual(getHipotecaDisplayName(jsonRow, columns), "Cliente JSON");
                const fallbackRow = [
                  "h2",
                  "Cliente Base",
                  "",
                  "Banco Demo",
                  120000,
                  1600,
                  "2026-06-21",
                ];
                assert.strictEqual(getHipotecaDisplayName(fallbackRow, columns), "Cliente Base");
                """
            ),
        )


class InmuebleDetailRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const openInmuebleDetail =",
            "if (inmuebleManualSaveBtn)",
        ).replace("api(", "globalThis.api(")
        cls.return_names = ["openInmuebleDetail"]

    def _run(self, initial_tab: str, body: str) -> None:
        prelude = dedent(
            f"""
            const tabCalls = [];
            const makeNode = () => ({{
              textContent: "",
              innerHTML: "",
              classList: {{
                add() {{}},
                remove() {{}},
                toggle() {{}},
              }},
            }});
            const state = globalThis.state = {{
              currentInmuebleTabKey: {json.dumps(initial_tab)},
              pendingInmuebleCitaPrefill: null,
              booting: false,
              currentWorkspaceCompanyId: "emp-other",
              crmWorkspaceView: "inmuebles",
            }};
            globalThis.inmuebleDetail = {{}};
            globalThis.empresaSelect = {{ value: "" }};
            globalThis.inmuebleTitle = makeNode();
            globalThis.inmuebleSubtitle = makeNode();
            globalThis.inmuebleDatosGrid = null;
            globalThis.inmuebleCaptacionGrid = null;
            globalThis.inmuebleNoticiaGrid = null;
            globalThis.inmuebleDemandaCliente = null;
            globalThis.inmuebleVisitaDemanda = null;
            globalThis.inmuebleActividadClientes = null;
            globalThis.inmuebleMap = null;
            globalThis.inmuebleEstadoInfo = null;
            globalThis.inmuebleDocsList = null;
            globalThis.inmuebleTecnoActions = null;
            globalThis.inmuebleActividadForm = null;
            globalThis.pendingInlineEdits = {{
              inmueble: new Map(),
              captacion: new Map(),
            }};
            globalThis.window = {{
              location: {{ search: "?workspace=ws-1" }},
              scrollTo() {{}},
            }};
            globalThis.normalizeInmuebleTabKey = (tab) => {{
              const key = String(tab || "").trim();
              if (!key) return "datos";
              if (key === "docs") return "adjuntos";
              return key;
            }};
            globalThis.setInmuebleTab = (tab) => {{
              const key = globalThis.normalizeInmuebleTabKey(tab);
              tabCalls.push(key);
              state.currentInmuebleTabKey = key;
            }};
            globalThis.syncInmuebleManualSaveButton = () => {{}};
            globalThis.setInmuebleSaveStatus = () => {{}};
            globalThis.setCrmWorkspaceView = () => {{}};
            globalThis.ensureTenantParams = () => {{}};
            globalThis.setUrlParams = () => {{}};
            globalThis.updateTableVisibility = () => {{}};
            globalThis.resetInmuebleActividadForm = () => {{}};
            globalThis.normalizeInmobiliariaPersona = (value) => String(value || "").trim();
            globalThis.inferInmobiliariaCategoria = () => "vivienda";
            globalThis.resolveInmuebleTipoOperacion = () => "venta";
            globalThis.resolveInmuebleMainEtapa = () => "Inmueble";
            globalThis.resolveCaptacionCodePrefix = () => "INM";
            globalThis.loadClientesList = () => Promise.resolve([]);
            globalThis.api = async () => ({{
              inmueble: {{
                id: "inv-1",
                empresa_id: "emp-1",
                titulo: "Casa Demo",
                direccion: "Calle 1",
                referencia: "REF-1",
                poblacion: "Madrid",
              }},
              captacion: {{}},
              propietarios: [],
              docs: [],
              servicios: [],
            }});
            globalThis.pushCrmRecentItem = () => {{}};
            globalThis.renderEditableGrid = () => {{}};
            globalThis.renderPropietariosEditor = () => {{}};
            globalThis.bindPostalLookup = () => {{}};
            globalThis.loadDemandasList = async () => [];
            globalThis.populateDemandasSelect = () => {{}};
            globalThis.populateClientesSelect = () => {{}};
            globalThis.scheduleAutoInmuebleCatastroLookup = () => {{}};
            globalThis.buildInmuebleDisplayAddress = () => "";
            globalThis.getInmuebleCatastroInputMapFromDom = () => ({{}});
            globalThis.loadInmuebleChecklist = () => {{}};
            globalThis.refreshCurrentInmuebleProfile = () => {{}};
            globalThis.renderInmuebleValoracionTab = () => {{}};
            globalThis.refreshInmuebleVisitSheetButton = () => {{}};
            globalThis.loadInmuebleDemandas = () => {{}};
            globalThis.loadInmuebleCompradores = () => {{}};
            globalThis.loadInmuebleVisitas = () => {{}};
            globalThis.loadInmuebleActividad = () => {{}};
            globalThis.loadInmuebleDocs = () => {{}};
            globalThis.getPendingInlineEditsCount = () => 0;
            globalThis.syncInmuebleArchivePendingButton = () => {{}};
            globalThis.syncInmuebleEncargoCloseButton = () => {{}};
            globalThis.syncInmuebleEncargoModalButton = () => {{}};
            globalThis.syncInmuebleNoticiaTab = () => {{}};
            globalThis.applyPendingInmuebleCitaPrefill = () => {{}};
            """
        )
        script = make_factory_script(self.segment, [], self.return_names, prelude, body)
        run_node_script(script)

    def test_refresh_from_datos_keeps_datos_tab(self):
        self._run(
            "datos",
            dedent(
                """
                const { openInmuebleDetail } = api;
                await openInmuebleDetail("inv-1", "inmuebles", { keepTab: true });
                assert.ok(tabCalls.length >= 2);
                assert.ok(tabCalls.every((tab) => tab === "datos"));
                assert.strictEqual(state.currentInmuebleTabKey, "datos");
                """
            ),
        )

    def test_refresh_from_actividades_keeps_actividad_tab(self):
        self._run(
            "actividad",
            dedent(
                """
                const { openInmuebleDetail } = api;
                await openInmuebleDetail("inv-1", "inmuebles", { keepTab: true });
                assert.ok(tabCalls.length >= 2);
                assert.ok(tabCalls.every((tab) => tab === "actividad"));
                assert.strictEqual(state.currentInmuebleTabKey, "actividad");
                """
            ),
        )

    def test_refresh_from_encargos_keeps_estado_tab(self):
        self._run(
            "estado",
            dedent(
                """
                const { openInmuebleDetail } = api;
                await openInmuebleDetail("inv-1", "inmuebles", { keepTab: true });
                assert.ok(tabCalls.length >= 2);
                assert.ok(tabCalls.every((tab) => tab === "estado"));
                assert.strictEqual(state.currentInmuebleTabKey, "estado");
                """
            ),
        )

    def test_refresh_without_keep_tab_defaults_to_datos(self):
        self._run(
            "actividad",
            dedent(
                """
                const { openInmuebleDetail } = api;
                await openInmuebleDetail("inv-1", "inmuebles");
                assert.ok(tabCalls.length >= 2);
                assert.ok(tabCalls.every((tab) => tab === "datos"));
                assert.strictEqual(state.currentInmuebleTabKey, "datos");
                """
            ),
        )


class GestoriaBudgetDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const applyGestoriaBudgetTipoDefaults =",
            "const persistGestoriaTrabajoTipo = async",
        )
        cls.param_names = [
            "gestoriaBudgetQuickForm",
            "gestoriaBudgetTipoTrabajo",
            "getGestoriaTipoMeta",
            "renderGestoriaBudgetTipoTemplateFields",
            "syncGestoriaBudgetQuickComputed",
        ]
        cls.return_names = ["applyGestoriaBudgetTipoDefaults"]

    def _run(self, prelude: str, body: str) -> None:
        script = make_factory_script(self.segment, self.param_names, self.return_names, prelude, body)
        run_node_script(script)

    def _budget_prelude(
        self,
        *,
        initial_name: str = "Tipo A",
        initial_key: str = "tipo_a",
        initial_precio: int | float = 100,
        initial_iva: int | float = 10,
        initial_categoria: str = "fiscal",
    ) -> str:
        return dedent(
            f"""
            const subtotalInput = {{ value: "", dataset: {{}} }};
            const ivaPctInput = {{ value: "", dataset: {{}} }};
            const ivaInput = {{ value: "", dataset: {{}} }};
            const totalInput = {{ value: "", dataset: {{}} }};
            const gestoriaBudgetQuickForm = {{
              dataset: {{}},
              querySelector(selector) {{
                if (selector === '[name="subtotal"]') return subtotalInput;
                if (selector === '[name="iva_pct"]') return ivaPctInput;
                if (selector === '[name="impuestos"]') return ivaInput;
                if (selector === '[name="total"]') return totalInput;
                return null;
              }},
            }};
            const makeMeta = (nombre, tipo_key, precio_base, iva_pct, categoria = "fiscal") => ({{
              nombre,
              tipo_key,
              precio_base,
              iva_pct,
              categoria,
              sla_dias: 7,
              plantilla_json: "",
            }});
            let currentMeta = makeMeta({initial_name!r}, {initial_key!r}, {initial_precio!r}, {initial_iva!r}, {initial_categoria!r});
            const gestoriaBudgetTipoTrabajo = {{
              get selectedOptions() {{
                return [
                  {{
                    value: currentMeta.nombre,
                    dataset: {{
                      key: currentMeta.tipo_key,
                      categoria: currentMeta.categoria,
                      sla: String(currentMeta.sla_dias),
                      ivaPct: String(currentMeta.iva_pct),
                      precioBase: String(currentMeta.precio_base),
                      plantillaJson: "",
                    }},
                  }},
                ];
              }},
            }};
            const getGestoriaTipoMeta = () => currentMeta;
            const renderGestoriaBudgetTipoTemplateFields = () => {{
              const meta = currentMeta;
              gestoriaBudgetQuickForm.dataset.gestoriaBudgetTipo = meta.tipo_key;
              gestoriaBudgetQuickForm.dataset.gestoriaBudgetCategoria = meta.categoria;
              return meta;
            }};
            const isManual = (input) => String(input?.dataset?.gestoriaBudgetManual || "").trim() === "1";
            const shouldApplyGestoriaBudgetQuickDefault = (input) => {{
              const current = String(input?.value || "").trim();
              return !current || !isManual(input);
            }};
            const parseMoney = (value) => Number(String(value || "").trim() || 0);
            const syncGestoriaBudgetQuickComputed = () => {{
              const subtotal = parseMoney(subtotalInput.value);
              const ivaPct = Math.max(0, Math.min(100, parseMoney(ivaPctInput.value)));
              const ivaManual = isManual(ivaInput);
              const totalManual = isManual(totalInput);
              const computedIva = subtotal > 0 ? (subtotal * ivaPct) / 100 : 0;
              if (!isManual(ivaPctInput)) ivaPctInput.value = ivaPct ? String(ivaPct) : "";
              if (!ivaManual) ivaInput.value = computedIva > 0 ? computedIva.toFixed(2) : "";
              const effectiveIva = ivaManual ? parseMoney(ivaInput.value) : computedIva;
              if (!totalManual) totalInput.value = subtotal > 0 ? (subtotal + effectiveIva).toFixed(2) : "";
            }};
            """
        )

    def test_empty_form_seeds_defaults_and_computes_total(self):
        self._run(
            self._budget_prelude(),
            dedent(
                """
                const { applyGestoriaBudgetTipoDefaults } = api;
                applyGestoriaBudgetTipoDefaults();
                assert.strictEqual(subtotalInput.value, "100");
                assert.strictEqual(ivaPctInput.value, "10");
                assert.strictEqual(ivaInput.value, "10.00");
                assert.strictEqual(totalInput.value, "110.00");
                """
            ),
        )

    def test_manual_values_survive_explicit_type_change(self):
        self._run(
            self._budget_prelude(),
            dedent(
                """
                const { applyGestoriaBudgetTipoDefaults } = api;
                applyGestoriaBudgetTipoDefaults();

                subtotalInput.value = "999";
                subtotalInput.dataset.gestoriaBudgetManual = "1";
                ivaPctInput.value = "19";
                ivaPctInput.dataset.gestoriaBudgetManual = "1";
                ivaInput.value = "189.81";
                ivaInput.dataset.gestoriaBudgetManual = "1";
                totalInput.value = "1188.81";
                totalInput.dataset.gestoriaBudgetManual = "1";

                currentMeta = makeMeta("Tipo B", "tipo_b", 250, 21, "sociedades");
                applyGestoriaBudgetTipoDefaults();

                assert.strictEqual(subtotalInput.value, "999");
                assert.strictEqual(ivaPctInput.value, "19");
                assert.strictEqual(ivaInput.value, "189.81");
                assert.strictEqual(totalInput.value, "1188.81");
                assert.strictEqual(gestoriaBudgetQuickForm.dataset.gestoriaBudgetTipo, "tipo_b");
                assert.strictEqual(gestoriaBudgetQuickForm.dataset.gestoriaBudgetCategoria, "sociedades");
                """
            ),
        )

    def test_programmatic_refresh_and_catalog_reload_keep_user_values(self):
        self._run(
            self._budget_prelude(),
            dedent(
                """
                const { applyGestoriaBudgetTipoDefaults } = api;
                applyGestoriaBudgetTipoDefaults();

                subtotalInput.value = "777";
                subtotalInput.dataset.gestoriaBudgetManual = "1";
                ivaPctInput.value = "7";
                ivaPctInput.dataset.gestoriaBudgetManual = "1";
                ivaInput.value = "54.39";
                ivaInput.dataset.gestoriaBudgetManual = "1";

                currentMeta = makeMeta("Tipo C", "tipo_c", 175, 18, "sociedades");
                applyGestoriaBudgetTipoDefaults();
                assert.strictEqual(subtotalInput.value, "777");
                assert.strictEqual(ivaPctInput.value, "7");
                assert.strictEqual(ivaInput.value, "54.39");
                assert.strictEqual(totalInput.value, "831.39");

                currentMeta = makeMeta("Tipo D", "tipo_d", 300, 8, "fiscal");
                applyGestoriaBudgetTipoDefaults();
                assert.strictEqual(subtotalInput.value, "777");
                assert.strictEqual(ivaPctInput.value, "7");
                assert.strictEqual(ivaInput.value, "54.39");
                assert.strictEqual(totalInput.value, "831.39");
                assert.strictEqual(gestoriaBudgetQuickForm.dataset.gestoriaBudgetTipo, "tipo_d");
                assert.strictEqual(gestoriaBudgetQuickForm.dataset.gestoriaBudgetCategoria, "fiscal");
                """
            ),
        )


class GestoriaBudgetQuickComputedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const syncGestoriaBudgetQuickComputed =",
            "const renderGestoriaBudgetsList =",
        )
        cls.return_names = ["syncGestoriaBudgetQuickComputed"]

    def _run_case(
        self,
        *,
        subtotal: str,
        iva_pct: str,
        iva: str,
        expected_subtotal: str,
        expected_iva_pct: str,
        expected_iva: str,
        expected_total: str,
        subtotal_manual: bool = False,
        iva_pct_manual: bool = False,
        iva_manual: bool = False,
        total_manual: bool = False,
    ) -> None:
        prelude = dedent(
            f"""
            const makeInput = (value = "", manual = false) => ({{
              value: String(value),
              dataset: manual ? {{ gestoriaBudgetManual: "1" }} : {{}},
            }});
            const subtotalInput = makeInput({json.dumps(subtotal)}, {str(subtotal_manual).lower()});
            const ivaPctInput = makeInput({json.dumps(iva_pct)}, {str(iva_pct_manual).lower()});
            const ivaInput = makeInput({json.dumps(iva)}, {str(iva_manual).lower()});
            const totalInput = makeInput("", {str(total_manual).lower()});
            const gestoriaBudgetQuickForm = globalThis.gestoriaBudgetQuickForm = {{
              querySelector(selector) {{
                if (selector === '[name="subtotal"]') return subtotalInput;
                if (selector === '[name="iva_pct"]') return ivaPctInput;
                if (selector === '[name="impuestos"]') return ivaInput;
                if (selector === '[name="total"]') return totalInput;
                return null;
              }},
            }};
            globalThis.parseMoneyValue = (value) => Number(String(value || "").trim().replace(",", ".").replace(/[^\\d.-]/g, "")) || 0;
            globalThis.isGestoriaBudgetQuickFieldManual = (input) => String(input?.dataset?.gestoriaBudgetManual || "").trim() === "1";
            """
        )
        script = make_factory_script(self.segment, [], self.return_names, prelude, dedent(
            f"""
            const {{ syncGestoriaBudgetQuickComputed }} = api;
            syncGestoriaBudgetQuickComputed();
            assert.strictEqual(subtotalInput.value, {json.dumps(expected_subtotal)});
            assert.strictEqual(ivaPctInput.value, {json.dumps(expected_iva_pct)});
            assert.strictEqual(ivaInput.value, {json.dumps(expected_iva)});
            assert.strictEqual(totalInput.value, {json.dumps(expected_total)});
            """
        ))
        run_node_script(script)

    def test_total_computation_respects_empty_zero_and_negative_subtotals(self):
        cases = [
            {
                "name": "blank fields",
                "subtotal": "",
                "iva_pct": "",
                "iva": "",
                "expected_subtotal": "",
                "expected_iva_pct": "",
                "expected_iva": "",
                "expected_total": "",
            },
            {
                "name": "zero subtotal keeps manual taxes",
                "subtotal": "0",
                "iva_pct": "21",
                "iva": "15",
                "expected_subtotal": "0",
                "expected_iva_pct": "21",
                "expected_iva": "15",
                "expected_total": "15.00",
                "iva_manual": True,
            },
            {
                "name": "negative subtotal keeps negative manual taxes",
                "subtotal": "-100",
                "iva_pct": "21",
                "iva": "-21",
                "expected_subtotal": "-100",
                "expected_iva_pct": "21",
                "expected_iva": "-21",
                "expected_total": "-121.00",
                "iva_manual": True,
            },
            {
                "name": "negative subtotal recomputes automatic taxes",
                "subtotal": "-50",
                "iva_pct": "10",
                "iva": "",
                "expected_subtotal": "-50",
                "expected_iva_pct": "10",
                "expected_iva": "-5.00",
                "expected_total": "-55.00",
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                self._run_case(**{k: v for k, v in case.items() if k != "name"})


class GestoriaCoreCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const GESTORIA_CORE_TRABAJO_TIPOS =",
            "const seedGestoriaCoreServicios = async",
        )
        cls.param_names = []
        cls.return_names = ["GESTORIA_CORE_TRABAJO_TIPOS", "buildGestoriaCoreCatalogPlan"]

    def _run(self, body: str) -> None:
        script = make_factory_script(self.segment, self.param_names, self.return_names, "", body)
        run_node_script(script)

    def test_empty_catalog_generates_core_upserts(self):
        self._run(
            dedent(
                """
                const { GESTORIA_CORE_TRABAJO_TIPOS, buildGestoriaCoreCatalogPlan } = api;
                const plan = buildGestoriaCoreCatalogPlan([]);
                assert.strictEqual(plan.upserts.length, GESTORIA_CORE_TRABAJO_TIPOS.length);
                assert.ok(plan.upserts.every((item) => item.isInsert && item.needsPersist));
                assert.deepStrictEqual(plan.deactivateRows, []);
                """
            )
        )

    def test_deleted_core_type_is_recreated_and_custom_rows_are_marked_for_deactivation(self):
        self._run(
            dedent(
                """
                const { GESTORIA_CORE_TRABAJO_TIPOS, buildGestoriaCoreCatalogPlan } = api;
                const makeRow = (item, idx, overrides = {}) => ({
                  id: `core-${idx}`,
                  tipo_key: item.tipo_key,
                  nombre: item.nombre,
                  categoria: item.categoria,
                  activo: 1,
                  orden: item.orden,
                  color: item.color,
                  sla_dias: item.sla_dias,
                  iva_pct: item.iva_pct,
                  precio_base: item.precio_base,
                  plantilla_json: "",
                  ...overrides,
                });
                const rows = GESTORIA_CORE_TRABAJO_TIPOS
                  .filter((item) => item.tipo_key !== "nominas")
                  .map(makeRow)
                  .concat([
                    {
                      id: "custom-1",
                      tipo_key: "custom_servicio",
                      nombre: "Servicio personalizado",
                      categoria: "otros",
                      activo: 1,
                      orden: 1,
                      color: "#222222",
                      sla_dias: 3,
                      iva_pct: 21,
                      precio_base: 0,
                    },
                  ]);
                const plan = buildGestoriaCoreCatalogPlan(rows, { deactivateOthers: true });
                const missing = plan.upserts.find((item) => item.key === "nominas");
                assert.ok(missing);
                assert.ok(missing.isInsert);
                assert.ok(missing.needsPersist);
                assert.strictEqual(plan.deactivateRows.length, 1);
                assert.strictEqual(plan.deactivateRows[0].tipo_key, "custom_servicio");
                """
            )
        )

    def test_inactive_core_type_is_reactivated(self):
        self._run(
            dedent(
                """
                const { GESTORIA_CORE_TRABAJO_TIPOS, buildGestoriaCoreCatalogPlan } = api;
                const first = GESTORIA_CORE_TRABAJO_TIPOS[0];
                const rows = [
                  {
                    id: "core-1",
                    tipo_key: first.tipo_key,
                    nombre: first.nombre,
                    categoria: first.categoria,
                    activo: 0,
                    orden: first.orden,
                    color: first.color,
                    sla_dias: first.sla_dias,
                    iva_pct: first.iva_pct,
                    precio_base: first.precio_base,
                    plantilla_json: "",
                  },
                ];
                const plan = buildGestoriaCoreCatalogPlan(rows);
                const item = plan.upserts.find((row) => row.key === first.tipo_key);
                assert.ok(item);
                assert.ok(item.isReactivated);
                assert.ok(item.needsPersist);
                """
            )
        )

    def test_matching_catalog_is_idempotent(self):
        self._run(
            dedent(
                """
                const { GESTORIA_CORE_TRABAJO_TIPOS, buildGestoriaCoreCatalogPlan } = api;
                const rows = GESTORIA_CORE_TRABAJO_TIPOS.map((item, idx) => ({
                  id: `core-${idx}`,
                  ...item,
                  activo: 1,
                  plantilla_json: "",
                }));
                const plan = buildGestoriaCoreCatalogPlan(rows);
                assert.ok(plan.upserts.every((item) => !item.needsPersist));
                assert.strictEqual(plan.deactivateRows.length, 0);
                """
            )
        )


class GestoriaModelosScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.segment = extract_segment(
            "const loadGestoriaModelos =",
            "const saveClienteProfesionalField =",
        ).replace("api(", "globalThis.api(")
        cls.param_names = [
            "state",
            "gestoriaModelosTable",
            "window",
            "ensureWorkspaceCompanyContabilidadCache",
            "syncGestoriaModelosDownloadButton",
            "getCurrentUser",
            "fetch",
        ]
        cls.return_names = ["loadGestoriaModelos", "deleteGestoriaModelo"]

    def _run(self, prelude: str, body: str) -> None:
        shared_prelude = dedent(
            """
            globalThis.resolveGestoriaScopeParams = (clienteIdOrOpts = "", empresaId = "") => {
              if (clienteIdOrOpts && typeof clienteIdOrOpts === "object") {
                const scope = {};
                const clienteId = String(clienteIdOrOpts.clienteId || "").trim();
                const scopeEmpresaId = String(clienteIdOrOpts.empresaId || "").trim();
                if (clienteId) scope.clienteId = clienteId;
                if (scopeEmpresaId) scope.empresaId = scopeEmpresaId;
                return scope;
              }
              const scope = {};
              const clienteId = String(clienteIdOrOpts || "").trim();
              const empresa = String(empresaId || "").trim();
              if (clienteId) scope.clienteId = clienteId;
              if (empresa) scope.empresaId = empresa;
              return scope;
            };
            """
        )
        script = make_factory_script(self.segment, self.param_names, self.return_names, shared_prelude + prelude, body)
        run_node_script(script)

    def test_load_with_empresa_scope_preserves_empresa_filter(self):
        self._run(
            dedent(
                """
                const state = { currentWorkspaceCompanyId: "emp-other", gestoriaModelosCache: null };
                const gestoriaModelosTable = { innerHTML: "", appendChild() {} };
                const window = {};
                const apiCalls = [];
                globalThis.api = async (url) => {
                  apiCalls.push(url);
                  return { rows: [] };
                };
                const ensureWorkspaceCompanyContabilidadCache = () => ({ modelos: null });
                const syncGestoriaModelosDownloadButton = () => {};
                const getCurrentUser = () => "tester";
                const fetch = async () => ({ json: async () => ({ ok: true }) });
                """
            ),
            dedent(
                """
                const { loadGestoriaModelos } = api;
                await loadGestoriaModelos("", "emp-1");
                assert.strictEqual(apiCalls.length, 1);
                const params = new URLSearchParams(apiCalls[0].split("?")[1] || "");
                assert.strictEqual(params.get("cliente_id"), null);
                assert.strictEqual(params.get("empresa_id"), "emp-1");
                """
            ),
        )

    def test_load_with_cliente_scope_preserves_cliente_filter(self):
        self._run(
            dedent(
                """
                const state = { currentWorkspaceCompanyId: "emp-other", gestoriaModelosCache: null };
                const gestoriaModelosTable = { innerHTML: "", appendChild() {} };
                const window = {};
                const apiCalls = [];
                globalThis.api = async (url) => {
                  apiCalls.push(url);
                  return { rows: [] };
                };
                const ensureWorkspaceCompanyContabilidadCache = () => ({ modelos: null });
                const syncGestoriaModelosDownloadButton = () => {};
                const getCurrentUser = () => "tester";
                const fetch = async () => ({ json: async () => ({ ok: true }) });
                """
            ),
            dedent(
                """
                const { loadGestoriaModelos } = api;
                await loadGestoriaModelos("cli-1");
                assert.strictEqual(apiCalls.length, 1);
                const params = new URLSearchParams(apiCalls[0].split("?")[1] || "");
                assert.strictEqual(params.get("cliente_id"), "cli-1");
                assert.strictEqual(params.get("empresa_id"), null);
                """
            ),
        )

    def test_load_with_combined_scope_preserves_both_filters(self):
        self._run(
            dedent(
                """
                const state = { currentWorkspaceCompanyId: "emp-other", gestoriaModelosCache: null };
                const gestoriaModelosTable = { innerHTML: "", appendChild() {} };
                const window = {};
                const apiCalls = [];
                globalThis.api = async (url) => {
                  apiCalls.push(url);
                  return { rows: [] };
                };
                const ensureWorkspaceCompanyContabilidadCache = () => ({ modelos: null });
                const syncGestoriaModelosDownloadButton = () => {};
                const getCurrentUser = () => "tester";
                const fetch = async () => ({ json: async () => ({ ok: true }) });
                """
            ),
            dedent(
                """
                const { loadGestoriaModelos } = api;
                await loadGestoriaModelos({ clienteId: "cli-1", empresaId: "emp-1" });
                assert.strictEqual(apiCalls.length, 1);
                const params = new URLSearchParams(apiCalls[0].split("?")[1] || "");
                assert.strictEqual(params.get("cliente_id"), "cli-1");
                assert.strictEqual(params.get("empresa_id"), "emp-1");
                """
            ),
        )

    def test_delete_reloads_same_scope_after_delete(self):
        self._run(
            dedent(
                """
                const state = { currentWorkspaceCompanyId: "emp-other", gestoriaModelosCache: null };
                const gestoriaModelosTable = { innerHTML: "", appendChild() {} };
                const window = {};
                const apiCalls = [];
                globalThis.api = async (url) => {
                  apiCalls.push(url);
                  return { rows: [] };
                };
                const ensureWorkspaceCompanyContabilidadCache = () => ({ modelos: null });
                const syncGestoriaModelosDownloadButton = () => {};
                const getCurrentUser = () => "tester";
                const fetchCalls = [];
                const fetch = async (url, options) => {
                  fetchCalls.push([url, options]);
                  return { json: async () => ({ ok: true }) };
                };
                """
            ),
            dedent(
                """
                const { deleteGestoriaModelo } = api;
                await deleteGestoriaModelo("modelo-1", { clienteId: "cli-1", empresaId: "emp-1" });
                await new Promise((resolve) => setTimeout(resolve, 0));
                assert.strictEqual(fetchCalls.length, 1);
                assert.strictEqual(fetchCalls[0][0], "/api/gestoria_modelos_delete");
                assert.strictEqual(apiCalls.length, 1);
                const params = new URLSearchParams(apiCalls[0].split("?")[1] || "");
                assert.strictEqual(params.get("cliente_id"), "cli-1");
                assert.strictEqual(params.get("empresa_id"), "emp-1");
                """
            ),
        )


class SegurosPresupuestosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.load_segment = extract_segment(
            "const loadSegurosCrm =",
            "const renderSegurosRamosDashboard =",
        ).replace("api(", "globalThis.api(")
        cls.render_segment = extract_segment(
            "const renderSegurosPresupuestos =",
            "const renderSegurosUpdateSelect =",
        )

    def _run_load(self, prelude: str, body: str) -> None:
        script = make_factory_script(self.load_segment, [], ["loadSegurosCrm"], prelude, body)
        run_node_script(script)

    def _run_render(self, prelude: str, body: str) -> None:
        script = make_factory_script(self.render_segment, [], ["renderSegurosPresupuestos"], prelude, body)
        run_node_script(script)

    def test_load_seguros_crm_invokes_renderer_and_shows_pending_presupuestos(self):
        self._run_load(
            dedent(
                """
                class FakeNode {
                  constructor(tag = "div") {
                    this.tagName = String(tag || "div").toUpperCase();
                    this.children = [];
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.textContent = "";
                    this.innerHTML = "";
                  }
                  appendChild(child) {
                    this.children.push(child);
                    return child;
                  }
                  addEventListener() {}
                  setAttribute(name, value) {
                    this[name] = String(value);
                  }
                  querySelector() {
                    return null;
                  }
                  querySelectorAll() {
                    return [];
                  }
                  closest() {
                    return null;
                  }
                }
                const document = {
                  createElement: (tag) => new FakeNode(tag),
                  createTextNode: (text) => {
                    const node = new FakeNode("#text");
                    node.textContent = String(text || "");
                    return node;
                  },
                  addEventListener() {},
                };
                const state = globalThis.state = {
                  segurosCrmEstadoContains: "",
                  segurosCrmFilterRamo: "",
                  segurosCrmFilterCompania: "",
                  segurosRenovarPendientesIds: [],
                  segurosTab: "crm",
                };
                const segurosCrmTable = globalThis.segurosCrmTable = new FakeNode("div");
                const segurosCrmInfo = globalThis.segurosCrmInfo = new FakeNode("div");
                const segurosPresupuestosList = globalThis.segurosPresupuestosList = new FakeNode("div");
                const segurosCrmSearch = globalThis.segurosCrmSearch = { value: "" };
                const segurosCrmClienteInput = globalThis.segurosCrmClienteInput = { value: "" };
                const segurosEstadoFilter = globalThis.segurosEstadoFilter = { value: "all" };
                const seguroOcrCompania = globalThis.seguroOcrCompania = null;
                const segurosComplianceKpis = globalThis.segurosComplianceKpis = new FakeNode("div");
                const segurosEventosTable = globalThis.segurosEventosTable = new FakeNode("div");
                const segurosReclamacionesTable = globalThis.segurosReclamacionesTable = new FakeNode("div");
                const segurosAgendaTable = globalThis.segurosAgendaTable = new FakeNode("div");
                const segurosAgendaInfo = globalThis.segurosAgendaInfo = new FakeNode("div");
                const renderCalls = [];
                const apiResponses = [{
                  columns: ["id", "estado", "tomador", "compania", "ramo", "poliza_numero", "prima_total"],
                  rows: [
                    ["pres-1", "presupuesto", "Cliente Demo", "Aseguradora", "Hogar", "P-1", "123.45"],
                    ["pol-2", "en vigor", "Cliente Activo", "Aseguradora", "Auto", "P-2", "210.00"],
                  ],
                }];
                globalThis.document = document;
                globalThis.window = { requestAnimationFrame: () => {} };
                globalThis.SEGUROS_ONLY_UPLOADED_MODE = false;
                globalThis.api = async (url) => {
                  renderCalls.push(url);
                  return apiResponses.shift() || { columns: [], rows: [] };
                };
                globalThis.renderSegurosPresupuestos = (data) => {
                  renderCalls.push({ presupuestos: data });
                };
                globalThis.renderSegurosUpdateSelect = () => {};
                globalThis.renderSegurosChecklistSelect = () => {};
                globalThis.renderSegurosAiSelect = () => {};
                globalThis.resolveCrmSegurosEmpresa = () => ({ id: "emp-1", nombre: "Seguros Demo" });
                globalThis.resolveLegacyEmpresaId = (empresa) => String(empresa?.id || "").trim();
                globalThis.normalizeSimple = (value) => String(value || "").trim().toLowerCase();
                globalThis.getSegurosRamoLabel = (value) => String(value || "").trim();
                globalThis.renderTableInto = () => {};
                globalThis.refreshSegurosColaboradoresList = () => {};
                globalThis.refreshSegurosRamosList = () => {};
                globalThis.loadSegurosOportunidades = () => {};
                globalThis.loadAcciones = () => {};
                globalThis.loadSegurosOfertas = () => {};
                globalThis.loadSegurosReferidos = () => {};
                globalThis.loadSegurosCampanas = () => {};
                globalThis.loadSegurosComisiones = () => {};
                globalThis.loadSegurosInsights = () => {};
                globalThis.loadSegurosAlertas = () => {};
                globalThis.loadSegurosKpis = () => {};
                globalThis.loadSegurosDataQuality = () => {};
                globalThis.renderSegurosRamosDashboard = () => {};
                globalThis.populateSegurosOperationalSelects = () => {};
                globalThis.loadSegurosComplianceForm = () => {};
                globalThis.loadSegurosComplianceKpis = () => {};
                globalThis.loadSegurosEventos = () => {};
                globalThis.loadSegurosReclamaciones = () => {};
                globalThis.loadSegurosRecibos = () => {};
                globalThis.loadSegurosSiniestros = () => {};
                globalThis.hydrateSegurosRecibosFormSelects = () => Promise.resolve();
                globalThis.hydrateSegurosSiniestrosFormSelects = () => Promise.resolve();
                globalThis.populateAgendaClientes = () => {};
                globalThis.resolveSegurosDashboardEmpresaId = () => "";
                globalThis.segurosCompliancePoliza = null;
                globalThis.segurosEventosPolizaId = null;
                globalThis.segurosPreferenciasClientes = null;
                globalThis.segurosPreferenciasClienteInput = null;
                globalThis.segurosPreferenciasClienteId = null;
                globalThis.segurosOfertasClientes = null;
                globalThis.segurosOfertasClienteInput = null;
                globalThis.segurosOfertasClienteId = null;
                globalThis.segurosReferidosClientes = null;
                globalThis.segurosReferidosClienteInput = null;
                globalThis.segurosReferidosClienteId = null;
                globalThis.segurosRecClientes = null;
                globalThis.segurosRecClienteInput = null;
                globalThis.segurosRecClienteId = null;
                globalThis.createCompanyBadge = (text) => {
                  const node = new FakeNode("span");
                  node.textContent = String(text || "");
                  return node;
                };
                globalThis.euroFormatter = { format: (value) => `€${Number(value || 0).toFixed(2)}` };
                globalThis.escapeHtml = (value) => String(value ?? "");
                globalThis.parseMoneyValue = (value) => Number(String(value || "").replace(",", ".").replace(/[^\\d.-]/g, "")) || 0;
                globalThis.formatCell = (_field, value) => String(value ?? "");
                globalThis.formatAgendaDate = () => "2026-01-01";
                globalThis.SERVICE_LABELS = { seguros: "Seguros" };
                """
            ),
            dedent(
                """
                const { loadSegurosCrm } = api;
                loadSegurosCrm();
                await new Promise((resolve) => setTimeout(resolve, 0));
                assert.strictEqual(renderCalls.filter((item) => typeof item === "string").length, 1);
                const renderPayload = renderCalls.find((item) => item && typeof item === "object" && Object.prototype.hasOwnProperty.call(item, "presupuestos"));
                assert.ok(renderPayload);
                assert.strictEqual(renderPayload.presupuestos.rows.length, 2);
                assert.strictEqual(segurosPresupuestosList.children.length, 0);
                """
            ),
        )

    def test_render_seguros_presupuestos_handles_empty_and_missing_dom(self):
        self._run_render(
            dedent(
                """
                class FakeNode {
                  constructor(tag = "div") {
                    this.tagName = String(tag || "div").toUpperCase();
                    this.children = [];
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.textContent = "";
                    this.innerHTML = "";
                  }
                  appendChild(child) {
                    this.children.push(child);
                    return child;
                  }
                  addEventListener() {}
                  setAttribute(name, value) {
                    this[name] = String(value);
                  }
                  querySelector() {
                    return null;
                  }
                  querySelectorAll() {
                    return [];
                  }
                  closest() {
                    return null;
                  }
                }
                const document = {
                  createElement: (tag) => new FakeNode(tag),
                  createTextNode: (text) => {
                    const node = new FakeNode("#text");
                    node.textContent = String(text || "");
                    return node;
                  },
                  addEventListener() {},
                };
                globalThis.document = document;
                globalThis.createCompanyBadge = (text) => {
                  const node = new FakeNode("span");
                  node.textContent = String(text || "");
                  return node;
                };
                globalThis.euroFormatter = { format: (value) => `€${Number(value || 0).toFixed(2)}` };
                globalThis.escapeHtml = (value) => String(value ?? "");
                globalThis.normalizeSimple = (value) => String(value || "").trim().toLowerCase();
                globalThis.parseMoneyValue = (value) => Number(String(value || "").replace(",", ".").replace(/[^\\d.-]/g, "")) || 0;
                globalThis.SERVICE_LABELS = { seguros: "Seguros" };
                const segurosPresupuestosList = globalThis.segurosPresupuestosList = new FakeNode("div");
                """
            ),
            dedent(
                """
                const { renderSegurosPresupuestos } = api;
                renderSegurosPresupuestos({
                  columns: ["id", "estado", "tomador", "compania", "ramo", "poliza_numero", "prima_total"],
                  rows: [
                    ["pres-1", "presupuesto", "Cliente Demo", "Aseguradora", "Hogar", "P-1", "123.45"],
                    ["pol-2", "en vigor", "Cliente Activo", "Aseguradora", "Auto", "P-2", "210.00"],
                  ],
                });
                assert.strictEqual(segurosPresupuestosList.children.length, 1);
                const list = segurosPresupuestosList.children[0];
                assert.strictEqual(list.children.length, 1);
                const card = list.children[0];
                const title = card.children[0];
                assert.strictEqual(title.children[0].textContent, "Cliente Demo");
                assert.strictEqual(segurosPresupuestosList.innerHTML, "");

                segurosPresupuestosList.innerHTML = "stale";
                assert.doesNotThrow(() => renderSegurosPresupuestos({ columns: [], rows: [] }));
                assert.strictEqual(segurosPresupuestosList.innerHTML, "<p class='muted'>Sin presupuestos pendientes.</p>");

                globalThis.segurosPresupuestosList = null;
                assert.doesNotThrow(() => renderSegurosPresupuestos({ columns: [], rows: [] }));
                """
            ),
        )

    def test_load_seguros_crm_clears_pending_presupuestos_when_company_disappears(self):
        self._run_load(
            dedent(
                """
                class FakeNode {
                  constructor(tag = "div") {
                    this.tagName = String(tag || "div").toUpperCase();
                    this.children = [];
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.textContent = "";
                    this.innerHTML = "";
                  }
                  appendChild(child) {
                    this.children.push(child);
                    return child;
                  }
                  addEventListener() {}
                  setAttribute(name, value) {
                    this[name] = String(value);
                  }
                  querySelector() {
                    return null;
                  }
                  querySelectorAll() {
                    return [];
                  }
                  closest() {
                    return null;
                  }
                }
                const document = {
                  createElement: (tag) => new FakeNode(tag),
                  createTextNode: (text) => {
                    const node = new FakeNode("#text");
                    node.textContent = String(text || "");
                    return node;
                  },
                  addEventListener() {},
                };
                const state = globalThis.state = {
                  segurosCrmEstadoContains: "",
                  segurosCrmFilterRamo: "",
                  segurosCrmFilterCompania: "",
                  segurosRenovarPendientesIds: ["old"],
                  segurosTab: "crm",
                  segurosCrmData: { columns: ["id"], rows: [["old"]] },
                  segurosRamosSource: { columns: ["id"], rows: [["old"]] },
                  segurosComisionesRows: [{ compania: "Antigua", ramo: "Viejo", porcentaje: 7 }],
                  segurosInsightsLastKey: "cached",
                  segurosInsightsLastAt: 123,
                };
                const segurosCrmTable = globalThis.segurosCrmTable = new FakeNode("div");
                const segurosCrmInfo = globalThis.segurosCrmInfo = new FakeNode("div");
                const segurosPresupuestosList = globalThis.segurosPresupuestosList = new FakeNode("div");
                const segurosCrmSearch = globalThis.segurosCrmSearch = { value: "" };
                const segurosCrmClienteInput = globalThis.segurosCrmClienteInput = { value: "" };
                const segurosEstadoFilter = globalThis.segurosEstadoFilter = { value: "all" };
                const seguroOcrCompania = globalThis.seguroOcrCompania = null;
                const segurosComplianceKpis = globalThis.segurosComplianceKpis = new FakeNode("div");
                const segurosEventosTable = globalThis.segurosEventosTable = new FakeNode("div");
                const segurosReclamacionesTable = globalThis.segurosReclamacionesTable = new FakeNode("div");
                const segurosAgendaTable = globalThis.segurosAgendaTable = new FakeNode("div");
                const segurosAgendaInfo = globalThis.segurosAgendaInfo = new FakeNode("div");
                const renderCalls = [];
                let activeEmpresa = { id: "emp-1", nombre: "Seguros Demo" };
                const apiResponses = [{
                  columns: ["id", "estado", "tomador", "compania", "ramo", "poliza_numero", "prima_total"],
                  rows: [["pres-1", "presupuesto", "Cliente Demo", "Aseguradora", "Hogar", "P-1", "123.45"]],
                }];
                globalThis.document = document;
                globalThis.window = { requestAnimationFrame: () => {} };
                globalThis.SEGUROS_ONLY_UPLOADED_MODE = false;
                globalThis.api = async (url) => {
                  renderCalls.push(url);
                  return apiResponses.shift() || { columns: [], rows: [] };
                };
                globalThis.renderSegurosPresupuestos = (data) => {
                  renderCalls.push({ presupuestos: data });
                  const rows = Array.isArray(data?.rows) ? data.rows : [];
                  if (!rows.length) {
                    segurosPresupuestosList.innerHTML = "<p class='muted'>Sin presupuestos pendientes.</p>";
                    return;
                  }
                  segurosPresupuestosList.innerHTML = "";
                };
                globalThis.renderSegurosUpdateSelect = () => {};
                globalThis.renderSegurosChecklistSelect = () => {};
                globalThis.renderSegurosAiSelect = () => {};
                globalThis.resolveCrmSegurosEmpresa = () => activeEmpresa;
                globalThis.resolveLegacyEmpresaId = (empresa) => String(empresa?.id || "").trim();
                globalThis.normalizeSimple = (value) => String(value || "").trim().toLowerCase();
                globalThis.getSegurosRamoLabel = (value) => String(value || "").trim();
                globalThis.renderTableInto = () => {};
                globalThis.refreshSegurosColaboradoresList = () => {};
                globalThis.refreshSegurosRamosList = () => {};
                globalThis.loadSegurosOportunidades = () => {};
                globalThis.loadAcciones = () => {};
                globalThis.loadSegurosOfertas = () => {};
                globalThis.loadSegurosReferidos = () => {};
                globalThis.loadSegurosCampanas = () => {};
                globalThis.loadSegurosComisiones = () => {};
                globalThis.loadSegurosInsights = () => {};
                globalThis.loadSegurosAlertas = () => {};
                globalThis.loadSegurosKpis = () => {};
                globalThis.loadSegurosDataQuality = () => {};
                globalThis.renderSegurosRamosDashboard = () => {};
                globalThis.populateSegurosOperationalSelects = () => {};
                globalThis.loadSegurosComplianceForm = () => {};
                globalThis.loadSegurosComplianceKpis = () => {};
                globalThis.loadSegurosEventos = () => {};
                globalThis.loadSegurosReclamaciones = () => {};
                globalThis.loadSegurosRecibos = () => {};
                globalThis.loadSegurosSiniestros = () => {};
                globalThis.hydrateSegurosRecibosFormSelects = () => Promise.resolve();
                globalThis.hydrateSegurosSiniestrosFormSelects = () => Promise.resolve();
                globalThis.populateAgendaClientes = () => {};
                globalThis.resolveSegurosDashboardEmpresaId = () => "";
                globalThis.refreshSegurosOcrComisionSuggestion = () => {};
                globalThis.segurosCompliancePoliza = null;
                globalThis.segurosEventosPolizaId = null;
                globalThis.segurosPreferenciasClientes = null;
                globalThis.segurosPreferenciasClienteInput = null;
                globalThis.segurosPreferenciasClienteId = null;
                globalThis.segurosOfertasClientes = null;
                globalThis.segurosOfertasClienteInput = null;
                globalThis.segurosOfertasClienteId = null;
                globalThis.segurosReferidosClientes = null;
                globalThis.segurosReferidosClienteInput = null;
                globalThis.segurosReferidosClienteId = null;
                globalThis.segurosRecClientes = null;
                globalThis.segurosRecClienteInput = null;
                globalThis.segurosRecClienteId = null;
                globalThis.createCompanyBadge = (text) => {
                  const node = new FakeNode("span");
                  node.textContent = String(text || "");
                  return node;
                };
                globalThis.euroFormatter = { format: (value) => `€${Number(value || 0).toFixed(2)}` };
                globalThis.escapeHtml = (value) => String(value ?? "");
                globalThis.parseMoneyValue = (value) => Number(String(value || "").replace(",", ".").replace(/[^\\d.-]/g, "")) || 0;
                globalThis.formatCell = (_field, value) => String(value ?? "");
                globalThis.formatAgendaDate = () => "2026-01-01";
                globalThis.SERVICE_LABELS = { seguros: "Seguros" };
                """
            ),
            dedent(
                """
                const { loadSegurosCrm } = api;
                loadSegurosCrm();
                await new Promise((resolve) => setTimeout(resolve, 0));
                assert.strictEqual(renderCalls.filter((item) => typeof item === "object" && item && Object.prototype.hasOwnProperty.call(item, "presupuestos")).length, 1);
                assert.strictEqual(segurosPresupuestosList.innerHTML, "");
                activeEmpresa = null;
                segurosPresupuestosList.innerHTML = "<div class='inline-row'>antiguo</div>";
                loadSegurosCrm();
                await new Promise((resolve) => setTimeout(resolve, 0));
                const presupuestosRenderCalls = renderCalls.filter((item) => item && typeof item === "object" && Object.prototype.hasOwnProperty.call(item, "presupuestos"));
                assert.strictEqual(presupuestosRenderCalls[presupuestosRenderCalls.length - 1].presupuestos.rows.length, 0);
                assert.strictEqual(segurosPresupuestosList.innerHTML, "<p class='muted'>Sin presupuestos pendientes.</p>");
                assert.deepStrictEqual(state.segurosCrmData, { columns: [], rows: [] });
                assert.strictEqual(state.segurosRamosSource, null);
                assert.deepStrictEqual(state.segurosComisionesRows, []);
                assert.strictEqual(state.segurosInsightsLastKey, "");
                assert.strictEqual(state.segurosInsightsLastAt, 0);
                assert.deepStrictEqual(state.segurosRenovarPendientesIds, []);
                """
            ),
        )

    def test_load_seguros_crm_survives_renderer_error(self):
        self._run_load(
            dedent(
                """
                class FakeNode {
                  constructor(tag = "div") {
                    this.tagName = String(tag || "div").toUpperCase();
                    this.children = [];
                    this.dataset = {};
                    this.style = {};
                    this.className = "";
                    this.textContent = "";
                    this.innerHTML = "";
                  }
                  appendChild(child) {
                    this.children.push(child);
                    return child;
                  }
                  addEventListener() {}
                  setAttribute(name, value) {
                    this[name] = String(value);
                  }
                  querySelector() {
                    return null;
                  }
                  querySelectorAll() {
                    return [];
                  }
                  closest() {
                    return null;
                  }
                }
                const document = {
                  createElement: (tag) => new FakeNode(tag),
                  createTextNode: (text) => {
                    const node = new FakeNode("#text");
                    node.textContent = String(text || "");
                    return node;
                  },
                  addEventListener() {},
                };
                const state = globalThis.state = {
                  segurosCrmEstadoContains: "",
                  segurosCrmFilterRamo: "",
                  segurosCrmFilterCompania: "",
                  segurosRenovarPendientesIds: [],
                  segurosTab: "crm",
                };
                const segurosCrmTable = globalThis.segurosCrmTable = new FakeNode("div");
                const segurosCrmInfo = globalThis.segurosCrmInfo = new FakeNode("div");
                const segurosPresupuestosList = globalThis.segurosPresupuestosList = new FakeNode("div");
                const segurosCrmSearch = globalThis.segurosCrmSearch = { value: "" };
                const segurosCrmClienteInput = globalThis.segurosCrmClienteInput = { value: "" };
                const segurosEstadoFilter = globalThis.segurosEstadoFilter = { value: "all" };
                const seguroOcrCompania = globalThis.seguroOcrCompania = null;
                const segurosComplianceKpis = globalThis.segurosComplianceKpis = new FakeNode("div");
                const segurosEventosTable = globalThis.segurosEventosTable = new FakeNode("div");
                const segurosReclamacionesTable = globalThis.segurosReclamacionesTable = new FakeNode("div");
                const segurosAgendaTable = globalThis.segurosAgendaTable = new FakeNode("div");
                const segurosAgendaInfo = globalThis.segurosAgendaInfo = new FakeNode("div");
                const renderCalls = [];
                globalThis.document = document;
                globalThis.window = { requestAnimationFrame: () => {} };
                globalThis.SEGUROS_ONLY_UPLOADED_MODE = false;
                globalThis.api = async () => ({
                  columns: ["id", "estado", "tomador", "compania", "ramo", "poliza_numero", "prima_total"],
                  rows: [["pres-1", "presupuesto", "Cliente Demo", "Aseguradora", "Hogar", "P-1", "123.45"]],
                });
                globalThis.renderSegurosPresupuestos = () => {
                  renderCalls.push("render");
                  throw new Error("boom");
                };
                globalThis.renderSegurosUpdateSelect = () => {};
                globalThis.renderSegurosChecklistSelect = () => {};
                globalThis.renderSegurosAiSelect = () => {};
                globalThis.resolveCrmSegurosEmpresa = () => ({ id: "emp-1", nombre: "Seguros Demo" });
                globalThis.resolveLegacyEmpresaId = (empresa) => String(empresa?.id || "").trim();
                globalThis.normalizeSimple = (value) => String(value || "").trim().toLowerCase();
                globalThis.getSegurosRamoLabel = (value) => String(value || "").trim();
                globalThis.renderTableInto = () => {};
                globalThis.refreshSegurosColaboradoresList = () => {};
                globalThis.refreshSegurosRamosList = () => {};
                globalThis.loadSegurosOportunidades = () => {};
                globalThis.loadAcciones = () => {};
                globalThis.loadSegurosOfertas = () => {};
                globalThis.loadSegurosReferidos = () => {};
                globalThis.loadSegurosCampanas = () => {};
                globalThis.loadSegurosComisiones = () => {};
                globalThis.loadSegurosInsights = () => {};
                globalThis.loadSegurosAlertas = () => {};
                globalThis.loadSegurosKpis = () => {};
                globalThis.loadSegurosDataQuality = () => {};
                globalThis.renderSegurosRamosDashboard = () => {};
                globalThis.populateSegurosOperationalSelects = () => {};
                globalThis.loadSegurosComplianceForm = () => {};
                globalThis.loadSegurosComplianceKpis = () => {};
                globalThis.loadSegurosEventos = () => {};
                globalThis.loadSegurosReclamaciones = () => {};
                globalThis.loadSegurosRecibos = () => {};
                globalThis.loadSegurosSiniestros = () => {};
                globalThis.hydrateSegurosRecibosFormSelects = () => Promise.resolve();
                globalThis.hydrateSegurosSiniestrosFormSelects = () => Promise.resolve();
                globalThis.populateAgendaClientes = () => {};
                globalThis.resolveSegurosDashboardEmpresaId = () => "";
                globalThis.segurosCompliancePoliza = null;
                globalThis.segurosEventosPolizaId = null;
                globalThis.segurosPreferenciasClientes = null;
                globalThis.segurosPreferenciasClienteInput = null;
                globalThis.segurosPreferenciasClienteId = null;
                globalThis.segurosOfertasClientes = null;
                globalThis.segurosOfertasClienteInput = null;
                globalThis.segurosOfertasClienteId = null;
                globalThis.segurosReferidosClientes = null;
                globalThis.segurosReferidosClienteInput = null;
                globalThis.segurosReferidosClienteId = null;
                globalThis.segurosRecClientes = null;
                globalThis.segurosRecClienteInput = null;
                globalThis.segurosRecClienteId = null;
                globalThis.createCompanyBadge = (text) => {
                  const node = new FakeNode("span");
                  node.textContent = String(text || "");
                  return node;
                };
                globalThis.euroFormatter = { format: (value) => `€${Number(value || 0).toFixed(2)}` };
                globalThis.escapeHtml = (value) => String(value ?? "");
                globalThis.parseMoneyValue = (value) => Number(String(value || "").replace(",", ".").replace(/[^\\d.-]/g, "")) || 0;
                globalThis.formatCell = (_field, value) => String(value ?? "");
                globalThis.formatAgendaDate = () => "2026-01-01";
                globalThis.SERVICE_LABELS = { seguros: "Seguros" };
                """
            ),
            dedent(
                """
                const { loadSegurosCrm } = api;
                loadSegurosCrm();
                await new Promise((resolve) => setTimeout(resolve, 0));
                assert.strictEqual(renderCalls.length, 1);
                assert.ok(state.segurosCrmData);
                assert.strictEqual(state.segurosCrmData.rows.length, 1);
                assert.strictEqual(segurosCrmInfo.textContent, "");
                """
            ),
        )
