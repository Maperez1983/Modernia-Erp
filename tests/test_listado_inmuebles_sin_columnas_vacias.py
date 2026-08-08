"""El listado de inmuebles pedía seis columnas y la API mandaba tres.

Abriendo el listado del CRM inmobiliario, cuatro de sus seis columnas de datos
salían en blanco. Con los datos de prueba eso no prueba nada —podían estar vacías
de verdad—, así que se midió contra los 86 inmuebles reales de producción:

    Subtipología inm.      18/86 tienen dato
    Inmueble: Tel. pr.     24/86
    Necesidad de vta.      18/66 (en captaciones)
    Propietario            42/86

O sea que **había dato y no se veía**. La causa no era de datos sino de un desajuste:
la tabla pinta `row.subtipologia`, `row.propietario_telefono` y
`row.necesidad_venta_alquiler`, y el `SELECT` de `/api/inmuebles` no pedía ninguno de
los tres. Dos estaban en `inmuebles` sin más; el tercero vive en `captaciones`, tabla
que la consulta **ya unía** para `noticia_verificada`, así que solo faltaba pedirlo.

Estuve a punto de quitar la columna «Necesidad de vta.» por muerta: en `inmuebles` no
existe ese campo. Lo salvó mirar dónde vivía antes de borrar nada — es un dato del
negocio (Venta / Alquiler / Permuta), no un resto.

Este test ata las dos puntas: cada campo que la tabla pinta tiene que venir en la
consulta. Es lo único que evita que vuelvan a separarse.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def tabla_del_listado():
    i = APP.index("const buildCrmInmueblesDenseTableNode")
    return APP[i: APP.index("\nconst ", i + 10)]


def consulta_del_endpoint():
    i = SERVER.index('if path == "/api/inmuebles"')
    cuerpo = SERVER[i: i + 9000]
    j = cuerpo.index("SELECT")
    return cuerpo[j: cuerpo.index("ORDER BY", j)]


class CadaColumnaRecibeSuDatoTests(unittest.TestCase):
    #: Campo que lee cada celda, en el orden en que salen en pantalla.
    CAMPOS = ["direccion", "propietarios", "propietario_telefono",
              "subtipologia", "necesidad_venta_alquiler", "precio_encargo"]

    def test_la_consulta_pide_todo_lo_que_la_tabla_pinta(self):
        sql = consulta_del_endpoint()
        faltan = [c for c in self.CAMPOS if c not in sql]
        self.assertEqual(faltan, [], f"columnas que saldrán vacías siempre: {faltan}")

    def test_la_tabla_sigue_pintando_esos_campos(self):
        """Si alguien renombra un campo en la tabla, el test de arriba deja de
        proteger nada: aquí se comprueba que siguen siendo esos."""
        t = tabla_del_listado()
        for campo in ("subtipologia", "propietario_telefono", "necesidad_venta_alquiler", "precio_encargo"):
            with self.subTest(campo=campo):
                self.assertIn(f"row.{campo}", t)

    def test_la_necesidad_se_trae_de_captaciones(self):
        """No está en `inmuebles`: es de la captación, y esa unión ya existía."""
        sql = consulta_del_endpoint()
        self.assertIn("MAX(cap.necesidad_venta_alquiler) AS necesidad_venta_alquiler", sql)
        self.assertIn("LEFT JOIN captaciones cap", consulta_del_endpoint() + SERVER[SERVER.index('if path == "/api/inmuebles"'):][:9000])

    def test_no_se_borro_la_columna_por_creerla_muerta(self):
        """Estuve a punto: en `inmuebles` no existe ese campo. Es un dato del
        negocio (Venta / Alquiler / Permuta), no un resto."""
        self.assertIn("Necesidad de vta.", APP)

    def test_los_dos_campos_del_inmueble_se_piden(self):
        sql = consulta_del_endpoint()
        self.assertIn("i.subtipologia", sql)
        self.assertIn("i.propietario_telefono", sql)

    def test_el_propietario_llega_por_la_union_de_clientes(self):
        sql = consulta_del_endpoint()
        self.assertIn("GROUP_CONCAT(c.nombre", sql)
        self.assertIn("row.propietarios", tabla_del_listado())

    def test_se_agrupa_por_inmueble(self):
        """Con dos uniones de uno a muchos —propietarios y captaciones— sin
        `GROUP BY` saldría el mismo inmueble repetido una vez por propietario."""
        i = SERVER.index('if path == "/api/inmuebles"')
        self.assertIn("GROUP BY i.id", SERVER[i: i + 9000])


if __name__ == "__main__":
    unittest.main()


class ElFiltroQueFiltrabaSinVerseTests(unittest.TestCase):
    """«Mostrando 3 de 5 inmuebles» y ningún filtro a la vista.

    El listado aplica un filtro de estado que por defecto vale «activos», así que
    esconde los vendidos y los cerrados. El pie lo delataba —«3 de 5»— pero el
    control estaba en el HTML con `class="hidden"` y **nadie se la quitaba nunca**:
    el `select` existía, su `change` funcionaba, y era invisible.

    O sea que faltaban inmuebles, se decía en letra pequeña, y no había forma de
    saber por qué ni de llegar a ellos. Para ver una venta cerrada había que saber
    que el filtro existía.
    """

    HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

    def test_el_filtro_de_estado_se_ve(self):
        i = self.HTML.index('id="crmInmuebleEstadoFilterMirror"')
        etiqueta = self.HTML[self.HTML.rindex("<select", 0, i): self.HTML.index(">", i) + 1]
        self.assertNotIn('class="hidden"', etiqueta)

    def test_sigue_ofreciendo_las_cuatro_opciones(self):
        i = self.HTML.index('id="crmInmuebleEstadoFilterMirror"')
        bloque = self.HTML[i: self.HTML.index("</select>", i)]
        for v in ("activos", "vendidos", "cerrados", "todos"):
            with self.subTest(opcion=v):
                self.assertIn(f'value="{v}"', bloque)

    def test_el_cambio_sigue_atendido(self):
        self.assertIn("crmInmuebleEstadoFilterMirror.addEventListener", APP)


class LosDosBuscadoresDicenQueBuscanTests(unittest.TestCase):
    """Dos campos idénticos a 90 píxeles uno de otro.

    `syncCrmGlobalSearchUi` copiaba el `placeholder` del buscador de la vista al de
    la barra, así que los dos ponían «Buscar en la lista...». No hacen lo mismo: el
    de la barra busca en todo el CRM y despliega sugerencias; el de la lista filtra
    la tabla que tienes delante.
    """

    def test_el_de_la_barra_ya_no_copia_al_de_la_lista(self):
        i = APP.index("const syncCrmGlobalSearchUi")
        cuerpo = APP[i: APP.index("\nconst ", i + 10)]
        self.assertNotIn('getAttribute?.("placeholder")', cuerpo)
        self.assertIn('crmGlobalSearch.placeholder = "Buscar en todo el CRM...";', cuerpo)

    def test_el_de_la_lista_sigue_diciendo_lo_suyo(self):
        html = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")
        i = html.index('id="crmInmuebleSearchMirror"')
        self.assertIn("Buscar en la lista", html[i: i + 300])
