"""La carta que acompaña al presupuesto, hecha con los datos de la comunidad.

El campo `carta_presentacion` existía desde siempre y **estaba vacío en los diez
presupuestos guardados**: nadie lo había usado nunca. El texto que salía en el PDF
estaba escrito a fuego dentro del motor de imagen, así que no se podía cambiar sin un
despliegue y no se podía adaptar a cada comunidad.

Ahora hay plantillas editables, se rellenan con lo que hay tecleado en pantalla y el
resultado se puede reescribir antes de enviar.

Dos decisiones que estos tests fijan:

- **Una frase con un hueco sin resolver se cae entera.** Es preferible una carta más
  corta que una que diga «su comunidad de {viviendas} viviendas». Esto se le manda a
  un presidente de comunidad, no es un borrador interno.
- **Generar no pisa lo escrito sin preguntar.** Si ya hay una carta redactada, se
  pide confirmación: reescribir encima sería tirar el trabajo hecho.

Sobre el contenido: la plantilla «general» es el texto que ya usaba la casa, rescatado
del motor viejo, con sus afirmaciones sobre el despacho —los años, los servicios—, que
son suyas. Las otras dos no añaden ninguna afirmación nueva de ese tipo a propósito:
describen lo que el presupuesto trae detrás y poco más.
"""

import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

DATOS = {
    "comunidad": "C.P. Velázquez 11",
    "direccion": "Avenida de Velázquez 11, Málaga",
    "viviendas": "24",
    "unidades": "24 viviendas y 30 trasteros",
    "cuota": "181,50 €",
    "empresa": "Fincas Velázquez",
    "colegiado": "3079",
}


class LosHuecosSeRellenanOLaFraseSeCaeTests(unittest.TestCase):
    def test_rellena_lo_que_puede(self):
        salida = server.render_carta_presentacion("Propuesta para {comunidad}.", DATOS)
        self.assertEqual(salida, "Propuesta para C.P. Velázquez 11.")

    def test_una_frase_con_un_hueco_sin_dato_no_sale(self):
        """Antes que «su comunidad de {viviendas} viviendas», mejor no decirlo."""
        salida = server.render_carta_presentacion(
            "Hola.\nSu comunidad de {viviendas} viviendas.\nAdiós.", dict(DATOS, viviendas=""))
        self.assertEqual(salida, "Hola.\nAdiós.")

    def test_no_quedan_llaves_en_el_resultado(self):
        for plantilla in server.FINCAS_CARTAS_DEFECTO:
            with self.subTest(clave=plantilla["clave"]):
                salida = server.render_carta_presentacion(plantilla["cuerpo"], DATOS)
                self.assertNotIn("{", salida)
                self.assertNotIn("}", salida)

    def test_con_todo_vacio_no_revienta(self):
        vacio = {k: "" for k in DATOS}
        for plantilla in server.FINCAS_CARTAS_DEFECTO:
            with self.subTest(clave=plantilla["clave"]):
                salida = server.render_carta_presentacion(plantilla["cuerpo"], vacio)
                self.assertNotIn("{", salida)

    def test_las_lineas_en_blanco_no_se_arrastran(self):
        self.assertEqual(server.render_carta_presentacion("Uno.\n\n\nDos.", DATOS), "Uno.\nDos.")

    def test_sin_plantilla_devuelve_vacio(self):
        self.assertEqual(server.render_carta_presentacion("", DATOS), "")
        self.assertEqual(server.render_carta_presentacion(None, DATOS), "")


class LasUnidadesSeCuentanEnCastellanoTests(unittest.TestCase):
    def test_singular_y_plural(self):
        self.assertEqual(server.describe_unidades_edificio({"num_vecinos": 1}), "1 vivienda")
        self.assertEqual(server.describe_unidades_edificio({"num_vecinos": 24}), "24 viviendas")
        self.assertEqual(server.describe_unidades_edificio({"num_locales": 1}), "1 local")

    def test_enumera_con_y_al_final(self):
        texto = server.describe_unidades_edificio(
            {"num_vecinos": 24, "num_locales": 1, "num_trasteros": 30, "num_aparcamientos": 12})
        self.assertEqual(texto, "24 viviendas, 1 local, 30 trasteros y 12 plazas de garaje")

    def test_lo_que_esta_a_cero_no_se_nombra(self):
        """«24 viviendas y 0 trasteros» no lo escribiría nadie."""
        texto = server.describe_unidades_edificio({"num_vecinos": 24, "num_locales": 0, "num_trasteros": 30})
        self.assertEqual(texto, "24 viviendas y 30 trasteros")

    def test_sin_unidades_devuelve_vacio(self):
        """Y con eso la frase que las mencionaba se cae sola."""
        self.assertEqual(server.describe_unidades_edificio({}), "")
        self.assertEqual(server.describe_unidades_edificio({"num_vecinos": 0}), "")


