"""KPIs de la ficha del trabajador: salario, costes sociales, horas y vacaciones.

Cuatro de las cinco cifras son números sueltos y van como tarjetas; convertirlos en
gráfico no añadiría nada. Solo las vacaciones piden forma, y la correcta es una
barra de parte-sobre-total (disfrutadas sobre las pactadas).

Medido en producción el 2026-07-31: no había ninguna nómina cargada, así que
salario y costes salen a 0. Por eso se devuelve `tiene_nominas`: la interfaz dice
"sin nóminas cargadas" en vez de enseñar un 0 que parece un dato real.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
CSS = (RAIZ / "web" / "styles.css").read_text(encoding="utf-8")
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE workspace_rrhh_nominas (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, year INTEGER,
  month INTEGER, bruto REAL DEFAULT 0, neto REAL DEFAULT 0, ss_empresa REAL DEFAULT 0, ss_trabajador REAL DEFAULT 0);
CREATE TABLE workspace_registro_horario (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, fecha TEXT,
  hora_inicio TEXT, hora_fin TEXT, minutos_trabajados INTEGER DEFAULT 0);
CREATE TABLE workspace_rrhh_profile (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, vacaciones_dias_anuales REAL);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, nombre TEXT, source TEXT DEFAULT 'manual');
CREATE TABLE workspace_rrhh_ausencias (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, empresa_id TEXT,
  tipo TEXT, estado TEXT, fecha_inicio TEXT, fecha_fin TEXT);
CREATE TABLE empresas (id TEXT PRIMARY KEY, nombre TEXT, vacaciones_modo TEXT);
"""


def _conn(*, nominas=True, dias_vac=22):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO workspace_registro_personal VALUES ('p1','ws','Ana','manual')")
    c.execute("INSERT INTO workspace_rrhh_profile VALUES ('f','ws','p1',?)", (dias_vac,))
    if nominas:
        for m in (1, 2):
            c.execute("INSERT INTO workspace_rrhh_nominas VALUES (?,'ws','p1',2026,?,2500,1900,800,160)", (f"n{m}", m))
    c.execute("INSERT INTO workspace_registro_horario VALUES ('h1','ws','p1','2026-03-02','09:00','17:00',480)")
    c.commit()
    return c


class SalarioYCostesTests(unittest.TestCase):
    def test_suma_los_recibos_del_ejercicio(self):
        c = _conn()
        k = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)
        self.assertEqual(k["salario_bruto"], 5000.0)
        self.assertEqual(k["salario_neto"], 3800.0)
        self.assertEqual(k["ss_empresa"], 1600.0)
        self.assertEqual(k["recibos"], 2)
        c.close()

    def test_el_coste_de_empresa_es_bruto_mas_cuota_patronal(self):
        c = _conn()
        k = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)
        self.assertEqual(k["coste_empresa"], k["salario_bruto"] + k["ss_empresa"])
        # La cuota del trabajador NO suma al coste de empresa: ya está dentro del bruto.
        self.assertNotEqual(k["coste_empresa"], k["salario_bruto"] + k["ss_trabajador"])
        c.close()

    def test_sin_nominas_lo_dice_en_vez_de_devolver_un_cero_mudo(self):
        c = _conn(nominas=False)
        k = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)
        self.assertFalse(k["tiene_nominas"])
        self.assertEqual(k["salario_bruto"], 0)
        c.close()

    def test_no_mezcla_ejercicios(self):
        c = _conn()
        c.execute("INSERT INTO workspace_rrhh_nominas VALUES ('viejo','ws','p1',2025,1,9999,9999,9999,9999)")
        c.commit()
        k = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)
        self.assertEqual(k["salario_bruto"], 5000.0)
        c.close()


class HorasTrabajadasTests(unittest.TestCase):
    def test_cuenta_solo_los_fichajes_cerrados(self):
        """Un fichaje abierto no ha producido horas todavía."""
        c = _conn()
        c.execute("INSERT INTO workspace_registro_horario VALUES ('h2','ws','p1','2026-03-03','09:00',NULL,0)")
        c.commit()
        k = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)
        self.assertEqual(k["horas_trabajadas"], 8.0)
        c.close()

    def test_no_cuenta_otros_anios(self):
        c = _conn()
        c.execute("INSERT INTO workspace_registro_horario VALUES ('h3','ws','p1','2025-03-02','09:00','17:00',480)")
        c.commit()
        self.assertEqual(server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)["horas_trabajadas"], 8.0)
        c.close()


