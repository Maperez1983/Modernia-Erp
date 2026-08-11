"""Una barra de módulo no puede esconder pestañas sin decirlo.

`.tc-modulebar` lleva `flex-wrap: nowrap` con `overflow-x: auto`, y la barra de
scroll está oculta a propósito (`scrollbar-width: none` y `::-webkit-scrollbar
{height:0}`). Cuando las pestañas no caben, las últimas quedan fuera del borde **sin
ninguna señal de que haya más**: ni scrollbar, ni sombra, ni flecha.

Ya pasó con Seguros —11 pestañas— y se arregló haciendo que esa barra envolviera en
dos filas. El arreglo se escribió para un id concreto, así que el siguiente módulo que
creciera volvía a caer. Y cayó: el 2026-08-11, al añadir la pestaña de Ajustes,
Fincas pasó de 7 a 8 pestañas de 104 px —888 px de ancho mínimo— y perdió
Presupuestos y Ajustes en cuanto la ventana bajaba de eso.

Este test no vigila esos dos ids: vigila la regla. Mide cada barra por sus pestañas y
exige que envuelva la que no quepa con holgura.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

#: Ancho de pestaña y hueco de cada variante, leídos de `styles.css`.
MEDIDAS = {"--compact": (104, 8), "--micro": (86, 8), "": (92, 10)}

#: Por debajo de esto una barra cabe en cualquier pantalla de trabajo razonable; por
#: encima hay que envolver. 800 px es el ancho útil de un portátil de 1280 con el
#: panel lateral abierto.
HOLGURA = 800


def _cierra_div(texto, ini):
    profundidad = 0
    for m in re.finditer(r"<div\b|</div>", texto[ini:]):
        profundidad += 1 if m.group(0) == "<div" else -1
        if profundidad == 0:
            return ini + m.end()
    return len(texto)


def barras_de_modulo():
    for m in re.finditer(r'<div class="([^"]*tc-modulebar[^"]*)"[^>]*id="([A-Za-z]+)"', HTML):
        clases, bid = m.group(1), m.group(2)
        trozo = HTML[m.start(): _cierra_div(HTML, m.start())]
        pestañas = len(re.findall(r'<button[^>]*class="[^"]*tc-module', trozo))
        variante = next((v for v in ("--compact", "--micro") if v in clases), "")
        ancho, hueco = MEDIDAS[variante]
        yield {
            "id": bid,
            "pestañas": pestañas,
            "necesita": pestañas * ancho + max(0, pestañas - 1) * hueco,
            "envuelve": bool(re.search(rf"#{bid}\b[^{{]*\{{[^}}]*flex-wrap:\s*wrap", CSS, re.S)),
        }


class NingunaBarraSeCortaSinAvisarTests(unittest.TestCase):
    def test_hay_barras_que_medir(self):
        """Si el marcado cambia y el test deja de encontrar barras, no vigila nada."""
        barras = list(barras_de_modulo())
        self.assertGreaterEqual(len(barras), 5)
        self.assertTrue(all(b["pestañas"] > 0 for b in barras), [b["id"] for b in barras])

    def test_la_que_no_cabe_envuelve(self):
        culpables = [
            f"{b['id']}: {b['pestañas']} pestañas = {b['necesita']} px y no envuelve"
            for b in barras_de_modulo()
            if b["necesita"] > HOLGURA and not b["envuelve"]
        ]
        self.assertEqual(
            culpables,
            [],
            "Barras que se cortan sin barra de scroll visible. Añade el id a la regla "
            "de `flex-wrap: wrap` en styles.css:\n" + "\n".join(culpables),
        )

    def test_la_de_fincas_es_de_las_que_envuelven(self):
        """El caso que lo destapó, por si alguien quita el id de la regla."""
        fincas = next(b for b in barras_de_modulo() if b["id"] == "workspaceFincasTabs")
        self.assertGreater(fincas["necesita"], HOLGURA)
        self.assertTrue(fincas["envuelve"])


class LasEtiquetasNoSeAbrevianAMediasTests(unittest.TestCase):
    """«Conta» y «Presup.» convivían con «Incidencias» y «Proveedores».

    No se abreviaban por falta de sitio: la pestaña mide lo mismo para todas y una
    etiqueta de once letras entra. Era inconsistencia a secas.
    """

    def _etiquetas(self):
        i = HTML.index('id="workspaceFincasTabs"')
        trozo = HTML[i: _cierra_div(HTML, HTML.rindex("<div", 0, i))]
        return dict(
            re.findall(r'data-fincas-tab-btn="([a-z_]+)".*?tc-mod-label">([^<]+)<', trozo, re.S)
        )

    def test_ninguna_acaba_en_punto(self):
        abreviadas = [k for k, v in self._etiquetas().items() if v.strip().endswith(".")]
        self.assertEqual(abreviadas, [], f"Etiquetas abreviadas con punto: {abreviadas}")

    def test_contabilidad_y_presupuestos_van_enteras(self):
        etiquetas = self._etiquetas()
        self.assertEqual(etiquetas.get("contabilidad"), "Contabilidad")
        self.assertEqual(etiquetas.get("presupuestos"), "Presupuestos")

    def test_la_pestaña_de_comunidades_va_en_plural(self):
        """Lista todas las comunidades; el singular decía otra cosa."""
        self.assertEqual(self._etiquetas().get("comunidades"), "Comunidades")


class SeVeDondeEstaElFocoYCualEstaAbiertaTests(unittest.TestCase):
    """Dos avisos que se pisaban, y uno que no existía.

    El anillo de foco de teclado es `button:focus` —peso 0-1-1— y el de la pestaña
    abierta es `.tc-modulebar .tab.tc-module.active` —peso 0-4-0—. Gana el segundo,
    así que al tabular hasta la pestaña ya seleccionada **no cambiaba nada en
    pantalla**: no había forma de saber dónde estaba el foco. Encima el anillo general
    va al 22 % de opacidad, y sobre el fondo dorado de la pestaña apenas se ve.

    Y cuál estaba abierta se decía solo con ese borde: sin `aria-current`, quien
    navega con lector de pantalla oía ocho botones iguales.
    """

    def test_hay_un_foco_propio_para_las_pestañas(self):
        self.assertRegex(
            CSS,
            r"\.tc-modulebar \.tab\.tc-module:focus-visible",
            "Sin regla propia, el foco lo tapa el estado activo.",
        )

    def test_ese_foco_gana_al_estado_activo(self):
        """Si no cubre también `.active`, la pestaña abierta se queda sin foco visible."""
        self.assertRegex(CSS, r"\.tc-modulebar \.tab\.tc-module\.active:focus-visible")

    def test_va_en_focus_visible_y_no_en_focus(self):
        """Con `:focus` a secas el anillo se queda pegado tras un clic de ratón."""
        bloque = re.search(
            r"\.tc-modulebar \.tab\.tc-module:focus-visible.*?\{([^}]*)\}", CSS, re.S
        )
        self.assertIsNotNone(bloque)
        self.assertIn("outline", bloque.group(1))

    def test_la_pestaña_abierta_se_anuncia(self):
        """Con `role="tab"` el atributo correcto es `aria-selected`, no `aria-current`.

        Lo pone `activarPatronDePestanas` para las nueve barras a la vez, escuchando la
        clase `.active` que cada módulo ya mantiene. Quien lo comprueba de verdad, contra
        un DOM y pulsando teclas, es `test_patron_de_pestanas.py`."""
        i = APP.index("const activarPatronDePestanas")
        cuerpo = APP[i: APP.index("\ndocument.addEventListener(", i)]
        self.assertIn('setAttribute("role", "tab")', cuerpo)
        self.assertIn('setAttribute("aria-selected"', cuerpo)
        self.assertNotIn("aria-current", APP)


if __name__ == "__main__":
    unittest.main()
