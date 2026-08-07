"""Las mayorías de la Ley de Propiedad Horizontal, precargadas y comprobables.

La primera versión de las juntas dejaba los porcentajes en blanco «para no inventar
derecho». El usuario lo discutió el 2026-08-07 y tenía razón: el artículo 17 de la
LPH es un texto publicado, no una opinión, y dejarlo vacío no protegía de nada —solo
obligaba a poner a mano en cada junta algo que está escrito—.

Así que van sembrados, pero con dos condiciones que este fichero fija:

1. **Cada mayoría y cada tipo de acuerdo llevan su artículo al lado.** Sin él, el
   porcentaje hay que creérselo; con él se comprueba en treinta segundos y se sabe
   qué mirar cuando la ley cambie.
2. **Todo es editable.** Son valores de partida, no una verdad clavada en el código.

Lo que sigue sin decidirse aquí, y no por prudencia sino porque de verdad no es
mecánico:

- **Clasificar el punto del orden del día.** Que una obra concreta sea «mejora no
  necesaria» (17.4) o «servicio común de interés general» (17.3) es un juicio del
  administrador. La lista propone; no decide.
- **El quórum.** Se dan las cifras y quien preside decide.

Y una advertencia que va escrita en los propios datos: el apartado del alquiler
turístico (17.12) se ha reformado más de una vez, así que se siembra marcado como
«VERIFICAR». Esto es LPH: Cataluña, Navarra, Aragón y Baleares tienen régimen civil
propio con mayorías distintas.
"""

import datetime
import os
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
os.environ.pop("DATABASE_URL", None)
from web import server  # noqa: E402


class LasFraccionesSonLasQueSonTests(unittest.TestCase):
    def test_la_aritmetica_de_cada_fraccion(self):
        porcentajes = {m["clave"]: m["porcentaje"] for m in server.FINCAS_MAYORIAS_DEFECTO}
        self.assertEqual(porcentajes["unanimidad"], 100.0)
        self.assertEqual(porcentajes["tres_quintos"], 60.0)
        self.assertEqual(porcentajes["mayoria_simple"], 50.0)
        self.assertAlmostEqual(porcentajes["un_tercio"], 100 / 3, places=4)

    def test_la_mayoria_simple_hay_que_superarla_no_igualarla(self):
        simple = next(m for m in server.FINCAS_MAYORIAS_DEFECTO if m["clave"] == "mayoria_simple")
        self.assertEqual(simple["estricta"], 1)

    def test_cada_una_dice_su_articulo(self):
        for item in server.FINCAS_MAYORIAS_DEFECTO:
            with self.subTest(clave=item["clave"]):
                self.assertTrue(item.get("articulo", "").startswith("LPH art."))


