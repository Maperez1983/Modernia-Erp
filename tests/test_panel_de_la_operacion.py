"""El botonaje de la operación, ejecutado de verdad y no leído.

La lección viene de dos veces: un bloque que usaba una variable fuera de su
ámbito dejó el portal del comprador en «x is not defined» —sin una sola ficha— y
los tests seguían en verde porque comprobaban el HTML que sirve el servidor, no
el JavaScript corriendo. Aquí el módulo se carga en un DOM de verdad, con `fetch`
sustituido, y se comprueba lo que pinta y lo que manda al pulsar.

Va en un fichero aparte de `app.js` a propósito: cuelga de una sola pantalla —la
ficha de un inmueble—, no necesita nada del resto de la aplicación y así no hay
que tocar un fichero de cincuenta mil líneas que están editando otras manos.
"""

import json
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
MODULO = RAIZ / "web" / "inmo_operacion.js"


def corre(guion, ofertas, respuestas=None, contestaciones=None):
    """Monta un DOM con la ficha de un inmueble, carga el módulo y ejecuta `guion`.

    Devuelve lo que el guión imprima como JSON. `contestaciones` es la cola de lo
    que devuelve cada `prompt`, y `respuestas` lo que contesta cada POST.
    """
    envoltorio = """
const { JSDOM } = require("jsdom");
const fs = require("fs");

const dom = new JSDOM(`<!doctype html><html><head></head><body>
  <div id="inmuebleSummaryCard" data-inmueble-id="INM-1">ficha</div>
</body></html>`, { runScripts: "outside-only", pretendToBeVisual: true });

global.window = dom.window;
global.document = dom.window.document;
global.MutationObserver = dom.window.MutationObserver;

const OFERTAS = __OFERTAS__;
const RESPUESTAS = __RESPUESTAS__;
const COLA = __COLA__;
const enviado = [];

dom.window.fetch = async (ruta, opciones) => {
  // Por el método y no por «hay opciones»: `pide` manda siempre un segundo
  // argumento —las credenciales— también en las lecturas.
  if (!opciones || opciones.method !== "POST") {
    return { ok: true, json: async () => ({ ofertas: OFERTAS }) };
  }
  const cuerpo = JSON.parse(opciones.body || "{}");
  enviado.push({ ruta, cuerpo });
  const r = RESPUESTAS[ruta] || { ok: true };
  return { ok: r.ok !== false, json: async () => r };
};
dom.window.prompt = () => (COLA.length ? COLA.shift() : "");
dom.window.confirm = () => true;
dom.window.alert = () => {};
global.fetch = dom.window.fetch;

eval(fs.readFileSync(__MODULO__, "utf8"));

(async () => {
  const salida = await (async () => { __GUION__ })();
  console.log(JSON.stringify({ salida, enviado, html: document.body.innerHTML }));
})();
"""
    guion_js = (envoltorio
                .replace("__OFERTAS__", json.dumps(ofertas))
                .replace("__RESPUESTAS__", json.dumps(respuestas or {}))
                .replace("__COLA__", json.dumps(contestaciones or []))
                .replace("__MODULO__", json.dumps(str(MODULO)))
                .replace("__GUION__", guion))
    proc = subprocess.run(["node", "-e", guion_js], cwd=str(RAIZ),
                          capture_output=True, text=True, timeout=90)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.strip()[-2000:])
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _oferta(**extra):
    base = {
        "id": "of-1", "estado": "presentada", "titulo": "Oferta presentada",
        "importe": 242000, "comprador": "Carlos Comprador", "financiacion": True,
        "puede_presentar": True, "mediacion": "", "sugerir_financiacion": False,
        "financiacion_estado": "", "comentario": "", "contraoferta": 0, "senal": 0,
        "fases": [{"clave": "presentada", "etiqueta": "Presentada al banco"}],
    }
    base.update(extra)
    return base


class ElPanelSeMontaSoloTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
            raise unittest.SkipTest("node no disponible")
        try:
            subprocess.run(["node", "-e", "require('jsdom')"], cwd=str(RAIZ),
                           capture_output=True, check=True)
        except Exception:
            raise unittest.SkipTest("jsdom no instalado")

    def test_se_engancha_a_la_ficha_del_inmueble(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;", [_oferta()])
        self.assertIn("op-panel", r["html"])
        self.assertIn("Carlos Comprador", r["html"])
        self.assertIn("242.000", r["html"].replace("&nbsp;", " "))

    def test_no_se_cuelga_de_una_tarjeta_de_listado(self):
        """`data-inmueble-id` lo llevan también las tarjetas de los listados: con el
        selector genérico el panel aparecía dentro de un resultado de búsqueda, con
        el id de otro inmueble."""
        r = corre("""document.getElementById("inmuebleSummaryCard").remove();
                     const t = document.createElement("div");
                     t.className = "crm-mini-card";
                     t.dataset.inmuebleId = "OTRO-9";
                     document.body.appendChild(t);
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""", [_oferta()])
        self.assertNotIn("op-panel", r["html"])

    def test_la_ficha_estampa_el_inmueble_que_tiene_abierto(self):
        """El id vive en el closure de `app.js` y no llegaba al DOM, así que el
        panel no tenía de dónde sacarlo y no se montaba nunca."""
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("inmuebleSummaryCard.dataset.inmuebleId", app)

    def test_sin_ficha_de_inmueble_no_se_monta_nada(self):
        r = corre("""document.getElementById("inmuebleSummaryCard").remove();
                     window.InmoOperacion.revisa();
                     await new Promise((ok) => setTimeout(ok, 40)); return 1;""", [_oferta()])
        self.assertNotIn("op-panel", r["html"])

    def test_una_oferta_presentada_ofrece_las_cuatro_salidas(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;", [_oferta()])
        for accion in ("presentar", "contraoferta", "aceptar", "rechazar"):
            with self.subTest(accion):
                self.assertIn(f'data-accion="{accion}"', r["html"])

    def test_presentar_manda_la_nota_del_asesor(self):
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     document.querySelector('[data-accion="presentar"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""",
                  [_oferta()], contestaciones=["Cliente solvente"])
        envio = [e for e in r["enviado"] if e["ruta"] == "/api/inmueble_oferta_presentar"]
        self.assertEqual(len(envio), 1, r["enviado"])
        self.assertEqual(envio[0]["cuerpo"], {"oferta_id": "of-1", "nota": "Cliente solvente"})

    def test_aceptar_pide_la_senal_y_la_manda(self):
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     document.querySelector('[data-accion="aceptar"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""",
                  [_oferta()], contestaciones=["6000", "", "2099-01-01", ""])
        envio = [e for e in r["enviado"] if e["ruta"] == "/api/inmueble_oferta_responder"][0]
        self.assertEqual(envio["cuerpo"]["decision"], "aceptar")
        self.assertEqual(envio["cuerpo"]["senal"], "6000")
        self.assertEqual(envio["cuerpo"]["limite"], "2099-01-01")

    def test_cancelar_el_prompt_no_manda_nada(self):
        """Arrepentirse a mitad no puede presentar una oferta al propietario."""
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     window.prompt = () => null;
                     document.querySelector('[data-accion="presentar"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""", [_oferta()])
        self.assertEqual(r["enviado"], [])

    def test_reservada_ofrece_las_arras_y_no_lo_anterior(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(estado="reservada", titulo="Reservado a tu nombre")])
        self.assertIn('data-accion="arras"', r["html"])
        self.assertNotIn('data-accion="contraoferta"', r["html"])

    def test_el_justificante_pendiente_ofrece_verificar(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(estado="reserva_justificada", titulo="Justificante recibido")])
        self.assertIn('data-accion="verificar"', r["html"])

    def test_la_alerta_de_financiacion_sale_cuando_toca(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(estado="reservada", sugerir_financiacion=True)])
        self.assertIn("op-alerta", r["html"])
        self.assertIn("¿lo vinculamos con Financiaciones?", r["html"])
        self.assertIn('data-accion="financiar"', r["html"])

    def test_con_el_estudio_en_marcha_se_puede_mover_la_fase(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(estado="reservada", financiacion_estado="estudio")])
        self.assertIn('data-accion="fase"', r["html"])
        self.assertIn('data-accion="cerrarFinanciacion"', r["html"])
        self.assertNotIn("op-alerta", r["html"])

    def test_mover_la_fase_manda_la_clave_y_la_nota_interna(self):
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     document.querySelector('[data-accion="fase"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""",
                  [_oferta(estado="reservada", financiacion_estado="estudio")],
                  contestaciones=["preaprobada", "ojo con el impagado"])
        envio = [e for e in r["enviado"] if e["ruta"] == "/api/inmueble_oferta_financiacion_fase"][0]
        self.assertEqual(envio["cuerpo"]["fase"], "preaprobada")
        self.assertEqual(envio["cuerpo"]["nota"], "ojo con el impagado")

    def test_la_mediacion_se_ve_en_la_ficha(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(mediacion="propietario_acepta", mediacion_at="2026-08-13 10:00",
                           puede_presentar=False)])
        self.assertIn("El propietario ACEPTA", r["html"])
        self.assertNotIn('data-accion="presentar"', r["html"])

    def test_el_error_del_servidor_se_enseña_tal_cual(self):
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     let dicho = "";
                     window.alert = (t) => { dicho = t; };
                     document.querySelector('[data-accion="verificar"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return dicho;""",
                  [_oferta(estado="reserva_justificada")],
                  respuestas={"/api/inmueble_oferta_verificar":
                              {"ok": False, "error": "No hay ningún justificante pendiente"}})
        self.assertEqual(r["salida"], "No hay ningún justificante pendiente")

    def test_el_encargo_se_manda_desde_la_cabecera(self):
        r = corre("""await new Promise((ok) => setTimeout(ok, 60));
                     document.querySelector('[data-accion="encargo"]').click();
                     await new Promise((ok) => setTimeout(ok, 60)); return 1;""", [_oferta()])
        envio = [e for e in r["enviado"] if e["ruta"] == "/api/inmueble_encargo_firma"][0]
        self.assertEqual(envio["cuerpo"], {"inmueble_id": "INM-1"})

    def test_sin_ofertas_lo_dice_y_no_revienta(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;", [])
        self.assertIn("Todavía no hay ofertas", r["html"])

    def test_el_nombre_del_comprador_se_escapa(self):
        r = corre("await new Promise((ok) => setTimeout(ok, 60)); return 1;",
                  [_oferta(comprador='<img src=x onerror="alert(1)">')])
        self.assertNotIn("<img src=x", r["html"])
        self.assertIn("&lt;img", r["html"])


class ElEnganchePorFicheroTests(unittest.TestCase):
    """Que el módulo exista no basta: si no está en la lista blanca del servidor
    da 404, y si no está en el shell no se carga nunca."""

    def test_el_servidor_lo_sirve(self):
        fuente = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
        i = fuente.index("allowlist = {")
        self.assertIn('"inmo_operacion.js"', fuente[i:fuente.index("}", i)])

    def test_la_aplicacion_lo_carga(self):
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        i = html.index("APP_SHELL_SCRIPTS = [")
        self.assertIn("inmo_operacion.js", html[i:html.index("];", i)])

    def test_el_service_worker_lo_precachea_con_su_version(self):
        sw = (RAIZ / "web" / "sw.js").read_text(encoding="utf-8")
        self.assertIn("/inmo_operacion.js?v=1", sw)
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("inmo_operacion.js?v=1", html)


if __name__ == "__main__":
    unittest.main()
