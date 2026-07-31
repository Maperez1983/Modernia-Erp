"""Pedir una baja por API dejaba la cuenta activa y respondía `ok: true`.

    values.append(1 if str(payload.get(field) or "1").strip().lower() in {...} else 0)

Con `{"activo": 0}`, `payload.get("activo")` es `0`, que en Python es falso: el
`or` lo sustituye por `"1"` y se escribe justo lo contrario de lo que se pidió.
Sin error, sin aviso, con `ok: true` de vuelta.

Salió al dar de baja a dos personas que ya no trabajan en Modernia: las tres
escrituras (dos fichas y una cuenta) contestaron que sí y no cambiaron nada.

La interfaz se libraba de casualidad — manda `activo` como cadena desde un
`<select>`, y `"0"` sí es verdadero en Python.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class PayloadFlagTests(unittest.TestCase):
    def test_respeta_el_cero_de_json(self):
        """El caso que provocó todo esto."""
        self.assertEqual(server.payload_flag({"activo": 0}, "activo", 1), 0)

    def test_respeta_el_false_de_json(self):
        self.assertEqual(server.payload_flag({"activo": False}, "activo", 1), 0)

    def test_sigue_entendiendo_las_cadenas_que_manda_la_interfaz(self):
        for crudo in ("0", "false", "no", "off", "No", " OFF "):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.payload_flag({"activo": crudo}, "activo", 1), 0)
        for crudo in ("1", "true", "si", "sí", "on", "Sí", " ON "):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.payload_flag({"activo": crudo}, "activo", 0), 1)

    def test_el_uno_y_el_true_siguen_activando(self):
        self.assertEqual(server.payload_flag({"x": 1}, "x", 0), 1)
        self.assertEqual(server.payload_flag({"x": True}, "x", 0), 1)

    def test_si_no_viene_la_clave_manda_el_defecto(self):
        self.assertEqual(server.payload_flag({}, "activo", 1), 1)
        self.assertEqual(server.payload_flag({}, "activo", 0), 0)

    def test_vacio_o_nulo_es_como_no_venir(self):
        for crudo in (None, "", "   "):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.payload_flag({"x": crudo}, "x", 1), 1)
                self.assertEqual(server.payload_flag({"x": crudo}, "x", 0), 0)

    def test_una_cadena_sin_sentido_no_invierte_la_intencion(self):
        # Ante lo que no se entiende, el defecto; nunca lo contrario del defecto.
        self.assertEqual(server.payload_flag({"x": "quizá"}, "x", 1), 1)
        self.assertEqual(server.payload_flag({"x": "quizá"}, "x", 0), 0)


class NingunSitioVuelveAlPatronRotoTests(unittest.TestCase):
    """`payload.get(k) or "<defecto>"` se traga el 0 y el False de JSON."""

    def test_las_banderas_de_estado_usan_el_ayudante(self):
        for clave in ("activo", "registro_horario_activo", "alert_missing_checkin",
                      "alert_missing_checkout", "notify_worker", "notify_admin"):
            with self.subTest(clave=clave):
                self.assertNotIn(f'str(payload.get("{clave}") or "1")', SERVER)
                self.assertNotIn(f'str(payload.get("{clave}") or "0")', SERVER)

    def test_usuarios_update_no_puede_reactivar_a_quien_pides_desactivar(self):
        i = SERVER.index('elif parsed.path == "/api/usuarios_update":')
        bloque = SERVER[i: SERVER.index("elif parsed.path ==", i + 100)]
        self.assertIn('payload_flag(payload, field, 1)', bloque)
        self.assertNotIn('str(payload.get(field) or "1")', bloque)

    def test_la_ficha_de_rrhh_tampoco(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_personal":')
        bloque = SERVER[i: SERVER.index("elif parsed.path ==", i + 100)]
        self.assertIn('active_flag = payload_flag(payload, "activo", 1)', bloque)


if __name__ == "__main__":
    unittest.main()
