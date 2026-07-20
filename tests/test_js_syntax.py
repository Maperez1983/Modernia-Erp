import json
import shutil
import subprocess
import unittest
from pathlib import Path
from textwrap import dedent


class JavaScriptSyntaxTests(unittest.TestCase):
    def test_shared_bundle_references_use_real_filename(self):
        root = Path(__file__).resolve().parents[1]
        index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        app_shared_js = (root / "web" / "app_shared.js").read_text(encoding="utf-8")
        sw_js = (root / "web" / "sw.js").read_text(encoding="utf-8")
        server_py = (root / "web" / "server.py").read_text(encoding="utf-8")

        self.assertIn("window.__APP_SHELL_BOOTSTRAP__", index_html)
        self.assertIn("app-auth.js?v=16", index_html)
        self.assertIn("app.js?v=793", index_html)
        self.assertNotIn('<script src="app.js?v=792"', index_html)
        self.assertNotIn('<script src="ui-foundation.js?v=5"', index_html)
        self.assertNotIn('<script src="app-routing.js?v=13"', index_html)
        self.assertIn('app_shared.js?v=2', index_html)
        self.assertNotIn('<script src="app_shared.js?v=1"', index_html)
        self.assertNotIn('leaflet.css', index_html.split("window.__APP_SHELL_BOOTSTRAP__")[0])
        self.assertNotIn("app-shared.js", index_html)
        self.assertIn("/app_shared.js?v=2", sw_js)
        self.assertNotIn("/app-shared.js?v=1", sw_js)
        self.assertIn('"app_shared.js"', server_py)
        self.assertNotIn('"app-shared.js"', server_py)
        self.assertIn('const openBlobInNewTab = (blob, filename = "archivo") => {', app_shared_js)
        self.assertIn('a.target = "_blank";', app_shared_js)
        self.assertNotIn('a.download = filename || "archivo";', app_shared_js)
        self.assertNotIn('window.open(url, "_blank", "noopener,noreferrer")', app_shared_js)
        self.assertIn('const getHipotecaPrintBrandContext = ({ filters = {}, title = "" } = {}) => {', app_js)
        self.assertIn('const openCrmPrintWindow = ({ title = "Impresión", html = "" } = {}) => {', app_js)
        self.assertIn('hipoteca-print-brand-logo', app_js)
        self.assertIn('hipoteca-print-summary', app_js)
        self.assertIn('const downloadHipotecaBdtExcel = async () => {', app_js)
        self.assertIn('/api/hipotecas_listado_excel', app_js)
        self.assertNotIn('openHipotecaFirmadasListadoPrint', app_js)
        self.assertNotIn('downloadHipotecasFirmadasExcel', app_js)
        open_blob_snippet = app_js[
            app_js.index("const fallbackOpenBlobInNewTab =")
            : app_js.index("const fallbackFetchBlobFromGet =")
        ]
        print_window_snippet = app_js[
            app_js.index("const openCrmPrintWindow =")
            : app_js.index("const writeCrmPrintWindow =")
        ]
        self.assertIn('a.target = "_blank";', open_blob_snippet)
        self.assertNotIn('a.download = filename || "archivo";', open_blob_snippet)
        self.assertIn('a.target = "_blank";', print_window_snippet)
        self.assertNotIn("a.download", print_window_snippet)
        self.assertIn('window.print()', app_js)
        self.assertIn('id="hipotecaBdtExcelListado"', index_html)
        self.assertIn('PDF listado', index_html)
        self.assertIn('Excel listado', index_html)
        self.assertIn('Fichas de hipotecas', index_html)
        self.assertNotIn('hipotecaBdtPrintFirmadas2026', index_html)
        self.assertNotIn('hipotecaBdtExcelFirmadas2026', index_html)

    def test_app_js_boot_falls_back_without_shared_module_and_prefers_shared_helpers(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node no está disponible")

        root = Path(__file__).resolve().parents[1]
        app_js_path = root / "web" / "app.js"
        app_js = app_js_path.read_text(encoding="utf-8")
        marker = "const api = async"
        self.assertIn(marker, app_js)
        prefix = app_js[: app_js.index(marker)]
        self.assertIn("const useSharedOrFallback =", app_js)
        self.assertIn("const fallbackFetchWithTimeout =", app_js)
        self.assertIn('console.warn("CRMAppShared no disponible; usando fallbacks locales de arranque.")', app_js)

        script = dedent(
            f"""
            const assert = require("assert");
            const prefix = {json.dumps(prefix)};

            function buildHarness(shared) {{
              const warns = [];
              const toastLog = [];
              const runner = new Function(
                "window",
                "document",
                "localStorage",
                "fetch",
                "AbortController",
                "setTimeout",
                "clearTimeout",
                "Headers",
                "URL",
                "URLSearchParams",
                "Blob",
                "console",
                prefix + `
return {{
  fetchWithTimeout,
  sanitizeApiUrl,
  safeHrefUrl,
  safeUrlValue,
  normalizeTenantWorkspaceSlug,
  setUiToast,
  hideUiToast,
  probeDbHealth,
  getDeepLinkParams,
  getDeepLinkToken,
  safeImageUrl,
  safeOpenUrl,
  openBlobInNewTab,
  fetchBlobFromGet,
}};`
              );
              const toast = {{
                classList: {{ remove() {{}}, add() {{}} }},
                innerHTML: "",
                appendChild(node) {{
                  toastLog.push(String(node && node.textContent ? node.textContent : ""));
                }},
              }};
              const document = {{
                getElementById(id) {{
                  return id === "uiErrorToast" ? toast : null;
                }},
                createElement(tag) {{
                  return {{
                    tagName: String(tag || "").toUpperCase(),
                    textContent: "",
                    appendChild() {{}},
                    removeChild() {{}},
                    classList: {{ add() {{}}, remove() {{}} }},
                  }};
                }},
                body: {{
                  appendChild() {{}},
                  removeChild() {{}},
                }},
              }};
              const window = {{
                CRMAppShared: shared,
                location: {{
                  origin: "https://crm.example",
                  search: "?workspace=alpha",
                  hash: "#firma_inmo=abc",
                }},
                open() {{ return null; }},
                document,
              }};
              window.window = window;
              const result = runner(
                window,
                document,
                {{ removeItem() {{}} }},
                async () => ({{
                  ok: true,
                  status: 200,
                  json: async () => ({{}}),
                  text: async () => "",
                  blob: async () => new Blob(["x"]),
                  headers: {{ get: () => null }},
                }}),
                class {{ constructor() {{ this.signal = {{}}; }} abort() {{}} }},
                setTimeout,
                clearTimeout,
                Headers,
                URL,
                URLSearchParams,
                Blob,
                {{ warn: (...args) => warns.push(args.join(" ")) }}
              );
              return {{ ...result, warns, toastLog, window }};
            }}

            (async () => {{
              const fallback = buildHarness(null);
              assert.strictEqual(fallback.warns.length, 1);
              assert.ok(fallback.warns[0].includes("CRMAppShared"));
              for (const name of [
                "fetchWithTimeout",
                "sanitizeApiUrl",
                "safeHrefUrl",
                "safeUrlValue",
                "normalizeTenantWorkspaceSlug",
                "setUiToast",
                "hideUiToast",
                "probeDbHealth",
                "getDeepLinkParams",
                "getDeepLinkToken",
                "safeImageUrl",
                "safeOpenUrl",
                "openBlobInNewTab",
                "fetchBlobFromGet",
              ]) {{
                assert.strictEqual(typeof fallback[name], "function");
              }}
              const fallbackResponse = await fallback.fetchWithTimeout("/api/health");
              assert.strictEqual(fallbackResponse.ok, true);
              assert.strictEqual(fallback.sanitizeApiUrl("/api/foo?token=secret&x=1"), "https://crm.example/api/foo?token=***&x=1");
              assert.strictEqual(fallback.safeHrefUrl("javascript:alert(1)"), "");
              assert.strictEqual(fallback.safeHrefUrl("/foo"), "https://crm.example/foo");
              assert.strictEqual(fallback.safeUrlValue("blob:abc", {{ allowBlob: true }}), "blob:abc");
              assert.strictEqual(fallback.normalizeTenantWorkspaceSlug("modernia"), "verifika2");
              assert.strictEqual(fallback.getDeepLinkToken("firma_inmo"), "abc");
              fallback.setUiToast("Aviso", "Detalle");
              assert.deepStrictEqual(fallback.toastLog.slice(0, 2), ["Aviso", "Detalle"]);
              const fallbackHealth = await fallback.probeDbHealth();
              assert.strictEqual(fallbackHealth.ok, true);
              fallback.hideUiToast();

              const shared = buildHarness({{
                normalizeSlugLike: (value) => `shared-slug:${{value}}`,
                normalizeTenantWorkspaceSlug: (value) => `shared-tenant:${{value}}`,
                fetchWithTimeout: async () => "shared-fetch",
                setUiToast: (...args) => `shared-toast:${{args.join("|")}}`,
                hideUiToast: () => "shared-hide",
                probeDbHealth: async () => "shared-probe",
                sanitizeApiUrl: (value) => `shared-sanitize:${{value}}`,
                getDeepLinkParams: () => new URLSearchParams("foo=bar"),
                getDeepLinkToken: (name) => `shared-token:${{name}}`,
                safeUrlValue: (value) => `shared-safe:${{value}}`,
                safeHrefUrl: (value) => `shared-href:${{value}}`,
                safeImageUrl: (value) => `shared-image:${{value}}`,
                safeOpenUrl: (value) => `shared-open:${{value}}`,
                openBlobInNewTab: () => "shared-blob",
                fetchBlobFromGet: async () => "shared-fetch-blob",
              }});
              assert.strictEqual(await shared.fetchWithTimeout("/api/test"), "shared-fetch");
              assert.strictEqual(shared.sanitizeApiUrl("/api/foo"), "shared-sanitize:/api/foo");
              assert.strictEqual(shared.safeHrefUrl("/foo"), "shared-href:/foo");
              assert.strictEqual(shared.safeUrlValue("/foo"), "shared-safe:/foo");
              assert.strictEqual(shared.normalizeTenantWorkspaceSlug("modernia"), "shared-tenant:modernia");
              assert.strictEqual(shared.setUiToast("A", "B"), "shared-toast:A|B");
              assert.strictEqual(shared.hideUiToast(), "shared-hide");
              assert.strictEqual(await shared.probeDbHealth(), "shared-probe");
              assert.strictEqual(shared.getDeepLinkToken("portal_token"), "shared-token:portal_token");
              assert.strictEqual(shared.safeImageUrl("/img.png"), "shared-image:/img.png");
              assert.strictEqual(shared.safeOpenUrl("/doc.pdf"), "shared-open:/doc.pdf");
              assert.strictEqual(shared.openBlobInNewTab(new Blob(["x"]), "x.pdf"), "shared-blob");
              assert.strictEqual(await shared.fetchBlobFromGet("/blob"), "shared-fetch-blob");
            }})().catch((err) => {{
              console.error(err);
              process.exit(1);
            }});
            """
        )

        subprocess.run([node, "-e", script], check=True, capture_output=True, text=True)

    def test_modified_javascript_files_parse(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node no está disponible")

        root = Path(__file__).resolve().parents[1]
        for rel_path in ("web/app_shared.js", "web/ui-foundation.js", "web/app.js", "web/sw.js"):
            subprocess.run(
                [node, "--check", str(root / rel_path)],
                check=True,
                capture_output=True,
                text=True,
            )

    def test_hipotecas_listado_print_uses_excel_like_columns(self):
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "web" / "app.js").read_text(encoding="utf-8")
        index_html = (root / "web" / "index.html").read_text(encoding="utf-8")

        self.assertIn('const HIPOTECA_BDT_PRINT_COLUMNS = [', app_js)
        for label in ("Fecha de firma", "Nombre cliente", "Banco", "Importe de hipoteca", "Comisión cobrada"):
            self.assertIn(label, app_js)
        self.assertIn("openHipotecaBdtListadoPrint", app_js)
        self.assertIn("downloadHipotecaBdtExcel", app_js)
        self.assertIn("writeCrmPrintWindow", app_js)
        self.assertIn('id="hipotecaBdtPrintListado"', index_html)
        self.assertIn('id="hipotecaBdtExcelListado"', index_html)
        self.assertIn('id="hipotecaBdtPrintFichas"', index_html)
        self.assertIn('PDF listado', index_html)
        self.assertIn('Excel listado', index_html)
        self.assertIn('Fichas de hipotecas', index_html)
        self.assertNotIn('hipotecaBdtPrintFirmadas2026', index_html)
        self.assertNotIn('hipotecaBdtExcelFirmadas2026', index_html)
