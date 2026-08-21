"""Las barras de módulo cumplen el patrón de pestañas del W3C.

Declarar `role="tablist"` es una promesa: el lector de pantalla anuncia «lista de
pestañas» y quien lo usa deja de tabular y empieza a pulsar flechas. Si las flechas no
están programadas, se queda atrapado — y encima ya no se fía del tabulador. Por eso
esto no se comprueba leyendo el fuente: se ejecuta el código real en un DOM y se
pulsan las teclas.

En la casa había dos `role="tablist"` —las fases de pedidos y la vista de agenda— y
`ArrowRight` no aparecía ni una vez en los 96.000 renglones de `app.js`. Justo la
trampa que este test existe para que no se repita.

El bloque se recorta de `web/app.js` en vez de copiarlo: si alguien lo cambia allí,
aquí se prueba lo cambiado.
"""

import re
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def bloque_del_patron():
    """El trozo de app.js que implementa el patrón, tal cual está."""
    ini = APP.index("const ETIQUETA_DE_BARRA = {")
    fin = APP.index("const initDensityToggle = () => {", ini)
    return APP[ini:fin]


GUION = r"""
(async () => {
const assert = require("assert");
const { JSDOM } = require("jsdom");
const dom = new JSDOM(`<!doctype html><html><body>
  <div class="tc-modulebar tc-modulebar--compact" id="workspaceFincasTabs">
    <button type="button" class="tab tc-module active" data-fincas-tab-btn="dashboard">Dashboard</button>
    <button type="button" class="tab tc-module" data-fincas-tab-btn="comunidades">Comunidades</button>
    <button type="button" class="tab tc-module" data-fincas-tab-btn="ajustes">Ajustes</button>
    <button type="button" class="tab tc-module hidden" data-fincas-tab-btn="ficha">Ficha</button>
  </div>
  <div data-fincas-tab="dashboard">uno</div>
  <div data-fincas-tab="comunidades">dos</div>
  <div data-fincas-tab="ajustes">tres</div>
</body></html>`, { url: "https://crm.example/", pretendToBeVisual: true });
global.window = dom.window; global.document = dom.window.document;
global.CSS = dom.window.CSS; global.MutationObserver = dom.window.MutationObserver;

__BLOQUE__

activarPatronDePestanas();
const barra = document.getElementById("workspaceFincasTabs");
const pes = [...barra.querySelectorAll(".tab.tc-module")];
const visibles = pes.filter((b) => !b.classList.contains("hidden"));

assert.strictEqual(barra.getAttribute("role"), "tablist", "la barra no es tablist");
assert.strictEqual(barra.getAttribute("aria-label"), "Módulo de fincas", "sin etiqueta");
visibles.forEach((b) => assert.strictEqual(b.getAttribute("role"), "tab", "botón sin role=tab"));

assert.strictEqual(visibles[0].getAttribute("aria-selected"), "true");
assert.strictEqual(visibles[1].getAttribute("aria-selected"), "false");
assert.strictEqual(visibles[0].tabIndex, 0, "la activa debe ser tabulable");
assert.strictEqual(visibles[1].tabIndex, -1, "las demás salen del tabulador");
assert.strictEqual(visibles.filter((b) => b.tabIndex === 0).length, 1, "la barra es UNA parada");

assert.ok(visibles[0].getAttribute("aria-controls"), "sin aria-controls");
const panel = document.getElementById(visibles[0].getAttribute("aria-controls"));
assert.strictEqual(panel.getAttribute("role"), "tabpanel");
assert.strictEqual(panel.getAttribute("aria-labelledby"), visibles[0].id);

let clics = 0;
visibles.forEach((b) => b.addEventListener("click", () => { clics += 1; }));
const pulsa = (tecla) => visibles.find((b) => b === document.activeElement)
  .dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: tecla, bubbles: true }));

visibles[0].focus();
pulsa("ArrowRight");
assert.strictEqual(document.activeElement, visibles[1], "→ no movió el foco");
pulsa("ArrowRight");
assert.strictEqual(document.activeElement, visibles[2], "→ no avanzó otra vez");
pulsa("ArrowRight");
assert.strictEqual(document.activeElement, visibles[0], "→ no dio la vuelta al final");
pulsa("ArrowLeft");
assert.strictEqual(document.activeElement, visibles[2], "← no dio la vuelta al principio");
pulsa("Home");
assert.strictEqual(document.activeElement, visibles[0], "Inicio no lleva a la primera");
pulsa("End");
assert.strictEqual(document.activeElement, visibles[2], "Fin no lleva a la última");
assert.strictEqual(clics, 6, "moverse con flechas tiene que activar la pestaña");

assert.ok(!visibles.includes(pes[3]), "la pestaña oculta no entra en el recorrido");

visibles[0].classList.remove("active");
visibles[2].classList.add("active");
await new Promise((r) => setTimeout(r, 20));
assert.strictEqual(visibles[2].getAttribute("aria-selected"), "true", "no siguió a la clase active");
assert.strictEqual(visibles[0].getAttribute("aria-selected"), "false");
assert.strictEqual(visibles[2].tabIndex, 0);

console.log("OK");
})().catch((e) => { console.error(e); process.exit(1); });
"""




