"""Aceptar un presupuesto de fincas da de alta la comunidad.

Era el único hueco que le quedaba al módulo. El circuito estaba entero —censo,
presupuesto anual, recibos, remesa SEPA, conciliación, morosidad, juntas,
liquidación, balance, cierre— pero **la puerta de entrada estaba desconectada**:
aceptar un presupuesto solo abría una tarea de «formalizar nota de encargo», y la
comunidad había que teclearla otra vez a mano en la pestaña de fincas. Denominación,
dirección, CIF, referencia catastral y unidades, todo ello ya escrito en el
presupuesto que se acababa de aceptar.

La cautela que estos tests vigilan es la de no repetir el fallo que acabamos de
arreglar en los presupuestos: **volver a guardar no puede crear otra comunidad**. Se
busca antes por tres caminos, en este orden:

1. La comunidad a la que ya apunta el presupuesto, si sigue existiendo.
2. La **referencia catastral**, que es lo único que identifica un edificio sin
   ambigüedad: dos comunidades pueden llamarse «Comunidad de Propietarios» y ser
   distintas, y la misma puede estar escrita de tres formas.
3. El nombre normalizado, como último recurso.

Solo si no aparece por ninguno de los tres se crea.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

CALC = {
    "comunidad_denominacion": "Comunidad de Propietarios Rocío Jurado 18",
    "comunidad_direccion": "Calle Rocío Jurado 18, Puerto de la Torre",
    "comunidad_cif": "H12345678",
    "referencia_catastral": "6968701UF6666N",
    "solicitante_nombre": "Quien pidió el presupuesto",
    "num_vecinos": 92, "num_locales": 0, "num_trasteros": 95, "num_aparcamientos": 115,
    "cuota_sugerida": 670.0,
}


class BaseTests(unittest.TestCase):
    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)

    def alta(self, calc=None, **kw):
        return server.alta_comunidad_desde_presupuesto(
            self.conn, kw.pop("workspace_id", "ws1"), kw.pop("empresa_id", "emp1"),
            dict(CALC, **(calc or {})), subtotal=kw.pop("subtotal", 670.0), **kw)

    def comunidades(self, workspace_id="ws1"):
        return self.conn.execute(
            "SELECT * FROM workspace_fincas_comunidades WHERE workspace_id = ?", (workspace_id,)
        ).fetchall()


class SeCreaConLosDatosDelPresupuestoTests(BaseTests):
    def test_se_crea_y_lo_dice(self):
        comunidad_id, creada = self.alta()
        self.assertTrue(comunidad_id)
        self.assertTrue(creada)
        self.assertEqual(len(self.comunidades()), 1)

    def test_se_copian_los_datos_que_ya_estaban_escritos(self):
        self.alta()
        fila = self.comunidades()[0]
        self.assertEqual(server.row_value(fila, "nombre", ""), CALC["comunidad_denominacion"])
        self.assertEqual(server.row_value(fila, "direccion", ""), CALC["comunidad_direccion"])
        self.assertEqual(server.row_value(fila, "cif", ""), "H12345678")
        self.assertEqual(server.row_value(fila, "referencia_catastral", ""), "6968701UF6666N")

    def test_se_copian_las_unidades(self):
        """Son las que mandan sobre los recibos y el reparto: si no vienen, hay que
        volver a contarlas a mano."""
        self.alta()
        fila = self.comunidades()[0]
        self.assertEqual(server.row_value(fila, "num_vecinos", 0), 92)
        self.assertEqual(server.row_value(fila, "num_trasteros", 0), 95)
        self.assertEqual(server.row_value(fila, "num_aparcamientos", 0), 115)

    def test_la_cuota_va_sin_iva(self):
        """La ficha y el panel suman cuotas base; con el IVA dentro, la cartera
        saldría un 21 % más alta de lo que es."""
        self.alta(subtotal=670.0)
        fila = self.comunidades()[0]
        self.assertAlmostEqual(float(server.row_value(fila, "cuota_mensual", 0)), 670.0, places=2)
        self.assertAlmostEqual(float(server.row_value(fila, "cuota_sugerida", 0)), 670.0, places=2)

    def test_nace_activa_y_con_su_empresa(self):
        self.alta()
        fila = self.comunidades()[0]
        self.assertEqual(server.row_value(fila, "estado", ""), "Activa")
        self.assertEqual(server.row_value(fila, "empresa_id", ""), "emp1")

    def test_el_solicitante_se_guarda_como_presidente(self):
        """Suele serlo. «Suele» no es «es», así que se deja donde se pueda corregir."""
        self.alta()
        self.assertEqual(server.row_value(self.comunidades()[0], "presidente", ""), "Quien pidió el presupuesto")


class NoSeCreaDosVecesTests(BaseTests):
    def test_volver_a_guardar_no_crea_otra(self):
        """Es el mismo fallo que acabamos de arreglar en los presupuestos."""
        primero, _ = self.alta()
        segundo, creada = self.alta({"comunidad_id": primero})
        self.assertEqual(segundo, primero)
        self.assertFalse(creada)
        self.assertEqual(len(self.comunidades()), 1)

    def test_se_reconoce_por_la_referencia_catastral(self):
        """Aunque el nombre esté escrito distinto: el catastro es lo que identifica
        un edificio sin ambigüedad."""
        primero, _ = self.alta()
        segundo, creada = self.alta({"comunidad_denominacion": "CP ROCIO JURADO"})
        self.assertEqual(segundo, primero)
        self.assertFalse(creada)

    def test_se_reconoce_por_el_nombre_sin_catastro(self):
        primero, _ = self.alta({"referencia_catastral": ""})
        segundo, creada = self.alta({"referencia_catastral": ""})
        self.assertEqual(segundo, primero)
        self.assertFalse(creada)

    def test_el_nombre_se_compara_normalizado(self):
        """«C.P. ROCÍO JURADO 18» y «cp rocio jurado 18» son la misma finca."""
        primero, _ = self.alta({"referencia_catastral": "", "comunidad_denominacion": "C.P. Rocío Jurado 18"})
        segundo, creada = self.alta({"referencia_catastral": "", "comunidad_denominacion": "CP ROCIO JURADO 18"})
        self.assertEqual(segundo, primero)
        self.assertFalse(creada)

    def test_dos_comunidades_distintas_siguen_siendo_dos(self):
        self.alta()
        otra, creada = self.alta({"comunidad_denominacion": "C.P Maria Manrique 4",
                                  "referencia_catastral": "0000000AA0000A"})
        self.assertTrue(creada)
        self.assertEqual(len(self.comunidades()), 2)
        self.assertNotEqual(otra, "")

    def test_un_id_que_ya_no_existe_no_bloquea_el_alta(self):
        """Si borraron la comunidad, aceptar otra vez tiene que volver a crearla."""
        _id, creada = self.alta({"comunidad_id": "yanoexiste", "referencia_catastral": "", })
        self.assertTrue(creada)

    def test_la_comunidad_de_otro_workspace_no_cuenta(self):
        primero, _ = self.alta(workspace_id="ws1")
        segundo, creada = self.alta(workspace_id="ws2")
        self.assertNotEqual(segundo, primero)
        self.assertTrue(creada)


class SinDatosNoSeInventaNadaTests(BaseTests):
    def test_sin_nombre_ni_catastro_no_se_crea(self):
        _id, creada = self.alta({"comunidad_denominacion": "", "referencia_catastral": ""})
        self.assertFalse(creada)
        self.assertEqual(len(self.comunidades()), 0)

    def test_sin_workspace_no_se_crea(self):
        self.assertEqual(server.alta_comunidad_desde_presupuesto(self.conn, "", "emp1", CALC), ("", False))

    def test_con_calc_que_no_es_un_diccionario_no_revienta(self):
        self.assertEqual(server.alta_comunidad_desde_presupuesto(self.conn, "ws1", "emp1", None), ("", False))

    def test_solo_con_catastro_se_crea_con_un_nombre_util(self):
        _id, creada = self.alta({"comunidad_denominacion": ""})
        self.assertTrue(creada)
        self.assertIn("6968701UF6666N", server.row_value(self.comunidades()[0], "nombre", ""))


class DondeSeEngranaTests(unittest.TestCase):
    def handler(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_presupuestos"')
        return SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]

    def test_solo_al_aceptar(self):
        cuerpo = self.handler()
        i = cuerpo.index('elif estado == "Aceptado":')
        siguiente = cuerpo.index("            else:", i)
        self.assertIn("alta_comunidad_desde_presupuesto", cuerpo[i:siguiente])

    def test_no_al_rechazar_ni_en_borrador(self):
        cuerpo = self.handler()
        rechazo = cuerpo[cuerpo.index('if estado in {"Estudio", "Rechazado"}:'): cuerpo.index('elif estado == "Aceptado":')]
        self.assertNotIn("alta_comunidad_desde_presupuesto", rechazo)

    def test_solo_para_fincas(self):
        """Aceptar un presupuesto de gestoría no puede crear una comunidad."""
        cuerpo = self.handler()
        i = cuerpo.index("alta_comunidad_desde_presupuesto")
        self.assertIn("if servicio_es_fincas:", cuerpo[i - 300: i])

    def test_el_presupuesto_se_queda_apuntando_a_la_comunidad(self):
        """Es lo que hace que volver a guardarlo no cree otra."""
        cuerpo = self.handler()
        i = cuerpo.index("alta_comunidad_desde_presupuesto")
        trozo = cuerpo[i: i + 900]
        self.assertIn('calculo["comunidad_id"] = comunidad_id', trozo)
        self.assertIn("UPDATE workspace_presupuestos SET calculo_json = ?", trozo)

    def test_un_fallo_del_alta_no_tumba_la_aceptacion(self):
        """El estado y su tarea ya están guardados: perderlos por esto sería peor."""
        cuerpo = self.handler()
        i = cuerpo.index("alta_comunidad_desde_presupuesto")
        self.assertIn("except Exception:", cuerpo[i: i + 900])

    def test_la_cuota_que_se_pasa_es_la_base(self):
        cuerpo = self.handler()
        i = cuerpo.index("alta_comunidad_desde_presupuesto")
        self.assertIn("subtotal=subtotal", cuerpo[i: i + 400])


if __name__ == "__main__":
    unittest.main()


class LaClaveDelNombreTests(unittest.TestCase):
    """`normalize_lookup_text` deja «C.P.» como «C P», con un espacio de más.

    En fincas esa es la variante que más se da: en la base de producción hay
    «C.P ASTREA 3» y «C.P Maria Manrique 4» escritas así. Comparando con la
    normalización a secas, aceptar dos veces la misma finca escrita «C.P.» y «CP»
    habría creado dos comunidades.
    """

    def test_con_puntos_y_sin_puntos_es_la_misma(self):
        self.assertEqual(server.clave_comunidad("C.P. Rocío Jurado 18"),
                         server.clave_comunidad("CP ROCIO JURADO 18"))

    def test_las_tildes_y_las_mayusculas_dan_igual(self):
        self.assertEqual(server.clave_comunidad("Comunidad de Propietarios Rocío Jurado"),
                         server.clave_comunidad("COMUNIDAD DE PROPIETARIOS ROCIO JURADO"))

    def test_dos_fincas_distintas_no_se_confunden(self):
        self.assertNotEqual(server.clave_comunidad("C.P Maria Manrique 4"),
                            server.clave_comunidad("C.P Maria Manrique 6"))

    def test_vacio_da_vacio(self):
        self.assertEqual(server.clave_comunidad(""), "")
        self.assertEqual(server.clave_comunidad(None), "")

    def test_un_nombre_vacio_no_casa_con_otro_vacio(self):
        """Si no, una comunidad sin nombre absorbería a la siguiente sin nombre."""
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        calc = {"referencia_catastral": "AAA", "comunidad_denominacion": ""}
        primero, _ = server.alta_comunidad_desde_presupuesto(conn, "ws1", "e", calc)
        otra, creada = server.alta_comunidad_desde_presupuesto(
            conn, "ws1", "e", {"referencia_catastral": "BBB", "comunidad_denominacion": ""})
        self.assertTrue(creada)
        self.assertNotEqual(otra, primero)
