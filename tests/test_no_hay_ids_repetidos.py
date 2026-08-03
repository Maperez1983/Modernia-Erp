"""Dos elementos con el mismo id: el segundo nace muerto.

`document.getElementById` devuelve el primero que encuentra, así que cuando dos
trozos de pantalla comparten id, uno de los dos deja de funcionar sin que nadie
avise. No hay error en consola, no falla el despliegue: simplemente hay una
tarjeta que nunca se rellena.

Los tres casos que había en producción el 2026-08-03:

  - `workspaceCollections*` y `workspaceRemittances*`: la tarjeta "Cobros y
    remesas" estaba pegada dos veces en index.html. Se veían las dos en Motores ·
    Presupuestos, y la de abajo salía con los desplegables vacíos.
  - `tableToolbar`: se llamaba igual la barra de "Año operativo" de la home y la
    del explorador. Como la de la home va antes, `app.js` se quedaba con ella y
    le aplicaba las reglas de mostrar/ocultar pensadas para la otra.
  - `gestoriaTrabajosTable`: el resumen del explorador y la tarjeta "Gestiones
    vinculadas" de la ficha del cliente. Ganaba el explorador, así que la ficha
    del cliente no pintaba nunca sus gestiones.

Los tres son el mismo fallo. Este test lo corta de raíz.
"""

import collections
import unittest
from html.parser import HTMLParser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Los elementos vacíos de HTML no llevan cierre; da igual aquí, pero el parser
# los recorre igual y solo nos interesa el atributo id.
class RecolectorDeIds(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = collections.Counter()
        self.lineas = collections.defaultdict(list)

    def handle_starttag(self, tag, attrs):
        valor = dict(attrs).get("id")
        if valor:
            self.ids[valor] += 1
            self.lineas[valor].append(self.getpos()[0])


class IndexHtmlNoRepiteIdsTests(unittest.TestCase):
    def test_cada_id_aparece_una_sola_vez(self):
        recolector = RecolectorDeIds()
        recolector.feed((RAIZ / "web" / "index.html").read_text(encoding="utf-8"))
        repetidos = {k: v for k, v in recolector.ids.items() if v > 1}
        detalle = "\n".join(
            f"  {k} x{v} (líneas {', '.join(str(n) for n in recolector.lineas[k])})"
            for k, v in sorted(repetidos.items())
        )
        self.assertEqual(
            repetidos,
            {},
            "ids repetidos en index.html; el segundo no lo verá getElementById:\n" + detalle,
        )


class CadaTablaEscribeEnLoSuyoTests(unittest.TestCase):
    """El reparto concreto que quedó tras separar los ids."""

    def setUp(self):
        self.app = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

    def test_la_ficha_del_cliente_tiene_su_propio_contenedor(self):
        self.assertIn('id="clienteGestionesTable"', self.html)
        self.assertIn('const clienteGestionesTable = document.getElementById("clienteGestionesTable")', self.app)

    def test_la_ficha_no_escribe_en_el_resumen_del_explorador(self):
        i = self.app.index("const loadGestoriaTrabajos = (clienteId)")
        bloque = self.app[i: self.app.index("\nconst ", i + 10)]
        self.assertIn("clienteGestionesTable", bloque)
        self.assertNotIn("gestoriaTrabajosTable", bloque)

    def test_la_barra_de_ano_de_la_home_no_se_llama_como_la_del_explorador(self):
        self.assertIn('id="homeYearToolbar"', self.html)
        # La regla que la ocultaba por compartir id sigue alcanzándola.
        css = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("body.crm-context-vertical #homeYearToolbar", css)

    def test_cobros_y_remesas_solo_esta_una_vez(self):
        self.assertEqual(self.html.count("<h3>Cobros y remesas</h3>"), 1)


if __name__ == "__main__":
    unittest.main()
