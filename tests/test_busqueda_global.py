"""Encontrar a alguien sin saber en qué CRM está.

El botón "Buscar" de la barra y el atajo "/" hacían lo mismo: mover el cursor a la
caja de búsqueda que hubiera en pantalla. En una vista sin caja, nada. Y cada CRM
busca solo en lo suyo, así que para dar con un cliente había que acertar antes el
módulo. Con 2045 fichas, eso es un peaje diario.

Lo que se comprueba aquí, además de que exista:

  - Que **acota por workspace**. Una búsqueda global sin ámbito es una fuga: basta
    escribir dos letras para listar la cartera de otro tenant.
  - Que **normaliza NIF y teléfono**. Nadie los teclea como están guardados
    ("12345678-Z" contra "12345678Z", "600 11 22 33" contra "600112233").
  - Que **ordena por lo que buscabas**, no alfabéticamente: quien escribe un NIF
    exacto quiere esa ficha, no la que va primero por la A.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
UI = (RAIZ / "web" / "ui-foundation.js").read_text(encoding="utf-8")


def bloque_endpoint():
    i = SERVER.index('if path == "/api/buscar_global":')
    return SERVER[i: SERVER.index('if path == "/api/', i + 60)]


class ElEndpointTests(unittest.TestCase):
    def test_existe(self):
        self.assertIn('if path == "/api/buscar_global":', SERVER)

    def test_sin_workspace_no_devuelve_nada(self):
        """Sin ámbito, devolver la base entera sería una fuga entre tenants."""
        bloque = bloque_endpoint()
        i = bloque.index("if not workspace_id:")
        self.assertIn('"rows": []', bloque[i: i + 220])

    def test_comprueba_que_el_usuario_pertenece_al_workspace(self):
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id)", bloque_endpoint())

    def test_usa_la_regla_de_ambito_del_resto_del_crm(self):
        self.assertIn('clientes_workspace_scope_sql(conn, workspace_id, alias="c")', bloque_endpoint())

    def test_no_busca_con_una_sola_letra(self):
        """Una letra devolvería media cartera y una consulta cara por cada tecla."""
        self.assertIn("len(texto) < 2", bloque_endpoint())

    def test_normaliza_el_nif(self):
        bloque = bloque_endpoint()
        self.assertIn('nif_busqueda = re.sub(r"[^0-9A-Za-z]", "", texto).upper()', bloque)
        self.assertIn("REPLACE(REPLACE(REPLACE(UPPER(COALESCE(c.nif", bloque)

    def test_normaliza_el_telefono(self):
        bloque = bloque_endpoint()
        self.assertIn('tel_busqueda = re.sub(r"\\D", "", texto)', bloque)
        self.assertIn("movil", bloque)

    def test_ordena_por_relevancia_no_por_orden_alfabetico(self):
        bloque = bloque_endpoint()
        self.assertIn("def peso(item)", bloque)
        self.assertIn("resultados.sort(key=peso)", bloque)
        # El NIF exacto es lo más fuerte que puede escribir alguien.
        i_nif = bloque.index("if nif_busqueda and nif_clave == nif_busqueda")
        i_nombre = bloque.index("if nombre_clave == clave")
        self.assertLess(i_nif, i_nombre)

    def test_limita_los_resultados(self):
        self.assertIn('min(int(params.get("limit", ["25"])[0] or 25), 50)', bloque_endpoint())


class LaPantallaTests(unittest.TestCase):
    def test_el_panel_existe_y_es_accesible(self):
        self.assertIn('id="busquedaGlobal"', HTML)
        self.assertIn('role="dialog"', HTML)
        self.assertIn('aria-modal="true"', HTML)
        self.assertIn('aria-live="polite"', HTML)

    def test_los_dos_atajos_llevan_a_la_busqueda_global(self):
        """El botón Buscar y la tecla "/" deben acabar en el mismo sitio."""
        self.assertEqual(UI.count("window.abrirBusquedaGlobal?.()"), 2)

    def test_conserva_el_comportamiento_viejo_como_respaldo(self):
        """Si la búsqueda global no está disponible, enfocar la caja sigue valiendo."""
        i = UI.index('if (event.key === "/" && !typing)')
        bloque = UI[i: i + 700]
        self.assertIn("window.abrirBusquedaGlobal?.()", bloque)
        self.assertIn('input[type="search"]', bloque)

    def test_no_se_abre_sin_workspace(self):
        i = APP.index("window.abrirBusquedaGlobal = ")
        self.assertIn("if (!String(state.currentWorkspaceId || \"\").trim()) return false;", APP[i: i + 300])

    def test_espera_antes_de_consultar(self):
        """Sin espera, cada tecla es una consulta contra toda la cartera."""
        i = APP.index("// Búsqueda global")
        bloque = APP[i:]
        self.assertIn("setTimeout(() => buscar(texto), 220)", bloque)

    def test_descarta_las_respuestas_que_llegan_tarde(self):
        """Escribir es más rápido que la red: la última petición es la que vale."""
        i = APP.index("const buscar = async (texto)")
        bloque = APP[i: i + 1400]
        self.assertIn("const mio = ++seq;", bloque)
        self.assertIn("if (mio !== seq) return;", bloque)

    def test_se_maneja_con_el_teclado(self):
        i = APP.index("// Búsqueda global")
        bloque = APP[i:]
        for tecla in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
            with self.subTest(tecla=tecla):
                self.assertIn(f'event.key === "{tecla}"', bloque)

    def test_escapa_lo_que_pinta(self):
        """Los nombres vienen de la base; pintarlos en crudo es una inyección."""
        i = APP.index("const pintar = () => {")
        bloque = APP[i: i + 1200]
        self.assertNotIn("${fila.nombre}", bloque)
        self.assertIn("escapeHtml(fila.nombre", bloque)

class NoConfundirNoEstaConNoPuedesVerloTests(unittest.TestCase):
    """Un 401 pintado como "Sin resultados" hace creer que la persona no existe.

    Visto en producción el 2026-08-04: con la sesión caducada, el panel decía
    'Sin resultados para "bouzyane"' sobre una ficha que existe. Y se abría encima
    del formulario de acceso, tapándolo.
    """

    def setUp(self):
        i = APP.index("// Búsqueda global")
        self.bloque = APP[i:]

    def test_la_sesion_caducada_se_dice_tal_cual(self):
        self.assertIn("res.status === 401", self.bloque)
        self.assertIn("Tu sesión ha caducado", self.bloque)

    def test_cualquier_otro_error_tampoco_es_sin_resultados(self):
        self.assertIn("if (!res.ok)", self.bloque)

    def test_no_se_abre_sobre_la_pantalla_de_acceso(self):
        i = self.bloque.index("window.abrirBusquedaGlobal = ")
        apertura = self.bloque[i: i + 700]
        self.assertIn("authLoginOverlay", apertura)
        self.assertIn('classList.contains("auth-pending")', apertura)


if __name__ == "__main__":
    unittest.main()
