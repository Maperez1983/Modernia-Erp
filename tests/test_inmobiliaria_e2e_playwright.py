import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@unittest.skipUnless(
    (os.environ.get("RUN_PLAYWRIGHT_E2E") or "").strip().lower() in ("1", "true", "yes", "si", "sí", "on"),
    "E2E Playwright desactivado (exporta RUN_PLAYWRIGHT_E2E=1 para ejecutarlo).",
)
class InmobiliariaE2EPlaywrightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from web import server as _server

        cls.server = _server

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "e2e.sqlite"
        self.uploads_dir = Path(self.tmpdir.name) / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

        # Forzar SQLite aunque exista DATABASE_URL/POSTGRES_URL en el entorno.
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
            SET servicio = 'Inmobiliaria', activo = 1, updated_at = datetime('now')
            WHERE LOWER(TRIM(usuario)) = 'admin'
            """,
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

    def test_inmobiliaria_crea_inmueble_y_pdf(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

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

            page.goto(f"{self.base_url}/?crm=inmo&nosw=1&swcleared=1", wait_until="domcontentloaded")
            page.wait_for_selector("#crmSection:not(.hidden)", timeout=20000)

            page.wait_for_selector("#crmTopNewBtn", timeout=20000)
            page.click("#crmTopNewBtn")
            page.wait_for_selector("#crmInsertModal:not(.hidden)", timeout=5000)
            page.click('button[data-crm-insert="captacion"]')
            page.wait_for_selector("#crmCaptacionModal:not(.hidden)", timeout=5000)

            page.fill('#crmCaptacionCreateForm input[name="direccion"]', "CALLE E2E 123")
            page.select_option('#crmCaptacionCreateForm select[name="tipo_inmueble"]', "Piso")
            page.fill('#crmCaptacionCreateForm input[name="referencia_catastral"]', "1234567UF7613S0001AB")

            with page.expect_response(lambda r: "/api/captaciones" in r.url and r.request.method == "POST") as create_info:
                page.click('#crmCaptacionCreateForm button[type="submit"]')
            create_resp = create_info.value
            create_data = {}
            try:
                create_data = create_resp.json()
            except Exception:
                create_data = {}
            self.assertTrue(create_resp.ok, msg=f"Alta inmueble HTTP {create_resp.status} · {create_data}")
            inmueble_id = str(create_data.get("inmueble_id") or "").strip()
            captacion_id = str(create_data.get("id") or "").strip()
            self.assertTrue(inmueble_id, msg=f"Alta inmueble sin inmueble_id · {create_data}")
            self.assertTrue(captacion_id, msg=f"Alta inmueble sin captacion id · {create_data}")

            page.goto(
                f"{self.base_url}/?crm=inmo&inmueble={inmueble_id}&nosw=1&swcleared=1",
                wait_until="domcontentloaded",
            )
            page.wait_for_selector("#inmuebleGoEstadoBtn", timeout=20000)

            # Los PDFs de consumo requieren que el inmueble esté en Encargo.
            stage = page.evaluate(
                """
                async ({ id, etapa, empresa_nombre }) => {
                  const res = await fetch("/api/captaciones_update", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ id, etapa, empresa_nombre }),
                  });
                  let data = {};
                  try { data = await res.json(); } catch (e) { data = {}; }
                  return { ok: res.ok, status: res.status, data };
                }
                """,
                {"id": captacion_id, "etapa": "Encargo", "empresa_nombre": "EMPRESA E2E"},
            )
            self.assertTrue(bool(stage.get("ok")), msg=f"Stage HTTP {stage.get('status')} · {stage.get('data')}")

            pdf_url = f"{self.base_url}/api/inmueble_consumo_pdf?id={inmueble_id}&kind=venta_ficha"
            with page.expect_download(timeout=20000) as dl_info:
                try:
                    page.goto(pdf_url, wait_until="domcontentloaded")
                except Exception as exc:
                    # Playwright lanza "Download is starting" al navegar a URLs que descargan.
                    if "Download is starting" not in str(exc):
                        raise
            download = dl_info.value
            path = download.path()
            self.assertTrue(path, msg="No se pudo obtener la ruta del download")
            with open(path, "rb") as handle:
                body = handle.read(16)
            self.assertTrue(body.startswith(b"%PDF"), msg=f"Download no-PDF (primeros 16 bytes): {body!r}")

            context.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