class ElCatalogoDeAcuerdosTests(unittest.TestCase):
    def catalogo(self):
        return {t["clave"]: t for t in server.FINCAS_TIPOS_ACUERDO_DEFECTO}

    def test_las_asignaciones_del_articulo_17(self):
        """Cada tipo con la mayoría que le asigna la ley y el apartado del que sale."""
        esperado = {
            "ordinario": ("mayoria_simple", "LPH art. 17.7"),
            "titulo_estatutos": ("unanimidad", "LPH art. 17.6"),
            "servicios_comunes": ("tres_quintos", "LPH art. 17.3"),
            "arrendar_comunes": ("tres_quintos", "LPH art. 17.3"),
            "mejoras_no_necesarias": ("tres_quintos", "LPH art. 17.4"),
            "alquiler_turistico": ("tres_quintos", "LPH art. 17.12"),
            "energias_telecom": ("un_tercio", "LPH art. 17.1"),
            "accesibilidad": ("mayoria_simple", "LPH art. 17.2"),
        }
        catalogo = self.catalogo()
        for clave, (mayoria, articulo) in esperado.items():
            with self.subTest(clave=clave):
                self.assertEqual(catalogo[clave]["mayoria_clave"], mayoria)
                self.assertEqual(catalogo[clave]["articulo"], articulo)

    def test_la_recarga_electrica_no_necesita_acuerdo(self):
        """Basta comunicación previa (17.5): no hay que llevarlo a votación."""
        recarga = self.catalogo()["recarga_electrica"]
        self.assertEqual(recarga["mayoria_clave"], "")
        self.assertIn("comunicación previa", recarga["nota"])

    def test_todas_las_mayorias_citadas_existen(self):
        """Un tipo apuntando a una mayoría inexistente dejaría el punto sin dictaminar."""
        claves = {m["clave"] for m in server.FINCAS_MAYORIAS_DEFECTO} | {""}
        for tipo in server.FINCAS_TIPOS_ACUERDO_DEFECTO:
            with self.subTest(clave=tipo["clave"]):
                self.assertIn(tipo.get("mayoria_clave", ""), claves)

    def test_el_alquiler_turistico_va_marcado_para_verificar(self):
        """Es el apartado que más se ha movido; no se da por bueno sin comprobar."""
        self.assertIn("VERIFICAR", self.catalogo()["alquiler_turistico"]["nota"])

    def test_la_letra_pequena_que_cambia_quien_paga(self):
        catalogo = self.catalogo()
        self.assertIn("quienes lo solicitan", catalogo["energias_telecom"]["nota"])
        self.assertIn("tres mensualidades", catalogo["mejoras_no_necesarias"]["nota"])

    def test_avisa_de_que_accesibilidad_puede_no_necesitar_acuerdo(self):
        self.assertIn("10.1.b", catalogo_nota := self.catalogo()["accesibilidad"]["nota"])
        self.assertIn("no necesitan acuerdo", catalogo_nota)

    def test_esta_escrito_que_hay_regimenes_forales(self):
        i = SERVER.index("FINCAS_TIPOS_ACUERDO_DEFECTO = [")
        cabecera = SERVER[max(0, i - 1800): i]
        for territorio in ("Cataluña", "Navarra"):
            with self.subTest(territorio=territorio):
                self.assertIn(territorio, cabecera)


