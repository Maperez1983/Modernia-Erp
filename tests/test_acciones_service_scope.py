import sqlite3
import sys
import types
import unittest

if "PIL" not in sys.modules:
    pil_stub = types.ModuleType("PIL")
    pil_stub.Image = object()
    pil_stub.ImageDraw = object()
    pil_stub.ImageEnhance = object()
    pil_stub.ImageFilter = object()
    pil_stub.ImageFont = object()
    pil_stub.ImageOps = object()
    sys.modules["PIL"] = pil_stub

from web.server import build_acciones_service_where


class AccionesServiceScopeTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE acciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              workspace_id TEXT,
              servicio TEXT,
              inmueble_id TEXT,
              asesoramiento_id TEXT,
              related_tipo TEXT,
              tipo TEXT,
              fecha TEXT,
              hora TEXT
            );
            """
        )
        rows = [
            ("a1", "e1", "", "inmobiliaria", "", "", "", "Cita", "2026-06-10", "10:00"),
            ("a2", "e1", "", "Compraventa", "", "", "", "Cita adquisición", "2026-06-11", "10:00"),
            ("a3", "e1", "", "Alquiler", "", "", "", "Cita comprador", "2026-06-12", "10:00"),
            ("a4", "e1", "", "", "imm-1", "", "", "Seguimiento", "2026-06-13", "10:00"),
            ("a5", "e1", "", "", "", "", "captacion", "Llamada", "2026-06-14", "10:00"),
            ("a6", "e1", "", "", "", "", "", "Cita propietarios", "2026-06-15", "10:00"),
            ("a7", "e1", "", "seguros", "", "", "", "Renovación", "2026-06-16", "10:00"),
            ("a8", "e1", "", "", "", "", "", "Llamada general", "2026-06-17", "10:00"),
        ]
        self.conn.executemany(
            "INSERT INTO acciones (id, empresa_id, workspace_id, servicio, inmueble_id, asesoramiento_id, related_tipo, tipo, fecha, hora) VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def _ids_for_service(self, service: str) -> list[str]:
        where_sql, values = build_acciones_service_where("a", service)
        rows = self.conn.execute(
            f"SELECT id FROM acciones a WHERE {where_sql} ORDER BY fecha, hora"
            ,
            values,
        ).fetchall()
        return [str(row["id"]) for row in rows]

    def test_inmobiliaria_scope_recovers_legacy_service_labels_and_blank_rows(self):
        ids = self._ids_for_service("inmobiliaria")
        self.assertEqual(ids, ["a1", "a2", "a3", "a4", "a5", "a6"])

    def test_other_service_rows_are_not_leaked_into_inmobiliaria_agenda(self):
        ids = self._ids_for_service("inmobiliaria")
        self.assertNotIn("a7", ids)
        self.assertNotIn("a8", ids)

    def test_financiaciones_scope_accepts_legacy_hipotecas_label(self):
        self.conn.execute(
            "INSERT INTO acciones (id, empresa_id, workspace_id, servicio, inmueble_id, asesoramiento_id, related_tipo, tipo, fecha, hora) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("f1", "e1", "", "Hipotecas Modernia", "", "", "", "Cita", "2026-06-18", "09:00"),
        )
        self.conn.execute(
            "INSERT INTO acciones (id, empresa_id, workspace_id, servicio, inmueble_id, asesoramiento_id, related_tipo, tipo, fecha, hora) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("f2", "e1", "", "", "", "", "hipoteca", "Llamada", "2026-06-19", "09:00"),
        )
        self.conn.commit()
        ids = self._ids_for_service("financiaciones")
        self.assertIn("f1", ids)
        self.assertIn("f2", ids)


if __name__ == "__main__":
    unittest.main()
