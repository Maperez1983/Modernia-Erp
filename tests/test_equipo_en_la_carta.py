"""Quién va a llevar la comunidad, con nombre y cargo.

La carta hablaba de «un despacho multidisciplinar» y debajo salía una foto de grupo
sin pie: se veía a doce personas y no se sabía quién era ninguna. Ahora la carta
nombra al equipo y la foto pasa a tener sentido.

Los nombres van en **su propia tabla**, no escritos en el código. La razón es
práctica: las personas entran y salen de un despacho más a menudo de lo que se
cambia una plantilla, y no puede hacer falta un despliegue para quitar de la carta a
quien ya no está.

Dos decisiones que estos tests fijan:

- **El equipo se congela dentro del presupuesto.** Al generarlo se copia la lista al
  `calculo_json`. Si mañana alguien deja el despacho, el PDF que ya se envió tiene
  que seguir diciendo lo que decía el día que se mandó; un documento entregado no
  puede cambiar solo.
- **Guardar reemplaza la lista entera.** Con altas y bajas sueltas, quien se va se
  queda en la carta hasta que alguien se acuerda de borrarlo.

Sobre los datos: los nombres y los cargos son los que dio la casa, literales. No los
he retocado ni completado —ni las tildes ni los cargos— porque son personas reales.
"""

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
HTML = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

sys.path.insert(0, str(RAIZ))
from web import server  # noqa: E402

try:
    from pypdf import PdfReader

    LISTO = True
except Exception:  # pragma: no cover
    LISTO = False


class LaListaDePartidaTests(unittest.TestCase):
    def test_estan_los_cinco_que_dio_la_casa(self):
        nombres = [m["nombre"] for m in server.FINCAS_EQUIPO_DEFECTO]
        self.assertEqual(nombres, [
            "Miguel Ángel Pérez Rodríguez",
            "Daniel Gallardo Romero",
            "Barbara Salazar Oular",
            "Teresa Ramos Rueda",
            "Ana Portero Palma",
        ])

    def test_cada_uno_con_su_cargo(self):
        cargos = {m["nombre"]: m["cargo"] for m in server.FINCAS_EQUIPO_DEFECTO}
        self.assertEqual(cargos["Miguel Ángel Pérez Rodríguez"], "Administrador de Fincas")
        self.assertEqual(cargos["Daniel Gallardo Romero"], "Oficial Habilitado administración de fincas")
        self.assertEqual(cargos["Barbara Salazar Oular"], "Seguros")
        self.assertEqual(cargos["Teresa Ramos Rueda"], "Asesora Fiscal persona física")
        self.assertEqual(cargos["Ana Portero Palma"], "Abogada")

    def test_nadie_lleva_colegiado_inventado(self):
        """El 3079 que ya salía en el presupuesto no se le cuelga a nadie sin que
        alguien lo confirme: atribuir un número de colegiado es afirmar algo."""
        for miembro in server.FINCAS_EQUIPO_DEFECTO:
            with self.subTest(nombre=miembro["nombre"]):
                self.assertEqual(str(miembro.get("colegiado") or ""), "")


class ComoSeEscribeCadaUnoTests(unittest.TestCase):
    def test_nombre_y_cargo(self):
        self.assertEqual(
            server.describe_miembro_equipo({"nombre": "Ana Portero Palma", "cargo": "Abogada"}),
            "Ana Portero Palma — Abogada",
        )

    def test_con_numero_de_colegiado(self):
        self.assertEqual(
            server.describe_miembro_equipo(
                {"nombre": "Miguel Ángel Pérez Rodríguez", "cargo": "Administrador de Fincas", "colegiado": "3079"}),
            "Miguel Ángel Pérez Rodríguez — Administrador de Fincas, colegiado nº 3079",
        )

    def test_sin_cargo_no_queda_un_guion_suelto(self):
        self.assertEqual(server.describe_miembro_equipo({"nombre": "Ana Portero Palma"}), "Ana Portero Palma")

    def test_colegiado_sin_cargo(self):
        self.assertEqual(
            server.describe_miembro_equipo({"nombre": "Ana", "colegiado": "12"}), "Ana — Colegiado nº 12")

    def test_sin_nombre_no_hay_linea(self):
        """Un cargo sin nombre no dice nada; mejor que no salga."""
        self.assertEqual(server.describe_miembro_equipo({"cargo": "Abogada"}), "")
        self.assertEqual(server.describe_miembro_equipo({}), "")
        self.assertEqual(server.describe_miembro_equipo(None), "")


