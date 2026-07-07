import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _chrome_binary():
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise unittest.SkipTest("Google Chrome no disponible para la E2E de contabilidad.")


@unittest.skipUnless(
    (os.environ.get("RUN_PLAYWRIGHT_E2E") or "").strip().lower() in ("1", "true", "yes", "si", "sí", "on"),
    "E2E desactivado (exporta RUN_PLAYWRIGHT_E2E=1 para ejecutarlo).",
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
        self.company_row = {
            "id": "emp-e2e",
            "legacy_empresa_id": "emp-e2e",
            "nombre": "EMPRESA E2E",
            "razon_social": "EMPRESA E2E",
            "nif": "B12345678",
            "direccion": "Calle E2E 1",
            "activo": 1,
        }
        self.client_id = "cli-e2e"
        self.third_party_id = "ter-e2e"
        self.invoice_id = "fac-e2e-1"
        self.asiento_id = "asi-e2e-1"
        self.bank_id = "bank-e2e-1"
        self.model_id = "mod-e2e-1"
        self._seed_database()

        self.httpd = self.server.ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        self.httpd.daemon_threads = True
        self.server.Handler.db_path = str(self.db_path)
        self.server.Handler.ocr_db_path = str(Path(self.tmpdir.name) / "ocr.sqlite")
        self.server.UPLOADS = self.uploads_dir

        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self._server_thread = threading.Thread(target=self.httpd.serve_forever, name="e2e-httpd", daemon=True)
        self._server_thread.start()
        time.sleep(0.05)

        self.chrome_proc = None
        self.debug_port = _free_port()
        self._start_chrome()

    def tearDown(self):
        try:
            if self.chrome_proc:
                self.chrome_proc.terminate()
                try:
                    self.chrome_proc.wait(timeout=10)
                except Exception:
                    self.chrome_proc.kill()
        except Exception:
            pass
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

    def _seed_database(self):
        now = _now_iso()
        today = datetime.now(timezone.utc).date()
        due_date = (today + timedelta(days=10)).isoformat()

        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, nif, direccion, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, datetime(?), datetime(?))
            """,
            (self.company_row["id"], self.company_row["nombre"], self.company_row["nif"], self.company_row["direccion"], now, now),
        )
        self.conn.execute(
            """
            UPDATE usuarios
            SET servicio = 'Gestoria', activo = 1, updated_at = datetime('now')
            WHERE LOWER(TRIM(usuario)) = 'admin'
            """,
        )
        self.conn.execute(
            """
            INSERT INTO clientes (id, empresa_id, nombre, nif, estado, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Activo', datetime(?), datetime(?))
            """,
            (self.client_id, self.company_row["id"], "CLIENTE E2E", "12345678Z", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, created_at, updated_at)
            VALUES (?, ?, ?, 'Gestoria', 'Activo', datetime(?), datetime(?))
            """,
            ("ce-e2e-1", self.client_id, self.company_row["id"], now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_terceros (id, empresa_id, nif, nombre, tipo, cuenta_contable, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'Cliente', '430000', datetime(?), datetime(?))
            """,
            (self.third_party_id, self.company_row["id"], "12345678Z", "CLIENTE E2E", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_facturas (
              id, empresa_id, cliente_id, tercero_id, tipo, numero, fecha_emision, descripcion,
              base_imponible, base_exenta, base_no_sujeta, cuota_iva, cuota_irpf, total, iva_pct,
              tipo_operacion, estado_ocr, doc_key, archivo_hash, dedupe_key, raw_text, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, 'venta', ?, ?, ?, ?, 0, 0, ?, 0, ?, 21, 'servicio', 'Validado', '', '', '', '', datetime(?), datetime(?)
            )
            """,
            (
                self.invoice_id,
                self.company_row["id"],
                self.client_id,
                self.third_party_id,
                "F-E2E-001",
                today.isoformat(),
                "Factura E2E",
                1000.0,
                210.0,
                1210.0,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_asientos (
              id, empresa_id, cliente_id, factura_id, fecha, concepto, diario, referencia,
              total_debe, total_haber, punteado_banco, punteado_banco_by, punteado_banco_at,
              punteado_banco_notas, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, 'general', ?, ?, ?, 1, 'admin', datetime('now'), 'Seed E2E', datetime(?), datetime(?)
            )
            """,
            (
                self.asiento_id,
                self.company_row["id"],
                self.client_id,
                self.invoice_id,
                today.isoformat(),
                "Venta E2E",
                "F-E2E-001",
                1210.0,
                1210.0,
                now,
                now,
            ),
        )
        line_rows = [
            ("line-e2e-1", self.third_party_id, "430000", "Cliente E2E", 1210.0, 0.0, "", None),
            ("line-e2e-2", self.third_party_id, "700000", "Venta de servicios", 0.0, 1000.0, "", None),
            ("line-e2e-3", self.third_party_id, "477000", "IVA repercutido", 0.0, 210.0, "iva", 21.0),
        ]
        for line_id, tercero_id, cuenta, descripcion, debe, haber, impuesto_tipo, impuesto_pct in line_rows:
            self.conn.execute(
                """
                INSERT INTO gestoria_asiento_lineas (
                  id, asiento_id, tercero_id, cuenta, descripcion, debe, haber, impuesto_tipo, impuesto_pct, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
                """,
                (line_id, self.asiento_id, tercero_id, cuenta, descripcion, debe, haber, impuesto_tipo, impuesto_pct, now, now),
            )
        self.conn.execute(
            """
            INSERT INTO gestoria_cuentas_bancarias (
              id, empresa_id, iban, banco_nombre, cuenta_contable, titular, es_principal, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, datetime(?), datetime(?))
            """,
            (self.bank_id, self.company_row["id"], "ES6600000000000000000000", "Banco E2E", "572000", "EMPRESA E2E", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_movimientos_bancarios (
              id, empresa_id, cuenta_bancaria_id, fecha_operacion, fecha_valor, concepto, importe, saldo, divisa,
              codigo, numero_documento, referencia1, referencia2, info_adicional, origen_fichero, origen_hash,
              punteado, punteado_at, punteado_by, punteado_notas, asiento_id, matched_score, matched_reason,
              conciliacion_estado, conciliacion_confianza, regla_aplicada, validado_manual_at, validado_manual_by,
              validado_manual_notas, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, 'EUR', '', '', '', '', '', '', '',
              1, datetime('now'), 'admin', 'Seed E2E', ?, 99, 'E2E',
              'Conciliado', 99, 'seed', datetime('now'), 'admin',
              'Seed E2E', datetime(?), datetime(?)
            )
            """,
            (
                "mov-e2e-1",
                self.company_row["id"],
                self.bank_id,
                today.isoformat(),
                today.isoformat(),
                "Cobro factura E2E",
                1210.0,
                1210.0,
                self.asiento_id,
                now,
                now,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO gestoria_modelos (id, cliente_id, modelo, periodicidad, proxima_fecha, responsable, estado, notas, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
            """,
            (
                self.model_id,
                self.client_id,
                "E2E Declaracion",
                "Trimestral",
                due_date,
                "admin",
                "Pendiente",
                "Seed e2e",
                now,
                now,
            ),
        )
        try:
            self.server.bootstrap_default_workspace(self.conn)
        except Exception:
            pass
        self.conn.commit()

    def _start_chrome(self):
        chrome = _chrome_binary()
        user_data_dir = Path(self.tmpdir.name) / "chrome-profile"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        self.chrome_proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={self.debug_port}",
                f"--user-data-dir={user_data_dir}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._wait_for_debug_port()

    def _wait_for_debug_port(self, timeout=30):
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{self.debug_port}/json/version"
        last_error = None
        while time.time() < deadline:
            try:
                with urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return
            except URLError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
            time.sleep(0.2)
        raise RuntimeError(f"No se pudo abrir el puerto CDP {self.debug_port}: {last_error}")

    def _run_node_browser_flow(self):
        script = """
(async () => {
  const [baseUrl, debugPortRaw, companyJson] = process.argv.slice(1);
  const debugPort = Number(debugPortRaw);
  const company = JSON.parse(companyJson);
  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const connect = (wsUrl) => new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    ws.addEventListener("open", () => resolve(ws));
    ws.addEventListener("error", (event) => reject(event.error || new Error("WebSocket error")));
  });
  const makeClient = (ws) => {
    let nextId = 1;
    const pending = new Map();
    ws.addEventListener("message", (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (!msg || typeof msg !== "object" || !msg.id) return;
      const entry = pending.get(msg.id);
      if (!entry) return;
      pending.delete(msg.id);
      if (msg.error) {
        entry.reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      } else {
        entry.resolve(msg.result || {});
      }
    });
    ws.addEventListener("close", () => {
      for (const entry of pending.values()) {
        entry.reject(new Error("WebSocket cerrado"));
      }
      pending.clear();
    });
    return {
      ws,
      send(method, params = {}) {
        const id = nextId++;
        const promise = new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
        ws.send(JSON.stringify({ id, method, params }));
        return promise;
      },
    };
  };
  const evalExpr = async (client, expression) => {
    const response = await client.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      awaitPromise: true,
      userGesture: true,
    });
    if (response.exceptionDetails) {
      const details = response.exceptionDetails;
      const nested = details.exception || {};
      const message = nested.description || nested.value || details.text || "Runtime.evaluate falló";
      throw new Error(`${message}${nested.className ? ` [${nested.className}]` : ""}`);
    }
    return response.result ? response.result.value : undefined;
  };
  const waitFor = async (client, expression, timeoutMs = 30000, intervalMs = 100) => {
    const deadline = Date.now() + timeoutMs;
    let lastError = null;
    while (Date.now() < deadline) {
      try {
        const value = await evalExpr(client, expression);
        if (value) return value;
      } catch (err) {
        lastError = err;
      }
      await delay(intervalMs);
    }
    throw new Error(`Timeout esperando: ${expression}${lastError ? ` · ${lastError.message}` : ""}`);
  };
  const click = async (client, selector) => {
    await evalExpr(
      client,
      `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        if (!el) throw new Error("Selector no encontrado");
        el.click();
        return true;
      })()`
    );
  };
  const textOf = async (client, selector) => {
    const value = await evalExpr(
      client,
      `(() => {
        const el = document.querySelector(${JSON.stringify(selector)});
        return el ? (el.innerText || el.textContent || "") : "";
      })()`
    );
    return String(value || "");
  };
  const waitVisibleTab = async (client, tabSelector, paneSelector, expectedFragments = [], timeoutMs = 30000) => {
    await click(client, tabSelector);
    const checks = expectedFragments.map((fragment) => `text.includes(${JSON.stringify(fragment)})`).join(" && ");
    const expression = `(() => {
      const btn = document.querySelector(${JSON.stringify(tabSelector)});
      const pane = document.querySelector(${JSON.stringify(paneSelector)});
      if (!btn || !pane) return false;
      const text = pane.innerText || pane.textContent || "";
      return btn.getAttribute("aria-pressed") === "true"
        && !pane.hidden
        && !pane.classList.contains("hidden")
        && !text.includes("Cargando")
        ${checks ? `&& ${checks}` : ""};
    })()`;
    try {
      await waitFor(client, expression, timeoutMs);
    } catch (error) {
      const currentText = await textOf(client, paneSelector);
      throw new Error(`${error?.message || error || "Timeout"} :: ${String(currentText || "").slice(0, 500)}`);
    }
    return textOf(client, paneSelector);
  };
  const browserVersion = await fetch(`http://127.0.0.1:${debugPort}/json/version`).then((res) => res.json());
  const browser = makeClient(await connect(browserVersion.webSocketDebuggerUrl));
  const created = await browser.send("Target.createTarget", { url: "about:blank" });
  const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((res) => res.json());
  const targetInfo = Array.isArray(targets) ? targets.find((item) => item.id === created.targetId) : null;
  if (!targetInfo) throw new Error("No se encontró el target creado");
  const page = makeClient(await connect(targetInfo.webSocketDebuggerUrl));
  await page.send("Page.enable");
  await page.send("Runtime.enable");
  await page.send("Page.navigate", { url: `${baseUrl}/?nosw=1&swcleared=1` });
  await waitFor(page, `Boolean(document.querySelector("#authLoginUser"))`, 30000);
  await evalExpr(
    page,
    `(() => {
      document.querySelector("#authLoginUser").value = "admin";
      document.querySelector("#authLoginPass").value = "adminadmin";
      document.querySelector("#authLoginForm button[type='submit']").click();
      return true;
    })()`
  );
  await waitFor(page, `(() => !document.body.classList.contains("auth-locked"))()`, 30000);
  await evalExpr(
    page,
    `(() => {
      return true;
    })()`
  );
  await waitFor(page, `typeof openWorkspaceCompanyFicha === "function"`, 30000);
  await evalExpr(
    page,
    `(() => {
      if (typeof openWorkspaceCompanyFicha !== "function") {
        throw new Error("openWorkspaceCompanyFicha no está disponible");
      }
      if (typeof setPage === "function") setPage("empresa");
      if (typeof setModule === "function") setModule("empresas");
      openWorkspaceCompanyFicha(${JSON.stringify(company.id)}, "dashboard");
      return true;
    })()`
  );
  await waitFor(page, `Boolean(document.querySelector('[data-company-conta-shell="1"]'))`, 30000);
  await evalExpr(
    page,
    `(() => {
      if (typeof setWorkspaceCompanyContabilidadTab !== "function") {
        throw new Error("setWorkspaceCompanyContabilidadTab no está disponible");
      }
      return setWorkspaceCompanyContabilidadTab("dashboard", { force: true });
    })()`
  );
  await waitFor(page, `(() => {
    const pane = document.querySelector('[data-company-conta-pane="dashboard"]');
    return pane && (pane.innerText || "").includes("Dashboard contable");
  })()`, 30000);

  const snapshots = {};
  snapshots.dashboard = await textOf(page, '[data-company-conta-pane="dashboard"]');
  snapshots.diario = await waitVisibleTab(
    page,
    '[data-company-conta-tab="diario"]',
    '[data-company-conta-pane="diario"]',
    ['Libro diario', '430000', '700000']
  );
  snapshots.mayor = await waitVisibleTab(
    page,
    '[data-company-conta-tab="mayor"]',
    '[data-company-conta-pane="mayor"]',
    ['Libro mayor', '430000', '700000']
  );
  snapshots.balanceSituacion = await waitVisibleTab(
    page,
    '[data-company-conta-tab="balances"]',
    '[data-company-conta-pane="balances"]',
    ['430000']
  );
  snapshots.pyg = await waitVisibleTab(
    page,
    '[data-company-conta-balance-tab="pyg"]',
    '[data-company-conta-pane="pyg"]',
    ['700000']
  );
  snapshots.modelos = await waitVisibleTab(
    page,
    '[data-company-conta-tab="modelos"]',
    '[data-company-conta-pane="modelos"]',
    ['Modelos fiscales', 'E2E Declaracion']
  );
  snapshots.asientos = await waitVisibleTab(
    page,
    '[data-company-conta-tab="asientos"]',
    '[data-company-conta-pane="asientos"]',
    ['Asientos', 'F-E2E-001']
  );
  const status = await textOf(page, '[data-company-conta-status]');
  browser.ws.close();
  page.ws.close();
  console.log(JSON.stringify({ snapshots, status }));
})().catch((err) => {
  console.error(err && err.stack ? err.stack : String(err));
  process.exit(1);
});
"""
        result = subprocess.run(
            [
                "node",
                "-e",
                script,
                self.base_url,
                str(self.debug_port),
                json.dumps(self.company_row, ensure_ascii=False),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"E2E CDP falló con código {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        payload = result.stdout.strip()
        if not payload:
            raise AssertionError(f"E2E CDP sin salida utilizable.\nSTDERR:\n{result.stderr}")
        return json.loads(payload)

    def test_ficha_contabilidad_tabs_reales(self):
        result = self._run_node_browser_flow()
        snapshots = result["snapshots"]

        self.assertIn("Dashboard contable", snapshots["dashboard"])
        self.assertIn("Libro diario", snapshots["diario"])
        self.assertIn("Libro mayor", snapshots["mayor"])
        self.assertIn("Balance de situación", snapshots["balanceSituacion"])
        self.assertIn("Modelos fiscales", snapshots["modelos"])
        self.assertIn("Asientos", snapshots["asientos"])
        self.assertIn("Sección activa", result["status"])

        unique_snapshots = {
            snapshots["dashboard"],
            snapshots["diario"],
            snapshots["mayor"],
            snapshots["balanceSituacion"],
            snapshots["pyg"],
            snapshots["modelos"],
            snapshots["asientos"],
        }
        self.assertGreaterEqual(len(unique_snapshots), 5)
        self.assertIn("430000", snapshots["diario"])
        self.assertIn("700000", snapshots["diario"])
        self.assertIn("430000", snapshots["balanceSituacion"])
        self.assertIn("700000", snapshots["pyg"])
        self.assertIn("E2E Declaracion", snapshots["modelos"])
        self.assertIn("F-E2E-001", snapshots["asientos"])


if __name__ == "__main__":
    unittest.main()