class VacacionesTests(unittest.TestCase):
    def test_devuelve_total_usadas_y_pendientes(self):
        c = _conn()
        c.execute("INSERT INTO workspace_rrhh_ausencias VALUES ('a','ws','p1','e1','Vacaciones','Aprobada','2026-08-03','2026-08-07')")
        c.commit()
        v = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)["vacaciones"]
        self.assertEqual(v["dias_total"], 22)
        self.assertEqual(v["dias_usados"] + v["dias_pendientes"], v["dias_total"])
        self.assertGreater(v["dias_usados"], 0)
        c.close()

    def test_sin_ausencias_todo_pendiente(self):
        c = _conn()
        v = server.fetch_workspace_rrhh_persona_kpis(c, "ws", "p1", year=2026)["vacaciones"]
        self.assertEqual(v["dias_usados"], 0)
        self.assertEqual(v["dias_pendientes"], 22)
        c.close()


class AutorizacionTests(unittest.TestCase):
    def test_gestor_o_ficha_propia(self):
        i = SERVER.index('if path == "/api/workspace_rrhh_ficha_kpis":')
        b = SERVER[i: SERVER.index("if path ==", i + 100)]
        self.assertIn("workspace_actor_can_manage_workspace", b)
        self.assertIn("workspace_persona_id_for_user", b)
        self.assertIn("status=403", b)


class PresentacionTests(unittest.TestCase):
    def test_usa_la_paleta_validada_y_no_el_verde_de_marca(self):
        """El verde de la app no pasa el suelo de croma: lee como gris."""
        i = APP.index("const RRHH_COLOR_DISFRUTADAS")
        bloque = APP[i: i + 300]
        self.assertIn("#2a78d6", bloque)
        self.assertIn("#eb6834", bloque)
        self.assertNotIn("#3c6e71", bloque)

    def test_la_barra_no_depende_solo_del_color(self):
        i = APP.index("const renderRrhhKpis")
        b = APP[i: APP.index("const loadRrhhKpis", i)]
        self.assertIn("aria-label", b)          # descripción para lector de pantalla
        self.assertIn("disfrutados", b)         # leyenda con cifras
        self.assertIn("pendientes", b)

    def test_hay_hueco_entre_segmentos(self):
        # 2px de separación: distingue los tramos sin depender del color.
        i = CSS.index(".rrhh-vac-bar")
        self.assertIn("gap: 2px", CSS[i: i + 300])

    def test_tiene_modo_oscuro_propio(self):
        i = CSS.index(".rrhh-vac-usadas")
        self.assertIn("prefers-color-scheme: dark", CSS[i:])
        self.assertIn("#3987e5", CSS[i:])


if __name__ == "__main__":
    unittest.main()


class LosKpisEstanDondeSeMiraLaFichaTests(unittest.TestCase):
    """Estaban puestos en la pantalla equivocada.

    Se añadieron al panel antiguo de "Ficha laboral" (`#workspaceRrhhProfileForm`),
    pero la ficha que se abre pulsando a alguien en Equipo es otra vista, con sus
    propias pestañas. Al comprobarlo contra producción, el contenedor no existía en
    la pantalla que de verdad se usa: el endpoint devolvía las cifras y nadie las
    veía.
    """

    APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    def test_el_dashboard_del_miembro_incluye_los_kpis(self):
        i = self.APP.index("const dashboardHtml = ")
        tramo = self.APP[i - 700: i + 300]
        self.assertIn('id="workspaceRrhhKpis"', tramo)
        self.assertIn("const dashboardHtml = kpisHtml + renderRrhhEconomicosDashboardPanel({", self.APP)

    def test_solo_si_hay_ficha(self):
        # Sin ficha no hay persona_id que consultar; pedirlo daría un 400.
        self.assertIn("const kpisHtml = employee?.id", self.APP)

    def test_el_contenedor_lleva_la_persona(self):
        i = self.APP.index("const kpisHtml = employee?.id")
        self.assertIn('data-persona="${escapeHtml(String(employee.id))}"', self.APP[i: i + 400])

    def test_se_cargan_al_pintar(self):
        # `loadRrhhKpis()` vive dentro de renderWorkspaceRrhhHub, que es quien pinta
        # el detalle y quien se vuelve a llamar al cambiar de pestaña.
        self.assertIn("loadRrhhKpis();", self.APP)
        self.assertIn("state.workspaceRrhhEquipoMemberTab = String(button.dataset.rrhhMemberTab", self.APP)
