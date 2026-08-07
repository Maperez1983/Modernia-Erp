"""Juntas: asistencia, votación por doble medida y acta.

Es donde un programa de fincas se gana el sueldo y donde más se equivoca la gente
contando a mano, porque un acuerdo no se mide por una cosa sino por dos: cuántos
propietarios votan a favor **y** qué coeficiente suman. El caso que este test fija:

    10 propietarios. Seis pequeños al 5 % y cuatro grandes al 17,5 %.
    Los seis pequeños votan a favor de instalar el ascensor.

Por cabezas es el 60 % —parecería aprobado por tres quintos—, pero solo suman el
30 % del coeficiente. No está aprobado. Enseñar una sola de las dos medidas es la
forma de dar por bueno un acuerdo impugnable.

**Las mayorías vienen precargadas de la LPH, con su artículo al lado.** La primera
versión las dejaba en blanco por prudencia y era prudencia mal entendida: el artículo
17 es un texto publicado, no una opinión. Van sembradas y **editables**, cada una con
el artículo del que sale, para que se pueda comprobar de un vistazo y corregir cuando
la ley cambie sin depender de la memoria de nadie. Lo que sigue siendo un juicio del
administrador es **clasificar el punto**: que una obra sea «mejora no necesaria» o
«servicio común de interés general» no lo decide una lista.

El quórum no se dictamina: se dan las cifras de asistencia y quien preside decide.
Ver también `test_mayorias_de_la_lph.py`.
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

try:
    from pypdf import PdfReader

    HAY_PYPDF = True
except Exception:  # pragma: no cover
    HAY_PYPDF = False


class JuntaDePrueba(unittest.TestCase):
    #: Seis pequeños al 5 % y cuatro grandes al 17,5 %: suman 100.
    COEFICIENTES = [5, 5, 5, 5, 5, 5, 17.5, 17.5, 17.5, 17.5]

    def setUp(self):
        self.conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(self.conn)
        self.ahora = datetime.datetime.now().isoformat(timespec="seconds")
        self.ws, self.com, self.junta = "ws1", "com1", "j1"
        self.conn.execute(
            "INSERT INTO workspace_fincas_comunidades (id, workspace_id, nombre, direccion, estado, "
            "created_at, updated_at) VALUES (?,?,?,?,'Activa',datetime(?),datetime(?))",
            (self.com, self.ws, "C.P. Velázquez 11", "Avenida Velázquez 11", self.ahora, self.ahora),
        )
        self.conn.execute(
            "INSERT INTO workspace_fincas_juntas (id, workspace_id, comunidad_id, fecha, tipo, estado, "
            "created_at, updated_at) VALUES (?,?,?,'2026-09-15','Ordinaria','Celebrada',datetime(?),datetime(?))",
            (self.junta, self.ws, self.com, self.ahora, self.ahora),
        )
        for i, coef in enumerate(self.COEFICIENTES):
            self.conn.execute(
                "INSERT INTO workspace_fincas_vecinos (id, workspace_id, comunidad_id, nombre, piso, "
                "coeficiente, created_at, updated_at) VALUES (?,?,?,?,?,?,datetime(?),datetime(?))",
                (f"v{i}", self.ws, self.com, f"Propietario {i + 1}", f"{i // 2 + 1}{'AB'[i % 2]}",
                 coef, self.ahora, self.ahora),
            )
        self.conn.commit()

    def asisten(self, indices, representados=()):
        for i in indices:
            self.conn.execute(
                "INSERT INTO workspace_fincas_junta_asistentes (id, workspace_id, junta_id, vecino_id, "
                "asiste, representado_por, created_at, updated_at) VALUES (?,?,?,?,1,?,datetime(?),datetime(?))",
                (f"a{i}", self.ws, self.junta, f"v{i}",
                 "Propietario 1" if i in representados else None, self.ahora, self.ahora),
            )
        self.conn.commit()

    def acuerdo(self, acuerdo_id, titulo, mayoria=None, orden=1):
        self.conn.execute(
            "INSERT INTO workspace_fincas_junta_acuerdos (id, workspace_id, junta_id, orden, titulo, "
            "mayoria_clave, created_at, updated_at) VALUES (?,?,?,?,?,?,datetime(?),datetime(?))",
            (acuerdo_id, self.ws, self.junta, orden, titulo, mayoria, self.ahora, self.ahora),
        )
        self.conn.commit()

    def votan(self, acuerdo_id, indices, voto="Favor"):
        for i in indices:
            self.conn.execute(
                "INSERT INTO workspace_fincas_junta_votos (id, workspace_id, acuerdo_id, vecino_id, voto, "
                "created_at, updated_at) VALUES (?,?,?,?,?,datetime(?),datetime(?))",
                (os.urandom(8).hex(), self.ws, acuerdo_id, f"v{i}", voto, self.ahora, self.ahora),
            )
        self.conn.commit()

    def recuento(self):
        return server.calcular_recuento_junta(self.conn, self.ws, self.junta)


class LaAsistenciaSeCuentaDeLasDosFormasTests(JuntaDePrueba):
    def test_seis_pequenos_son_mayoria_de_cabezas_y_minoria_de_coeficiente(self):
        self.asisten(range(6))
        a = self.recuento()["asistencia"]
        self.assertEqual(a["asistentes"], 6)
        self.assertEqual(a["asistentes_pct_propietarios"], 60.0)
        self.assertEqual(a["asistentes_pct_coeficiente"], 30.0)

    def test_los_representados_cuentan_pero_se_distinguen(self):
        self.asisten(range(8), representados=(7,))
        a = self.recuento()["asistencia"]
        self.assertEqual(a["asistentes"], 8)
        self.assertEqual(a["presentes"], 7)
        self.assertEqual(a["representados"], 1)

    def test_quien_no_asiste_no_cuenta(self):
        self.asisten([0, 1])
        self.assertEqual(self.recuento()["asistencia"]["asistentes"], 2)

    def test_no_se_dictamina_el_quorum(self):
        """Poner un umbral inventado sería peor que no poner ninguno."""
        self.asisten(range(6))
        self.assertNotIn("quorum", self.recuento()["asistencia"])


class ElAcuerdoSeMideConLasDosMedidasTests(JuntaDePrueba):
    def test_el_caso_del_ascensor(self):
        """60 % de cabezas y 30 % de coeficiente no son tres quintos."""
        self.asisten(range(6))
        self.acuerdo("ac1", "Instalación de ascensor", "tres_quintos")
        self.votan("ac1", range(6))
        ac = self.recuento()["acuerdos"][0]
        self.assertEqual(ac["favor_propietarios"], 60.0)
        self.assertEqual(ac["favor_coeficiente"], 30.0)
        self.assertFalse(ac["aprobado"])

    def test_cuando_alcanza_por_las_dos_si_se_aprueba(self):
        self.asisten(range(10))
        self.acuerdo("ac1", "Aprobación de cuentas", "mayoria_simple")
        self.votan("ac1", range(8))  # 80 % de cabezas y 65 % de coeficiente
        ac = self.recuento()["acuerdos"][0]
        self.assertTrue(ac["aprobado"])

    def test_el_porcentaje_es_sobre_toda_la_comunidad_no_sobre_los_que_votan(self):
        """Si no, una junta de cuatro gatos aprobaría cualquier cosa por unanimidad."""
        self.asisten([0, 1])
        self.acuerdo("ac1", "Lo que sea", "unanimidad")
        self.votan("ac1", [0, 1])
        ac = self.recuento()["acuerdos"][0]
        self.assertEqual(ac["favor_propietarios"], 20.0)
        self.assertFalse(ac["aprobado"])

    def test_sin_mayoria_elegida_no_se_dictamina(self):
        self.asisten(range(10))
        self.acuerdo("ac1", "Ruegos y preguntas")
        self.votan("ac1", range(10))
        self.assertIsNone(self.recuento()["acuerdos"][0]["aprobado"])

    def test_los_contrarios_y_las_abstenciones_se_cuentan_aparte(self):
        self.asisten(range(10))
        self.acuerdo("ac1", "Derrama", "mayoria_simple")
        self.votan("ac1", [0, 1, 2], "Favor")
        self.votan("ac1", [3, 4], "Contra")
        self.votan("ac1", [5], "Abstencion")
        ac = self.recuento()["acuerdos"][0]
        self.assertEqual((ac["favor"], ac["contra"], ac["abstencion"]), (3, 2, 1))

    def test_la_mayoria_simple_exige_superar_la_mitad_no_igualarla(self):
        self.asisten(range(10))
        self.acuerdo("ac1", "Empate", "mayoria_simple")
        # Cinco grandes/pequeños que suman exactamente el 50 % de coeficiente.
        self.votan("ac1", [6, 7, 0, 1, 2])  # 17,5*2 + 5*3 = 50 %
        ac = self.recuento()["acuerdos"][0]
        self.assertEqual(ac["favor_coeficiente"], 50.0)
        self.assertFalse(ac["aprobado"])


class LasMayoriasSonConfigurablesTests(unittest.TestCase):
    def test_solo_se_siembra_la_aritmetica_de_cada_fraccion(self):
        porcentajes = {m["clave"]: m["porcentaje"] for m in server.FINCAS_MAYORIAS_DEFECTO}
        self.assertEqual(porcentajes["unanimidad"], 100.0)
        self.assertEqual(porcentajes["tres_quintos"], 60.0)
        self.assertEqual(porcentajes["mayoria_simple"], 50.0)
        self.assertAlmostEqual(porcentajes["un_tercio"], 100 / 3, places=4)

    def test_la_mayoria_simple_es_estricta(self):
        simple = next(m for m in server.FINCAS_MAYORIAS_DEFECTO if m["clave"] == "mayoria_simple")
        self.assertEqual(simple["estricta"], 1)

    def test_cada_mayoria_dice_de_que_articulo_sale(self):
        """Sin el artículo al lado, el porcentaje hay que creérselo."""
        for item in server.FINCAS_MAYORIAS_DEFECTO:
            with self.subTest(clave=item["clave"]):
                self.assertTrue(item.get("articulo", "").startswith("LPH art."))

    def test_se_pueden_editar(self):
        self.assertIn('elif parsed.path in ("/api/workspace_fincas_junta_asistencia"', SERVER)
        self.assertIn('"/api/workspace_fincas_mayorias",', SERVER)


@unittest.skipUnless(HAY_PYPDF, "hace falta pypdf")
class ElActaTests(JuntaDePrueba):
    def acta(self):
        self.asisten(range(8), representados=(7,))
        self.acuerdo("ac1", "Aprobación de las cuentas", "mayoria_simple", orden=1)
        self.votan("ac1", range(8))
        self.acuerdo("ac2", "Instalación de ascensor", "tres_quintos", orden=2)
        self.votan("ac2", range(6))
        self.acuerdo("ac3", "Ruegos y preguntas", None, orden=3)
        recuento = self.recuento()
        comunidad = self.conn.execute(
            "SELECT * FROM workspace_fincas_comunidades WHERE id=?", (self.com,)
        ).fetchone()
        import io

        pdf = server.build_acta_junta_pdf(recuento, comunidad, workspace={"primary_color": "#3C6E71"},
                                          company={"nombre": "Estudio Velazquez"})
        return pdf, "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)

    def test_es_texto_no_una_imagen(self):
        import io

        pdf, _t = self.acta()
        for pagina in PdfReader(io.BytesIO(pdf)).pages:
            self.assertTrue(list((pagina.get("/Resources", {}) or {}).get("/Font") or {}))

    def test_recoge_la_asistencia_y_quien_representa(self):
        _pdf, texto = self.acta()
        self.assertIn("8 de 10", texto)
        self.assertIn("Propietario 1", texto)

    def test_dice_el_resultado_de_cada_punto(self):
        _pdf, texto = self.acta()
        self.assertIn("APROBADO", texto)
        self.assertIn("NO APROBADO", texto)
        self.assertIn("Sin mayoría asignada", texto)

    def test_da_las_dos_medidas_en_cada_acuerdo(self):
        _pdf, texto = self.acta()
        self.assertIn("de los propietarios", texto)
        self.assertIn("de los coeficientes", texto)

    def test_sale_sin_firmar(self):
        _pdf, texto = self.acta()
        self.assertIn("secretario administrador", texto)
        self.assertIn("presidente", texto)

    def test_los_dos_cargos_no_salen_pegados(self):
        """El motor junta los espacios múltiples: se apilan en líneas distintas."""
        _pdf, texto = self.acta()
        self.assertNotIn("administrador V.º B.º", texto)


class LosEndpointsEstanGuardadosTests(unittest.TestCase):
    def test_las_escrituras_exigen_pertenencia(self):
        i = SERVER.index('elif parsed.path in ("/api/workspace_fincas_junta_asistencia"')
        cuerpo = SERVER[i: i + 1200]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_los_get_tambien(self):
        for ruta in ("/api/workspace_fincas_junta", "/api/workspace_fincas_acta", "/api/workspace_fincas_mayorias"):
            with self.subTest(ruta=ruta):
                i = SERVER.index(f'if path == "{ruta}"')
                self.assertIn("enforce_workspace_membership", SERVER[i: i + 1600])

    def test_un_voto_solo_entra_en_un_acuerdo_del_workspace(self):
        i = SERVER.index('if parsed.path == "/api/workspace_fincas_junta_voto"')
        cuerpo = SERVER[i: i + 1800]
        self.assertIn("WHERE id = ? AND workspace_id = ?", cuerpo)

    def test_la_pantalla_dice_que_el_quorum_lo_decide_quien_preside(self):
        self.assertIn("El quórum lo decide quien preside", APP)


if __name__ == "__main__":
    unittest.main()
