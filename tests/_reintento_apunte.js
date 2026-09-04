// Ejercita la función real `guardarApunteDeComunidad` de web/app.js con el `fetch` y el
// `window.confirm` sustituidos, y escribe en JSON lo que hizo en cada caso.
// Lo lee tests/test_cifras_que_no_pueden_ser.py; no se ejecuta a mano.
const fs = require("fs");
const path = require("path");

const fuente = fs.readFileSync(path.join(__dirname, "..", "web", "app.js"), "utf8");
const ini = fuente.indexOf("const guardarApunteDeComunidad");
if (ini < 0) {
  console.error("no está guardarApunteDeComunidad en web/app.js");
  process.exit(2);
}
const cuerpo = fuente.slice(ini, fuente.indexOf("\n};", ini) + 3).replace("const ", "var ", 1);

let llamadas = [];
let respuestas = [];
let preguntado = null;
let contesta = false;

global.fetch = async (url, opciones) => {
  llamadas.push({ url, cuerpo: JSON.parse(opciones.body) });
  const r = respuestas.shift();
  return { status: r.status, json: async () => r.datos };
};
global.window = {
  confirm: (texto) => {
    preguntado = texto;
    return contesta;
  },
};

eval(cuerpo);

async function caso(sus_respuestas, dice_que_si, payload) {
  llamadas = [];
  respuestas = sus_respuestas;
  preguntado = null;
  contesta = dice_que_si;
  let devuelto = null;
  let excepcion = null;
  try {
    devuelto = await guardarApunteDeComunidad(payload);
  } catch (e) {
    excepcion = e.message;
  }
  return {
    llamadas: llamadas.length,
    primera: llamadas[0] ? llamadas[0].cuerpo : null,
    segunda: llamadas[1] ? llamadas[1].cuerpo : null,
    url: llamadas[0] ? llamadas[0].url : null,
    preguntado,
    devuelto,
    excepcion,
  };
}

(async () => {
  const pide_confirmar = {
    status: 409,
    datos: {
      error: "1.000.000.000.000,00 € es mucho para un apunte de comunidad. Si es correcto, confírmalo.",
      requiere_confirmacion: true,
      importe: 1e12,
    },
  };
  const salida = {
    normal: await caso([{ status: 200, datos: { ok: true, id: "a1" } }], false,
                       { importe: 2450.75, concepto: "Ascensor" }),
    confirma: await caso([pide_confirmar, { status: 200, datos: { ok: true, id: "a2" } }], true,
                         { importe: 1e12, concepto: "Derrama" }),
    cancela: await caso([pide_confirmar], false, { importe: 1e12, concepto: "Derrama" }),
    negativo: await caso([{ status: 400, datos: { error: "El importe va en positivo: lo que decide si suma o resta es el tipo (Gasto o Ingreso). Si es un abono, anótalo como ingreso." } }],
                         true, { importe: -500, concepto: "Abono" }),
  };
  process.stdout.write(JSON.stringify(salida));
})();
