#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import open_db_conn  # type: ignore


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def pick_precio_venta(row: dict) -> float | None:
    for key in ("precio_contrato", "precio_propuesta", "precio_escritura"):
        val = row.get(key)
        try:
            num = float(val) if val is not None else None
        except Exception:
            num = None
        if num is not None and num >= 10_000:
            return num
    return None


def calc_desviacion(precio_encargo: float | None, precio_venta: float | None) -> tuple[float | None, float | None]:
    if precio_encargo is None or precio_venta is None or precio_encargo == 0:
        return None, None
    desv = round(precio_encargo - precio_venta, 2)
    pct = round(((precio_encargo - precio_venta) / precio_encargo) * 100.0, 2)
    return desv, pct


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normaliza operaciones históricas: elimina señales/arras (<10.000€) de precio_propuesta y recalcula desviación."
    )
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta de SQLite (ignorado si DATABASE_URL apunta a Postgres).")
    parser.add_argument("--company", default="", help="Filtra por empresa (nombre exacto).")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios. Sin esto, solo simula.")
    parser.add_argument("--only-historico", action="store_true", help="Solo estado='Importado historico'.")
    args = parser.parse_args()

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        empresa_id = ""
        if args.company:
            empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.company,)).fetchone()
            if not empresa:
                raise SystemExit(f"Empresa no encontrada: {args.company}")
            empresa_id = str(empresa["id"] if isinstance(empresa, dict) else empresa[0])

        where = [
            "LOWER(COALESCE(tipo_operacion, 'venta')) = 'venta'",
        ]
        values: list[object] = []
        if empresa_id:
            where.append("empresa_id = ?")
            values.append(empresa_id)
        if args.only_historico:
            where.append("estado = ?")
            values.append("Importado historico")
        where_sql = " AND ".join(where)

        rows = conn.execute(
            f"""
            SELECT id, empresa_id, direccion, precio_encargo, precio_propuesta, precio_contrato, precio_escritura,
                   desviacion_euros, desviacion_pct
            FROM operaciones_inmobiliarias
            WHERE {where_sql}
            ORDER BY COALESCE(NULLIF(fecha_escritura, ''), NULLIF(fecha_operacion, ''), updated_at, created_at) DESC
            """,
            values,
        ).fetchall()

        touched = []
        ts = now_iso()
        for raw in rows:
            row = dict(raw)
            precio_propuesta = row.get("precio_propuesta")
            try:
                pp = float(precio_propuesta) if precio_propuesta is not None else None
            except Exception:
                pp = None
            update: dict[str, object] = {}
            if pp is not None and pp < 10_000:
                update["precio_propuesta"] = None
                row["precio_propuesta"] = None

            precio_venta = pick_precio_venta(row)
            try:
                pe = float(row.get("precio_encargo")) if row.get("precio_encargo") is not None else None
            except Exception:
                pe = None
            desv, pct = calc_desviacion(pe, precio_venta)
            if desv is not None or pct is not None:
                update["desviacion_euros"] = desv
                update["desviacion_pct"] = pct
            # Si antes había desviación y ya no procede (faltan precios), limpiamos.
            if (desv is None and pct is None) and (row.get("desviacion_euros") is not None or row.get("desviacion_pct") is not None):
                update["desviacion_euros"] = None
                update["desviacion_pct"] = None

            if update:
                update["updated_at"] = ts
                touched.append(
                    {
                        "id": row.get("id"),
                        "direccion": row.get("direccion"),
                        "update": update,
                    }
                )
                if args.apply:
                    set_clause = ", ".join(f"{k} = ?" for k in update.keys())
                    conn.execute(
                        f"UPDATE operaciones_inmobiliarias SET {set_clause} WHERE id = ?",
                        (*update.values(), row.get("id")),
                    )

        if args.apply and touched:
            conn.commit()
        print({"updated": len(touched), "sample": touched[:8], "applied": bool(args.apply)})
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