class LasTresPlantillasTests(unittest.TestCase):
    def claves(self):
        return [p["clave"] for p in server.FINCAS_CARTAS_DEFECTO]

    def test_cubren_los_casos_que_se_dan(self):
        self.assertEqual(self.claves(), ["general", "cambio_administrador", "obra_nueva"])

    def test_la_general_es_el_texto_que_ya_usaba_la_casa(self):
        """Estaba dentro del motor de imagen, no en la base: nadie podía tocarlo."""
        general = server.FINCAS_CARTAS_DEFECTO[0]["cuerpo"]
        self.assertIn("Nuestro objetivo es sencillo: tranquilidad para la comunidad", general)
        self.assertIn("despacho multidisciplinar", general)

    def test_las_otras_dos_no_inventan_afirmaciones_sobre_el_despacho(self):
        """Los años de experiencia y los premios los pone la casa, no yo."""
        for plantilla in server.FINCAS_CARTAS_DEFECTO[1:]:
            with self.subTest(clave=plantilla["clave"]):
                cuerpo = plantilla["cuerpo"].lower()
                for reclamo in ("años", "líderes", "los mejores", "premiad", "referente"):
                    self.assertNotIn(reclamo, cuerpo)

    def test_solo_prometen_lo_que_el_crm_hace(self):
        """El detalle de la cuota existe de verdad."""
        cambio = server.FINCAS_CARTAS_DEFECTO[1]["cuerpo"]
        self.assertIn("de dónde sale cada euro", cambio)

    def test_ninguna_explica_el_portal_a_parrafo(self):
        """Lo metí en las tres y el usuario lo cortó en seco: «eso no pinta nada en
        una carta de presentación». Tenía razón — una carta no es una ficha de
        producto. El portal existe y se sigue vendiendo, pero desde la lista de
        servicios incluidos, que es donde el cliente busca qué compra por su cuota."""
        for plantilla in server.FINCAS_CARTAS_DEFECTO:
            with self.subTest(clave=plantilla["clave"]):
                cuerpo = plantilla["cuerpo"]
                self.assertNotIn("enlace propio", cuerpo)
                self.assertNotIn("sin usuario ni contraseña", cuerpo)

    def test_el_portal_sigue_ofreciendose_donde_toca(self):
        self.assertIn("Portal del propietario", APP)
        i = APP.index("const FINCAS_SERVICIOS_DEFAULT")
        self.assertIn("Portal del propietario", APP[i: APP.index("];", i)])

    def test_lo_que_se_ofrece_del_portal_es_lo_que_hace(self):
        """Aunque ya no vaya en la carta, la lista de servicios lo promete: que sea
        verdad se comprueba igual. Cada pieza existe y está probada en
        `test_portal_del_propietario.py`: sin contraseña, solo lo suyo, caduca y se
        puede anular."""
        self.assertIn("FINCAS_PORTAL_DIAS_VALIDEZ", SERVER)
        self.assertIn("revocado", SERVER)
        i = SERVER.index("def fetch_fincas_portal_public")
        self.assertIn("Ningún otro propietario", SERVER[i: i + 1400])

    def test_todas_dicen_de_que_comunidad_hablan(self):
        for plantilla in server.FINCAS_CARTAS_DEFECTO:
            with self.subTest(clave=plantilla["clave"]):
                self.assertIn("{comunidad}", plantilla["cuerpo"])


class SeGuardanYSeEditanTests(unittest.TestCase):
    def test_se_siembran_en_la_base(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        items = server.fetch_workspace_fincas_cartas(conn, "ws1")
        self.assertEqual([c["clave"] for c in items], ["general", "cambio_administrador", "obra_nueva"])

    def test_no_se_siembran_dos_veces(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        server.fetch_workspace_fincas_cartas(conn, "ws1")
        server.fetch_workspace_fincas_cartas(conn, "ws1")
        self.assertEqual(len(server.fetch_workspace_fincas_cartas(conn, "ws1")), 3)

    def test_cada_workspace_tiene_las_suyas(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        server.fetch_workspace_fincas_cartas(conn, "ws1")
        conn.execute("UPDATE workspace_fincas_cartas SET cuerpo = 'mío' WHERE workspace_id = 'ws1'")
        conn.commit()
        otras = server.fetch_workspace_fincas_cartas(conn, "ws2")
        self.assertNotEqual(otras[0]["cuerpo"], "mío")

    def test_el_endpoint_exige_pertenencia_con_escritura(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_carta"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_el_get_de_plantillas_tambien_comprueba(self):
        i = SERVER.index('if path == "/api/workspace_fincas_cartas"')
        self.assertIn("enforce_workspace_membership", SERVER[i: i + 1200])


class LaPantallaTests(unittest.TestCase):
    def test_la_carta_tiene_su_propio_bloque(self):
        """Estaba enterrada junto a la foto del edificio."""
        self.assertIn('id="workspaceFincasBudgetCartaPanel"', HTML)
        self.assertIn("va en la primera página del PDF", HTML)

    def test_hay_selector_de_plantilla_y_boton(self):
        self.assertIn('id="workspaceFincasBudgetCartaPlantilla"', HTML)
        self.assertIn('id="workspaceFincasBudgetCartaGenerar"', HTML)

    def test_generar_no_pisa_lo_escrito_sin_preguntar(self):
        self.assertIn("Ya hay una carta escrita", APP)

    def test_se_compone_con_lo_que_hay_en_pantalla(self):
        """Se genera antes de crear el presupuesto, así que no vale lo guardado."""
        i = APP.index("const generarCartaDePresentacion")
        cuerpo = APP[i: i + 2000]
        self.assertIn('valor("comunidad_denominacion")', cuerpo)
        self.assertIn('valor("num_trasteros")', cuerpo)

    def test_las_plantillas_se_cargan_al_abrir_el_bloque(self):
        """No en cada carga de la pantalla: casi nunca se toca."""
        self.assertIn('addEventListener("toggle"', APP)
        self.assertIn("cargarPlantillasDeCarta", APP)

    def test_avisa_de_que_hay_que_revisarla(self):
        self.assertIn("Revísala antes de enviar", APP)


if __name__ == "__main__":
    unittest.main()
