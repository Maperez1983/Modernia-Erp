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

    def _open_crm_inmo(self, page):
        page.goto(f"{self.base_url}/?crm=inmo&nosw=1&swcleared=1", wait_until="domcontentloaded")
        page.wait_for_selector("#crmSection:not(.hidden)", timeout=20000)

    def _create_inmueble(self, page):
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
        return inmueble_id, captacion_id

    def _open_inmueble(self, page, inmueble_id):
        page.goto(
            f"{self.base_url}/?crm=inmo&inmueble={inmueble_id}&nosw=1&swcleared=1",
            wait_until="domcontentloaded",
        )
        page.wait_for_selector("#inmuebleGoEstadoBtn", timeout=20000)
        # Asegura que el contexto de empresa esté disponible antes de guardar acciones (evita FK por empresa_id vacío).
        page.wait_for_function(
            "(() => { try { return (state && Array.isArray(state.empresas) && state.empresas.length > 0 && String(resolveCrmInmoEmpresaId()||'').trim()); } catch(e){ return false; } })()",
            timeout=20000,
        )
        page.wait_for_function(
            "(() => { try { return !!(state && String(state.currentInmuebleId||'').trim()); } catch(e){ return false; } })()",
            timeout=20000,
        )

    def test_inmobiliaria_crea_inmueble_y_pdf(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._open_crm_inmo(page)
            inmueble_id, captacion_id = self._create_inmueble(page)
            self._open_inmueble(page, inmueble_id)

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

    def test_inmobiliaria_cambiar_estado_crea_cita_y_avanza(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._open_crm_inmo(page)
            inmueble_id, _captacion_id = self._create_inmueble(page)
            self._open_inmueble(page, inmueble_id)

            # "Cambiar estado" pre-rellena la cita de adquisición en la pestaña Actividad.
            page.click("#inmuebleGoEstadoBtn")
            page.wait_for_selector("#inmuebleTabActividad:not(.hidden)", timeout=15000)
            page.wait_for_selector("#inmuebleActividadForm", timeout=15000)

            # Cerramos la cita como Realizada/Positivo para forzar avance de etapa.
            page.select_option('#inmuebleActividadForm select[name="estado"]', "Completada")
            page.select_option('#inmuebleActividadForm select[name="resultado_cierre"]', "Positivo")

            with page.expect_response(lambda r: "/api/acciones" in r.url and r.request.method == "POST") as act_info:
                page.click('#inmuebleActividadForm button[type="submit"]')
            act_resp = act_info.value
            act_data = {}
            try:
                act_data = act_resp.json()
            except Exception:
                act_data = {}
            self.assertTrue(act_resp.ok, msg=f"Acción HTTP {act_resp.status} · {act_data}")
            # El workflow debería mover de Inmueble -> Noticia (o Encargo en algunos escenarios).
            next_stage = str(act_data.get("inmueble_estado") or act_data.get("captacion_etapa") or "").strip()
            self.assertIn(next_stage, {"Noticia", "Encargo"}, msg=f"Etapa inesperada: {next_stage} · {act_data}")

            context.close()
            browser.close()

    def test_inmobiliaria_crear_actividad_desde_quick_new(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._open_crm_inmo(page)

            page.click("#crmTopNewBtn")
            page.wait_for_selector("#crmInsertModal:not(.hidden)", timeout=5000)
            page.click('button[data-crm-insert="actividad"]')
            page.wait_for_selector("#actionModal:not(.hidden)", timeout=10000)

            # En este flujo el servicio viene bloqueado por la UI (lock_service=true).
            service_value = page.input_value("#actionModalServicioSelect")
            self.assertEqual(service_value, "inmobiliaria")

            today = datetime.now().date().isoformat()
            page.fill("#actionModalFecha", today)
            page.fill("#actionModalTipo", "Llamada")
            page.fill("#actionModalNotas", "E2E: llamada de prueba")

            with page.expect_response(lambda r: r.url.endswith("/api/acciones") and r.request.method == "POST") as resp_info:
                page.click("#actionModalSave")
            resp = resp_info.value
            data = {}
            try:
                data = resp.json()
            except Exception:
                data = {}
            self.assertTrue(resp.ok, msg=f"Acción (modal) HTTP {resp.status} · {data}")

            context.close()
            browser.close()

    def test_inmobiliaria_comprador_demanda_visita_y_hoja_visita_pdf(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)
            self._open_crm_inmo(page)

            # 1) Crear inmueble y pasar a Encargo.
            inmueble_id, captacion_id = self._create_inmueble(page)
            self._open_inmueble(page, inmueble_id)
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

            # 2) Crear cliente comprador (modal CRM).
            page.click("#crmTopNewBtn")
            page.wait_for_selector("#crmInsertModal:not(.hidden)", timeout=5000)
            page.click('button[data-crm-insert="cliente"]')
            page.wait_for_selector("#crmClienteModal:not(.hidden)", timeout=5000)
            page.fill('#crmClienteCreateForm input[name="nombre"]', "COMPRADOR E2E")
            page.fill('#crmClienteCreateForm input[name="nif"]', "12345678Z")
            with page.expect_response(lambda r: r.url.endswith("/api/clientes") and r.request.method == "POST") as cli_info:
                page.click('#crmClienteCreateForm button[type="submit"]')
            cli_resp = cli_info.value
            cli_data = {}
            try:
                cli_data = cli_resp.json()
            except Exception:
                cli_data = {}
            self.assertTrue(cli_resp.ok, msg=f"Cliente HTTP {cli_resp.status} · {cli_data}")
            buyer_id = str(cli_data.get("id") or "").strip()
            self.assertTrue(buyer_id, msg=f"Cliente sin id · {cli_data}")

            # 3) Crear demanda del comprador.
            demanda = page.evaluate(
                """
                async ({ cliente_id }) => {
                  const res = await fetch("/api/demandas", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({
                      empresa_nombre: "EMPRESA E2E",
                      cliente_id,
                      pedido: "Pedido E2E",
                      tipo: "Compra",
                      estado: "Activa",
                      fase: "Captación",
                      prioridad: "Media",
                      responsable: "admin",
                      fecha_insercion: new Date().toISOString().slice(0, 10),
                      notas: "E2E demanda",
                    }),
                  });
                  let data = {};
                  try { data = await res.json(); } catch (e) { data = {}; }
                  return { ok: res.ok, status: res.status, data };
                }
                """,
                {"cliente_id": buyer_id},
            )
            self.assertTrue(bool(demanda.get("ok")), msg=f"Demanda HTTP {demanda.get('status')} · {demanda.get('data')}")

            # Sacar demanda_id mirando últimas demandas (no hay id en response).
            demanda_row = page.evaluate(
                """
                async () => {
                  const res = await fetch("/api/demandas?empresa_id=emp-e2e&limit=5", { credentials: "same-origin" });
                  const data = await res.json().catch(() => ({}));
                  const rows = Array.isArray(data?.rows) ? data.rows : [];
                  return rows[0] || null;
                }
                """
            )
            self.assertTrue(demanda_row and demanda_row.get("id"), msg=f"No se pudo resolver demanda: {demanda_row}")
            demanda_id = demanda_row["id"]

            # 4) Crear visita (inmueble <-> demanda).
            visita = page.evaluate(
                """
                async ({ inmueble_id, demanda_id }) => {
                  const res = await fetch("/api/visitas", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({
                      empresa_nombre: "EMPRESA E2E",
                      inmueble_id,
                      demanda_id,
                      fecha: new Date().toISOString().slice(0,10),
                      hora: "12:00",
                      estado: "pendiente",
                      asesor: "admin",
                      notas: "E2E visita",
                    }),
                  });
                  let data = {};
                  try { data = await res.json(); } catch (e) { data = {}; }
                  return { ok: res.ok, status: res.status, data };
                }
                """,
                {"inmueble_id": inmueble_id, "demanda_id": demanda_id},
            )
            self.assertTrue(bool(visita.get("ok")), msg=f"Visita HTTP {visita.get('status')} · {visita.get('data')}")

            # 5) Generar hoja de visita PDF (ahora debería existir comprador por demanda/visita).
            pdf_url = f"{self.base_url}/api/inmueble_visita_pdf?id={inmueble_id}&demanda_id={demanda_id}"
            with page.expect_download(timeout=20000) as dl_info:
                try:
                    page.goto(pdf_url, wait_until="domcontentloaded")
                except Exception as exc:
                    if "Download is starting" not in str(exc):
                        raise
            download = dl_info.value
            path = download.path()
            self.assertTrue(path)
            with open(path, "rb") as handle:
                body = handle.read(16)
            self.assertTrue(body.startswith(b"%PDF"))

            context.close()
            browser.close()

    def test_inmobiliaria_docs_upload_local_s3_fallback(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            self._login(page)

            # Pedir "presign" sin credenciales: debe devolver URL local.
            presign = page.evaluate(
                """
                async () => {
                  const res = await fetch("/api/s3_presign", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "same-origin",
                    body: JSON.stringify({ filename: "e2e_test.pdf", content_type: "application/pdf", prefix: "inmuebles" }),
                  });
                  const data = await res.json().catch(() => ({}));
                  return { ok: res.ok, status: res.status, data };
                }
                """
            )
            self.assertTrue(bool(presign.get("ok")), msg=f"Presign HTTP {presign.get('status')} · {presign.get('data')}")
            url = presign["data"].get("url")
            key = presign["data"].get("key")
            self.assertTrue(url and key, msg=f"Presign inválido: {presign}")

            # Subir por PUT al endpoint local.
            put = page.evaluate(
                """
                async ({ url }) => {
                  const bytes = new TextEncoder().encode("%PDF-1.4\\n% E2E\\n1 0 obj<<>>endobj\\ntrailer<<>>\\n%%EOF\\n");
                  const res = await fetch(url, {
                    method: "PUT",
                    headers: { "Content-Type": "application/pdf" },
                    body: bytes,
                    credentials: "same-origin",
                  });
                  const data = await res.json().catch(() => ({}));
                  return { ok: res.ok, status: res.status, data };
                }
                """,
                {"url": url},
            )
            self.assertTrue(bool(put.get("ok")), msg=f"PUT HTTP {put.get('status')} · {put.get('data')}")

            # Resolver URL por /api/s3_url (debe devolver /uploads/...).
            resolved = page.evaluate(
                """
                async ({ key }) => {
                  const res = await fetch(`/api/s3_url?key=${encodeURIComponent(key)}`, { credentials: "same-origin" });
                  const data = await res.json().catch(() => ({}));
                  return { ok: res.ok, status: res.status, data };
                }
                """,
                {"key": key},
            )
            self.assertTrue(bool(resolved.get("ok")), msg=f"s3_url HTTP {resolved.get('status')} · {resolved.get('data')}")
            final_url = str(resolved["data"].get("url") or "")
            self.assertTrue(final_url.startswith("/uploads/s3_local/"), msg=f"URL inesperada: {final_url}")

            context.close()
            browser.close()


if __name__ == "__main__":
    unittest.main()
