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


class LasEtiquetasDeLaBarraDelCrmNoSeCortanTests(unittest.TestCase):
    """«DASHBOAR» y «NMUEBL» en la barra del CRM inmobiliario.

    Los pastillones de navegación se reparten el ancho con
    `grid-auto-columns: minmax(44px, 1fr)`. Con la barra llena se quedan en 44 px, y
    la etiqueta va a 8 px con recorte a dos líneas. Pero «Dashboard» e «Inmuebles»
    son palabras sin punto de corte: no partían, se desbordaban a 51 y 47 px, y el
    botón de al lado las tapaba.

    Probé a subir el mínimo del pastillón a 68 px para que cupieran en una línea y
    **salió peor**: al no caber los ocho, el contenedor no desplaza —tiene
    `overflow: visible`— y «Inmuebles» desaparecía del todo. Un botón feo se usa;
    uno que no está, no. Se revirtió.

    El arreglo de fondo sería acortar las etiquetas («Panel» en vez de «Dashboard»),
    pero eso es decidir nombres de producto, no maquetar.
    """

    CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")

    def test_la_etiqueta_no_se_sale_del_boton(self):
        # Hay cuatro reglas con este selector; la que manda es la última.
        i = self.CSS.rindex("#crmSection .crm-workspace-tabs.crm-lightning-tabs .tc-mod-label {")
        bloque = self.CSS[i: self.CSS.index("}", i)]
        self.assertIn("max-width: 100%", bloque)
        self.assertIn("overflow-wrap: anywhere", bloque)

    def test_no_se_subio_el_minimo_del_pastillon(self):
        """Dejaba «Inmuebles» fuera de la pantalla."""
        self.assertNotIn("grid-auto-columns: minmax(68px, 1fr)", self.CSS)

    def test_queda_escrito_por_que_no(self):
        self.assertIn("«Inmuebles» desaparecía entero", self.CSS)
