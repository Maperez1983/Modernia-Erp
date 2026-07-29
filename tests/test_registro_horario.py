import sqlite3
import unittest

from web import server
from web.server import (
    compute_worked_minutes,
    build_workspace_time_summary,
    build_workspace_time_csv,
    log_workspace_registro_audit,
    verify_workspace_registro_audit_chain,
    log_rrhh_read_access,
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


class AuditChainTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        # Tabla mínima con las columnas de la cadena de integridad.
        self.conn.executescript(
            """
            CREATE TABLE workspace_registro_audit (
              id TEXT PRIMARY KEY, workspace_id TEXT, empresa_id TEXT, persona_id TEXT,
              entity_type TEXT, entity_id TEXT, action TEXT, actor_user_id TEXT, actor_nombre TEXT,
              before_json TEXT, after_json TEXT, created_at TEXT, prev_hash TEXT, integrity_hash TEXT
            );
            """
        )
        self.conn.commit()

    def _add(self, i):
        log_workspace_registro_audit(
            self.conn, "ws-1", persona_id="p1", entity_type="fichaje", entity_id=f"f{i}",
            action="update", actor={"user_id": "u1", "usuario": "admin"},
            before={"x": i}, after={"x": i + 1}, now=f"2026-07-29 10:0{i}:00",
        )

    def test_chain_valida_tras_varios_registros(self):
        for i in range(1, 4):
            self._add(i)
        self.conn.commit()
        res = verify_workspace_registro_audit_chain(self.conn, "ws-1")
        self.assertTrue(res["ok"])
        self.assertEqual(res["checked"], 3)

    def test_detecta_manipulacion_de_un_registro(self):
        for i in range(1, 4):
            self._add(i)
        self.conn.commit()
        # Manipular el contenido de un registro pasado (sin recalcular su hash) rompe la cadena.
        self.conn.execute("UPDATE workspace_registro_audit SET after_json = ? WHERE entity_id = 'f2'", ('{"x": 999}',))
        self.conn.commit()
        res = verify_workspace_registro_audit_chain(self.conn, "ws-1")
        self.assertFalse(res["ok"])
        self.assertIsNotNone(res["broken_at"])

    def test_detecta_borrado_de_un_registro(self):
        for i in range(1, 4):
            self._add(i)
        self.conn.commit()
        # Borrar un registro intermedio rompe el encadenamiento prev_hash.
        self.conn.execute("DELETE FROM workspace_registro_audit WHERE entity_id = 'f2'")
        self.conn.commit()
        res = verify_workspace_registro_audit_chain(self.conn, "ws-1")
        self.assertFalse(res["ok"])

    def test_log_lectura_registra_acceso_rgpd(self):
        # RGPD accountability: un acceso de lectura crea un registro con action='lectura'.
        log_rrhh_read_access(
            self.conn, "ws-1", {"user_id": "u1", "usuario": "gestor"},
            entity_type="ficha_rrhh", entity_id="p1", persona_id="p1",
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT action, entity_type, actor_user_id, persona_id FROM workspace_registro_audit WHERE workspace_id = 'ws-1' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], "lectura")
        self.assertEqual(row["entity_type"], "ficha_rrhh")
        self.assertEqual(row["actor_user_id"], "u1")
        # El acceso de lectura también entra en la cadena tamper-evident.
        self.assertTrue(verify_workspace_registro_audit_chain(self.conn, "ws-1")["ok"])


if __name__ == "__main__":
    unittest.main()
