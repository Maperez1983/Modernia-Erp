#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import open_db_conn  # type: ignore


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normaliza inmuebles importados como 'Historico vendido' para que queden como 'Vendido' (inactivos)."
    )
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta de SQLite (ignorado si DATABASE_URL apunta a Postgres).")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios. Sin esto, solo simula.")
    parser.add_argument("--company", default="", help="Filtra por empresa (nombre exacto).")
    args = parser.parse_args()

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        empresa_id = ""
        if args.company:
            empresa = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.company,)).fetchone()
            if not empresa:
                raise SystemExit(f"Empresa no encontrada: {args.company}")
            empresa_id = str(empresa["id"])

        where = "LOWER(TRIM(COALESCE(estado, ''))) IN ('historico vendido', 'histórico vendido')"
        values: list[object] = []
        if empresa_id:
            where = f"empresa_id = ? AND {where}"
            values.append(empresa_id)

        rows = conn.execute(f"SELECT id, empresa_id, direccion, estado FROM inmuebles WHERE {where}", values).fetchall()
        if not rows:
            print({"updated": 0, "applied": bool(args.apply)})
            return 0

        timestamp = now_iso()
        if args.apply:
            conn.execute(
                f"UPDATE inmuebles SET estado = 'Vendido', updated_at = ? WHERE {where}",
                (timestamp, *values),
            )
            conn.commit()

        sample = [dict(row) for row in rows[:8]]
        print({"updated": len(rows), "sample": sample, "applied": bool(args.apply)})
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
