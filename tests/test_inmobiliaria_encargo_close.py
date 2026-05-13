import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web import server


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class InmobiliariaEncargoCloseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "encargo_close.sqlite"
        server.ensure_tables(self.db_path)
        self.conn = server.open_sqlite_conn(str(self.db_path), with_row_factory=True)
        self.empresa_id = "emp-encargo"
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (self.empresa_id, "EMPRESA ENCARGO", now, now),
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

    def test_close_encargo_inserts_cierre_updates_estado_and_archives_pending_actions(self):
        now = _now_iso()
        inmueble_id = os.urandom(16).hex()
        self.conn.execute(
            """
            INSERT INTO inmuebles (
              id, empresa_id, referencia, direccion, tipo_operacion, tipo_inmueble, precio_objetivo, estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                inmueble_id,
                self.empresa_id,
                "TEST-ENCARGO-1",
                "CALLE TEST ENCARGO 1",
                "venta",
                "Piso",
                100000.0,
                "Encargo",
                now,
                now,
            ),
        )
        # Crea acciones pendientes (para validar archivado).
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

        res = server.close_inmueble_encargo_positive(
            self.conn,
            self.empresa_id,
            inmueble_id,
            now,
            usuario="tester",
            fecha_cierre="2026-05-12",
            importe_final=123456.78,
            numero_citas=7,
            tipo="Vendido",
            notas="Test cierre",
            archive_pending=True,
        )
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("tipo"), "Vendido")
        # Puede archivar también acciones "auto" creadas al mover etapa (checklist/pending defaults).
        self.assertGreaterEqual(int(res.get("archived") or 0), 2)
        self.assertTrue(res.get("cierre_id"))

        cierre = self.conn.execute(
            "SELECT * FROM inmueble_cierres WHERE id = ? LIMIT 1",
            (res["cierre_id"],),
        ).fetchone()
        self.assertIsNotNone(cierre)
        self.assertEqual(cierre["tipo"], "Vendido")
        self.assertEqual(cierre["fecha_cierre"], "2026-05-12")
        self.assertAlmostEqual(float(cierre["importe_final"]), 123456.78, places=2)
        self.assertEqual(int(cierre["numero_citas"]), 7)
        self.assertEqual(cierre["usuario"], "tester")

        inm = self.conn.execute(
            "SELECT estado FROM inmuebles WHERE id = ? LIMIT 1",
            (inmueble_id,),
        ).fetchone()
        self.assertEqual((inm["estado"] if inm else None), "Vendido")

        capt = self.conn.execute(
            "SELECT etapa FROM captaciones WHERE inmueble_id = ? AND empresa_id = ? LIMIT 1",
            (inmueble_id, self.empresa_id),
        ).fetchone()
        self.assertEqual((capt["etapa"] if capt else None), "Vendido")

        rows = self.conn.execute(
            "SELECT id, estado FROM acciones WHERE empresa_id = ? AND inmueble_id = ? ORDER BY id",
            (self.empresa_id, inmueble_id),
        ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        self.assertEqual(by_id[a1]["estado"], "Cancelada")
        self.assertEqual(by_id[a2]["estado"], "Cancelada")
        self.assertEqual(by_id[a3]["estado"], "Completada")


if __name__ == "__main__":
    unittest.main()
