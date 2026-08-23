"""Un piso vendido y otro en venta se veían igual en el listado.

La tabla densa de inmuebles no tiene columna de estado: lo único que lo indica es la
sigla que va delante de la dirección. Y `resolveCaptacionCodePrefix` sólo distinguía
tres casos —IN, NT y «EN» para todo lo demás—, así que con el filtro en «Todos» salía:

    EN - Calle Larios 3, 4º A      ← vendido
    EN - Alameda Principal 20      ← en venta

Lo mismo para un alquilado y para uno cerrado en negativo.

Y había un problema de vocabulario debajo: la fase se llamaba «Alquiler», que se lee
como *está en alquiler* cuando quiere decir *está alquilado*. La misma palabra para el
escaparate y para el desenlace. En producción había diez inmuebles con operación de
alquiler y estado «Vendido», que es lo que pasa cuando el cierre positivo manda todo al
mismo sitio.

Ahora la fase se llama «Alquilado» y la sigla mira también si se vende o se alquila:

    EV  en venta        VD  vendido
    EA  en alquiler     AQ  alquilado
    AR  con arras       RS  reservado
    NT  noticia         CN  cerrado negativamente
    IN  inmueble

Arras (AR) y reserva (RS) tienen sigla propia: están comprometidas, pero la venta no se
ha consumado y anunciarla como vendida es adelantarse. Por dentro el sistema las sigue
agrupando en «Vendido» para el embudo —eso venía de antes—; lo que cambia es lo que lee
la persona en la lista.
"""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "web" / "app.js"
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


def siglas(casos):
    """Ejecuta las funciones reales de `app.js`, no una copia."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node no está disponible")
    fuente = APP.read_text(encoding="utf-8")
    trozos = []
    for nombre in ("const normalizeSimple", "const normalizeCrmMainEtapa",
                   "const resolveCaptacionCodePrefix"):
        ini = fuente.index(nombre)
        fin = fuente.index("\n};", ini) + 3
        trozos.append(fuente[ini:fin].replace("const ", "var ", 1))
    guion = "\n".join(trozos) + (
        "\nconsole.log(JSON.stringify(" + json.dumps(casos)
        + ".map(function (c) { return resolveCaptacionCodePrefix(c[0], c[1]); })));"
    )
    r = subprocess.run([node, "-e", guion], capture_output=True, text=True, cwd=str(RAIZ))
    if r.returncode:
        raise AssertionError(f"node falló:\n{r.stdout}\n{r.stderr}")
    return json.loads(r.stdout.strip())


class LaSiglaDistingueElEstadoTests(unittest.TestCase):
    def test_en_venta_y_vendido_no_se_ven_igual(self):
        self.assertEqual(siglas([["Encargo", "venta"], ["Vendido", "venta"]]), ["EV", "VD"])

    def test_en_alquiler_y_alquilado_tampoco(self):
        self.assertEqual(siglas([["Encargo", "alquiler"], ["Alquilado", "alquiler"]]), ["EA", "AQ"])

    def test_el_escaparate_separa_venta_de_alquiler(self):
        """Antes los dos eran «EN» y no se sabía qué se ofrecía."""
        self.assertEqual(siglas([["Encargo", "venta"], ["Encargo", "alquiler"]]), ["EV", "EA"])

    def test_un_cierre_negativo_no_parece_un_encargo_vivo(self):
        self.assertEqual(siglas([["Cerrado negativamente", "venta"]]), ["CN"])

    def test_unas_arras_no_son_una_venta_hecha(self):
        """Están firmadas, pero la venta no se ha consumado."""
        self.assertEqual(siglas([["Contrato de arras", "venta"], ["Arras", "venta"],
                                 ["Vendido", "venta"]]), ["AR", "AR", "VD"])

    def test_un_reservado_tampoco(self):
        self.assertEqual(siglas([["Reservado", "venta"], ["Reserva", "venta"]]), ["RS", "RS"])

    def test_los_tres_compromisos_se_distinguen_entre_si(self):
        """Reservado, con arras y vendido son tres momentos distintos de la misma venta."""
        self.assertEqual(siglas([["Reservado", "venta"], ["Contrato de arras", "venta"],
                                 ["Vendido", "venta"]]), ["RS", "AR", "VD"])

    def test_lo_que_ya_funcionaba_sigue_igual(self):
        self.assertEqual(siglas([["Noticia", "venta"], ["Inmueble", ""]]), ["NT", "IN"])

    def test_la_fase_de_alquiler_ya_no_es_ambigua(self):
        """«Alquiler» se leía como el escaparate; ahora la fase dice «Alquilado»."""
        self.assertEqual(siglas([["Alquiler", "alquiler"]]), ["AQ"])
        self.assertIn('if (key.includes("alquil")) return "Alquilado";',
                      APP.read_text(encoding="utf-8"))

    def test_el_servidor_cierra_el_alquiler_como_alquilado(self):
        self.assertIn('"alquiler": "Alquilado",', SERVER)
        self.assertNotIn('if tipo_label not in {"Vendido", "Alquiler"}:', SERVER)


if __name__ == "__main__":
    unittest.main()
