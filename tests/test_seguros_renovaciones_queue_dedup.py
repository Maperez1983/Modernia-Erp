import hashlib
import sqlite3
import unittest
from datetime import date, timedelta

import web.server as server


class SegurosRenovacionesQueueDedupTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE seguros (
              id TEXT PRIMARY KEY,
              empresa_id TEXT,
              cliente_id TEXT,
              tomador TEXT,
              compania TEXT,
              ramo TEXT,
              poliza_numero TEXT,
              prima_total REAL,
              comision REAL,
              porcentaje REAL,
              estado TEXT,
              estado_poliza TEXT,
              fecha_efecto TEXT,
              fecha_vencimiento TEXT,
              poliza_key TEXT,
              poliza_url TEXT,
              created_at TEXT,
              updated_at TEXT
            );
            CREATE TABLE seguros_renovaciones (
              id TEXT PRIMARY KEY,
              empresa_id TEXT NOT NULL,
              poliza_id TEXT,
              poliza_key TEXT NOT NULL,
              fecha_vencimiento TEXT NOT NULL,
              estado TEXT NOT NULL DEFAULT 'pendiente',
              responsable TEXT,
              proxima_accion_fecha TEXT,
              ultimo_contacto_fecha TEXT,
              notas TEXT,
              motivo_perdida TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE (empresa_id, poliza_key, fecha_vencimiento)
            );
            """
        )

    def tearDown(self):
        self.conn.close()

    def test_queue_dedups_by_normalized_policy_number(self):
        # Forzamos modo SQLite para que la normalización SQL use GLOB/SUBSTR (sin regex).
        server.db_is_postgres_enabled = lambda: False

        today = date.today()
        efecto = (today - timedelta(days=200)).isoformat()
        venc = (today + timedelta(days=10)).isoformat()

        # Mismo nº de póliza "real", escrito distinto. El segundo tiene PDF y updated_at más reciente,
        # debe ganar por ORDER BY (has_pdf DESC, sort_ts DESC).
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, tomador, compania, ramo, poliza_numero,
              prima_total, comision, porcentaje, estado, estado_poliza,
              fecha_efecto, fecha_vencimiento, poliza_key, poliza_url, created_at, updated_at
            ) VALUES (
              's1', 'e1', 'c1', 'Cliente', 'REALE', 'Hogar', 'P- 1',
              100.0, 10.0, 10.0, 'En vigor', '', ?, ?, '', '', ?, ?
            )
            """,
            (efecto, venc, today.isoformat(), (today - timedelta(days=1)).isoformat()),
        )
        self.conn.execute(
            """
            INSERT INTO seguros (
              id, empresa_id, cliente_id, tomador, compania, ramo, poliza_numero,
              prima_total, comision, porcentaje, estado, estado_poliza,
              fecha_efecto, fecha_vencimiento, poliza_key, poliza_url, created_at, updated_at
            ) VALUES (
              's2', 'e1', 'c1', 'Cliente', 'REALE', 'Hogar', 'P.1',
              100.0, 10.0, 10.0, 'En vigor', '', ?, ?, 'k', 'u', ?, ?
            )
            """,
            (efecto, venc, today.isoformat(), today.isoformat()),
        )

        # Emula la query + dedup del endpoint /api/seguros_renovaciones_queue.
        in_vigor_expr = server.in_vigor_policy_filter()
        fecha_efecto_date = server.seguro_date_sql("fecha_efecto", "s")
        fecha_venc_raw_date = server.seguro_date_sql("fecha_vencimiento", "s")
        fecha_venc_expr = (
            f"COALESCE({fecha_venc_raw_date}, "
            f"CASE WHEN {fecha_efecto_date} IS NOT NULL THEN DATE({fecha_efecto_date}, '+1 year') ELSE NULL END)"
        )
        compania_expr = "LOWER(TRIM(compania))"
        exclude_sin_seguro = f"({compania_expr} IS NULL OR {compania_expr} = '' OR {compania_expr} != 'sin seguro')"
        pdf_assoc_expr = "(NULLIF(TRIM(s.poliza_url), '') IS NOT NULL OR NULLIF(TRIM(s.poliza_key), '') IS NOT NULL)"
        poliza_norm_expr = (
            "REPLACE(REPLACE(REPLACE(REPLACE(LOWER(TRIM(COALESCE(s.poliza_numero, ''))), ' ', ''), '.', ''), '-', ''), '_', '')"
        )
        fecha_efecto_key = "SUBSTR(COALESCE(CAST(s.fecha_efecto AS TEXT), ''), 1, 10)"
        real_policy_key_expr = (
            f"CASE WHEN {poliza_norm_expr} <> '' THEN {poliza_norm_expr} ELSE "
            f"LOWER(TRIM(COALESCE(s.compania, ''))) || '|' || LOWER(TRIM(COALESCE(s.tomador, ''))) || '|' || {fecha_efecto_key} END"
        )

        rows = self.conn.execute(
            f"""
            SELECT
              s.id,
              {real_policy_key_expr} AS poliza_key_real,
              DATE({fecha_venc_expr}) AS fecha_vencimiento_norm,
              CASE WHEN {pdf_assoc_expr} THEN 1 ELSE 0 END AS has_pdf,
              COALESCE(s.updated_at, s.created_at) AS sort_ts
            FROM seguros s
            WHERE s.empresa_id = 'e1'
              AND {exclude_sin_seguro}
              AND {in_vigor_expr}
              AND {fecha_venc_expr} IS NOT NULL
              AND DATE({fecha_venc_expr}) BETWEEN DATE('now') AND DATE('now','+45 day')
            ORDER BY DATE({fecha_venc_expr}) ASC, has_pdf DESC, sort_ts DESC
            """,
        ).fetchall()

        seen = set()
        picked = []
        for row in rows:
            pol_key = (row["poliza_key_real"] or "").strip()
            venc_norm = (row["fecha_vencimiento_norm"] or "").strip()
            uniq = f"{pol_key}|{venc_norm}"
            if uniq in seen:
                continue
            seen.add(uniq)
            picked.append(dict(row))

        # Dedup => solo 1, y debe ser 's2' (tiene PDF y updated_at más reciente).
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0]["id"], "s2")

        # Inserta/actualiza la fila de renovaciones como hace el endpoint (modo SQLite).
        item = picked[0]
        rid = hashlib.sha1(f"e1|{item['poliza_key_real']}|{item['fecha_vencimiento_norm']}".encode("utf-8")).hexdigest()
        now = today.isoformat()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO seguros_renovaciones (
              id, empresa_id, poliza_id, poliza_key, fecha_vencimiento,
              estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, 'pendiente', datetime(?), datetime(?)
            )
            """,
            (rid, "e1", item["id"], item["poliza_key_real"], item["fecha_vencimiento_norm"], now, now),
        )
        self.conn.execute(
            """
            UPDATE seguros_renovaciones
            SET poliza_id = ?,
                updated_at = datetime(?)
            WHERE empresa_id = ?
              AND poliza_key = ?
              AND fecha_vencimiento = ?
            """,
            (item["id"], now, "e1", item["poliza_key_real"], item["fecha_vencimiento_norm"]),
        )
        row = self.conn.execute("SELECT * FROM seguros_renovaciones WHERE id = ?", (rid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["poliza_id"], "s2")


if __name__ == "__main__":
    unittest.main()

