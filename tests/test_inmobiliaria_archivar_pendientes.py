import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web import server


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InmobiliariaArchivePendingActionsTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "archive.sqlite"
        server.ensure_tables(self.db_path)
        self.conn = server.open_sqlite_conn(str(self.db_path), with_row_factory=True)
        self.empresa_id = "emp-arch"
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (self.empresa_id, "EMPRESA ARCH", now, now),
        )
        self.conn.commit()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.tmpdir.cleanup()
        except Exception:
            pass

    def test_archive_pending_actions_marks_as_cancelada(self):
        now = _now_iso()
        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={"tipo_inmueble": "Piso", "direccion": "CALLE TEST 1", "precio_encargo": "100000"},
            now=now,
        )
        self.assertTrue(inmueble_id)

        a1 = os.urandom(16).hex()
        a2 = os.urandom(16).hex()
        a3 = os.urandom(16).hex()
        for aid, estado in ((a1, "Pendiente"), (a2, "Pendiente"), (a3, "Completada")):
            self.conn.execute(
                """
                INSERT INTO acciones (
                  id, empresa_id, servicio, inmueble_id, asunto, tipo, estado,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, 'inmobiliaria', ?, 'Acción test', 'Seguimiento', ?,
                  datetime(?), datetime(?)
                )
                """,
                (aid, self.empresa_id, inmueble_id, estado, now, now),
            )
        self.conn.commit()

        archived = server.archive_pending_inmueble_actions(
            self.conn, self.empresa_id, inmueble_id, now, usuario="test", reason="Archivado test"
        )
        self.assertEqual(archived, 2)

        rows = self.conn.execute(
            "SELECT id, estado, resultado_cierre FROM acciones WHERE empresa_id = ? AND inmueble_id = ? ORDER BY id",
            (self.empresa_id, inmueble_id),
        ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        self.assertEqual(by_id[a1]["estado"], "Cancelada")
        self.assertEqual(by_id[a2]["estado"], "Cancelada")
        self.assertEqual(by_id[a3]["estado"], "Completada")
        self.assertEqual(by_id[a1]["resultado_cierre"], "Archivado test")


if __name__ == "__main__":
    unittest.main()

