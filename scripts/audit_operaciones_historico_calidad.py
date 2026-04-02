#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import open_db_conn  # type: ignore


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except Exception:
        return None
    return num


def pick_sale_price(row: dict) -> float | None:
    for key in ("precio_contrato", "precio_propuesta", "precio_escritura"):
        num = safe_float(row.get(key))
        if num is not None and num >= 10_000:
            return num
    return None


def truthy_text(value) -> bool:
    return bool(str(value or "").strip())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita calidad de operaciones inmobiliarias históricas (campos clave + % completitud)."
    )
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta de SQLite (ignorado si DATABASE_URL apunta a Postgres).")
    parser.add_argument("--company", required=True, help="Empresa (nombre exacto).")
    parser.add_argument("--out", default="reports/audit_operaciones_historico.csv", help="CSV salida.")
    parser.add_argument("--year-from", type=int, default=0, help="Filtra desde año (inclusive).")
    parser.add_argument("--year-to", type=int, default=0, help="Filtra hasta año (inclusive).")
    parser.add_argument("--only-missing", action="store_true", help="Exporta solo filas con faltantes.")
    args = parser.parse_args()

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.company,)).fetchone()
        if not empresa:
            raise SystemExit(f"Empresa no encontrada: {args.company}")
        empresa_id = empresa["id"]

        where = ["empresa_id = ?", "estado = ?", "LOWER(COALESCE(tipo_operacion,'venta')) = 'venta'"]
        values: list[object] = [empresa_id, "Importado historico"]
        if args.year_from:
            where.append("COALESCE(anio, 0) >= ?")
            values.append(int(args.year_from))
        if args.year_to:
            where.append("COALESCE(anio, 0) <= ?")
            values.append(int(args.year_to))
        where_sql = " AND ".join(where)

        rows = conn.execute(
            f"""
            SELECT
              id, direccion, anio, mes,
              referencia_catastral,
              propietario1_nombre, propietario1_nif,
              propietario2_nombre, propietario2_nif,
              contraparte_nombre, contraparte_nif,
              fecha_encargo, fecha_propuesta, fecha_contrato, fecha_escritura, fecha_operacion,
              precio_encargo, precio_propuesta, precio_contrato, precio_escritura,
              honorarios, num_visitas,
              estado_documental, calidad_ocr,
              doc_nota_encargo_path, doc_propuesta_path, doc_escritura_path, doc_nota_simple_path
            FROM operaciones_inmobiliarias
            WHERE {where_sql}
            ORDER BY COALESCE(anio, 0), COALESCE(mes, ''), direccion
            """,
            values,
        ).fetchall()

        if not rows:
            print({"company": args.company, "rows": 0})
            return 0

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        per_bucket = defaultdict(lambda: defaultdict(int))
        exported = 0
        with out_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "anio",
                    "mes",
                    "direccion",
                    "referencia_catastral",
                    "propietarios",
                    "compradores",
                    "fecha_encargo",
                    "fecha_escritura",
                    "precio_encargo",
                    "precio_venta",
                    "precio_propuesta",
                    "precio_contrato",
                    "precio_escritura",
                    "estado_documental",
                    "calidad_ocr",
                    "missing_propietario",
                    "missing_comprador",
                    "missing_fecha_escritura",
                    "missing_precio_venta",
                    "missing_catastro",
                    "missing_doc_escritura",
                    "missing_doc_propuesta",
                    "missing_doc_encargo",
                    "doc_nota_encargo_path",
                    "doc_propuesta_path",
                    "doc_escritura_path",
                    "updated_at",
                ],
            )
            writer.writeheader()

            for raw in rows:
                row = dict(raw)
                bucket = f"{row.get('anio') or ''}-{str(row.get('mes') or '').strip() or ''}".strip("-") or "unknown"
                per_bucket[bucket]["total"] += 1

                propietarios = " | ".join([p for p in [row.get("propietario1_nombre"), row.get("propietario2_nombre")] if truthy_text(p)])
                compradores = str(row.get("contraparte_nombre") or "").strip()
                sale_price = pick_sale_price(row)

                missing_prop = not truthy_text(propietarios)
                missing_buy = not truthy_text(compradores)
                missing_escrit = not truthy_text(row.get("fecha_escritura"))
                missing_sale = sale_price is None
                missing_cat = not truthy_text(row.get("referencia_catastral"))
                missing_doc_escrit = not truthy_text(row.get("doc_escritura_path"))
                missing_doc_prop = not truthy_text(row.get("doc_propuesta_path"))
                missing_doc_enc = not truthy_text(row.get("doc_nota_encargo_path"))

                if not missing_prop:
                    per_bucket[bucket]["con_propietario"] += 1
                if not missing_buy:
                    per_bucket[bucket]["con_comprador"] += 1
                if not missing_escrit:
                    per_bucket[bucket]["con_fecha_escritura"] += 1
                if not missing_sale:
                    per_bucket[bucket]["con_precio_venta"] += 1
                if not missing_cat:
                    per_bucket[bucket]["con_catastro"] += 1

                has_missing = any([missing_prop, missing_buy, missing_escrit, missing_sale, missing_cat, missing_doc_escrit])
                if args.only_missing and not has_missing:
                    continue

                writer.writerow(
                    {
                        "anio": row.get("anio") or "",
                        "mes": row.get("mes") or "",
                        "direccion": row.get("direccion") or "",
                        "referencia_catastral": row.get("referencia_catastral") or "",
                        "propietarios": propietarios,
                        "compradores": compradores,
                        "fecha_encargo": row.get("fecha_encargo") or "",
                        "fecha_escritura": row.get("fecha_escritura") or "",
                        "precio_encargo": row.get("precio_encargo") if row.get("precio_encargo") is not None else "",
                        "precio_venta": sale_price if sale_price is not None else "",
                        "precio_propuesta": row.get("precio_propuesta") if row.get("precio_propuesta") is not None else "",
                        "precio_contrato": row.get("precio_contrato") if row.get("precio_contrato") is not None else "",
                        "precio_escritura": row.get("precio_escritura") if row.get("precio_escritura") is not None else "",
                        "estado_documental": row.get("estado_documental") or "",
                        "calidad_ocr": row.get("calidad_ocr") or "",
                        "missing_propietario": int(missing_prop),
                        "missing_comprador": int(missing_buy),
                        "missing_fecha_escritura": int(missing_escrit),
                        "missing_precio_venta": int(missing_sale),
                        "missing_catastro": int(missing_cat),
                        "missing_doc_escritura": int(missing_doc_escrit),
                        "missing_doc_propuesta": int(missing_doc_prop),
                        "missing_doc_encargo": int(missing_doc_enc),
                        "doc_nota_encargo_path": row.get("doc_nota_encargo_path") or "",
                        "doc_propuesta_path": row.get("doc_propuesta_path") or "",
                        "doc_escritura_path": row.get("doc_escritura_path") or "",
                        "updated_at": now_iso(),
                    }
                )
                exported += 1

        summary = {"rows": len(rows), "exported": exported, "out": str(out_path)}
        print(summary)
        # Print per bucket stats (compact)
        for bucket, stats in sorted(per_bucket.items()):
            total = stats["total"] or 0
            if not total:
                continue
            line = {
                "bucket": bucket,
                "total": total,
                "pct_propietario": round((stats["con_propietario"] / total) * 100.0, 1),
                "pct_comprador": round((stats["con_comprador"] / total) * 100.0, 1),
                "pct_fecha_escritura": round((stats["con_fecha_escritura"] / total) * 100.0, 1),
                "pct_precio_venta": round((stats["con_precio_venta"] / total) * 100.0, 1),
                "pct_catastro": round((stats["con_catastro"] / total) * 100.0, 1),
            }
            print(line)
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
