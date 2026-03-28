import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web import server
from web.server import (
    LEGAL_COPILOT_TOPICS,
    get_legal_copilot_topics,
    persist_generated_inmueble_pdf,
    resolve_legal_copilot_topic,
    sync_inmueble_stage_for_action,
)


class InmobiliariaWorkflowDocsTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE inmueble_docs (
              id TEXT PRIMARY KEY,
              inmueble_id TEXT NOT NULL,
              nombre TEXT,
              url TEXT,
              tipo TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE inmuebles (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              tipo_inmueble TEXT,
              direccion TEXT,
              codigo_postal TEXT,
              poblacion TEXT,
              provincia TEXT,
              zona TEXT,
              m2 REAL,
              habitaciones INTEGER,
              banos INTEGER,
              precio_objetivo REAL,
              precio_valoracion REAL,
              estado TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE captaciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              inmueble_id TEXT,
              propietario TEXT,
              tipo_inmueble TEXT,
              direccion TEXT,
              codigo_postal TEXT,
              poblacion TEXT,
              provincia TEXT,
              zona TEXT,
              m2 REAL,
              habitaciones INTEGER,
              banos INTEGER,
              precio_objetivo REAL,
              precio_valoracion REAL,
              etapa TEXT,
              situacion_comercial TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            """
        )
        self.conn.execute(
            """
            INSERT INTO inmuebles (
              id, empresa_id, tipo_inmueble, direccion, codigo_postal, poblacion, provincia,
              zona, m2, habitaciones, banos, precio_objetivo, precio_valoracion, estado,
              created_at, updated_at
            ) VALUES (
              'i1', 'e1', 'Piso', 'Calle Prueba 1', '29001', 'Málaga', 'Málaga',
              'Centro', 80, 3, 2, 250000, 240000, 'Noticia', '2026-03-28', '2026-03-28'
            )
            """
        )
        self.now = "2026-03-28T10:00:00+00:00"

    def tearDown(self):
        self.conn.close()

    def test_persist_generated_inmueble_pdf_creates_file_and_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            with patch.object(server, "UPLOADS", upload_root):
                result = persist_generated_inmueble_pdf(
                    self.conn,
                    "i1",
                    "Hoja de visita",
                    "Hoja de visita · Calle Prueba 1",
                    b"%PDF-1.4 fake",
                    "hoja_visita_prueba",
                    self.now,
                    replace_existing=True,
                )
                self.assertIsNotNone(result)
                self.assertTrue(Path(result["path"]).exists())
                self.assertTrue(result["url"].startswith("/uploads/inmuebles/generated/"))
        doc = self.conn.execute(
            "SELECT nombre, url, tipo FROM inmueble_docs WHERE inmueble_id = 'i1' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(doc)
        self.assertEqual(doc["tipo"], "Hoja de visita")
        self.assertEqual(doc["url"], result["url"])

    def test_persist_generated_inmueble_pdf_replace_existing_reuses_doc_and_removes_old_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            upload_root = Path(tmp)
            with patch.object(server, "UPLOADS", upload_root):
                first = persist_generated_inmueble_pdf(
                    self.conn,
                    "i1",
                    "Ficha venta",
                    "Ficha venta · Calle Prueba 1",
                    b"%PDF old",
                    "ficha_venta_prueba",
                    self.now,
                    replace_existing=True,
                )
                first_path = Path(first["path"])
                second = persist_generated_inmueble_pdf(
                    self.conn,
                    "i1",
                    "Ficha venta",
                    "Ficha venta · Calle Prueba 1",
                    b"%PDF new",
                    "ficha_venta_prueba",
                    self.now,
                    replace_existing=True,
                )
                self.assertEqual(first["id"], second["id"])
                self.assertTrue(Path(second["path"]).exists())
                self.assertEqual(Path(second["path"]).read_bytes(), b"%PDF new")
        total = self.conn.execute(
            "SELECT COUNT(*) AS total FROM inmueble_docs WHERE inmueble_id = 'i1' AND tipo = 'Ficha venta'"
        ).fetchone()["total"]
        self.assertEqual(total, 1)

    def test_sync_inmueble_stage_for_action_creates_captacion_and_updates_both_entities(self):
        sync_inmueble_stage_for_action(self.conn, "i1", "adquisicion", self.now)
        inmueble = self.conn.execute("SELECT estado FROM inmuebles WHERE id = 'i1'").fetchone()
        captacion = self.conn.execute(
            "SELECT etapa, situacion_comercial FROM captaciones WHERE inmueble_id = 'i1' LIMIT 1"
        ).fetchone()
        self.assertIsNotNone(captacion)
        self.assertEqual(inmueble["estado"], "Adquisición")
        self.assertEqual(captacion["etapa"], "Adquisición")
        self.assertEqual(captacion["situacion_comercial"], "Adquisición")

    def test_resolve_legal_copilot_topic_supports_keywords(self):
        topic_key, payload = resolve_legal_copilot_topic(
            "inmobiliaria",
            "",
            "Que riesgos tiene el contrato privado de arrendamiento y qué documento va después",
        )
        self.assertEqual(topic_key, "contrato_privado_arrendamiento")
        self.assertEqual(payload["title"], LEGAL_COPILOT_TOPICS["contrato_privado_arrendamiento"]["title"])

    def test_get_legal_copilot_topics_loads_editable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            legal_path = Path(tmp) / "legal.json"
            legal_path.write_text(
                """
                {
                  "topics": {
                    "encargo_venta": {
                      "title": "Encargo editable",
                      "summary": "Texto desde JSON"
                    }
                  }
                }
                """,
                encoding="utf-8",
            )
            with patch.object(server, "LEGAL_COPILOT_PATH", legal_path):
                server.LEGAL_COPILOT_CACHE["mtime"] = None
                server.LEGAL_COPILOT_CACHE["topics"] = None
                topics = get_legal_copilot_topics()
        self.assertEqual(topics["encargo_venta"]["title"], "Encargo editable")


if __name__ == "__main__":
    unittest.main()