class SeGuardaYSeEditaTests(unittest.TestCase):
    def conn(self):
        conn = server.get_db(":memory:")
        server.ensure_workspace_product_tables(conn)
        return conn

    def test_se_siembra_la_primera_vez(self):
        items = server.fetch_workspace_fincas_equipo(self.conn(), "ws1")
        self.assertEqual(len(items), 5)
        self.assertEqual(items[0]["nombre"], "Miguel Ángel Pérez Rodríguez")

    def test_no_se_siembra_dos_veces(self):
        conn = self.conn()
        server.fetch_workspace_fincas_equipo(conn, "ws1")
        server.fetch_workspace_fincas_equipo(conn, "ws1")
        self.assertEqual(len(server.fetch_workspace_fincas_equipo(conn, "ws1")), 5)

    def test_respeta_el_orden(self):
        items = server.fetch_workspace_fincas_equipo(self.conn(), "ws1")
        self.assertEqual([m["orden"] for m in items], [1, 2, 3, 4, 5])

    def test_cada_workspace_tiene_el_suyo(self):
        conn = self.conn()
        server.fetch_workspace_fincas_equipo(conn, "ws1")
        conn.execute("UPDATE workspace_fincas_equipo SET cargo = 'mío' WHERE workspace_id = 'ws1'")
        conn.commit()
        self.assertNotEqual(server.fetch_workspace_fincas_equipo(conn, "ws2")[0]["cargo"], "mío")

    def test_sin_sembrar_devuelve_vacio(self):
        self.assertEqual(server.fetch_workspace_fincas_equipo(self.conn(), "ws1", sembrar=False), [])

    def test_sin_workspace_no_devuelve_nada(self):
        self.assertEqual(server.fetch_workspace_fincas_equipo(self.conn(), ""), [])

    def test_no_caben_dos_veces_la_misma_persona(self):
        conn = self.conn()
        server.fetch_workspace_fincas_equipo(conn, "ws1")
        with self.assertRaises(Exception):
            conn.execute(
                "INSERT INTO workspace_fincas_equipo "
                "(id, workspace_id, nombre, cargo, colegiado, activo, orden, created_at, updated_at) "
                "VALUES ('x', 'ws1', 'Ana Portero Palma', 'Abogada', '', 1, 9, 'a', 'a')")
            conn.commit()