# Módulos de Node que estas pruebas necesitan y que viven en `node_modules`, que está
# en .gitignore: en una copia recién clonada no están.
MODULOS_DE_NODE = ("jsdom", "puppeteer-core", "lighthouse", "chrome-launcher")


def _falta_un_modulo_de_node(salida):
    """El fallo salía como un volcado de pila de Node y se leía como si lo probado
    estuviera roto —nos costó dar por rojas siete pruebas que estaban perfectamente—.
    Se mira el fallo concreto, y no la presencia del módulo por adelantado, para no
    saltarse las pruebas que usan Node sin necesitar ninguno de estos paquetes."""
    t = str(salida or "")
    return any(f"Cannot find module '{m}'" in t for m in MODULOS_DE_NODE)


class ElPatronFuncionaDeVerdadTests(unittest.TestCase):
    def test_roles_teclado_y_sincronia(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node no está disponible")
        guion = GUION.replace("__BLOQUE__", bloque_del_patron())
        r = subprocess.run([node, "-e", guion], capture_output=True, text=True, cwd=RAIZ)
        if r.returncode:
            if _falta_un_modulo_de_node(r.stderr):
                raise unittest.SkipTest("faltan dependencias de Node: ejecuta `npm install` en la raíz")
            self.fail(f"El patrón no se comporta como debe:\n{r.stdout}\n{r.stderr}")
        self.assertIn("OK", r.stdout)


class TodaBarraDeModuloEntraEnElPatronTests(unittest.TestCase):
    """El descubrimiento es en tiempo de ejecución a propósito.

    Las barras no son ocho sino nueve: la de RRHH se pinta desde JavaScript y no tiene
    id, así que ningún recorrido del HTML la encuentra. Por eso el patrón se aplica
    buscando `.tc-modulebar` en el DOM y no editando cada barra a mano.
    """

    def test_se_buscan_las_barras_en_el_dom(self):
        bloque = bloque_del_patron()
        self.assertIn('querySelectorAll?.(".tc-modulebar")', bloque)

    def test_la_de_rrhh_tambien_es_una_barra_de_modulo(self):
        i = APP.index("const renderTabs = () =>")
        self.assertIn("tc-modulebar", APP[i: i + 400])
        self.assertIn("tab tc-module", APP[i: i + 2500])

    def test_las_que_se_pintan_luego_se_enganchan_al_tocarlas(self):
        bloque = bloque_del_patron()
        for evento in ('"focusin"', '"pointerdown"'):
            with self.subTest(evento=evento):
                self.assertIn(evento, bloque)

    def test_cada_barra_con_id_tiene_su_etiqueta(self):
        """Un tablist sin nombre se anuncia como «lista de pestañas» y ya."""
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        i = APP.index("const ETIQUETA_DE_BARRA = {")
        mapa = APP[i: APP.index("};", i)]
        con_etiqueta = set(re.findall(r"^\s*([A-Za-z]+):", mapa, re.M))
        con_id = set(
            re.findall(r'<div class="[^"]*tc-modulebar[^"]*"[^>]*id="([A-Za-z]+)"', html)
        )
        self.assertTrue(con_id, "no se han encontrado barras con id en el HTML")
        self.assertEqual(
            sorted(con_id - con_etiqueta), [], "Barras sin entrada en ETIQUETA_DE_BARRA"
        )


if __name__ == "__main__":
    unittest.main()
