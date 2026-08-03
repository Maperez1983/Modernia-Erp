"""Dashboard e informe anual daban dos cifras del mismo ejercicio.

En 2025: 79.500 € en el dashboard y 78.000 € en el declarativo. La diferencia era
una indemnización con fecha de firma —Carolina López Méndez, 1.500 €— que el
dashboard contaba como hipoteca firmada y el informe no.

No eran dos errores: eran dos definiciones de "firmada" en dos sitios, y por eso
podían separarse sin que nadie lo notara. Ahora sale una sola constante.

Manda el criterio del informe: una indemnización no es una hipoteca firmada, por
mucho que haya comisión cobrada. Esa comisión sigue estando en el desglose por
estado, así que no desaparece de la vista.

El año NO era una diferencia, aunque yo lo dijera antes: los dos usan el año de
`fecha_firma`. La expresión que mira la columna `anio` alimenta solo contadores
de estados que no tienen firma (estudio, encargo, pendientes), donde es el
criterio razonable.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class UnaSolaDefinicionDeFirmadaTests(unittest.TestCase):
    def test_hay_una_constante_y_no_dos_listas(self):
        self.assertEqual(server.HIPOTECA_ESTADOS_FIRMADOS, ("firmada", "firmado"))

    def test_el_predicado_de_python_la_usa(self):
        i = SERVER.index("def is_hipoteca_signed_for_export")
        self.assertIn("in HIPOTECA_ESTADOS_FIRMADOS", SERVER[i: i + 400])

    def test_la_expresion_sql_la_usa(self):
        i = SERVER.index("def hipoteca_dashboard_closed_signed_expr")
        bloque = SERVER[i: SERVER.index("\ndef ", i + 10)]
        self.assertIn("HIPOTECA_ESTADOS_FIRMADOS", bloque)

    def test_la_indemnizacion_ya_no_cuenta_como_firmada(self):
        expr = server.hipoteca_dashboard_closed_signed_expr().lower()
        self.assertNotIn("indemniz", expr)

    def test_las_dos_vias_coinciden_estado_por_estado(self):
        """Lo que acepta el SQL tiene que aceptarlo el predicado, y al revés."""
        expr = server.hipoteca_dashboard_closed_signed_expr().lower()
        for estado in ("firmada", "firmado", "indemnización", "indemnizacion", "estudio", "pendiente", "caida"):
            fila = {"estado": estado, "fecha_firma": "2026-01-15"}
            acepta_sql = f"'{estado}'" in expr
            acepta_py = server.is_hipoteca_signed_for_export(fila)
            with self.subTest(estado=estado):
                self.assertEqual(acepta_sql, acepta_py, f"'{estado}' no se trata igual en SQL y en Python")

    def test_sigue_exigiendo_fecha_de_firma(self):
        # Sin fecha no hay ejercicio al que imputarla.
        self.assertIn("fecha_firma IS NOT NULL", server.hipoteca_dashboard_closed_signed_expr())
        self.assertFalse(server.is_hipoteca_signed_for_export({"estado": "Firmada", "fecha_firma": ""}))


class ElDashboardUsaElRelojDeLaAplicacionTests(unittest.TestCase):
    def test_no_usa_el_reloj_del_sistema(self):
        i = SERVER.index('if path == "/api/hipoteca_dashboard":')
        bloque = SERVER[i: i + 3000]
        self.assertNotIn("current_year = str(datetime.now().year)", bloque)
        self.assertIn("_ahora_local = app_now()", bloque)

    def test_el_mes_tambien(self):
        i = SERVER.index('if path == "/api/hipoteca_dashboard":')
        bloque = SERVER[i: i + 3000]
        self.assertIn('current_month = _ahora_local.strftime("%Y-%m")', bloque)


if __name__ == "__main__":
    unittest.main()
