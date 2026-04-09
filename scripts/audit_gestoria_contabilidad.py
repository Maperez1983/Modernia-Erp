#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def open_pg():
    from web.db_backend import open_postgres_conn  # noqa: E402

    return open_postgres_conn(with_row_factory=True)


def main():
    parser = argparse.ArgumentParser(description="Audita gestoria_contabilidad en Postgres.")
    parser.add_argument("--empresa-id", default="", help="Filtra por empresa_id.")
    parser.add_argument("--limit", type=int, default=20, help="Nº de filas a mostrar (default 20).")
    args = parser.parse_args()
    limit = max(1, min(int(args.limit or 20), 200))

    conn = open_pg()
    try:
        if args.empresa_id:
            empresa_id = str(args.empresa_id).strip()
            row = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       MIN(COALESCE(NULLIF(TRIM(fecha), ''), created_at)) AS min_fecha,
                       MAX(COALESCE(NULLIF(TRIM(fecha), ''), created_at)) AS max_fecha
                FROM gestoria_contabilidad
                WHERE empresa_id = ?
                """,
                (empresa_id,),
            ).fetchone()
            total = int((row or {}).get("total") or 0)
            print(f"empresa_id={empresa_id}")
            print(f"total_rows={total}")
            print(f"min_fecha={((row or {}).get('min_fecha') or '')}")
            print(f"max_fecha={((row or {}).get('max_fecha') or '')}")
            rows = conn.execute(
                """
                SELECT id, fecha, concepto, gestion, tipo, importe, notas,
                       cliente_id, seguro_id, hipoteca_id, created_at, updated_at
                FROM gestoria_contabilidad
                WHERE empresa_id = ?
                ORDER BY COALESCE(NULLIF(TRIM(fecha), ''), created_at) DESC
                LIMIT ?
                """,
                (empresa_id, limit),
            ).fetchall()
            print("latest:")
            for r in rows:
                d = dict(r)
                print(
                    f"- {d.get('fecha') or d.get('created_at')}"
                    f" tipo={d.get('tipo')!s}"
                    f" importe={d.get('importe')!s}"
                    f" gestion={d.get('gestion')!s}"
                    f" concepto={d.get('concepto')!s}"[:220]
                )
            return

        rows = conn.execute(
            """
            SELECT empresa_id,
                   COUNT(*) AS total,
                   MIN(COALESCE(NULLIF(TRIM(fecha), ''), created_at)) AS min_fecha,
                   MAX(COALESCE(NULLIF(TRIM(fecha), ''), created_at)) AS max_fecha
            FROM gestoria_contabilidad
            GROUP BY empresa_id
            ORDER BY total DESC
            LIMIT 50
            """
        ).fetchall()
        print(f"empresas_con_asientos={len(rows)}")
        for r in rows:
            d = dict(r)
            print(
                f"- empresa_id={d.get('empresa_id')} total={d.get('total')} "
                f"min={d.get('min_fecha')} max={d.get('max_fecha')}"
            )
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

