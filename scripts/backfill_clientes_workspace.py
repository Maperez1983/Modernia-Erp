#!/usr/bin/env python3
"""Rellena `clientes.workspace_id` (y el de `clientes_empresas`) para el tenant.

Contexto
--------
El ámbito de un cliente es el workspace, pero `clientes.workspace_id` no existía:
ni en `schema.sql` ni por migración. El scope se deducía de `clientes_empresas` y
del `empresa_id`, así que cualquier cliente sin ese vínculo desaparecía de todas
las listas de CRM aunque siguiera en la tabla. Verificado en producción el
2026-07-30: 2014 clientes en la tabla y 0 devueltos al acotar por workspace.

Qué hace
--------
1. Resuelve el workspace de cada cliente por sus vínculos en `clientes_empresas`
   (empresa -> empresas del workspace). Es la señal más fuerte que hay.
2. A los que no tienen vínculo les asigna `--workspace-id`, el tenant por defecto.
3. Rellena también `clientes_empresas.workspace_id` cuando está vacío.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada, solo informa.
- Reversible: antes de tocar nada guarda `(cliente_id, workspace_id)` en la tabla
  `clientes_workspace_backfill_backup`. `--rollback` restaura desde ahí.
- Idempotente: solo toca filas con el valor vacío, así que repetirlo no hace daño.
- Nunca sobreescribe un `workspace_id` que ya tenga valor.

Uso
---
    python scripts/backfill_clientes_workspace.py --db data/crm.sqlite \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0            # informe
    python scripts/backfill_clientes_workspace.py --db ... --workspace-id ... --apply
    python scripts/backfill_clientes_workspace.py --db ... --rollback --apply
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

BACKUP_TABLE = "clientes_workspace_backfill_backup"


def table_columns(conn, table):
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def resolve_by_links(conn):
    """cliente_id -> workspace_id deducido de las empresas vinculadas.

    Solo aceptamos el vínculo cuando es inequívoco: si un cliente cuelga de
    empresas de dos workspaces distintos no adivinamos, lo dejamos para el
    tenant por defecto y lo contamos aparte.
    """
    ce_cols = table_columns(conn, "clientes_empresas")
    if "workspace_id" not in ce_cols:
        return {}, set()
    rows = conn.execute(
        f"""
        SELECT cliente_id, workspace_id
        FROM clientes_empresas
        WHERE COALESCE(workspace_id, '') <> ''
        """
    ).fetchall()
    candidatos = {}
    for cliente_id, ws in rows:
        candidatos.setdefault(str(cliente_id), set()).add(str(ws))
    resueltos = {c: next(iter(w)) for c, w in candidatos.items() if len(w) == 1}
    ambiguos = {c for c, w in candidatos.items() if len(w) > 1}
    return resueltos, ambiguos


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Ruta de la base SQLite.")
    parser.add_argument(
        "--workspace-id",
        help="Workspace por defecto para los clientes sin vínculo resoluble.",
    )
    parser.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    parser.add_argument("--rollback", action="store_true", help="Restaura desde la tabla de respaldo.")
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA foreign_keys = ON")

    if "workspace_id" not in table_columns(conn, "clientes"):
        print("ERROR: `clientes` no tiene columna workspace_id. Arranca el servidor una vez", file=sys.stderr)
        print("       para que la migración la cree, y vuelve a lanzar esto.", file=sys.stderr)
        return 2

    if args.rollback:
        if BACKUP_TABLE not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
            print(f"No hay tabla {BACKUP_TABLE}: nada que revertir.")
            return 0
        filas = conn.execute(f"SELECT cliente_id, workspace_id FROM {BACKUP_TABLE}").fetchall()
        print(f"Restaurando {len(filas)} clientes a su valor previo.")
        if args.apply:
            for cliente_id, ws in filas:
                conn.execute(
                    "UPDATE clientes SET workspace_id = ? WHERE id = ?",
                    (ws, cliente_id),
                )
            conn.commit()
            print("Revertido.")
        else:
            print("En seco: nada escrito. Añade --apply.")
        return 0

    if not args.workspace_id:
        print("ERROR: hace falta --workspace-id (o --rollback).", file=sys.stderr)
        return 2

    pendientes = conn.execute(
        "SELECT id FROM clientes WHERE COALESCE(workspace_id, '') = ''"
    ).fetchall()
    pendientes = [str(r[0]) for r in pendientes]
    total = conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0]

    por_vinculo, ambiguos = resolve_by_links(conn)
    asignaciones = {}
    for cliente_id in pendientes:
        asignaciones[cliente_id] = por_vinculo.get(cliente_id) or args.workspace_id

    desde_vinculo = sum(1 for c in pendientes if c in por_vinculo)
    por_defecto = len(pendientes) - desde_vinculo

    print(f"Clientes en la tabla ........ {total}")
    print(f"Sin workspace ............... {len(pendientes)}")
    print(f"  resueltos por vínculo ..... {desde_vinculo}")
    print(f"  al workspace por defecto .. {por_defecto}  ({args.workspace_id})")
    if ambiguos:
        print(f"  vínculos ambiguos ......... {len(ambiguos)} (van al workspace por defecto)")

    ce_cols = table_columns(conn, "clientes_empresas")
    enlaces_pendientes = 0
    if "workspace_id" in ce_cols:
        enlaces_pendientes = conn.execute(
            "SELECT COUNT(*) FROM clientes_empresas WHERE COALESCE(workspace_id, '') = ''"
        ).fetchone()[0]
        print(f"Enlaces cliente-empresa sin workspace .. {enlaces_pendientes}")

    if not args.apply:
        print("\nEn seco: no se ha escrito nada. Añade --apply para ejecutarlo.")
        return 0

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
          cliente_id TEXT PRIMARY KEY,
          workspace_id TEXT
        )
        """
    )
    # El respaldo guarda el valor PREVIO (vacío) para poder deshacer sin ambigüedad.
    for cliente_id in asignaciones:
        conn.execute(
            f"INSERT OR IGNORE INTO {BACKUP_TABLE} (cliente_id, workspace_id) VALUES (?, NULL)",
            (cliente_id,),
        )
    for cliente_id, ws in asignaciones.items():
        conn.execute(
            "UPDATE clientes SET workspace_id = ? WHERE id = ? AND COALESCE(workspace_id, '') = ''",
            (ws, cliente_id),
        )
    if "workspace_id" in ce_cols and enlaces_pendientes:
        conn.execute(
            """
            UPDATE clientes_empresas
            SET workspace_id = (
              SELECT c.workspace_id FROM clientes c WHERE c.id = clientes_empresas.cliente_id
            )
            WHERE COALESCE(workspace_id, '') = ''
            """
        )
    conn.commit()

    restantes = conn.execute(
        "SELECT COUNT(*) FROM clientes WHERE COALESCE(workspace_id, '') = ''"
    ).fetchone()[0]
    print(f"\nHecho. Clientes sin workspace tras el backfill: {restantes}")
    print(f"Respaldo en `{BACKUP_TABLE}`; para deshacer: --rollback --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
