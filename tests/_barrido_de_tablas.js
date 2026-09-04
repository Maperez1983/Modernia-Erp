// Ejecuta el barrido real de `app.js` contra tablas de varias formas y devuelve, en
// JSON, cómo queda cada una. Lo lee tests/test_todas_las_tablas_se_ven_en_movil.py.
const fs = require("fs");
const path = require("path");
const { JSDOM } = require("jsdom");

const RAIZ = path.resolve(__dirname, "..");
const fuente = fs.readFileSync(path.join(RAIZ, "web/app.js"), "utf8");

function trozo(marca, fin) {
  const i = fuente.indexOf(marca);
  if (i < 0) throw new Error("no está: " + marca);
  const j = fuente.indexOf(fin, i);
  return fuente.slice(i, j + fin.length);
}

const dom = new JSDOM(`<!doctype html><body>
  <div id="a"><table><thead><tr><th>Fecha</th><th>Concepto</th><th>Importe</th></tr></thead>
    <tbody><tr><td>2026-08-10</td><td>Minuta</td><td>2.450,75 €</td></tr></tbody></table></div>

  <div id="b" class="ui-table ui-table-scroll"><table><thead><tr><th>Uno</th><th>Dos</th></tr></thead>
    <tbody><tr><td data-label="Uno">x</td><td data-label="Dos">y</td></tr></tbody></table></div>

  <div id="c"><table><tbody><tr><td>sin cabecera</td><td>ninguna</td></tr></tbody></table></div>

  <div id="d"><table><thead><tr><th>A</th><th>B</th><th>C</th></tr></thead>
    <tbody><tr><td colspan="3">Sin resultados</td></tr>
           <tr><td>1</td><td>2</td><td>3</td></tr></tbody></table></div>
</body>`);
global.window = dom.window;
global.document = dom.window.document;

eval(trozo("const UI_TABLA_MARCA", '"uiTablaLista";').replace("const ", "globalThis."));
eval(trozo("const aplicaSistemaDeDisenoATabla", "\n};").replace("const ", "globalThis."));
eval(trozo("const repasaLasTablas", "\n};").replace("const ", "globalThis."));

repasaLasTablas(document.body);
// Y otra vez: tiene que ser idempotente (el observador lo llama muchas veces).
repasaLasTablas(document.body);

const mira = (id) => {
  const caja = document.getElementById(id);
  const tabla = caja.querySelector("table");
  const filas = Array.from(tabla.querySelectorAll("tbody tr")).map((tr) =>
    Array.from(tr.children).map((td) => td.getAttribute("data-label")));
  return {
    envoltorios: caja.querySelectorAll(".ui-table").length + (caja.classList.contains("ui-table") ? 1 : 0),
    tablasDentro: caja.querySelectorAll("table").length,
    padreDeLaTabla: tabla.parentElement.className,
    etiquetas: filas,
  };
};
process.stdout.write(JSON.stringify({ a: mira("a"), b: mira("b"), c: mira("c"), d: mira("d") }));
