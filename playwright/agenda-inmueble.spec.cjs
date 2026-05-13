const { test, expect } = require("@playwright/test");
const { spawnSync, spawn } = require("child_process");

const DB_PATH = process.env.PW_DB || "/private/tmp/modernia_local.sqlite";
const HOST = "127.0.0.1";
const PORT = Number(process.env.PW_PORT || 8011);

function readSeed() {
  const py = `
import json, sqlite3
conn=sqlite3.connect(${JSON.stringify(DB_PATH)})
conn.row_factory=sqlite3.Row
cur=conn.cursor()
empresa=cur.execute("SELECT id FROM empresas ORDER BY created_at DESC LIMIT 1").fetchone()
empresa_id=(empresa["id"] if empresa else "")
inms=cur.execute("SELECT id FROM inmuebles ORDER BY created_at DESC LIMIT 5").fetchall()
print(json.dumps({"empresa_id": empresa_id, "inmuebles":[r["id"] for r in inms]}))
`;
  const res = spawnSync("python3", ["-c", py], { encoding: "utf-8" });
  if (res.status !== 0) throw new Error(`No se pudo leer seed sqlite: ${res.stderr || res.stdout}`);
  return JSON.parse(res.stdout.trim() || "{}");
}

function startServer() {
  const proc = spawn(
    "python3",
    [
      "-u",
      "web/server.py",
      "--db",
      DB_PATH,
      "--host",
      HOST,
      "--port",
      String(PORT),
    ],
    { cwd: process.env.PW_CWD || "/private/tmp/modernia_erp_clean", stdio: "pipe" }
  );
  return proc;
}

