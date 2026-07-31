"""Un fichaje que nadie cerró no puede convertirse en una jornada inventada.

La búsqueda de fichaje abierto usa `fecha <= hoy`, que es lo correcto para el turno
nocturno (entra a las 22:00, sale a las 02:00). Pero arrastraba también los de días
anteriores, así que si alguien olvidaba fichar la salida el lunes y el martes pulsaba
"Fichar salida", se escribía sobre la fila del LUNES con la hora del MARTES:

    entró 14:00 (lunes), pulsa salida 09:00 (martes)  ->  19,0 h registradas

Diecinueve horas que nunca ocurrieron, en un registro de obligada conservación
durante cuatro años. Y si en vez de "salida" pulsaba "entrada", se bloqueaba con un
409 que decía "ya existe un fichaje abierto HOY" — siendo de otro día.

La distinción no puede ser "¿es de otro día?", porque el turno nocturno también lo
es. Es el tiempo transcurrido.
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


def _fichaje(fecha, hora):
    return {"fecha": fecha, "hora_inicio": hora}


class MinutosAbiertoTests(unittest.TestCase):
    def test_cuenta_los_minutos_desde_la_entrada(self):
        ahora = datetime(2026, 7, 31, 17, 0)
        self.assertEqual(server.workspace_time_open_entry_minutes(_fichaje("2026-07-31", "09:00"), ahora), 480)

    def test_cuenta_bien_cruzando_medianoche(self):
        # Turno nocturno: entró ayer a las 22:00, son las 02:00 de hoy -> 4 h.
        ahora = datetime(2026, 8, 1, 2, 0)
        self.assertEqual(server.workspace_time_open_entry_minutes(_fichaje("2026-07-31", "22:00"), ahora), 240)

    def test_detecta_el_fichaje_de_hace_dias(self):
        ahora = datetime(2026, 8, 1, 9, 0)
        minutos = server.workspace_time_open_entry_minutes(_fichaje("2026-07-31", "14:00"), ahora)
        self.assertEqual(minutos, 1140)  # 19 h
        self.assertGreater(minutos, server.WORKSPACE_TIME_MAX_SHIFT_MINUTES)

    def test_acepta_fecha_con_hora_aware(self):
        ahora = datetime(2026, 7, 31, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(server.workspace_time_open_entry_minutes(_fichaje("2026-07-31", "09:00"), ahora), 480)

    def test_datos_incompletos_no_revientan(self):
        ahora = datetime(2026, 7, 31, 17, 0)
        self.assertIsNone(server.workspace_time_open_entry_minutes(None, ahora))
        self.assertIsNone(server.workspace_time_open_entry_minutes(_fichaje("", "09:00"), ahora))
        self.assertIsNone(server.workspace_time_open_entry_minutes(_fichaje("2026-07-31", ""), ahora))
        self.assertIsNone(server.workspace_time_open_entry_minutes(_fichaje("no-es-fecha", "09:00"), ahora))


class UmbralDeJornadaTests(unittest.TestCase):
    def test_el_umbral_no_baja_de_una_hora(self):
        self.assertGreaterEqual(server.WORKSPACE_TIME_MAX_SHIFT_MINUTES, 60)

    def test_el_turno_nocturno_cabe_de_sobra(self):
        # 22:00 -> 06:00 son 8 h: tiene que quedar por debajo del umbral o lo romperíamos.
        self.assertGreater(server.WORKSPACE_TIME_MAX_SHIFT_MINUTES, 8 * 60)


class DecisionDelToggleTests(unittest.TestCase):
    """La lógica vive dentro del handler; se fija por estructura."""

    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_registro_horario_toggle":')
        return SERVER[i : SERVER.index('elif parsed.path ==', i + 100)]

    def test_se_calcula_si_el_fichaje_esta_rancio(self):
        bloque = self._bloque()
        self.assertIn("fichaje_rancio", bloque)
        self.assertIn("WORKSPACE_TIME_MAX_SHIFT_MINUTES", bloque)

    def test_el_checkout_rancio_no_escribe(self):
        bloque = self._bloque()
        corte = bloque.index("if fichaje_rancio:")
        tramo = bloque[corte : bloque.index("start = str(open_row", corte)]
        self.assertIn("status=409", tramo)
        self.assertIn("open_entry_stale", tramo)
        # Lo importante: en ese tramo no hay ningún UPDATE.
        self.assertNotIn("UPDATE workspace_registro_horario", tramo)

    def test_el_checkin_no_se_bloquea_por_un_olvido_de_otro_dia(self):
        bloque = self._bloque()
        self.assertIn("if open_row and not fichaje_rancio:", bloque)

    def test_el_mensaje_ya_no_dice_hoy_cuando_es_de_otro_dia(self):
        bloque = self._bloque()
        self.assertNotIn("ya existe un fichaje abierto hoy para esa persona", bloque)
        self.assertIn("Tienes un turno abierto desde el", bloque)


class ElTurnoNocturnoSigueFuncionandoTests(unittest.TestCase):
    """La regresión que más me preocupaba al arreglar esto."""

    def test_cerrar_a_las_dos_de_la_madrugada_sigue_permitido(self):
        entrada = _fichaje("2026-07-31", "22:00")
        ahora = datetime(2026, 8, 1, 2, 0)
        minutos = server.workspace_time_open_entry_minutes(entrada, ahora)
        self.assertLessEqual(minutos, server.WORKSPACE_TIME_MAX_SHIFT_MINUTES, "el turno nocturno no puede considerarse rancio")
        # Y el cálculo de la jornada sigue dando 4 h.
        self.assertEqual(server.compute_worked_minutes("22:00", "02:00", 0), 240)

    def test_una_guardia_larga_de_catorce_horas_tambien(self):
        entrada = _fichaje("2026-07-31", "20:00")
        ahora = datetime(2026, 8, 1, 10, 0)
        self.assertLessEqual(server.workspace_time_open_entry_minutes(entrada, ahora), server.WORKSPACE_TIME_MAX_SHIFT_MINUTES)

    def test_pero_un_dia_entero_sin_cerrar_si_es_rancio(self):
        entrada = _fichaje("2026-07-30", "09:00")
        ahora = datetime(2026, 7, 31, 9, 0)
        self.assertGreater(server.workspace_time_open_entry_minutes(entrada, ahora), server.WORKSPACE_TIME_MAX_SHIFT_MINUTES)


if __name__ == "__main__":
    unittest.main()


class EstadoDeFichajeNoMienteTests(unittest.TestCase):
    """`/api/home_time_status` metía un fichaje viejo dentro de "hoy".

    Encontrado en la cuenta real el 2026-07-31: había un fichaje abierto del
    2026-07-20 y el estado lo devolvía como `today.checkin = "10:52"`. La pantalla
    ponía "Hoy: 10:52" y, peor, deshabilitaba "Fichar entrada" porque creía que ya
    se había fichado: el usuario no podía fichar y nada le explicaba por qué.
    """

    def _bloque(self):
        i = SERVER.index('if path == "/api/home_time_status":')
        return SERVER[i : SERVER.index("json_response(", SERVER.index("today_payload[\"stale\"]", i))]

    def test_el_estado_marca_el_fichaje_rancio(self):
        bloque = self._bloque()
        self.assertIn('today_payload["stale"]', bloque)
        self.assertIn("workspace_time_open_entry_minutes", bloque)
        self.assertIn("WORKSPACE_TIME_MAX_SHIFT_MINUTES", bloque)

    def test_usa_el_mismo_umbral_que_el_toggle(self):
        # Dos criterios distintos para lo mismo acabarían discrepando.
        self.assertEqual(SERVER.count("WORKSPACE_TIME_MAX_SHIFT_MINUTES"), 4)


class LaPantallaDeFichajeTests(unittest.TestCase):
    APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")

    def _bloque(self):
        i = self.APP.index("const renderHomeTimePunchModal")
        return self.APP[i : self.APP.index("const openHomeTimePunchModal", i)]

    def test_con_un_fichaje_rancio_se_puede_fichar_entrada(self):
        bloque = self._bloque()
        self.assertIn("const canCheckIn = rancio || !checkin;", bloque)

    def test_pero_no_salida(self):
        bloque = self._bloque()
        self.assertIn("const canCheckOut = Boolean(open) && !rancio;", bloque)

    def test_ya_no_dice_hoy_cuando_no_es_de_hoy(self):
        bloque = self._bloque()
        self.assertIn("sin cerrar", bloque)
        self.assertIn("entry_date", bloque)
        # El "Hoy: " literal solo se antepone si NO es rancio.
        self.assertIn('${rancio ? "" : "Hoy: "}', bloque)

    def test_se_explica_al_usuario_que_hacer(self):
        bloque = self._bloque()
        self.assertIn("corregirlo administración", bloque)