class ElFondoDeReservaTests(unittest.TestCase):
    def test_el_minimo_legal_esta_puesto(self):
        self.assertEqual(server.FINCAS_FONDO_RESERVA_MINIMO, 10.0)

    def test_se_usa_cuando_no_se_indica_otro(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_presupuesto_anual"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("or FINCAS_FONDO_RESERVA_MINIMO", cuerpo)

    def test_sigue_siendo_editable(self):
        """Es un mínimo: la junta puede acordar uno mayor."""
        i = SERVER.index("FINCAS_FONDO_RESERVA_MINIMO")
        self.assertIn("mínimo", SERVER[max(0, i - 300): i + 80])


class LaSegundaConvocatoriaCambiaElDenominadorTests(unittest.TestCase):
    """Es lo que más se cuenta mal a mano: el mismo voto sale aprobado o no."""

    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com, self.junta = "ws1", "com1", "j1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, estado, created_at, updated_at) "
            "VALUES (?,?,?,'Activa',datetime(?),datetime(?))", (self.com, self.ws, "C.P. X", ahora, ahora))
        self.conn.execute(
            "INSERT INTO workspace_fincas_juntas (id, workspace_id, comunidad_id, fecha, tipo, estado, "
            "segunda_convocatoria, created_at, updated_at) "
            "VALUES (?,?,?,'2026-09-15','Ordinaria','Celebrada',0,datetime(?),datetime(?))",
            (self.junta, self.ws, self.com, ahora, ahora))
        for i in range(10):  # diez propietarios al 10 % cada uno
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,10,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"P{i}", f"{i}A", ahora, ahora))
        for i in range(6):  # asisten seis
            self.conn.execute(
                "INSERT INTO workspace_fincas_junta_asistentes (id, workspace_id, junta_id, vecino_id, asiste, "
                "created_at, updated_at) VALUES (?,?,?,?,1,datetime(?),datetime(?))",
                (f"a{i}", self.ws, self.junta, f"v{i}", ahora, ahora))
        self.conn.execute(
            "INSERT INTO workspace_fincas_junta_acuerdos (id, workspace_id, junta_id, orden, titulo, "
            "mayoria_clave, created_at, updated_at) "
            "VALUES ('ac1',?,?,1,'Aprobar las cuentas','mayoria_simple',datetime(?),datetime(?))",
            (self.ws, self.junta, ahora, ahora))
        for i in range(4):  # votan a favor cuatro
            self.conn.execute(
                "INSERT INTO workspace_fincas_junta_votos (id, workspace_id, acuerdo_id, vecino_id, voto, "
                "created_at, updated_at) VALUES (?,?,'ac1',?,'Favor',datetime(?),datetime(?))",
                (f"x{i}", self.ws, f"v{i}", ahora, ahora))
        self.conn.commit()

    def acuerdo(self, segunda):
        self.conn.execute("UPDATE workspace_fincas_juntas SET segunda_convocatoria = ? WHERE id = ?",
                          (1 if segunda else 0, self.junta))
        self.conn.commit()
        return server.calcular_recuento_junta(self.conn, self.ws, self.junta)["acuerdos"][0]

    def test_en_primera_se_cuenta_sobre_toda_la_comunidad(self):
        ac = self.acuerdo(segunda=False)
        self.assertEqual(ac["favor_propietarios"], 40.0)
        self.assertEqual(ac["sobre"], "toda la comunidad")
        self.assertFalse(ac["aprobado"])

    def test_en_segunda_se_cuenta_sobre_los_asistentes(self):
        ac = self.acuerdo(segunda=True)
        self.assertAlmostEqual(ac["favor_propietarios"], 66.67, places=1)
        self.assertEqual(ac["sobre"], "los asistentes")
        self.assertTrue(ac["aprobado"])

    def test_la_asistencia_se_mide_siempre_sobre_el_total(self):
        """Medirla sobre sí misma daría siempre 100 % y no diría nada."""
        for segunda in (False, True):
            with self.subTest(segunda=segunda):
                self.conn.execute("UPDATE workspace_fincas_juntas SET segunda_convocatoria = ? WHERE id = ?",
                                  (1 if segunda else 0, self.junta))
                self.conn.commit()
                a = server.calcular_recuento_junta(self.conn, self.ws, self.junta)["asistencia"]
                self.assertEqual(a["asistentes_pct_propietarios"], 60.0)

    def test_el_recuento_dice_en_que_convocatoria_esta(self):
        self.assertTrue(
            server.calcular_recuento_junta(self.conn, self.ws, self.junta)["asistencia"]["segunda_convocatoria"]
            is False
        )

    def test_el_acta_lo_deja_escrito(self):
        i = SERVER.index("def build_acta_junta_pdf")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("segunda convocatoria", cuerpo)
        self.assertIn("LPH art. 17.7", cuerpo)


class LaPantallaLoEnsenaTests(unittest.TestCase):
    def test_el_tipo_de_acuerdo_se_elige_y_preselecciona_la_mayoria(self):
        self.assertIn('name="tipo_acuerdo"', APP)
        i = SERVER.index('if parsed.path == "/api/workspace_fincas_junta_acuerdo"')
        cuerpo = SERVER[i: i + 3000]
        self.assertIn('payload.get("tipo_acuerdo")', cuerpo)
        self.assertIn("if tipo_clave and not mayoria_clave", cuerpo)

    def test_la_mayoria_elegida_a_mano_manda_sobre_el_tipo(self):
        """El administrador puede discrepar de cómo se clasifica el punto."""
        i = SERVER.index('if parsed.path == "/api/workspace_fincas_junta_acuerdo"')
        self.assertIn("if tipo_clave and not mayoria_clave", SERVER[i: i + 3000])

    def test_se_ve_el_articulo_en_pantalla(self):
        self.assertIn("Según ${escapeHtml(ac.articulo)}", APP)

    def test_hay_casilla_de_segunda_convocatoria(self):
        self.assertIn("data-segunda", APP)
        self.assertIn("LPH art. 17.7", APP)

    def test_la_nota_del_tipo_se_ensena(self):
        self.assertIn("data-tipo-nota", APP)

    def test_el_endpoint_de_convocatoria_esta_guardado(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_junta_convocatoria"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)
        self.assertIn('"/api/workspace_fincas_junta_convocatoria",', SERVER)


if __name__ == "__main__":
    unittest.main()
