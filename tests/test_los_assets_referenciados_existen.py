"""Ninguna imagen del CRM puede apuntar a un fichero que no está.

Abriendo el módulo inmobiliario en el navegador —la primera vez que se mira la
aplicación funcionando y no solo su código— salió un logo roto en el carril. No era
cosa del entorno local: `/assets/verifika2/verifika2_mark.svg` **devuelve 404 en
producción**. El fichero no existe y nunca existió; lo que hay en `assets/verifika2/`
son el wordmark, tres insignias y un icono de aplicación.

Se referenciaba desde dos sitios, los dos de inmobiliaria:

- el logo del carril del CRM (`crm-lightning-logo`), y
- **la insignia «Verificado por Verifika²» que lleva cada inmueble verificado**, que
  es la que le da valor comercial a la ficha y salía con el icono de imagen rota.

Un `<img>` roto no lanza ningún error de JavaScript ni aparece en los registros del
servidor: se ve, y solo si alguien mira. Por eso este test recorre las referencias y
comprueba que el fichero está, que es la única forma de que no vuelva a pasar.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
#: Los assets se sirven desde la raíz del repositorio, no desde `web/`.
ASSETS = RAIZ
FUENTES = ("web/index.html", "web/app.js", "web/ui-foundation.js", "web/app-routing.js", "web/app_shared.js")


def referencias():
    patron = re.compile(r'["\'](/assets/[^"\'\s)]+\.(?:svg|png|jpg|jpeg|webp|ico|gif))["\']')
    for nombre in FUENTES:
        p = RAIZ / nombre
        if not p.exists():
            continue
        texto = p.read_text(encoding="utf-8")
        for m in patron.finditer(texto):
            linea = texto[: m.start()].count("\n") + 1
            yield nombre, linea, m.group(1)


class TodoLoQueSePintaExisteTests(unittest.TestCase):
    def test_ninguna_referencia_apunta_a_un_hueco(self):
        rotas = []
        for fichero, linea, ruta in referencias():
            if not (ASSETS / ruta.lstrip("/")).exists():
                rotas.append(f"{fichero}:{linea} -> {ruta}")
        self.assertEqual(rotas, [], "imágenes que no existen:\n  " + "\n  ".join(rotas))

    def test_el_que_estaba_roto_ya_no_se_usa(self):
        todas = {ruta for _f, _l, ruta in referencias()}
        self.assertNotIn("/assets/verifika2/verifika2_mark.svg", todas)

    def test_la_insignia_del_inmueble_tiene_logo(self):
        """Es la que dice «Verificado por Verifika²» en cada ficha."""
        app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        i = app.index("const buildVerifika2Badge")
        cuerpo = app[i: i + 600]
        m = re.search(r'src="(/assets/[^"]+)"', cuerpo)
        self.assertIsNotNone(m, "la insignia perdió su imagen")
        self.assertTrue((ASSETS / m.group(1).lstrip("/")).exists(), f"no existe {m.group(1)}")

    def test_el_carril_del_crm_tambien(self):
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        i = html.index('class="crm-lightning-logo"')
        m = re.search(r'src="(/assets/[^"]+)"', html[i - 200: i + 200])
        self.assertIsNotNone(m)
        self.assertTrue((ASSETS / m.group(1).lstrip("/")).exists(), f"no existe {m.group(1)}")

    def test_se_revisan_de_verdad_unas_cuantas(self):
        """Si el patrón dejara de encontrar nada, el test pasaría sin comprobar."""
        self.assertGreater(len(list(referencias())), 30)


if __name__ == "__main__":
    unittest.main()