async function waitForHealth(request) {
  const start = Date.now();
  while (Date.now() - start < 20_000) {
    try {
      const res = await request.get("/api/health");
      if (res.ok()) return;
    } catch {}
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("Servidor local no responde /api/health");
}

async function login(page) {
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#authLoginUser", { timeout: 20_000 });
  await page.fill("#authLoginUser", "admin");
  await page.fill("#authLoginPass", "admin1234");
  const respPromise = page.waitForResponse((resp) => resp.url().includes("/api/login") && resp.status() === 200, { timeout: 20_000 });
  await page.click("#authLoginForm button[type=submit]");
  await respPromise;
  // Espera a que el frontend desbloquee la UI (overlay hidden o body sin auth-locked)
  const overlay = page.locator("#authLoginOverlay");
  await expect
    .poll(
      async () => {
        const cls = (await overlay.getAttribute("class")) || "";
        const bodyCls = (await page.locator("body").getAttribute("class")) || "";
        return { cls, bodyCls };
      },
      { timeout: 20_000 }
    )
    .toMatchObject({ cls: expect.stringContaining("hidden") });

  // Algunos usuarios arrancan con el modal de “Registro horario” abierto (bloquea clicks).
  // Cerramos cualquier modal abierto visible que tenga botón "Cerrar".
  for (let i = 0; i < 5; i += 1) {
    const timeModal = page.locator(".modal-content", {
      has: page.locator('h3:has-text(\"Registro horario\")'),
    }).first();
    const closeBtn = timeModal.locator('button:has-text(\"Cerrar\")').first();
    if (await closeBtn.isVisible().catch(() => false)) {
      await closeBtn.click({ force: true }).catch(() => {});
      await page.waitForTimeout(350);
      continue;
    }
    break;
  }
}

async function setCrmView(page, view) {
  await page.evaluate((v) => {
    try {
      setCrmWorkspaceView(v);
    } catch (e) {
      // ignore
    }
  }, view);
  await page.waitForTimeout(300);
}

async function enterCrmInmobiliario(page) {
  // En la home, hay varios "Entrar". El primero visible suele ser CRM Inmobiliario.
  const candidates = page.locator('button:has-text(\"Entrar\"), a:has-text(\"Entrar\")');
  const count = await candidates.count();
  for (let i = 0; i < Math.min(count, 6); i += 1) {
    const c = candidates.nth(i);
    if (!(await c.isVisible().catch(() => false))) continue;
    await c.click({ force: true }).catch(() => {});
    const ok = await page.locator("#crmWorkspaceShell").isVisible().catch(() => false);
    if (ok) return;
    // Si no entró, vuelve atrás e intenta siguiente.
    await page.goBack().catch(() => {});
    await page.waitForTimeout(300);
  }
  // Fallback: busca por texto de card.
  const fallback = page.locator("text=CRM Inmobiliario").first();
  await expect(fallback).toBeVisible({ timeout: 20_000 });
  throw new Error("No pude entrar en CRM Inmobiliario (no aparece #crmWorkspaceShell).");
}

async function openInmueble(page, inmuebleId) {
  await page.evaluate((id) => {
    openInmuebleDetail(id, "inmuebles");
  }, inmuebleId);
  // Espera a que la ficha termine de cargar.
  await page.waitForFunction(() => {
    const el = document.getElementById("inmuebleTitle");
    const txt = String(el?.textContent || "");
    return txt && !txt.toLowerCase().includes("cargando");
  }, null, { timeout: 20_000 });
  // Cambia a pestaña actividad explícitamente y espera a que se muestre el panel.
  await page.evaluate(() => {
    try { setInmuebleTab("actividad"); } catch (e) {}
  });
  await page.waitForFunction(() => {
    const tab = document.getElementById("inmuebleTabActividad");
    return tab && !tab.classList.contains("hidden");
  }, null, { timeout: 20_000 });
  await expect(page.locator("#inmuebleActividadForm")).toBeAttached({ timeout: 20_000 });
  await expect(page.locator("#inmuebleActividadClienteInput")).toBeVisible({ timeout: 20_000 });
}

async function getActividadFormState(page) {
  return await page.evaluate(() => {
    const form = document.querySelector("#inmuebleActividadForm");
    if (!form) return null;
    const q = (sel) => form.querySelector(sel);
    return {
      cliente: String(document.querySelector("#inmuebleActividadClienteInput")?.value || ""),
      tipo: String(q('select[name=\"tipo\"]')?.value || ""),
      estado: String(q('select[name=\"estado\"]')?.value || ""),
      hora: String(q('input[name=\"hora\"]')?.value || ""),
      hora_fin: String(q('input[name=\"hora_fin\"]')?.value || ""),
    };
  });
}

async function fillAndSaveActividad(page, { tipo, clienteNombre, hora }) {
  const cliente = page.locator("#inmuebleActividadClienteInput");
  await cliente.scrollIntoViewIfNeeded();
  await cliente.fill(clienteNombre || "", { force: true });
  const tipoSel = page.locator('#inmuebleActividadForm select[name=\"tipo\"]');
  await tipoSel.scrollIntoViewIfNeeded();
  await tipoSel.selectOption({ label: tipo });
  const fecha = page.locator('#inmuebleActividadForm input[name=\"fecha\"]');
  await fecha.fill(new Date().toISOString().slice(0, 10), { force: true });
  if (hora) {
    const horaInp = page.locator('#inmuebleActividadForm input[name=\"hora\"]');
    await horaInp.fill(hora, { force: true });
  }
  await page.locator('#inmuebleActividadForm button[type=\"submit\"]').click({ force: true });
  await page.waitForTimeout(600);
}

test.describe("Agenda (desde inmueble) no hereda datos", () => {
  /** @type {import('child_process').ChildProcess | null} */
  let srv = null;
  let seed = null;

  test.beforeAll(async ({ request }) => {
    seed = readSeed();
    srv = startServer();
    await waitForHealth(request);
  });

  test.afterAll(async () => {
    try {
      if (srv) srv.kill("SIGTERM");
    } catch {}
  });

  test("cambiar de inmueble resetea formulario", async ({ page, request }) => {
    seed = seed || readSeed();
    expect(seed.empresa_id).toBeTruthy();
    expect(Array.isArray(seed.inmuebles)).toBeTruthy();
    expect(seed.inmuebles.length).toBeGreaterThanOrEqual(2);

    await login(page);
    await enterCrmInmobiliario(page);
    await setCrmView(page, "inmuebles");

    const inmA = seed.inmuebles[0];
    const inmB = seed.inmuebles[1];

    await openInmueble(page, inmA);
    await fillAndSaveActividad(page, { tipo: "Cita notaria", clienteNombre: "Cliente A", hora: "10:00" });

    // Cambia a otro inmueble: el formulario debe estar limpio (tipo=Llamada, cliente vacío, horas vacías)
    await openInmueble(page, inmB);
    const stB = await getActividadFormState(page);
    expect(stB).toBeTruthy();
    expect((stB.cliente || "").trim()).toBe("");
    expect(stB.tipo).toBe("Llamada");
    expect(stB.estado).toBe("Pendiente");
    expect((stB.hora || "").trim()).toBe("");
    expect((stB.hora_fin || "").trim()).toBe("");

    await fillAndSaveActividad(page, { tipo: "Cita propuesta", clienteNombre: "Cliente B", hora: "12:00" });

    // Volver a A: de nuevo limpio
    await openInmueble(page, inmA);
    const stA2 = await getActividadFormState(page);
    expect((stA2.cliente || "").trim()).toBe("");
    expect(stA2.tipo).toBe("Llamada");
  });
});
