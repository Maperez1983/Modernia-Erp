"""El arranque reenganchaba todas las empresas al workspace por defecto.

Cada vez que arrancaba la aplicación, `bootstrap_default_workspace` volvía a
enlazar TODAS las empresas a Verifika². Consecuencias, todas vistas en producción:

  - el holding heredaba la cartera de sus participadas, que es justo lo que se
    pidió evitar;
  - con una empresa colgando de dos workspaces,
    `resolve_workspace_id_for_empresa` se niega a adivinar —bien hecho— y devuelve
    '', así que las altas se quedaban sin ámbito;
  - deshacía en el siguiente despliegue cualquier desenganche hecho a mano.

Lo tercero fue lo que rompió producción el 2026-08-03: se desenganchó el holding,
se puso NOT NULL en `hipotecas.workspace_id` dando por bueno ese estado, y el
siguiente arranque volvió a enganchar. Resultado: dar de alta una hipoteca
fallaba con violación de NOT NULL.

Sembrar está bien la primera vez, cuando el workspace nace vacío. Repetirlo en
cada arranque no.
"""

import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class SoloSiembraLaPrimeraVezTests(unittest.TestCase):
    def _bloque(self):
        i = SERVER.index("def bootstrap_default_workspace")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_comprueba_si_ya_tiene_empresas(self):
        bloque = self._bloque()
        self.assertIn("SELECT COUNT(*) AS total FROM workspace_empresas WHERE workspace_id = ?", bloque)
        self.assertIn("if not int(row_value(ya_tiene", bloque)

    def test_el_enlace_masivo_queda_dentro_de_esa_condicion(self):
        bloque = self._bloque()
        guarda = bloque.index("if not int(row_value(ya_tiene")
        insercion = bloque.index("INSERT OR IGNORE INTO workspace_empresas")
        self.assertLess(guarda, insercion, "el enlace masivo tiene que estar detrás de la comprobación")

    def test_queda_escrito_por_que(self):
        # Para que nadie lo "arregle" quitando la condición.
        self.assertIn("holding heredara la cartera", self._bloque())


class LaRestriccionNoSeReponeSola(unittest.TestCase):
    """Ponerla mientras el ámbito no sea deducible tumba el alta de hipotecas."""

    def test_hipotecas_no_lleva_not_null_todavia(self):
        i = SERVER.index('ensure_column(conn, "hipotecas", "workspace_id"')
        tramo = SERVER[i: i + 900]
        self.assertNotIn('ensure_not_null(conn, "hipotecas"', tramo)

    def test_pero_clientes_si_lo_lleva(self):
        # Ahí sí se sostiene: la columna está poblada y las altas resuelven ámbito.
        self.assertIn('ensure_not_null(conn, "clientes", "workspace_id")', SERVER)


if __name__ == "__main__":
    unittest.main()
