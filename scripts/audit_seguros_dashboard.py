#!/usr/bin/env python3
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def open_sqlite(db_path: str):
    from web import server  # noqa: E402

    # Fuerza modo SQLite incluso si hay DATABASE_URL en entorno local.
    server.db_is_postgres_enabled = lambda: False  # type: ignore[assignment]
    conn = server.open_sqlite_conn(db_path, with_row_factory=True)
    try:
        setattr(conn, "__crm_backend__", "sqlite")
    except Exception:
        pass
    return conn


def main():
    from web import server  # noqa: E402

    parser = argparse.ArgumentParser(description="Auditoría rápida de KPIs/renovaciones en CRM Seguros (SQLite).")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a SQLite.")
    parser.add_argument("--empresa-id", required=True, help="empresa_id.")
    parser.add_argument("--days", type=int, default=90, help="Ventana de renovaciones (default 90).")
    args = parser.parse_args()

    conn = open_sqlite(args.db)
    try:
        empresa_id = str(args.empresa_id).strip()
        days = max(7, min(int(args.days or 90), 365))
        today = datetime.now().date()
        next_days = today + timedelta(days=days)

        rows = conn.execute("SELECT * FROM seguros WHERE empresa_id = ?", (empresa_id,)).fetchall()
        out = {
            "empresa_id": empresa_id,
            "today": today.isoformat(),
            "kpis": defaultdict(int),
            "warnings": defaultdict(list),
        }

        for row in rows or []:
            d = dict(row)
            compania = (d.get("compania") or "").strip().lower()
            if compania == "sin seguro":
                continue

            out["kpis"]["total"] += 1
            poliza_num = str(d.get("poliza_numero") or "").strip()
            if poliza_num:
                out["kpis"]["total_con_numero"] += 1

            bucket = server.seguro_estado_bucket_value(d, today=today)
            if bucket == "en_vigor":
                out["kpis"]["en_vigor"] += 1
                if poliza_num:
                    out["kpis"]["en_vigor_con_numero"] += 1
                else:
                    out["kpis"]["en_vigor_sin_numero"] += 1
                    out["warnings"]["en_vigor_sin_numero"].append(d.get("id"))

                missing = []
                for key in ("tomador", "poliza_numero", "compania", "fecha_efecto"):
                    if not str(d.get(key) or "").strip():
                        missing.append(key)
                if missing:
                    out["kpis"]["faltantes"] += 1
                    out["warnings"]["faltantes"].append({"id": d.get("id"), "missing": missing})

            fecha_efecto = server.parse_iso_date(d.get("fecha_efecto"))
            fecha_venc = server.parse_iso_date(d.get("fecha_vencimiento"))
            if fecha_efecto and not fecha_venc:
                fecha_venc = fecha_efecto + timedelta(days=365)
            if bucket == "en_vigor" and fecha_venc:
                if today <= fecha_venc <= today + timedelta(days=30):
                    out["kpis"]["vencen_30"] += 1
                if fecha_venc < today:
                    out["warnings"]["en_vigor_vencida"].append({"id": d.get("id"), "venc": fecha_venc.isoformat()})
                if today <= fecha_venc <= next_days:
                    out["kpis"]["renovaciones_hasta_days"] += 1
            elif bucket == "en_vigor" and not fecha_venc:
                out["warnings"]["en_vigor_sin_vencimiento"].append(d.get("id"))

        # Limitamos muestras para que sea legible.
        for key, items in list(out["warnings"].items()):
            out["warnings"][key] = items[:100]
        out["kpis"] = dict(out["kpis"])
        out["warnings"] = dict(out["warnings"])
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

