"""Teclear 31/02 no daba error: guardaba el 3 de marzo.

`normalizeDateInput` no miraba el calendario. "31/02/2026" salía como "2026-02-31" y el
navegador lo convertía solo en el 3 de marzo, sin avisar. El que lo teclea ve una fecha
distinta de la que puso, y en un recibo o en una convocatoria eso importa.

Y sólo traducía si la fecha llevaba barras: "31-02-2026" y "31.02.2026" —que también se
teclean, y son lo que sale de muchos exportadores— se guardaban tal cual, como texto que
no es una fecha. Las columnas son TEXT, así que nada se quejaba.

Ahora se valida el día contra el calendario y, si no existe, se devuelve vacío: mejor un
hueco que una fecha distinta de la que quería la persona.

Es la misma familia que el importe en formato inglés: el dato entra mal, sin error, y no
se nota hasta que algo no cuadra semanas después.
"""

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "web" / "app.js"


def normaliza(entradas):
    """Ejecuta la función real de `app.js`, no una copia de ella."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node no está disponible")
    fuente = APP.read_text(encoding="utf-8")
    ini = fuente.index("const normalizeDateInput = (value) => {")
    fin = fuente.index("\n};", ini) + 3
    guion = (
        fuente[ini:fin].replace("const normalizeDateInput", "var normalizeDateInput", 1)
        + "\nconsole.log(JSON.stringify("
        + json.dumps(entradas)
        + ".map(normalizeDateInput)));"
    )
    r = subprocess.run([node, "-e", guion], capture_output=True, text=True, cwd=str(RAIZ))
    if r.returncode:
        raise AssertionError(f"node falló:\n{r.stdout}\n{r.stderr}")
    return json.loads(r.stdout.strip())


class UnaFechaQueNoExisteNoSeInventaTests(unittest.TestCase):
    def test_el_31_de_febrero_no_pasa_a_marzo(self):
        self.assertEqual(normaliza(["31/02/2026", "2026-02-31", "31-02-2026"]), ["", "", ""])

    def test_el_29_de_febrero_depende_del_ano(self):
        self.assertEqual(normaliza(["29/02/2024", "29/02/2026"]), ["2024-02-29", ""])

    def test_un_mes_13_no_pasa(self):
        self.assertEqual(normaliza(["13/13/2026", "00/01/2026", "01/00/2026"]), ["", "", ""])

    def test_guiones_y_puntos_tambien_se_traducen(self):
        self.assertEqual(
            normaliza(["01-08-2026", "01.08.2026", "01/08/2026"]),
            ["2026-08-01", "2026-08-01", "2026-08-01"],
        )

    def test_lo_que_ya_funcionaba_sigue_igual(self):
        self.assertEqual(
            normaliza(["03/04/2026", "1/1/26", "2026-08-01", "2026-08-01T10:30", "2026-08", "", "hoy"]),
            ["2026-04-03", "2026-01-01", "2026-08-01", "2026-08-01T10:30", "2026-08", "", ""],
        )


if __name__ == "__main__":
    unittest.main()
