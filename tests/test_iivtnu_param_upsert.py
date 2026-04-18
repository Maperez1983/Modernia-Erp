import json
import sqlite3
import unittest
from datetime import date

from web.server import _iivtnu_upsert_param_set, ensure_iivtnu_schema


class IivtnuParamUpsertTests(unittest.TestCase):
    def test_upsert_param_set_inserts_and_updates(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        ensure_iivtnu_schema(conn)
        conn.execute(
            """
            INSERT INTO iivtnu_municipios (ine, nombre, provincia, comunidad, es_capital, created_at, updated_at)
            VALUES ('29067','Málaga','Málaga','Andalucía',1,'2025-01-01','2025-01-01')
            """
        )
        bonif_json = json.dumps({"bonificacion_pct": 50.0})
        res1 = _iivtnu_upsert_param_set(conn, "29067", date(2025, 3, 10), 29.0, bonificaciones_json=bonif_json, source_label="PDF")
        self.assertEqual(res1["action"], "inserted")
        row = conn.execute("SELECT tipo_gravamen_pct, bonificaciones_json FROM iivtnu_param_sets WHERE id = ?", (res1["id"],)).fetchone()
        self.assertIsNotNone(row)
        self.assertAlmostEqual(float(row["tipo_gravamen_pct"]), 29.0, places=3)

        res2 = _iivtnu_upsert_param_set(conn, "29067", date(2025, 7, 1), 30.0, bonificaciones_json=None, source_label="Manual")
        self.assertEqual(res2["action"], "updated")
        row2 = conn.execute("SELECT tipo_gravamen_pct FROM iivtnu_param_sets WHERE id = ?", (res2["id"],)).fetchone()
        self.assertAlmostEqual(float(row2["tipo_gravamen_pct"]), 30.0, places=3)

