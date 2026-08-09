#!/usr/bin/env python3
"""Rellena `inmuebles.workspace_id` en las fichas anteriores a ese campo.

Por qué
-------
81 de los 86 inmuebles de producción son anteriores al campo `workspace_id`. Ese
hueco es la raíz de media docena de fallos distintos que han ido apareciendo:

* un lead del portal Verifika2 no sabía a qué agencia pertenecía, y acababa en un
  workspace escrito a mano en el código;
* dar de alta un cliente desde una compraventa o una captación reventaba con un 500
  porque el ámbito no se podía deducir;
* toda guarda de permisos tiene que resolver el ámbito por empresa en vez de leerlo
  de la fila, que es más lento y más frágil.

Cada uno se ha ido parcheando por separado. Rellenar el campo cierra la categoría.

Cómo se decide
--------------
Por la empresa de la ficha, **descartando el workspace de plataforma** —el que
contiene la empresa técnica «Verifika2»—, que agrupa a todas las empresas y por eso
vuelve ambigua cualquier deducción. Sin él, cada empresa de producción cuelga de
exactamente un workspace: el de su agencia.

Si una ficha sigue siendo ambigua, **se deja como está**. Estampar el workspace
equivocado mezcla tenants en un CRM con datos personales; dejar el campo vacío
mantiene el comportamiento actual, que es el que ya funciona.

Uso
---
    python scripts/backfill_inmuebles_workspace.py            # ensayo, no escribe
    python scripts/backfill_inmuebles_workspace.py --aplicar  # escribe
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import (  # noqa: E402
    load_env_file,
    row_value,
    table_columns,
    workspaces_propios_de_empresa,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="escribe (por defecto sólo informa)")
    ap.add_argument("--backend", choices=("sqlite", "postgres"))
    ap.add_argument("--db", default="data/crm.sqlite")
    args = ap.parse_args()

    load_env_file()
    if args.backend:
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    conn = open_db_conn(args.db, with_row_factory=True)
    print(f"Base: {'Postgres' if backend == 'postgres' else 'SQLite ' + args.db}")
    print(f"Modo: {'APLICAR' if args.aplicar else 'ensayo (no escribe)'}\n")

    if "workspace_id" not in (table_columns(conn, "inmuebles") or set()):
        print("La tabla `inmuebles` no tiene columna workspace_id: nada que hacer.")
        return 0

    filas = conn.execute(
        """
        SELECT id, empresa_id, COALESCE(direccion, '') AS direccion
        FROM inmuebles
        WHERE COALESCE(TRIM(CAST(workspace_id AS TEXT)), '') = ''
        ORDER BY direccion
        """
    ).fetchall()
    print(f"Fichas sin workspace: {len(filas)}\n")
    if not filas:
        print("Nada que rellenar.")
        return 0

    # La deducción es por empresa, así que se resuelve una vez por empresa.
    cache = {}
    resueltas, ambiguas, sin_empresa = [], [], []
    for fila in filas:
        empresa_id = str(row_value(fila, "empresa_id", "") or "").strip()
        if not empresa_id:
            sin_empresa.append(fila)
            continue
        if empresa_id not in cache:
            cache[empresa_id] = workspaces_propios_de_empresa(conn, empresa_id)
        candidatos = cache[empresa_id]
        if len(candidatos) == 1:
            resueltas.append((fila, candidatos[0]))
        else:
            ambiguas.append((fila, candidatos))

    nombres = {}
    for _fila, ws in resueltas:
        if ws not in nombres:
            r = conn.execute("SELECT nombre FROM workspaces WHERE id = ? LIMIT 1", (ws,)).fetchone()
            nombres[ws] = str(row_value(r, "nombre", "") or ws) if r else ws

    reparto = Counter(nombres.get(ws, ws) for _f, ws in resueltas)
    print("Se pueden rellenar sin ambigüedad:")
    for nombre, cuantas in reparto.most_common():
        print(f"   {cuantas:>4}  ->  {nombre}")
    print(f"   {'-' * 24}\n   {len(resueltas):>4}  en total\n")

    if ambiguas:
        print(f"Se dejan como están por ambiguas ({len(ambiguas)}):")
        for fila, candidatos in ambiguas[:10]:
            print(f"   {str(row_value(fila, 'direccion', ''))[:40]:<42} {len(candidatos)} workspaces")
        print()
    if sin_empresa:
        print(f"Se dejan como están por no tener empresa ({len(sin_empresa)}).\n")

    if not args.aplicar:
        print("Ensayo. Repite con --aplicar para escribir.")
        return 0

    ahora = datetime.now(timezone.utc).isoformat()
    respaldo = RAIZ / "data" / f"backfill_inmuebles_workspace_{ahora[:19].replace(':', '')}.json"
    respaldo.parent.mkdir(parents=True, exist_ok=True)
    respaldo.write_text(
        json.dumps(
            [{"id": row_value(f, "id"), "empresa_id": row_value(f, "empresa_id"),
              "direccion": row_value(f, "direccion"), "workspace_id_nuevo": ws}
             for f, ws in resueltas],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Respaldo: {respaldo}")

    for fila, ws in resueltas:
        conn.execute(
            "UPDATE inmuebles SET workspace_id = ?, updated_at = ? WHERE id = ?",
            (ws, ahora, row_value(fila, "id")),
        )
    conn.commit()
    print(f"\nActualizadas {len(resueltas)} fichas.")

    quedan = conn.execute(
        "SELECT COUNT(*) AS n FROM inmuebles WHERE COALESCE(TRIM(CAST(workspace_id AS TEXT)), '') = ''"
    ).fetchone()
    print(f"Siguen sin workspace: {row_value(quedan, 'n', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
