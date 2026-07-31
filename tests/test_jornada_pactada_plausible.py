"""Una jornada diaria imposible no puede entrar ni propagarse.

En producción una ficha tenía `horas_pactadas_dia = 40`: las horas de la SEMANA
metidas en el campo del DÍA. Nada lo rechazó al guardarlo, y ese 40 se propagó a
la regularización de fichajes, que proponía cerrar 33 fichajes de esa trabajadora
a 16 h/día — 528 horas de jornada que nunca existieron. Se detectó antes de
ejecutarlo porque la propuesta se revisó; sin esa revisión habría entrado.

Dos capas: no dejar guardar el disparate, y no proponer nada a partir de un dato
imposible que ya esté guardado.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")
INDEX = (RAIZ / "web" / "index.html").read_text(encoding="utf-8")

SCHEMA = """
CREATE TABLE workspace_registro_horario (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT,
  persona_id TEXT, persona_nombre TEXT, fecha TEXT, hora_inicio TEXT, hora_fin TEXT,
  pausa_min INTEGER DEFAULT 0, minutos_trabajados INTEGER DEFAULT 0, estado TEXT);
CREATE TABLE workspace_registro_personal (id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT,
  nombre TEXT, horas_pactadas_dia REAL, activo INTEGER DEFAULT 1);
CREATE TABLE workspace_rrhh_turnos (id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT,
  weekday INTEGER, enabled INTEGER DEFAULT 1, hora_inicio TEXT, hora_fin TEXT, pausa_min INTEGER DEFAULT 0);
"""


def _conn(horas):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    c.execute("INSERT INTO workspace_registro_personal VALUES ('p1','ws1','e1','Irene',?,1)", (horas,))
    c.execute(
        "INSERT INTO workspace_registro_horario (id, workspace_id, empresa_id, persona_id, persona_nombre,"
        " fecha, hora_inicio, hora_fin, pausa_min, minutos_trabajados, estado)"
        " VALUES ('f1','ws1','e1','p1','Irene','2026-06-18','09:00',NULL,0,0,'Abierto')"
    )
    c.commit()
    return c


class LaPropuestaNoSeFiaDeUnaJornadaImposibleTests(unittest.TestCase):
    def test_cuarenta_horas_al_dia_no_genera_propuesta(self):
        c = _conn(40)
        f = server.fetch_workspace_open_time_entries(c, "ws1", antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "", "propuso cerrar a partir de una jornada de 40 h/día")
        self.assertEqual(f["origen_propuesta"], "sin_datos")
        c.close()

    def test_una_jornada_normal_si_propone(self):
        c = _conn(8)
        f = server.fetch_workspace_open_time_entries(c, "ws1", antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "17:00")
        self.assertEqual(f["minutos_propuestos"], 480)
        c.close()

    def test_el_limite_es_el_mismo_que_define_una_jornada_plausible(self):
        # 16 h por defecto: el mismo umbral que distingue un turno largo de un olvido.
        c = _conn(server.WORKSPACE_TIME_MAX_SHIFT_MINUTES / 60)
        f = server.fetch_workspace_open_time_entries(c, "ws1", antes_de="2026-07-31")[0]
        self.assertNotEqual(f["propuesta_hora_fin"], "", "el valor justo en el límite debería aceptarse")
        c.close()

    def test_justo_por_encima_del_limite_no(self):
        c = _conn(server.WORKSPACE_TIME_MAX_SHIFT_MINUTES / 60 + 0.25)
        f = server.fetch_workspace_open_time_entries(c, "ws1", antes_de="2026-07-31")[0]
        self.assertEqual(f["propuesta_hora_fin"], "")
        c.close()


class NoSeDejaGuardarLoImposibleTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_personal":')
        return SERVER[i : SERVER.index("elif parsed.path ==", i + 100)]

    def test_valida_las_horas_al_dia(self):
        bloque = self._bloque()
        self.assertIn("horas_pactadas_dia_fuera_de_rango", bloque)
        self.assertIn("WORKSPACE_TIME_MAX_SHIFT_MINUTES", bloque)
        self.assertIn("status=400", bloque)

    def test_el_mensaje_apunta_al_error_real(self):
        # Quien mete 40 está pensando en la semana: hay que decírselo.
        self.assertIn("jornada semanal", self._bloque())

    def test_valida_tambien_las_semanales(self):
        self.assertIn("horas_pactadas_semana_fuera_de_rango", self._bloque())

    def test_el_formulario_tambien_lo_limita(self):
        i = INDEX.index('name="horas_pactadas_dia"')
        campo = INDEX[i - 200 : i + 200]
        self.assertIn('max="16"', campo)


if __name__ == "__main__":
    unittest.main()
