"""Regularizar en bloque los fichajes que nadie cerró.

En producción había 126 fichajes abiertos en Modernia y 24 en Verifika², algunos
desde el 1 de abril, porque nadie cerraba y el aviso automático estaba apagado.

Borrarlos no era opción: el registro de jornada tiene conservación obligatoria de
cuatro años, y el propio sistema lo impide por diseño. Cerrarlos automáticamente
tampoco: sería inventar horas. Lo que se hace es proponer una salida a partir del
turno pactado y que una persona confirme, dejándolos marcados como corrección
manual y con auditoría.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE workspace_registro_horario (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT,
  persona_id TEXT, persona_nombre TEXT, fecha TEXT, hora_inicio TEXT, hora_fin TEXT,
  pausa_min INTEGER DEFAULT 0, minutos_trabajados INTEGER DEFAULT 0, estado TEXT,
  metodo_registro TEXT, notas TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT,
  nombre TEXT, horas_pactadas_dia REAL, activo INTEGER DEFAULT 1);
CREATE TABLE workspace_rrhh_turnos (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT,
  weekday INTEGER, enabled INTEGER DEFAULT 1, hora_inicio TEXT, hora_fin TEXT, pausa_min INTEGER DEFAULT 0);
"""

WS = "ws1"


def _conn(*, con_turno=True, horas=8.0):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO workspace_registro_personal VALUES ('p1', ?, 'e1', 'Ana', ?, 1)", (WS, horas))
    if con_turno:
        # 2026-07-21 es martes (isoweekday 2).
        c.execute("INSERT INTO workspace_rrhh_turnos VALUES ('t1', ?, 'p1', 2, 1, '09:00', '17:30', 30)", (WS,))
    c.execute(
        "INSERT INTO workspace_registro_horario (id, workspace_id, empresa_id, persona_id, persona_nombre,"
        " fecha, hora_inicio, hora_fin, pausa_min, minutos_trabajados, estado)"
        " VALUES ('f1', ?, 'e1', 'p1', 'Ana', '2026-07-21', '09:00', NULL, 0, 0, 'Abierto')", (WS,))
    c.commit()
    return c


class PropuestaDeSalidaTests(unittest.TestCase):
    def test_propone_la_hora_del_turno_pactado(self):
        c = _conn()
        f = server.fetch_workspace_open_time_entries(c, WS, antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "17:30")
        self.assertEqual(f["origen_propuesta"], "turno")
        self.assertEqual(f["propuesta_pausa_min"], 30)
        c.close()

    def test_sin_turno_cae_a_la_jornada_pactada(self):
        c = _conn(con_turno=False)
        f = server.fetch_workspace_open_time_entries(c, WS, antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "17:00")  # 09:00 + 8 h
        self.assertEqual(f["origen_propuesta"], "jornada_pactada")
        c.close()

    def test_sin_datos_no_inventa_nada(self):
        c = _conn(con_turno=False, horas=0)
        f = server.fetch_workspace_open_time_entries(c, WS, antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "")
        self.assertEqual(f["origen_propuesta"], "sin_datos")
        c.close()

    def test_la_propuesta_cuadra_con_lo_que_se_guardaria(self):
        # Si el listado dice 8,0 h y la base acaba con 8,5 h, la pantalla miente.
        c = _conn()
        f = server.fetch_workspace_open_time_entries(c, WS, antes_de="2026-07-31")[0]
        guardado = server.compute_worked_minutes(f["hora_inicio"], f["propuesta_hora_fin"], f["propuesta_pausa_min"])
        self.assertEqual(f["minutos_propuestos"], guardado)
        self.assertEqual(guardado, 480)
        c.close()

    def test_no_lista_los_de_hoy_ni_los_cerrados(self):
        c = _conn()
        c.execute("UPDATE workspace_registro_horario SET hora_fin = '18:00' WHERE id = 'f1'")
        c.commit()
        self.assertEqual(server.fetch_workspace_open_time_entries(c, WS, antes_de="2026-07-31"), [])
        c.close()


class EndpointRegularizarTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_horario_regularizar":')
        return SERVER[i : SERVER.index("elif parsed.path ==", i + 100)]

    def test_solo_para_gestores(self):
        self.assertIn("workspace_actor_can_manage_workspace", self._bloque())

    def test_no_cierra_sin_hora_explicita(self):
        bloque = self._bloque()
        self.assertIn("hora_fin_invalida", bloque)
        self.assertIn("parse_hhmm_to_minutes(hora_fin) is None", bloque)

    def test_respeta_el_bloqueo_de_mes(self):
        self.assertIn("is_workspace_time_month_locked", self._bloque())

    def test_marca_como_manual_y_deja_traza(self):
        bloque = self._bloque()
        self.assertIn("metodo_registro = 'Manual'", bloque)
        self.assertIn('action="regularizacion_cierre"', bloque)
        self.assertIn("log_workspace_registro_audit", bloque)

    def test_no_repisa_un_fichaje_ya_cerrado(self):
        self.assertIn("ya_cerrado", self._bloque())

    def test_la_ruta_esta_registrada(self):
        # Hay dos listas blancas de rutas POST; sin registrar, el endpoint da 404.
        self.assertGreaterEqual(SERVER.count('"/api/workspace_registro_horario_regularizar"'), 3)


class PantallaDeRegularizacionTests(unittest.TestCase):
    def test_pide_confirmacion_antes_de_cerrar(self):
        i = APP.index("const applyWorkspaceOpenEntries")
        bloque = APP[i : APP.index("const fillWorkspaceTimeEmployeeForm", i)]
        self.assertIn("confirm(", bloque)
        self.assertIn("corrección manual", bloque)

    def test_manda_la_pausa_para_que_cuadre_el_computo(self):
        i = APP.index("const applyWorkspaceOpenEntries")
        bloque = APP[i : APP.index("const fillWorkspaceTimeEmployeeForm", i)]
        self.assertIn("pausa_min", bloque)

    def test_las_filas_sin_propuesta_no_se_pueden_marcar(self):
        i = APP.index("const renderWorkspaceOpenEntries")
        bloque = APP[i : APP.index("const loadWorkspaceOpenEntries", i)]
        self.assertIn('f.propuesta_hora_fin ? "checked" : "disabled"', bloque)


if __name__ == "__main__":
    unittest.main()
