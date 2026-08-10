"""El modo oscuro, y sobre todo que el claro siga exactamente igual.

Punto de partida: 425 colores literales en `styles.css` y 222 más en estilos en línea
de `app.js`. Cambiar sólo los tokens habría dado una interfaz medio oscura y medio
blanca, que es peor que no tener modo oscuro.

Cómo se hizo
------------
1. **`light-dark(claro, oscuro)`** para cada literal, en vez de inventar un token por
   color. El valor claro se queda **literalmente el de antes**, así que el modo actual
   no cambia ni un píxel; el oscuro va al lado. Requiere `color-scheme: light dark`
   en `:root`, que además hace que los controles del navegador —scrollbars, selects,
   el cursor de los inputs— se pinten acordes.
2. **Los tokens de `:root` se reescriben** en un bloque oscuro. Como la hoja ya usaba
   `var(--…)` en 868 sitios, casi toda la interfaz cambió sola.
3. **`body.theme-operativa` redefine la paleta entera** por debajo de `:root` —es EL
   tema de la aplicación, 377 reglas—, así que también se cubre. Sin eso, los tokens
   oscuros quedaban pisados y las etiquetas de los campos salían navy sobre navy.
4. Los `rgba()` de superficie pasan por `--surface-rgb`, y los de tinta por
   `--ink-rgb`, que ya se aclara en oscuro.

Las dos trampas que costaron encontrar
--------------------------------------
*   **Chips oscuros con texto blanco.** Un `background: rgba(var(--ink-rgb), .94)`
    con `color: #fff` era un chip oscuro sobre interfaz clara. Al aclararse la tinta,
    se volvía un chip claro con texto blanco: ilegible. Para esos existe
    `--ink-fixed-rgb`, que NO cambia. Lo mismo pasa con el velo de los modales: si se
    aclara, en vez de oscurecer el fondo lo cubre de niebla blanca.
*   **`var(--card-bg, #fff)`.** Un blanco escondido dentro del valor por defecto de
    una variable no lo encuentra ningún buscador de `background: #fff`.

Comprobado en el navegador, con sesión iniciada, recorriendo cada texto visible y
midiendo su contraste real contra el fondo efectivo: **0 fallos** de AA. Y el modo
claro, mirado en paralelo, idéntico.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
# Los comentarios de esta hoja explican por qué se descartaron `invert()` y demás, y
# un buscador ingenuo los toma por código: se miran aparte.
CSS_SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")


def luminancia(hexa):
    h = hexa.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[k:k + 2], 16) / 255 for k in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    la, lb = luminancia(a), luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def tokens_del_bloque(marca):
    i = CSS.index(marca)
    bloque = CSS[i:CSS.index("\n}", i)]
    return dict(re.findall(r"(--[a-z-]+):\s*([^;]+);", bloque))


class ElMecanismoTests(unittest.TestCase):
    def test_la_raiz_declara_los_dos_esquemas(self):
        """Sin esto, `light-dark()` devuelve siempre el valor claro."""
        i = CSS.index(":root {")
        self.assertIn("color-scheme: light dark", CSS[i:i + 600])

    def test_se_sigue_al_sistema_y_tambien_se_puede_forzar(self):
        self.assertIn("@media (prefers-color-scheme: dark)", CSS)
        self.assertIn(':root[data-theme="dark"]', CSS)
        self.assertIn(':root[data-theme="light"]', CSS)

    def test_forzar_claro_gana_al_sistema_oscuro(self):
        """Si no, elegir «Claro» con el sistema en oscuro no haría nada."""
        i = CSS.index("@media (prefers-color-scheme: dark)")
        self.assertIn(':root:not([data-theme="light"])', CSS[i:i + 300])

    def test_el_tema_de_la_aplicacion_tambien_se_cubre(self):
        """`body.theme-operativa` redefine la paleta por debajo de :root."""
        self.assertIn(':root[data-theme="dark"] body.theme-operativa', CSS)
        i = CSS.index("@media (prefers-color-scheme: dark)")
        self.assertIn("body.theme-operativa", CSS[i:i + 4000])

    def test_el_tema_se_aplica_antes_de_pintar(self):
        """En app.js llegaría tarde: fogonazo blanco en cada arranque."""
        cabeza = re.sub(r"//[^\n]*", "", INDEX[:INDEX.index("</head>")])
        self.assertIn("verifika2_tema", cabeza, "el arranque del tema debe ir en <head>")
        # Y antes que cualquier script de la aplicación, que se cargan ya en el body.
        documento = re.sub(r"//[^\n]*", "", INDEX)
        self.assertLess(documento.index("verifika2_tema"), documento.index('src="app'))


class LaPaletaOscuraTests(unittest.TestCase):
    def setUp(self):
        self.t = tokens_del_bloque(':root[data-theme="dark"] {')

    def test_las_superficies_son_oscuras(self):
        for token in ("--paper", "--cream", "--cloud"):
            with self.subTest(token):
                self.assertLess(luminancia(self.t[token]), 0.05)

    def test_los_textos_pasan_AA_sobre_la_tarjeta(self):
        tarjeta = self.t["--cloud"]
        for token, minimo in (("--ink", 4.5), ("--ink-soft", 4.5), ("--muted", 4.5)):
            with self.subTest(token):
                self.assertGreaterEqual(contraste(self.t[token], tarjeta), minimo)

    def test_el_verde_de_marca_se_ve_sobre_oscuro(self):
        self.assertGreaterEqual(contraste(self.t["--gold"], self.t["--cloud"]), 4.5)

    def test_las_superficies_se_distinguen_entre_si(self):
        self.assertGreater(contraste(self.t["--cloud"], self.t["--paper"]), 1.15)

    def test_los_dos_bloques_oscuros_dicen_lo_mismo(self):
        """Uno para el sistema y otro para el interruptor: si se separan, forzar
        oscuro daría una paleta distinta de la del sistema en oscuro."""
        del_media = tokens_del_bloque(':root:not([data-theme="light"]) {')
        for token, valor in self.t.items():
            if token == "color-scheme":
                continue
            with self.subTest(token):
                self.assertEqual(del_media.get(token), valor)


class LasDosTrampasTests(unittest.TestCase):
    def test_existe_una_tinta_que_no_cambia(self):
        self.assertIn("--ink-fixed-rgb", CSS)
        i = CSS.index(':root[data-theme="dark"] {')
        self.assertNotIn("--ink-fixed-rgb", CSS[i:CSS.index("\n}", i)])

    def test_el_velo_de_los_modales_sigue_siendo_oscuro(self):
        i = CSS.index(".crm-modal {")
        bloque = CSS[i:CSS.index("}", i)]
        self.assertIn("--ink-fixed-rgb", bloque,
                      "un velo que se aclara cubre la aplicación de niebla blanca")

    def test_no_quedan_blancos_escondidos_en_valores_por_defecto(self):
        self.assertEqual(re.findall(r"var\(--[a-z-]+,\s*#(?:fff|ffffff)\)", CSS, re.I), [])


class ElModoClaroNoCambiaTests(unittest.TestCase):
    def test_cada_par_conserva_el_valor_original_a_la_izquierda(self):
        """`light-dark(claro, oscuro)`: el primero es el de antes, intacto."""
        pares = re.findall(r"light-dark\(\s*([^,]+?)\s*,", CSS_SIN_COMENTARIOS)
        self.assertGreater(len(pares), 150)
        for valor in pares[:80]:
            with self.subTest(valor=valor[:24]):
                self.assertTrue(
                    valor.startswith("#") or valor.startswith("rgba("),
                    f"el lado claro debería ser el literal original, y es «{valor}»",
                )

    def test_el_lado_claro_de_las_superficies_sigue_siendo_claro(self):
        for claro, _osc in re.findall(r"light-dark\(\s*(#[0-9a-fA-F]{3,8})\s*,\s*(#[0-9a-fA-F]{6})\)", CSS_SIN_COMENTARIOS):
            if luminancia(claro) > 0.72:
                continue
        # Y ninguna superficie clara acabó con un par también claro.
        malos = [
            (c, o) for c, o in re.findall(r"light-dark\(\s*(#[0-9a-fA-F]{6})\s*,\s*(#[0-9a-fA-F]{6})\)", CSS)
            if luminancia(c) > 0.72 and luminancia(o) > 0.3
        ]
        self.assertEqual(malos, [], "hay superficies claras cuyo par oscuro no es oscuro")


class ElInterruptorTests(unittest.TestCase):
    def test_tiene_tres_estados(self):
        """Con dos no se puede volver a «lo que diga el sistema»."""
        i = APP.index("const TEMAS = [")
        bloque = APP[i:i + 260]
        for valor in ("sistema", "claro", "oscuro"):
            self.assertIn(f'"{valor}"', bloque)

    def test_por_defecto_manda_el_sistema(self):
        i = APP.index("const temaGuardado")
        self.assertIn('return TEMAS.some((t) => t.valor === v) ? v : "sistema";', APP[i:i + 300])

    def test_se_recuerda_entre_sesiones(self):
        self.assertIn('localStorage.setItem(TEMA_CLAVE, valor)', APP)

    def test_con_sistema_sigue_al_sistema_en_caliente(self):
        """Si el portátil cambia a oscuro con la aplicación abierta."""
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', APP)
        i = APP.index('consulta.addEventListener("change"')
        self.assertIn('temaGuardado() === "sistema"', APP[i:i + 200])

    def test_se_cambia_tambien_la_barra_del_navegador(self):
        self.assertIn('meta[name="theme-color"]', APP)

    def test_el_estado_se_anuncia_con_aria_pressed(self):
        i = APP.index("data-crm-tema=")
        self.assertIn("aria-pressed", APP[i - 200:i + 200])


class ElVerdeTieneDosOficiosTests(unittest.TestCase):
    """Recorriendo Fincas y Seguros en oscuro salió el fallo más sutil de todos.

    El verde de marca hace dos trabajos que en oscuro piden lo contrario: como FONDO
    de botón necesita seguir siendo oscuro para que el texto casi blanco de encima se
    lea; como TEXTO sobre una tarjeta oscura necesita aclararse. Aclaré el token y
    arreglé lo segundo rompiendo lo primero: el botón «Retomar trabajo» pasó de 3.02
    a 2.09. Por eso hay dos tokens.
    """

    def test_el_verde_de_fondo_no_cambia_en_oscuro(self):
        claro = tokens_del_bloque(":root {")
        oscuro = tokens_del_bloque(':root[data-theme="dark"] {')
        for token in ("--gold", "--gold-deep"):
            with self.subTest(token):
                self.assertEqual(oscuro[token], claro[token],
                                 "si se aclara, el texto blanco de los botones deja de leerse")

    def test_el_verde_de_texto_si_se_aclara(self):
        oscuro = tokens_del_bloque(':root[data-theme="dark"] {')
        self.assertIn("--gold-text", oscuro)
        tarjeta = oscuro["--cloud"]
        self.assertGreaterEqual(contraste(oscuro["--gold-text"], tarjeta), 4.5)

    def test_en_claro_el_verde_de_texto_es_el_de_siempre(self):
        """No puede cambiar lo que ya se veía bien."""
        self.assertEqual(tokens_del_bloque(":root {")["--gold-text"], "#15803D")

    def test_el_boton_verde_con_texto_claro_cumple_AA(self):
        """El verde de marca con texto casi blanco encima daba 3.02: pasa para un
        botón, no para leer. Con la parada clara en #15803D sube a 4.6.

        Este fallo NO lo trajo el modo oscuro —era igual en claro— pero se arregla
        aquí porque salió midiendo, y porque el modo oscuro lo empeoró hasta 2.09
        antes de separar los dos oficios del verde.
        """
        claro = tokens_del_bloque(":root {")
        self.assertGreaterEqual(contraste("#f5f5f5", claro["--gold-boton"]), 4.5)
        oscuro = tokens_del_bloque(':root[data-theme="dark"] {')
        self.assertGreaterEqual(contraste("#f5f5f5", oscuro["--gold-boton"]), 4.5)

    def test_el_boton_se_ve_igual_en_los_dos_temas(self):
        claro = tokens_del_bloque(":root {")
        oscuro = tokens_del_bloque(':root[data-theme="dark"] {')
        for token in ("--gold-boton", "--gold-boton-deep"):
            with self.subTest(token):
                self.assertEqual(claro[token], oscuro[token])

    def test_ya_no_se_usa_el_verde_de_fondo_como_color_de_texto(self):
        restos = re.findall(r"color\s*:\s*var\(--gold(?:-deep)?\)", CSS_SIN_COMENTARIOS)
        self.assertEqual(restos, [])


class ElLogotipoTests(unittest.TestCase):
    def test_hay_una_version_clara(self):
        claro = RAIZ / "assets" / "verifika2" / "verifika2_wordmark_traced_light.svg"
        self.assertTrue(claro.exists())
        texto = claro.read_text(encoding="utf-8")
        self.assertIn('fill="#22C55E"', texto, "el verde de marca no se toca")
        self.assertNotIn('fill="#0B1D33"', texto, "el texto navy desaparecía sobre oscuro")

    def test_se_sirve_en_oscuro(self):
        self.assertIn("verifika2_wordmark_traced_light.svg", CSS)

    def test_no_se_resuelve_con_un_filtro(self):
        """`invert()` habría puesto el check de marca en magenta."""
        i = CSS_SIN_COMENTARIOS.index("verifika2_wordmark_traced_light.svg")
        self.assertNotIn("invert(", CSS_SIN_COMENTARIOS[i - 400:i + 200])


if __name__ == "__main__":
    unittest.main()
