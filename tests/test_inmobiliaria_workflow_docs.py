import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web import server
from web.server import (
    LEGAL_COPILOT_TOPICS,
    build_dgt_consulta_url,
    classify_legal_feed_entry,
    fetch_legal_radar_items,
    get_legal_copilot_catalog,
    get_legal_radar_sources_config,
    get_legal_copilot_topics,
    parse_legal_feed_entries,
    persist_generated_inmueble_pdf,
    resolve_legal_copilot_topic,
    scan_legal_radar_sources,
    sync_inmueble_stage_for_action,
    sync_legal_knowledge_updates,
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
            CREATE TABLE legal_radar_items (
              id TEXT PRIMARY KEY,
              area TEXT,
              fuente TEXT,
              referencia TEXT,
              titulo TEXT,
              fecha_publicacion TEXT,
              estado TEXT,
              impacto TEXT,
              topic_key TEXT,
              url TEXT,
              resumen TEXT,
              accion_recomendada TEXT,
              source_key TEXT,
              matched_keywords TEXT,
              auto_detected INTEGER DEFAULT 0,
              knowledge_synced_at TEXT,
              reviewed_at TEXT,
              reviewed_by TEXT,
              applied_at TEXT,
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

    def test_get_legal_copilot_catalog_returns_area_metadata(self):
        catalog = get_legal_copilot_catalog()
        area_keys = {item["key"] for item in catalog["areas"]}
        self.assertIn("inmobiliaria", area_keys)
        self.assertIn("gestoria", area_keys)

    def test_build_dgt_consulta_url_normalizes_reference(self):
        url = build_dgt_consulta_url("0542-23")
        self.assertEqual(url, "https://petete.tributos.hacienda.gob.es/consultas/?num_consulta=V0542-23")

    def test_fetch_legal_radar_items_sorts_pending_first_and_builds_summary(self):
        self.conn.execute(
            """
            INSERT INTO legal_radar_items (
              id, area, fuente, titulo, fecha_publicacion, estado, created_at, updated_at
            ) VALUES
              ('l1', 'inmobiliaria', 'BOE', 'Cambio 1', '2026-03-20', 'Aplicado', '2026-03-20', '2026-03-20'),
              ('l2', 'inmobiliaria', 'BOJA', 'Cambio 2', '2026-03-21', 'Pendiente', '2026-03-21', '2026-03-21'),
              ('l3', 'inmobiliaria', 'BOE', 'Cambio 3', '2026-03-22', 'Revisado', '2026-03-22', '2026-03-22')
            """
        )
        payload = fetch_legal_radar_items(self.conn, area="inmobiliaria", limit=10)
        self.assertEqual(payload["rows"][0]["id"], "l2")
        self.assertEqual(payload["summary"]["pendiente"], 1)
        self.assertEqual(payload["summary"]["revisado"], 1)
        self.assertEqual(payload["summary"]["aplicado"], 1)

    def test_get_legal_radar_sources_config_loads_editable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_path = Path(tmp) / "sources.json"
            source_path.write_text(
                """
                {
                  "version": 1,
                  "sources": [
                    {"key": "boe_test", "enabled": true, "feed_url": "https://example.test/feed.xml"}
                  ]
                }
                """,
                encoding="utf-8",
            )
            with patch.object(server, "LEGAL_RADAR_SOURCES_PATH", source_path):
                server.LEGAL_RADAR_SOURCES_CACHE["mtime"] = None
                server.LEGAL_RADAR_SOURCES_CACHE["payload"] = None
                payload = get_legal_radar_sources_config()
        self.assertEqual(payload["sources"][0]["key"], "boe_test")

    def test_parse_and_classify_legal_feed_entries(self):
        raw = b"""
        <rss version="2.0">
          <channel>
            <item>
              <title>Real Decreto-ley sobre arrendamientos urbanos y vivienda</title>
              <link>https://example.test/boe/1</link>
              <pubDate>Sat, 28 Mar 2026 09:00:00 GMT</pubDate>
              <description>Cambio en gastos de gestion inmobiliaria de arrendamiento de vivienda.</description>
              <guid>BOE-A-2026-12345</guid>
            </item>
          </channel>
        </rss>
        """
        source = {
            "key": "boe_general",
            "fuente": "BOE",
            "rules": [
                {
                    "topic_key": "contrato_privado_arrendamiento",
                    "keywords": ["arrendamientos urbanos", "gastos de gestion inmobiliaria"],
                    "impacto": "Alto",
                    "accion_recomendada": "Revisar contrato de arrendamiento.",
                }
            ],
        }
        entries = parse_legal_feed_entries(raw, source)
        self.assertEqual(len(entries), 1)
        detection = classify_legal_feed_entry("inmobiliaria", source, entries[0])
        self.assertEqual(detection["topic_key"], "contrato_privado_arrendamiento")
        self.assertEqual(detection["impacto"], "Alto")
        self.assertIn("arrendamientos urbanos", detection["matched_keywords"])

    def test_scan_legal_radar_sources_creates_items_and_syncs_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            legal_path = Path(tmp) / "legal.json"
            legal_path.write_text(
                json_dumps(
                    {
                        "version": 1,
                        "area": "inmobiliaria",
                        "topics": {
                            "contrato_privado_arrendamiento": {
                                "title": "Contrato privado de arrendamiento",
                                "summary": "Base",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            source_path = Path(tmp) / "sources.json"
            source_path.write_text(
                json_dumps(
                    {
                        "version": 1,
                        "area": "inmobiliaria",
                        "auto_sync_knowledge": True,
                        "sources": [
                            {
                                "key": "boe_test",
                                "fuente": "BOE",
                                "enabled": True,
                                "feed_url": "https://example.test/feed.xml",
                                "rules": [
                                    {
                                        "topic_key": "contrato_privado_arrendamiento",
                                        "keywords": ["arrendamientos urbanos"],
                                        "impacto": "Alto",
                                        "accion_recomendada": "Actualizar contrato.",
                                    }
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            raw = b"""
            <rss version="2.0"><channel><item>
              <title>Reforma de arrendamientos urbanos</title>
              <link>https://example.test/boe/2</link>
              <pubDate>2026-03-28</pubDate>
              <description>Actualizacion de arrendamientos urbanos.</description>
            </item></channel></rss>
            """
            with patch.object(server, "LEGAL_COPILOT_PATH", legal_path), patch.object(server, "LEGAL_RADAR_SOURCES_PATH", source_path), patch.object(
                server, "fetch_legal_feed_content", return_value=raw
            ):
                server.LEGAL_COPILOT_CACHE["mtime"] = None
                server.LEGAL_COPILOT_CACHE["topics"] = None
                server.LEGAL_RADAR_SOURCES_CACHE["mtime"] = None
                server.LEGAL_RADAR_SOURCES_CACHE["payload"] = None
                result = scan_legal_radar_sources(self.conn, area="inmobiliaria", now=self.now)
                self.assertEqual(result["created"], 1)
                self.assertEqual(result["knowledge_sync"]["synced"], 1)
                payload = json.loads(legal_path.read_text(encoding="utf-8"))
        updates = payload["topics"]["contrato_privado_arrendamiento"]["recent_updates"]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["accion_recomendada"], "Actualizar contrato.")


def json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    unittest.main()
