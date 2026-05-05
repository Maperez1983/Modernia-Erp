import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@unittest.skipUnless(
    (os.environ.get("RUN_PLAYWRIGHT_E2E") or "").strip().lower() in ("1", "true", "yes", "si", "sí", "on"),
    "E2E Playwright desactivado (exporta RUN_PLAYWRIGHT_E2E=1 para ejecutarlo).",
)
class SegurosE2EPlaywrightTests(unittest.TestCase):
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
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            ("emp-e2e", "EMPRESA E2E", now, now),
        )
        self.conn.execute(
            """
            UPDATE usuarios
            SET servicio = 'Seguros', activo = 1, updated_at = datetime('now')
            WHERE LOWER(TRIM(usuario)) = 'admin'
            """,
        )

        cliente_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO clientes (id, empresa_id, nombre, nif, estado, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Activo', datetime(?), datetime(?))
            """,
            (cliente_id, "emp-e2e", "CLIENTE E2E", "12345678Z", now, now),
        )

        today = datetime.now(timezone.utc).date()
        fecha_efecto = (today - timedelta(days=10)).isoformat()
        fecha_venc = (today + timedelta(days=10)).isoformat()
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id,
              fecha_efecto, fecha_vencimiento,
              tomador, compania, ramo, poliza_numero,
              prima_total, comision, colaborador,
              created_at, updated_at
            ) VALUES (
              ?, ?, ?,
              ?, ?,
              ?, ?, ?, ?,
              ?, ?, ?,
              datetime(?), datetime(?)
            )
            """,
            (
                "seg-e2e-1",
                "emp-e2e",
                cliente_id,
                fecha_efecto,
                fecha_venc,
                "CLIENTE E2E",
                "MAPFRE",
                "Auto",
                "POL-E2E-1",
                1000.0,
                150.0,
                "admin",
                now,
                now,
            ),
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

    def _login(self, page):
        page.goto(f"{self.base_url}/?nosw=1&swcleared=1", wait_until="domcontentloaded")
        page.fill("#authLoginUser", "admin")
        page.fill("#authLoginPass", "adminadmin")
        with page.expect_response(lambda r: r.url.endswith("/api/login")) as login_info:
            page.click('#authLoginForm button[type="submit"]')
        login_resp = login_info.value
        login_data = {}
        try:
            login_data = login_resp.json()
        except Exception:
            login_data = {}
        self.assertTrue(login_resp.ok, msg=f"Login HTTP {login_resp.status} · {login_data}")
        self.assertTrue(bool(login_data.get("ok")), msg=f"Login no OK · {login_data}")
        page.wait_for_function("() => !document.body.classList.contains('auth-locked')", timeout=20000)

    def _open_crm_seguros(self, page):
        page.goto(f"{self.base_url}/?crm=seguros&nosw=1&swcleared=1", wait_until="domcontentloaded")
        page.wait_for_selector("#segurosCrmSection:not(.hidden)", timeout=20000)
        page.wait_for_function(
            "(() => { try { return (state && Array.isArray(state.empresas) && state.empresas.length > 0); } catch(e){ return false; } })()",
            timeout=20000,
        )

    def test_seguros_dashboard_kpi_vencimientos_abre_renovaciones(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._open_crm_seguros(page)

            # Espera a que el KPI de vencimientos exista y refleje el seed.
            page.wait_for_selector("#segurosKpis .kpi-card--alert", timeout=20000)
            page.wait_for_function(
                "() => { const el = document.querySelector('#segurosKpis .kpi-card--alert .kpi-value'); return el && String(el.textContent||'').trim() !== ''; }",
                timeout=20000,
            )

            # Click en "Vencen 30 días" debe abrir listado de renovaciones.
            page.evaluate(
                """
                () => {
                  const el = document.querySelector('#segurosKpis .kpi-card--alert');
                  if (el) el.click();
                }
                """
            )
            page.wait_for_function(
                "() => { try { return (state && state.segurosTab === 'renovaciones'); } catch (e) { return false; } }",
                timeout=20000,
            )
            page.wait_for_selector(".seguros-tab.active[data-seguros-tab=\"renovaciones\"]", timeout=20000)
            page.wait_for_selector("#segurosRenovacionesTable table", timeout=20000)
            page.wait_for_function(
                "() => { const el = document.getElementById('segurosRenovacionesInfo'); return el && (el.textContent||'').includes('renovación'); }",
                timeout=20000,
            )

            browser.close()


if __name__ == "__main__":
    unittest.main()
