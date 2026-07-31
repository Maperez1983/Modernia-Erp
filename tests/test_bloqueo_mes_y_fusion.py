"""El bloqueo de mes no bloqueaba nada, y la fusión de fichas duplicadas.

`_normalize_month` llevaba el patrón escrito como `r"^\\d{4}-\\d{2}$"`. En una
cadena raw, `\\d` significa "barra invertida seguida de d", no "un dígito", así
que no casaba nunca y la función devolvía siempre "". Con eso se caía la función
entera de bloqueo de periodo: no se guardaba con clave válida ni se comprobaba al
fichar. Se podía cerrar un mes en la interfaz y seguir escribiendo en él.

Se descubrió comprobando que la fusión de fichas respetara el bloqueo: no lo
respetaba, y resultó que no lo respetaba nadie.
"""

import re
import sqlite3
import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class NormalizarMesTests(unittest.TestCase):
    def test_acepta_mes_y_fecha_completa(self):
        self.assertEqual(server._normalize_month("2026-05"), "2026-05")
        self.assertEqual(server._normalize_month("2026-05-10"), "2026-05")
        self.assertEqual(server._normalize_month("2026-05-10T09:00:00"), "2026-05")

    def test_rechaza_lo_que_no_es_un_mes(self):
        for valor in ("", None, "basura", "26-5", "2026", "mayo"):
            self.assertEqual(server._normalize_month(valor), "", f"aceptó {valor!r}")

    def test_el_patron_no_lleva_doble_barra(self):
        i = SERVER.index("def _normalize_month")
        bloque = SERVER[i : SERVER.index("\ndef ", i + 10)]
        self.assertNotIn(r'\\d{4}', bloque, "vuelve el escapado que rompía el bloqueo de mes")
        self.assertIn(r'\d{4}', bloque)


class BloqueoDeMesTests(unittest.TestCase):
    def _conn(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.executescript(
            "CREATE TABLE workspace_registro_periodos (id TEXT PRIMARY KEY, workspace_id TEXT,"
            " empresa_id TEXT, month TEXT, locked INTEGER);"
        )
        c.execute("INSERT INTO workspace_registro_periodos VALUES ('p','ws1','emp1','2026-05',1)")
        c.commit()
        return c

    def test_un_mes_bloqueado_lo_esta_de_verdad(self):
        c = self._conn()
        self.assertTrue(server.is_workspace_time_month_locked(c, "ws1", "2026-05-10", empresa_id="emp1"))
        self.assertTrue(server.is_workspace_time_month_locked(c, "ws1", "2026-05", empresa_id="emp1"))
        c.close()

    def test_otro_mes_no(self):
        c = self._conn()
        self.assertFalse(server.is_workspace_time_month_locked(c, "ws1", "2026-06-10", empresa_id="emp1"))
        c.close()

    def test_lo_comprueban_los_caminos_de_escritura(self):
        # Fichar, editar a mano, regularizar y fusionar: los cuatro tocan fichajes.
        self.assertGreaterEqual(SERVER.count("is_workspace_time_month_locked"), 5)


class FusionDeFichasTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_personal_merge":')
        return SERVER[i : SERVER.index("elif parsed.path ==", i + 100)]

    def test_solo_para_gestores(self):
        self.assertIn("workspace_actor_can_manage_workspace", self._bloque())

    def test_no_permite_fusionar_una_ficha_consigo_misma(self):
        self.assertIn("misma ficha", self._bloque())

    def test_respeta_el_bloqueo_de_mes(self):
        bloque = self._bloque()
        self.assertIn("is_workspace_time_month_locked", bloque)
        self.assertIn("bloqueados.append", bloque)

    def test_la_ficha_de_origen_se_desactiva_no_se_borra(self):
        bloque = self._bloque()
        self.assertIn("SET activo = 0", bloque)
        self.assertNotIn("DELETE FROM workspace_registro_personal", bloque)

    def test_no_desactiva_si_quedaron_fichajes_sin_mover(self):
        # Si un mes bloqueado impidió mover parte del historial, la ficha origen
        # sigue teniendo datos: desactivarla los escondería.
        self.assertIn("if movidos and not bloqueados:", self._bloque())

    def test_deja_traza(self):
        self.assertIn('action="fusion_fichas"', self._bloque())

    def test_la_ruta_esta_registrada(self):
        self.assertGreaterEqual(SERVER.count('"/api/workspace_registro_personal_merge"'), 3)


class OtrosRegexMalEscapadosTests(unittest.TestCase):
    """El mismo error de escapado aparece en más sitios; queda inventariado.

    No se arreglan aquí porque arreglarlos hace que funcionen cosas que hoy no
    hacen nada, y ese cambio de comportamiento merece revisarse uno a uno.
    """

    def test_inventario_conocido(self):
        restantes = re.findall(r'r"[^"]*\\\\[dwsSWDb]', SERVER)
        self.assertLessEqual(
            len(restantes), 10,
            "hay más regex con doble barra de los inventariados: revísalos antes de subir el listón",
        )


if __name__ == "__main__":
    unittest.main()
