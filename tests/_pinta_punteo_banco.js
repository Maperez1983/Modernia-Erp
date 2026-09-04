// Ejecuta la función real que pinta la tabla del punteo bancario, con jsdom, y
// devuelve lo que sale en la columna «Punteo» para cada movimiento.
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
  <div id="gestoriaBancoMovimientosTable"></div><div id="gestoriaBancoMovimientosInfo"></div>
</body>`);
global.window = dom.window; global.document = dom.window.document;

const gestoriaBancoMovimientosTable = document.getElementById("gestoriaBancoMovimientosTable");
const gestoriaBancoMovimientosInfo = document.getElementById("gestoriaBancoMovimientosInfo");
const euroFormatter = new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" });
const escapeHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const parseMoneyValue = (v) => Number(v) || 0;

eval(trozo("const CONCILIACION_CONFIANZA_MINIMA", "= 55;").replace("const ", "globalThis."));
eval(trozo("const renderGestoriaBancoMovimientos", "\n};").replace("const ", "var "));

// Los mismos cuatro movimientos de la base sembrada.
renderGestoriaBancoMovimientos([
  { id: "mv1", concepto: "Transferencia ACME", importe: 1210.0, punteado: 1,
    conciliacion_estado: "auto", conciliacion_confianza: 92.0, asiento_id: "asi1" },
  { id: "mv2", concepto: "Compra Apple.com", importe: -9.99, punteado: 1,
    conciliacion_estado: "pendiente", conciliacion_confianza: 0.0, asiento_id: "asi1" },
  { id: "mv3", concepto: "Recibo luz", importe: -84.3, punteado: 0,
    conciliacion_estado: "", conciliacion_confianza: 0.0, asiento_id: "" },
  { id: "mv4", concepto: "Cuota gestoría", importe: -150.0, punteado: 1,
    conciliacion_estado: "auto", conciliacion_confianza: 40.0, asiento_id: "asi1" },
]);

const filas = Array.from(gestoriaBancoMovimientosTable.querySelectorAll("tbody tr")).map((tr) => {
  const tds = tr.querySelectorAll("td");
  const badge = tds[5].querySelector(".ocr-badge");
  return {
    concepto: tds[1].textContent.trim(),
    celda: tds[5].textContent.trim().replace(/\s+/g, " "),
    clase: badge ? badge.className : "",
    etiqueta: badge ? badge.textContent.trim() : "",
    titulo: badge ? badge.title : "",
  };
});
process.stdout.write(JSON.stringify({ filas, pie: gestoriaBancoMovimientosInfo.textContent }));
