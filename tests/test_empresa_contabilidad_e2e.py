import os
import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@unittest.skipUnless(
    sync_playwright is not None
    and (os.environ.get("RUN_PLAYWRIGHT_E2E") or "").strip().lower() in ("1", "true", "yes", "si", "sí", "on"),
    "E2E de contabilidad desactivado (exporta RUN_PLAYWRIGHT_E2E=1 para ejecutarlo).",
)
class EmpresaContabilidadE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web import server as _server

        cls.server = _server

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "e2e.sqlite"
        self.uploads_dir = Path(self.tmpdir.name) / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        os.environ["APP_DB_BACKEND"] = "sqlite"

        self.server.ensure_tables(self.db_path)
        self.conn = self.server.open_sqlite_conn(str(self.db_path), with_row_factory=True)

        now = _now_iso()
        company_id = "emp-conta-e2e"
        client_id = "cli-conta-e2e"
        supplier_id = "ter-conta-e2e-sup"
        customer_id = "ter-conta-e2e-cust"
        compra_factura_id = "fac-conta-e2e-compra"
        venta_factura_id = "fac-conta-e2e-venta"
        compra_asiento_id = "asi-conta-e2e-compra"
        venta_asiento_id = "asi-conta-e2e-venta"

        self.company_id = company_id
        self.client_id = client_id

        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (company_id, "EMPRESA CONTA E2E", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO clientes (id, empresa_id, nombre, nif, estado, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Activo', datetime(?), datetime(?))
            """,
            (client_id, company_id, "CLIENTE CONTA E2E", "12345678Z", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, created_at, updated_at)
            VALUES (?, ?, ?, 'gestoria', 'Activo', datetime(?), datetime(?))
            """,
            ("ce-conta-e2e", client_id, company_id, now, now),
        )
        self.conn.execute(
            """
            UPDATE usuarios
            SET servicio = 'Gestoría', activo = 1, updated_at = datetime('now')
            WHERE LOWER(TRIM(usuario)) = 'admin'
            """,
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_terceros (id, empresa_id, nif, nombre, tipo, cuenta_contable, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (supplier_id, company_id, "B12345678", "PROVEEDOR E2E", "Proveedor", "400000", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_terceros (id, empresa_id, nif, nombre, tipo, cuenta_contable, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (customer_id, company_id, "C87654321", "CLIENTE E2E", "Cliente", "430000", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_modelos (
              id, cliente_id, modelo, periodicidad, proxima_fecha, responsable, estado, notas, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (
                "mod-conta-e2e-303",
                client_id,
                "Modelo 303",
                "Trimestral",
                (datetime.now(timezone.utc).date() + timedelta(days=15)).isoformat(),
                "admin",
                "Pendiente",
                "Carga E2E",
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tercero_id, tipo, numero, fecha_emision,
              descripcion, base_imponible, cuota_iva, cuota_irpf, total, iva_pct,
              estado_ocr, doc_key, archivo_hash, dedupe_key, raw_text, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                compra_factura_id,
                company_id,
                client_id,
                supplier_id,
                "compra",
                "F-E2E-COMPRA",
                "2026-07-01",
                "Factura E2E compra",
                100.0,
                21.0,
                0.0,
                121.0,
                21.0,
                "OK",
                "doc-e2e-compra",
                "",
                "",
                "",
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tercero_id, tipo, numero, fecha_emision,
              descripcion, base_imponible, cuota_iva, cuota_irpf, total, iva_pct,
              estado_ocr, doc_key, archivo_hash, dedupe_key, raw_text, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, ?,
              ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                venta_factura_id,
                company_id,
                client_id,
                customer_id,
                "venta",
                "F-E2E-VENTA",
                "2026-07-02",
                "Factura E2E venta",
                150.0,
                31.5,
                0.0,
                181.5,
                21.0,
                "OK",
                "doc-e2e-venta",
                "",
                "",
                "",
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_asientos (
              id, empresa_id, cliente_id, factura_id, fecha, concepto, diario, referencia,
              total_debe, total_haber, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (
                compra_asiento_id,
                company_id,
                client_id,
                compra_factura_id,
                "2026-07-01",
                "Asiento compra E2E",
                "General",
                "AC-E2E-1",
                121.0,
                121.0,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_asientos (
              id, empresa_id, cliente_id, factura_id, fecha, concepto, diario, referencia,
              total_debe, total_haber, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (
                venta_asiento_id,
                company_id,
                client_id,
                venta_factura_id,
                "2026-07-02",
                "Asiento venta E2E",
                "General",
                "AV-E2E-1",
                181.5,
                181.5,
                now,
                now,
            ),
        )
        self.conn.executemany(
            """
            INSERT INTO gestoria_asiento_lineas (
              id, asiento_id, tercero_id, cuenta, descripcion, debe, haber, impuesto_tipo, impuesto_pct, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            [
                (
                    "asl-conta-e2e-1",
                    compra_asiento_id,
                    supplier_id,
                    "600000",
                    "Compra E2E",
                    100.0,
                    0.0,
                    "",
                    0.0,
                    now,
                    now,
                ),
                (
                    "asl-conta-e2e-2",
                    compra_asiento_id,
                    None,
                    "472000",
                    "IVA soportado E2E",
                    21.0,
                    0.0,
                    "iva",
                    21.0,
                    now,
                    now,
                ),
                (
                    "asl-conta-e2e-3",
                    compra_asiento_id,
                    supplier_id,
                    "400000",
                    "Proveedor E2E",
                    0.0,
                    121.0,
                    "",
                    0.0,
                    now,
                    now,
                ),
                (
                    "asl-conta-e2e-4",
                    venta_asiento_id,
                    customer_id,
                    "430000",
                    "Cliente E2E",
                    181.5,
                    0.0,
                    "",
                    0.0,
                    now,
                    now,
                ),
                (
                    "asl-conta-e2e-5",
                    venta_asiento_id,
                    customer_id,
                    "700000",
                    "Venta E2E",
                    0.0,
                    150.0,
                    "",
                    0.0,
                    now,
                    now,
                ),
                (
                    "asl-conta-e2e-6",
                    venta_asiento_id,
                    None,
                    "477000",
                    "IVA repercutido E2E",
                    0.0,
                    31.5,
                    "iva",
                    21.0,
                    now,
                    now,
                ),
            ],
        )
        self.conn.commit()

        self.httpd = self.server.ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        self.httpd.daemon_threads = True
        self.server.Handler.db_path = str(self.db_path)
        self.server.Handler.ocr_db_path = str(Path(self.tmpdir.name) / "ocr.sqlite")
        self.server.UPLOADS = self.uploads_dir

        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._server_thread = threading.Thread(target=self.httpd.serve_forever, name="e2e-httpd", daemon=True)
        self._server_thread.start()
        time.sleep(0.05)

    def tearDown(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def _find_chrome_binary(self):
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            shutil.which("google-chrome"),
            shutil.which("google-chrome-stable"),
            shutil.which("chromium"),
            shutil.which("chromium-browser"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists() and os.access(candidate, os.X_OK):
                return candidate
        self.skipTest("Google Chrome no disponible para la prueba E2E de contabilidad.")

    def _login(self, page):
        page.goto(f"{self.base_url}/?nosw=1&swcleared=1", wait_until="commit")
        page.wait_for_selector("#authLoginUser", timeout=20000)
        page.fill("#authLoginUser", "admin")
        page.fill("#authLoginPass", "adminadmin")
        with page.expect_response(lambda r: r.url.endswith("/api/login")) as login_info:
            page.click('#authLoginForm button[type="submit"]')
        login_resp = login_info.value
        try:
            login_data = login_resp.json()
        except Exception:
            login_data = {}
        self.assertTrue(login_resp.ok, msg=f"Login HTTP {login_resp.status} · {login_data}")
        self.assertTrue(bool(login_data.get("ok")), msg=f"Login no OK · {login_data}")
        page.wait_for_function("() => !document.body.classList.contains('auth-locked')", timeout=60000)

    def _ensure_companies_loaded(self, page):
        page.wait_for_function("() => typeof state !== 'undefined'", timeout=60000)
        page.evaluate(
            """
            async (companyId) => {
              if (!Array.isArray(state.empresas) || !state.empresas.length) {
                const res = await fetch('/api/empresas', { credentials: 'same-origin' });
                state.empresas = await res.json();
              }
              return state.empresas.some((row) => String(row.id || '').trim() === String(companyId || '').trim());
            }
            """,
            self.company_id,
        )
        page.wait_for_function(
            """
            (companyId) => {
              try {
                return Array.isArray(state.empresas) && state.empresas.some((row) => String(row.id || '').trim() === String(companyId || '').trim());
              } catch (e) {
                return false;
              }
            }
            """,
            arg=self.company_id,
            timeout=60000,
        )

    def _open_company_ficha(self, page):
        page.wait_for_function("() => typeof openWorkspaceCompanyFicha === 'function'", timeout=60000)
        page.evaluate(
            """
            ({ companyId }) => {
              if (typeof openWorkspaceCompanyFicha === 'function') {
                openWorkspaceCompanyFicha(companyId, 'dashboard');
              }
            }
            """,
            {"companyId": self.company_id},
        )
        page.wait_for_selector("#workspaceCompanyFicha:not(.hidden)", timeout=60000)
        page.wait_for_function(
            """
            () => {
              const pane = document.querySelector('#workspaceCompanyFichaBody [data-company-conta-pane="dashboard"]');
              return !!pane && !(pane.classList.contains('hidden') || pane.hidden) && (pane.innerText || '').includes('Resumen contable');
            }
            """,
            timeout=60000,
        )

    def _wait_company_pane_text(self, page, pane_key, expected_text):
        page.wait_for_function(
            """
            ({ paneKey, expectedText }) => {
              const pane = document.querySelector(`#workspaceCompanyFichaBody [data-company-conta-pane="${paneKey}"]`);
              if (!pane) return false;
              if (pane.classList.contains('hidden') || pane.hidden) return false;
              const text = (pane.innerText || pane.textContent || '').replace(/\\s+/g, ' ');
              return text.includes(expectedText);
            }
            """,
            arg={"paneKey": pane_key, "expectedText": expected_text},
            timeout=60000,
        )

    def test_empresa_contabilidad_tabs_muestran_contenido_distinto(self):
        chrome_binary = self._find_chrome_binary()
        if sync_playwright is None:
            self.skipTest('Playwright no está instalado en este entorno.')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=chrome_binary)
            try:
                context = browser.new_context()
                page = context.new_page()
                page.set_default_navigation_timeout(120000)
                page.set_default_timeout(60000)

                self._login(page)
                self._ensure_companies_loaded(page)
                self._open_company_ficha(page)

                dashboard = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="dashboard"]')
                self.assertIn('Resumen contable', dashboard.inner_text())
                self.assertIn('EMPRESA CONTA E2E', dashboard.inner_text())

                page.click('#workspaceCompanyFicha [data-company-conta-tabs] button[data-company-conta-tab="diario"]')
                self._wait_company_pane_text(page, 'diario', 'Libro diario')
                diario = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="diario"]')
                diario_text = diario.inner_text()
                self.assertIn('Factura E2E compra', diario_text)
                self.assertIn('Factura E2E venta', diario_text)
                self.assertIn('600000', diario_text)
                self.assertIn('700000', diario_text)

                page.click('#workspaceCompanyFicha [data-company-conta-tabs] button[data-company-conta-tab="mayor"]')
                self._wait_company_pane_text(page, 'mayor', 'Libro mayor')
                mayor = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="mayor"]')
                mayor_text = mayor.inner_text()
                self.assertIn('Libro mayor', mayor_text)
                self.assertIn('400000', mayor_text)
                self.assertIn('430000', mayor_text)

                page.click('#workspaceCompanyFicha [data-company-conta-tabs] button[data-company-conta-tab="balances"]')
                self._wait_company_pane_text(page, 'balance-situacion', 'Balance de situación')
                balance = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="balance-situacion"]')
                balance_text = balance.inner_text()
                self.assertIn('Balance de situación', balance_text)
                self.assertIn('472000', balance_text)
                self.assertIn('400000', balance_text)

                page.click('#workspaceCompanyFicha [data-company-conta-balance-tabs] button[data-company-conta-balance-tab="pyg"]')
                self._wait_company_pane_text(page, 'pyg', 'P&G')
                pyg = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="pyg"]')
                pyg_text = pyg.inner_text()
                self.assertIn('P&G', pyg_text)
                self.assertIn('600000', pyg_text)
                self.assertIn('700000', pyg_text)

                page.click('#workspaceCompanyFicha [data-company-conta-tabs] button[data-company-conta-tab="modelos"]')
                self._wait_company_pane_text(page, 'modelos', 'Modelos fiscales')
                modelos = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="modelos"]')
                modelos_text = modelos.inner_text()
                self.assertIn('Modelos fiscales', modelos_text)
                self.assertIn('Modelo 303', modelos_text)

                page.click('#workspaceCompanyFicha [data-company-conta-tabs] button[data-company-conta-tab="asientos"]')
                self._wait_company_pane_text(page, 'asientos', 'Asientos')
                asientos = page.locator('#workspaceCompanyFichaBody [data-company-conta-pane="asientos"]')
                asientos_text = asientos.inner_text()
                self.assertIn('Asientos', asientos_text)
                self.assertIn('Asiento compra E2E', asientos_text)
                self.assertIn('Asiento venta E2E', asientos_text)
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