class LosEndpointsComprubebanPertenenciaTests(unittest.TestCase):
    def test_el_get_la_exige(self):
        i = SERVER.index('if path == "/api/workspace_fincas_equipo"')
        cuerpo = SERVER[i: i + 1200]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id)", cuerpo)
        self.assertIn("No autenticado", cuerpo)

    def test_el_post_la_exige_con_escritura(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_equipo"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_el_post_no_se_fia_del_workspace_del_cuerpo_sin_comprobarlo(self):
        """El `workspace_id` llega en el cuerpo, así que la comprobación va antes
        de tocar la base: si no, cualquiera reescribiría el equipo de otro."""
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_equipo"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertLess(cuerpo.index("enforce_workspace_membership"), cuerpo.index("DELETE FROM"))

    def test_esta_en_la_lista_de_rutas_permitidas(self):
        """Sin esto el POST responde «Endpoint no valido»."""
        i = SERVER.index('"/api/workspace_fincas_carta",')
        self.assertIn('"/api/workspace_fincas_equipo",', SERVER[i: i + 200])

    def test_guardar_reemplaza_la_lista_entera(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_equipo"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("DELETE FROM workspace_fincas_equipo WHERE workspace_id = ?", cuerpo)

    def test_no_guarda_a_nadie_sin_nombre_ni_repetido(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_fincas_equipo"')
        cuerpo = SERVER[i: SERVER.index("\n        elif parsed.path ==", i + 10)]
        self.assertIn("if not nombre or normalize_lookup_text(nombre) in vistos:", cuerpo)


@unittest.skipUnless(LISTO, "hace falta pypdf")
class EnElPdfTests(unittest.TestCase):
    WORKSPACE = {"nombre": "Modernia", "primary_color": "#3C6E71"}
    EMPRESA = {"nombre": "Inmovere Fincas", "razon_social": "Inmovere Fincas", "nif": "B26798231"}
    CLIENTE = {"nombre": "C.P. Ejemplo", "nif": "", "telefono": "", "email": ""}
    LINEAS = [{"categoria": "Edificio", "concepto": "Por vivienda", "cantidad": 92,
               "unidad": "vivienda", "precio_unitario": 5, "total_linea": 460}]

    def genera(self, calc_extra=None):
        calc = {"num_vecinos": 92, "carta_presentacion": "Gracias por su interés.",
                "colegiado_numero": "3079"}
        calc.update(calc_extra or {})
        budget = {"id": "x", "servicio": "fincas", "titulo": "Prueba", "fecha": "2026-08-08",
                  "subtotal": 460.0, "impuestos": 96.6, "total": 556.6,
                  "calculo_json": json.dumps(calc)}
        with mock.patch.object(server, "fetch_geocode_coordinates", return_value=None), \
             mock.patch.object(server, "build_mapa_estatico", return_value=None), \
             mock.patch.object(server, "build_vista_aerea", return_value=None):
            pdf = server.build_workspace_budget_pdf(
                budget, self.WORKSPACE, self.EMPRESA, self.CLIENTE, self.LINEAS)
        return "\n".join((p.extract_text() or "") for p in PdfReader(BytesIO(pdf)).pages)

    def equipo(self):
        return [{"nombre": m["nombre"], "cargo": m["cargo"], "colegiado": ""}
                for m in server.FINCAS_EQUIPO_DEFECTO]

    def test_sale_el_bloque_con_todos(self):
        texto = self.genera({"equipo": self.equipo()})
        self.assertIn("Quién va a llevar su comunidad", texto)
        for miembro in server.FINCAS_EQUIPO_DEFECTO:
            with self.subTest(nombre=miembro["nombre"]):
                self.assertIn(miembro["nombre"], texto)

    def test_sale_el_cargo_junto_al_nombre(self):
        texto = self.genera({"equipo": self.equipo()})
        self.assertIn("Ana Portero Palma — Abogada", texto)

    def test_sin_equipo_no_hay_bloque(self):
        texto = self.genera({"equipo": []})
        self.assertNotIn("Quién va a llevar", texto)

    def test_sin_carta_tampoco_sale(self):
        """El bloque vive dentro de la carta: sin carta no hay dónde ponerlo."""
        texto = self.genera({"carta_presentacion": "", "equipo": self.equipo()})
        self.assertNotIn("Quién va a llevar", texto)

    def test_una_entrada_sin_nombre_no_pinta_una_linea_vacia(self):
        texto = self.genera({"equipo": [{"nombre": "", "cargo": "Abogada"}]})
        self.assertNotIn("Quién va a llevar", texto)

    def test_si_alguien_lleva_colegiado_no_se_repite_la_linea_suelta(self):
        """Salían las dos: «… colegiado nº 3079» y «Administrador de Fincas
        Colegiado nº 3079», el mismo dato dos veces y una sin decir de quién es."""
        con = [{"nombre": "Miguel Ángel Pérez Rodríguez", "cargo": "Administrador de Fincas", "colegiado": "3079"}]
        texto = self.genera({"equipo": con})
        self.assertNotIn("Administrador de Fincas Colegiado nº 3079.", texto)
        self.assertIn("colegiado nº 3079", texto)

    def test_sin_colegiado_en_el_equipo_la_linea_suelta_se_queda(self):
        texto = self.genera({"equipo": self.equipo()})
        self.assertIn("Administrador de Fincas Colegiado nº 3079.", texto)


class ElEquipoSeCongelaEnElPresupuestoTests(unittest.TestCase):
    def test_se_copia_al_calculo_al_guardar(self):
        i = SERVER.index('calculo["servicios_grupo"]')
        cuerpo = SERVER[i: i + 900]
        self.assertIn('calculo["equipo"]', cuerpo)
        self.assertIn("fetch_workspace_fincas_equipo(conn, workspace_id)", cuerpo)

    def test_solo_los_activos(self):
        i = SERVER.index('calculo["equipo"]')
        self.assertIn('if m.get("activo")', SERVER[i: i + 400])

    def test_el_pdf_lo_lee_del_presupuesto_y_no_de_la_tabla(self):
        """Si lo leyera de la tabla, un PDF ya enviado cambiaría al cambiar el
        equipo. Se regeneran presupuestos antiguos a menudo."""
        i = SERVER.index("def build_workspace_budget_pdf(")
        cuerpo = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn('calc.get("equipo")', cuerpo)
        self.assertNotIn("fetch_workspace_fincas_equipo", cuerpo)


class LaPantallaTests(unittest.TestCase):
    def test_tiene_su_propio_plegable(self):
        self.assertIn('id="workspaceFincasBudgetEquipoPanel"', HTML)
        self.assertIn("Quién va a llevar su comunidad", HTML)

    def test_se_puede_anadir_y_quitar(self):
        self.assertIn('id="workspaceFincasBudgetEquipoAnadir"', HTML)
        self.assertIn("data-equipo-quitar", APP)

    def test_se_carga_al_abrir_el_plegable(self):
        """No en cada carga de pantalla: son datos de todo el workspace y casi
        nunca se tocan."""
        i = APP.index('getElementById("workspaceFincasBudgetEquipoPanel")')
        self.assertIn("if (ev.target.open) void cargarEquipoDeFincas();", APP[i: i + 300])

    def test_no_manda_filas_sin_nombre(self):
        i = APP.index("const leeEquipoFincas")
        self.assertIn(".filter((m) => m.nombre)", APP[i: i + 500])

    def test_avisa_de_que_hay_que_guardar_tras_quitar(self):
        self.assertIn("Recuerda darle a «Guardar equipo»", APP)

    def test_explica_que_los_presupuestos_ya_hechos_no_cambian(self):
        self.assertIn("el equipo que hubiera el día que se generó", HTML)


if __name__ == "__main__":
    unittest.main()
