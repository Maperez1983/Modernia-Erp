import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from web import server


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _make_pdf_bytes(title="Smoke"):
    header = f"%PDF-1.4\n% Smoke: {title}\n".encode("utf-8", "ignore")
    body = b"1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    return header + body


class InmobiliariaCrmSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "smoke.sqlite"
        # En local suele existir `DATABASE_URL` (Render). Para tests queremos forzar SQLite
        # pasando un `Path` a `ensure_tables()`.
        server.ensure_tables(self.db_path)
        self.conn = server.open_sqlite_conn(str(self.db_path), with_row_factory=True)
        self.empresa_id = "emp-smoke"
        self.workspace_id = "ws-smoke"
        now = _now_iso()
        self.conn.execute(
            """
            INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
            VALUES (?, ?, 1, datetime(?), datetime(?))
            """,
            (self.empresa_id, "EMPRESA SMOKE", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO workspaces (id, nombre, slug, estado, plan, created_at, updated_at)
            VALUES (?, ?, ?, 'Activo', 'Enterprise', datetime(?), datetime(?))
            """,
            (self.workspace_id, "WORKSPACE SMOKE", "workspace-smoke", now, now),
        )
        self.conn.execute(
            """
            INSERT INTO workspace_empresas (id, workspace_id, empresa_id, rol, created_at, updated_at)
            VALUES (?, ?, ?, 'Operadora', datetime(?), datetime(?))
            """,
            (os.urandom(16).hex(), self.workspace_id, self.empresa_id, now, now),
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

    def test_create_inmueble_agenda_and_pdf(self):
        now = _now_iso()
        cliente_id = server.ensure_cliente_for_inmobiliaria(
            self.conn,
            self.empresa_id,
            nombre="PROPIETARIO TEST",
            nif="12345678Z",
            now=now,
            extra={"telefono": "600000000", "email": "prop@test.local"},
        )
        self.assertTrue(cliente_id)

        inmueble_id = server.ensure_inmueble_for_compraventa(
            self.conn,
            self.empresa_id,
            payload={
                "tipo_inmueble": "Piso",
                "direccion": "CALLE FALSA 123",
                "referencia_catastral": "1234567UF7613S0001AB",
                "precio_encargo": "250000",
            },
            now=now,
        )
        self.assertTrue(inmueble_id)

        server.ensure_inmueble_propietario_link(self.conn, inmueble_id, cliente_id, now)
        cap_id = server.ensure_captacion_for_inmueble(self.conn, self.empresa_id, inmueble_id, now)
        self.assertTrue(cap_id)

        server.ensure_inmueble_checklist_defaults_if_empty(
            self.conn, inmueble_id, etapa="captacion", now=now, responsable="SMOKE"
        )
        server.ensure_pending_inmueble_stage_actions(
            self.conn, self.empresa_id, inmueble_id, etapa="captacion", now=now, responsable="SMOKE"
        )

        server.sync_inmueble_stage_for_action(self.conn, inmueble_id, destino="encargo", now=now)

        doc_row = server.persist_generated_inmueble_pdf(
            self.conn,
            inmueble_id=inmueble_id,
            tipo="hoja_visita",
            nombre="Hoja de visita (smoke)",
            pdf_bytes=_make_pdf_bytes("Hoja visita · Smoke"),
            filename_base="hoja_visita_smoke",
            now=now,
            replace_existing=False,
            empresa_id=self.empresa_id,
            usuario="smoke",
            plantilla_clave="hoja_visita",
            origen_tipo="smoke",
            origen_id=inmueble_id,
            payload_json={"source": "test"},
        )
        self.assertTrue(doc_row and doc_row.get("url"))


if __name__ == "__main__":
    unittest.main()

