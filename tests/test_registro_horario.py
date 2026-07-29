import unittest

from web.server import (
    compute_worked_minutes,
    build_workspace_time_summary,
    build_workspace_time_csv,
)


def _row(persona, worked, pactadas, fecha, hora_fin="17:00"):
    return {
        "persona_id": persona, "persona_nombre": persona,
        "minutos_trabajados": worked, "horas_pactadas_dia": pactadas,
        "pausa_min": 0, "estado": "cerrado", "hora_fin": hora_fin, "fecha": fecha,
    }


class ComputeWorkedMinutesTests(unittest.TestCase):
    def test_jornada_normal_descuenta_pausa(self):
        # 09:00-17:00 con 60 min de pausa = 7h.
        self.assertEqual(compute_worked_minutes("09:00", "17:00", 60), 420)

    def test_turno_nocturno_cruza_medianoche(self):
        # 22:00-06:00 con 30 min pausa = 8h - 30 = 7.5h (no negativo).
        self.assertEqual(compute_worked_minutes("22:00", "06:00", 30), 450)

    def test_pausa_mayor_que_jornada_no_da_negativo(self):
        self.assertEqual(compute_worked_minutes("09:00", "09:30", 60), 0)

    def test_horas_invalidas_devuelven_cero(self):
        self.assertEqual(compute_worked_minutes("", "17:00", 0), 0)
        self.assertEqual(compute_worked_minutes("09:00", None, 0), 0)


class OvertimeSummaryTests(unittest.TestCase):
    def test_horas_extra_por_dia_no_se_compensan(self):
        # Ana: día 1 = 9h/8h (1h extra), día 2 = 7h/8h (0 extra). Un día corto NO compensa uno largo.
        rows = [
            _row("Ana", 540, 8, "2026-07-01"),
            _row("Ana", 420, 8, "2026-07-02"),
            _row("Beto", 600, 8, "2026-07-01"),  # 10h/8h = 2h extra
        ]
        s = build_workspace_time_summary(rows, month="2026-07")
        self.assertEqual(s["horas_extra_hhmm"], "03:00")  # 1h Ana + 2h Beto
        self.assertEqual(s["minutos_extra"], 180)
        por_persona = {p["persona_nombre"]: p["horas_extra_hhmm"] for p in s["rows"]}
        self.assertEqual(por_persona["Ana"], "01:00")
        self.assertEqual(por_persona["Beto"], "02:00")

    def test_sin_exceso_no_hay_horas_extra(self):
        rows = [_row("Ana", 420, 8, "2026-07-01")]  # 7h/8h
        s = build_workspace_time_summary(rows, month="2026-07")
        self.assertEqual(s["horas_extra_hhmm"], "00:00")

    def test_csv_incluye_columna_horas_extra(self):
        rows = [_row("Ana", 540, 8, "2026-07-01")]
        raw = build_workspace_time_csv(rows)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        header = text.splitlines()[0]
        self.assertIn("horas_extra", header)
        # La fila de 9h/8h debe reflejar 01:00 de exceso.
        self.assertIn("01:00", text.splitlines()[1])


if __name__ == "__main__":
    unittest.main()
