"""Lo que salió de abrir la aplicación de verdad, en vez de leerla.

Hasta aquí toda la auditoría había sido estática: código y consultas de solo
lectura. Para juzgar la interfaz eso no basta —el apelotonamiento del PDF tampoco
se vio hasta convertirlo a imagen y mirarlo— así que se levantó el CRM en local
contra una SQLite vacía y se midió en el navegador.

Lo primero que apareció no fue de interfaz. **El servidor local se conectó a la
base de producción.** `load_env_file()` solo respeta una variable si ya existe en
el entorno (`if key not in os.environ`), así que `unset DATABASE_URL` no sirve de
nada: el `.env` la repone. Cualquiera que levante el servidor en su portátil para
mirar una pantalla está escribiendo en los datos de los clientes. Solo se vio
porque `/api/build_info` respondió «postgres».

Después, lo medido en un móvil de 812 px de alto:

- la cabecera ocupaba **272 px**, un tercio de la pantalla;
- el primer contenido útil empezaba en el píxel **486**, el 60 %;
- la marca se decía **tres veces** en la cabecera: el wordmark, la píldora
  «Verifika²» y el título «CRM 360»;
- «Acción principal» era un botón de la barra de todas las pantallas que solo
  **movía el foco** al primer botón visible. No hacía nada que el usuario pudiera
  notar, y su nombre prometía un comando.

Tras los cambios: cabecera 220 px y primer contenido en 387. Sigue habiendo trabajo
de fondo en la portada —cuatro bloques distintos dicen «continúa donde lo dejaste»—
pero eso es un rediseño, no un ajuste, y se propone aparte.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
UI = (RAIZ / "web" / "ui-foundation.js").read_text(encoding="utf-8")


class ElArranqueAvisaSiEsProduccionTests(unittest.TestCase):
    def test_existe_el_aviso(self):
        self.assertIn("def aviso_de_produccion(args):", SERVER)

    def test_se_llama_al_arrancar(self):
        i = SERVER.index("server = ThreadingHTTPServer((args.host, args.port), Handler)")
        self.assertIn("aviso_de_produccion(args)", SERVER[i - 300: i])

    def test_solo_cuando_hay_postgres(self):
        c = SERVER[SERVER.index("def aviso_de_produccion"): SERVER.index("\ndef main")]
        self.assertIn("if not dsn:", c)

    def test_no_molesta_en_la_plataforma(self):
        """En Render este arranque es el bueno y siempre hay PORT."""
        c = SERVER[SERVER.index("def aviso_de_produccion"): SERVER.index("\ndef main")]
        self.assertIn('os.environ.get("PORT")', c)

    def test_explica_que_unset_no_vale(self):
        """Es justo el error que cometí: sin esa frase, el siguiente lo repite."""
        c = SERVER[SERVER.index("def aviso_de_produccion"): SERVER.index("\ndef main")]
        self.assertIn("NO 'unset'", c)

    def test_no_bloquea_el_arranque(self):
        c = SERVER[SERVER.index("def aviso_de_produccion"): SERVER.index("\ndef main")]
        self.assertNotIn("sys.exit", c)
        self.assertNotIn("raise ", c)


class LaMarcaSeDiceUnaVezTests(unittest.TestCase):
    def test_fuera_la_pildora_que_repetia_verifika(self):
        i = HTML.index('<div class="brand"')
        cabecera = HTML[i: HTML.index("</header>", i)]
        self.assertNotIn('class="brand-kicker"', cabecera)

    def test_el_wordmark_y_el_titulo_siguen(self):
        i = HTML.index('<div class="brand"')
        cabecera = HTML[i: HTML.index("</header>", i)]
        self.assertIn("verifika2_wordmark_dark.svg", cabecera)
        self.assertIn("<h1>CRM 360</h1>", cabecera)


class ElBotonQueNoHaciaNadaTests(unittest.TestCase):
    def test_ya_no_esta_en_la_barra(self):
        self.assertNotIn("Acción principal", HTML)
        self.assertNotIn("Acción principal", UI)

    def test_buscar_se_queda_porque_si_hace_algo(self):
        self.assertIn('data-ui-action="focus-search"', HTML)

    def test_el_manejador_se_conserva(self):
        """La barra se genera en varios sitios; quitar el manejador sería otro
        cambio y no hace falta."""
        self.assertIn('if (action === "focus-primary")', UI)


class LaCabeceraCabeEnUnMovilTests(unittest.TestCase):
    def test_hay_reglas_para_pantalla_estrecha(self):
        self.assertIn("@media (max-width: 720px)", CSS)

    def test_el_logo_se_encoge_entero_no_solo_de_alto(self):
        """Primer intento fallido: con solo `max-height` el ancho seguía igual y la
        marca quedaba perdida dentro de su caja."""
        i = CSS.rindex("@media (max-width: 720px)")
        bloque = CSS[i:]
        self.assertIn("header .brand img { width: 52px; height: 52px;", bloque)

    def test_gana_a_la_regla_del_tema(self):
        """`body.theme-operativa .brand img` la pinta como insignia de 92x92: hay
        que igualar la especificidad o el ajuste no se aplica."""
        i = CSS.rindex("@media (max-width: 720px)")
        self.assertIn("body.theme-operativa header .brand img", CSS[i:])

    def test_el_rotulo_usuario_no_ocupa_una_linea_en_movil(self):
        i = CSS.rindex("@media (max-width: 720px)")
        self.assertIn("header .meta-user > span:first-child { display: none; }", CSS[i:])

    def test_el_escritorio_no_se_toca(self):
        """El ajuste va dentro del media query; fuera, la cabecera queda igual."""
        i = CSS.rindex("@media (max-width: 720px)")
        antes = CSS[:i]
        self.assertIn("width: 240px;", antes)


if __name__ == "__main__":
    unittest.main()
