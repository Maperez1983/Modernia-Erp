"""El fichaje "desaparecía" porque el inicio elegía la ficha equivocada.

Encontrado en producción el 2026-09-18. Dos trabajadores de Modernia tenían dos fichas
vinculadas a su usuario: la de siempre en Modernia, con todos sus fichajes, y otra
vacía en Verifika², creada sola al entrar en ese workspace. `/api/home_time_status`
elegía la ficha con el `updated_at` más reciente, pero el aviso diario de "no has
fichado" (`_update_alert_last_sent`) toca esa fecha en todas las fichas cada mañana.
Ganaba la que el aviso procesara la última: ese día fue la vacía, y la pantalla de
inicio decía "Sin fichaje de hoy" y no aparecía ningún fichaje del historial.
"""

import sqlite3
import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

USUARIO = "u-miguel"
MODERNIA = "ws-modernia"
VERIFIKA = "ws-verifika"


class EleccionDeFichaTests(unittest.TestCase):
    def setUp(self):
        self.c = sqlite3.connect(":memory:")
        self.c.row_factory = sqlite3.Row
        self.c.executescript(
            """
            CREATE TABLE workspace_registro_personal (
              id TEXT PRIMARY KEY, workspace_id TEXT, usuario_id TEXT, usuario_manual INTEGER,
              activo INTEGER, created_at TEXT, updated_at TEXT
            );
            CREATE TABLE workspace_registro_horario (
              id TEXT PRIMARY KEY, workspace_id TEXT, persona_id TEXT, fecha TEXT
            );
            """
        )

    def tearDown(self):
        self.c.close()

    def _ficha(self, pid, ws, creada, modificada, activo=1, manual=1):
        self.c.execute(
            "INSERT INTO workspace_registro_personal VALUES (?,?,?,?,?,?,?)",
            (pid, ws, USUARIO, manual, activo, creada, modificada),
        )

    def _fichaje(self, pid, ws, fecha):
        self.c.execute(
            "INSERT INTO workspace_registro_horario VALUES (?,?,?,?)",
            (f"{pid}-{fecha}", ws, pid, fecha),
        )

    def _elige(self, workspaces=(MODERNIA, VERIFIKA)):
        return server.workspace_de_fichaje_para_usuario(self.c, USUARIO, list(workspaces))

    def test_el_caso_real_gana_la_ficha_con_historial(self):
        # Los datos tal como estaban: el aviso tocó la ficha vacía 0,3 s después.
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-09-18T10:04:04.300066+02:00")
        self._ficha("p-ver", VERIFIKA, "2026-08-27T08:19:40.842429+00:00", "2026-09-18T10:04:04.606770+02:00")
        self._fichaje("p-mod", MODERNIA, "2026-07-20")
        self.assertEqual(self._elige(), MODERNIA)

    def test_el_aviso_diario_no_cambia_la_eleccion(self):
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-09-18 10:00:00")
        self._ficha("p-ver", VERIFIKA, "2026-08-27 08:19:40", "2026-09-18 10:00:00")
        self._fichaje("p-mod", MODERNIA, "2026-07-20")
        for dia in ("2026-09-19", "2026-09-20", "2026-09-21"):
            for pid in ("p-ver", "p-mod") if dia.endswith("0") else ("p-mod", "p-ver"):
                self.c.execute(
                    "UPDATE workspace_registro_personal SET updated_at = ? WHERE id = ?",
                    (f"{dia} 10:04:0{1 if pid == 'p-ver' else 0}", pid),
                )
            self.assertEqual(self._elige(), MODERNIA, f"cambió de ficha el {dia}")

    def test_si_empieza_a_fichar_en_otro_workspace_le_sigue(self):
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-09-18 10:00:00")
        self._ficha("p-ver", VERIFIKA, "2026-08-27 08:19:40", "2026-09-18 10:00:00")
        self._fichaje("p-mod", MODERNIA, "2026-07-20")
        self._fichaje("p-ver", VERIFIKA, "2026-09-18")
        self.assertEqual(self._elige(), VERIFIKA)

    def test_sin_fichajes_gana_la_ficha_mas_antigua(self):
        self._ficha("p-ver", VERIFIKA, "2026-09-04 07:00:00", "2026-09-18 10:04:05")
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-03-31 18:02:14")
        self.assertEqual(self._elige(), MODERNIA)

    def test_ignora_fichas_desactivadas(self):
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-03-31 18:02:14", activo=0)
        self._ficha("p-ver", VERIFIKA, "2026-08-27 08:19:40", "2026-08-27 08:19:40")
        self._fichaje("p-mod", MODERNIA, "2026-07-20")
        self.assertEqual(self._elige(), VERIFIKA)

    def test_solo_mira_los_workspaces_del_usuario(self):
        self._ficha("p-mod", MODERNIA, "2026-03-31 18:02:14", "2026-03-31 18:02:14")
        self._fichaje("p-mod", MODERNIA, "2026-07-20")
        self._ficha("p-ver", VERIFIKA, "2026-08-27 08:19:40", "2026-08-27 08:19:40")
        self.assertEqual(self._elige(workspaces=[VERIFIKA]), VERIFIKA)

    def test_sin_datos_no_revienta(self):
        self.assertEqual(self._elige(), "")
        self.assertEqual(server.workspace_de_fichaje_para_usuario(self.c, "", [MODERNIA]), "")
        self.assertEqual(server.workspace_de_fichaje_para_usuario(self.c, USUARIO, []), "")


class ElEndpointUsaLaEleccionEstableTests(unittest.TestCase):
    def test_home_time_status_ya_no_elige_por_updated_at(self):
        i = SERVER.index('if path == "/api/home_time_status":')
        bloque = SERVER[i : SERVER.index("# Si no hay vínculo directo", i)]
        self.assertIn("workspace_de_fichaje_para_usuario(", bloque)
        self.assertNotIn("updated_at", bloque)


if __name__ == "__main__":
    unittest.main()
