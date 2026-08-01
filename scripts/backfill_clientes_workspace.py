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
1. Resuelve el workspace de cada cliente por el `workspace_id` que ya tengan sus
   vínculos en `clientes_empresas`. Es la señal más fuerte que hay.
2. A los que no tienen vínculo les asigna `--workspace-id`, el tenant por defecto.
3. Rellena también `clientes_empresas.workspace_id` cuando está vacío.

Backend
-------
Habla con Postgres o con SQLite a través de la misma capa que el servidor
(`web.db_backend.open_db_conn`), así que el SQL se escribe una vez en dialecto
SQLite y se traduce solo. El backend sale de las variables de entorno
(`APP_DB_BACKEND`, `POSTGRES_URL`, `DATABASE_URL`, y el `.env` de la raíz) o de
`--backend`. El script SIEMPRE dice contra qué base va a trabajar antes de tocar
nada, y con `--apply` sobre Postgres exige confirmación tecleada.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada, solo informa.
- Transaccional: todo el backfill va en una transacción; si algo falla, ROLLBACK.
- Reversible: antes de tocar nada guarda el valor previo en
  `clientes_workspace_backfill_backup` y `clientes_empresas_workspace_backfill_backup`.
  `--rollback` restaura desde ahí.
- Idempotente: solo toca filas con el valor vacío, así que repetirlo no hace daño.
- Nunca sobreescribe un `workspace_id` que ya tenga valor.

Uso
---
    # SQLite (local)
    python scripts/backfill_clientes_workspace.py --backend sqlite --db data/crm.sqlite \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0            # informe

    # Postgres (Render). DATABASE_URL/POSTGRES_URL en el entorno.
    python scripts/backfill_clientes_workspace.py --backend postgres \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0            # informe
    python scripts/backfill_clientes_workspace.py --backend postgres \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0 --apply
    python scripts/backfill_clientes_workspace.py --backend postgres --rollback --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import is_postgres_enabled, open_db_conn
from web.schema_support import table_columns

BACKUP_TABLE = "clientes_workspace_backfill_backup"
LINKS_BACKUP_TABLE = "clientes_empresas_workspace_backfill_backup"

# Postgres no acepta un número ilimitado de parámetros por statement, y una lista
# IN gigante tampoco es buena idea sobre la red. Troceamos.
BATCH = 500


def _scalar(row):
    """Primera columna de una fila, venga como tupla o como dict."""
    if row is None:
        return None
    if isinstance(row, dict):
        return next(iter(row.values()), None)
    return row[0]


def _rows_as_tuples(rows):
    out = []
    for row in rows or []:
        if isinstance(row, dict):
            out.append(tuple(row.values()))
        else:
            out.append(tuple(row))
    return out


def _table_exists(conn, table):
    return bool(table_columns(conn, table))


def _count(conn, sql, params=None):
    return int(_scalar(conn.execute(sql, params or ()).fetchone()) or 0)


def resolve_by_links(conn):
    """cliente_id -> workspace_id deducido de las empresas vinculadas.

    Solo aceptamos el vínculo cuando es inequívoco: si un cliente cuelga de
    empresas de dos workspaces distintos no adivinamos, lo dejamos para el
    tenant por defecto y lo contamos aparte.
    """
    if "workspace_id" not in table_columns(conn, "clientes_empresas"):
        return {}, set()
    rows = _rows_as_tuples(
        conn.execute(
            """
            SELECT cliente_id, workspace_id
            FROM clientes_empresas
            WHERE COALESCE(workspace_id, '') <> ''
            """
        ).fetchall()
    )
    candidatos: dict[str, set[str]] = {}
    for cliente_id, ws in rows:
        candidatos.setdefault(str(cliente_id), set()).add(str(ws))
    resueltos = {c: next(iter(w)) for c, w in candidatos.items() if len(w) == 1}
    ambiguos = {c for c, w in candidatos.items() if len(w) > 1}
    return resueltos, ambiguos


def _describe_target(backend):
    """Qué base vamos a tocar, en una línea, sin filtrar la contraseña del DSN."""
    if backend != "postgres":
        return "SQLite"
    raw = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        return "Postgres (DSN no configurado)"
    sin_credenciales = raw.split("@")[-1] if "@" in raw else raw
    return f"Postgres {sin_credenciales}"


def _confirm_postgres_write(backend, assume_yes):
    if backend != "postgres" or assume_yes:
        return True
    print()
    print("Vas a ESCRIBIR en Postgres. Esto normalmente es producción.")
    print("Escribe 'si' para continuar (cualquier otra cosa aborta): ", end="", flush=True)
    try:
        respuesta = input().strip().lower()
    except EOFError:
        # Sin terminal interactiva no damos por bueno el silencio.
        print("\nSin confirmación (stdin no interactivo). Aborto. Usa --yes si es intencionado.")
        return False
    if respuesta not in {"si", "sí"}:
        print("Aborto.")
        return False
    return True


def _ensure_backup_tables(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {BACKUP_TABLE} (
          cliente_id TEXT PRIMARY KEY,
          workspace_id TEXT
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LINKS_BACKUP_TABLE} (
          link_id TEXT PRIMARY KEY,
          workspace_id TEXT
        )
        """
    )


def _chunks(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _apply_backfill(conn, asignaciones, ws_por_defecto, tiene_links):
    """Escribe el backfill. Por conjuntos, no fila a fila: 2000 round-trips
    contra Render son minutos; agrupado por workspace son un puñado."""
    _ensure_backup_tables(conn)

    # Respaldo del valor PREVIO de los clientes que vamos a tocar. `WHERE NOT EXISTS`
    # en vez de `INSERT OR IGNORE` para no depender de reescrituras del traductor.
    conn.execute(
        f"""
        INSERT INTO {BACKUP_TABLE} (cliente_id, workspace_id)
        SELECT c.id, c.workspace_id
        FROM clientes c
        WHERE COALESCE(c.workspace_id, '') = ''
          AND NOT EXISTS (
            SELECT 1 FROM {BACKUP_TABLE} b WHERE b.cliente_id = c.id
          )
        """  # nosec B608 - nombres de tabla constantes del módulo
    )

    # Agrupamos por destino: normalmente hay uno o dos workspaces, así que esto
    # son 1-2 UPDATE troceados en vez de una sentencia por cliente.
    por_workspace: dict[str, list[str]] = {}
    for cliente_id, ws in asignaciones.items():
        if ws and ws != ws_por_defecto:
            por_workspace.setdefault(ws, []).append(cliente_id)

    for ws, ids in por_workspace.items():
        for lote in _chunks(ids, BATCH):
            marcadores = ", ".join(["?"] * len(lote))
            conn.execute(
                f"""
                UPDATE clientes
                SET workspace_id = ?
                WHERE COALESCE(workspace_id, '') = ''
                  AND id IN ({marcadores})
                """,  # nosec B608 - marcadores parametrizados, no datos
                (ws, *lote),
            )

    # Barrido final: todo lo que siga vacío es del tenant por defecto. Una sola
    # sentencia, y además hace el script idempotente por construcción.
    conn.execute(
        "UPDATE clientes SET workspace_id = ? WHERE COALESCE(workspace_id, '') = ''",
        (ws_por_defecto,),
    )

    if not tiene_links:
        return

    conn.execute(
        f"""
        INSERT INTO {LINKS_BACKUP_TABLE} (link_id, workspace_id)
        SELECT ce.id, ce.workspace_id
        FROM clientes_empresas ce
        WHERE COALESCE(ce.workspace_id, '') = ''
          AND NOT EXISTS (
            SELECT 1 FROM {LINKS_BACKUP_TABLE} b WHERE b.link_id = ce.id
          )
        """  # nosec B608 - nombres de tabla constantes del módulo
    )
    conn.execute(
        """
        UPDATE clientes_empresas
        SET workspace_id = (
          SELECT c.workspace_id FROM clientes c WHERE c.id = clientes_empresas.cliente_id
        )
        WHERE COALESCE(workspace_id, '') = ''
          AND EXISTS (
            SELECT 1 FROM clientes c
            WHERE c.id = clientes_empresas.cliente_id
              AND COALESCE(c.workspace_id, '') <> ''
          )
        """
    )


def _do_rollback(conn, apply_changes):
    if not _table_exists(conn, BACKUP_TABLE):
        print(f"No hay tabla {BACKUP_TABLE}: nada que revertir.")
        return 0

    clientes = _rows_as_tuples(
        conn.execute(f"SELECT cliente_id, workspace_id FROM {BACKUP_TABLE}").fetchall()  # nosec B608
    )
    enlaces = []
    if _table_exists(conn, LINKS_BACKUP_TABLE):
        enlaces = _rows_as_tuples(
            conn.execute(f"SELECT link_id, workspace_id FROM {LINKS_BACKUP_TABLE}").fetchall()  # nosec B608
        )

    print(f"Restaurando {len(clientes)} clientes a su valor previo.")
    if enlaces:
        print(f"Restaurando {len(enlaces)} enlaces cliente-empresa a su valor previo.")
    if not apply_changes:
        print("En seco: nada escrito. Añade --apply.")
        return 0

    # Agrupamos por valor previo (casi siempre uno solo: NULL) para no ir fila a fila.
    def restaurar(tabla, columna_id, filas):
        por_valor: dict[object, list[str]] = {}
        for row_id, ws in filas:
            por_valor.setdefault(ws, []).append(row_id)
        for ws, ids in por_valor.items():
            for lote in _chunks(ids, BATCH):
                marcadores = ", ".join(["?"] * len(lote))
                conn.execute(
                    f"UPDATE {tabla} SET workspace_id = ? WHERE {columna_id} IN ({marcadores})",  # nosec B608
                    (ws, *lote),
                )

    restaurar("clientes", "id", clientes)
    if enlaces:
        restaurar("clientes_empresas", "id", enlaces)
    conn.commit()
    print("Revertido.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(REPO_ROOT / "data" / "crm.sqlite"),
        help="Ruta de la base SQLite. Se ignora con Postgres.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "sqlite", "postgres"],
        default="auto",
        help="Backend a usar. Por defecto se deduce del entorno (DATABASE_URL/POSTGRES_URL/.env).",
    )
    parser.add_argument(
        "--workspace-id",
        help="Workspace por defecto para los clientes sin vínculo resoluble.",
    )
    parser.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    parser.add_argument("--rollback", action="store_true", help="Restaura desde las tablas de respaldo.")
    parser.add_argument("--yes", action="store_true", help="No preguntar antes de escribir en Postgres.")
    args = parser.parse_args(argv)

    if args.backend == "sqlite":
        os.environ["APP_DB_BACKEND"] = "sqlite"
    elif args.backend == "postgres":
        os.environ["APP_DB_BACKEND"] = "postgres"

    backend = "postgres" if is_postgres_enabled() else "sqlite"
    destino = _describe_target(backend)
    if backend == "sqlite":
        destino = f"SQLite {args.db}"
    print(f"Base de datos ............... {destino}")

    # Caer a SQLite en silencio teniendo el DSN puesto es la forma más fácil de creer
    # que migraste producción cuando has tocado la copia local. Si hay algo parecido a
    # una cadena de Postgres en el entorno y aun así vamos a SQLite, se avisa y se para.
    if backend == "sqlite" and args.backend != "sqlite":
        indicios = [
            nombre
            for nombre in ("DATABASE_URL", "POSTGRES_URL")
            if (os.environ.get(nombre) or "").strip()
        ]
        if indicios:
            print(
                "ERROR: hay " + " y ".join(indicios) + " en el entorno, pero no se reconoce como Postgres.\n"
                "       Revisa que el nombre de la variable esté bien escrito y que el valor empiece\n"
                "       por 'postgres'. Para forzarlo: --backend postgres. Para usar la copia local\n"
                "       a propósito: --backend sqlite.",
                file=sys.stderr,
            )
            return 2

    try:
        conn = open_db_conn(args.db)
    except Exception as exc:
        print(f"ERROR: no se pudo conectar: {exc}", file=sys.stderr)
        return 2

    try:
        if "workspace_id" not in table_columns(conn, "clientes"):
            print("ERROR: `clientes` no tiene columna workspace_id. Arranca el servidor una vez", file=sys.stderr)
            print("       para que la migración la cree, y vuelve a lanzar esto.", file=sys.stderr)
            return 2

        if args.rollback:
            if args.apply and not _confirm_postgres_write(backend, args.yes):
                return 1
            return _do_rollback(conn, args.apply)

        if not args.workspace_id:
            print("ERROR: hace falta --workspace-id (o --rollback).", file=sys.stderr)
            return 2

        pendientes = [
            str(r[0])
            for r in _rows_as_tuples(
                conn.execute("SELECT id FROM clientes WHERE COALESCE(workspace_id, '') = ''").fetchall()
            )
        ]
        total = _count(conn, "SELECT COUNT(*) FROM clientes")

        por_vinculo, ambiguos = resolve_by_links(conn)
        asignaciones = {c: por_vinculo.get(c) or args.workspace_id for c in pendientes}

        desde_vinculo = sum(1 for c in pendientes if c in por_vinculo)
        por_defecto = len(pendientes) - desde_vinculo

        print(f"Clientes en la tabla ........ {total}")
        print(f"Sin workspace ............... {len(pendientes)}")
        print(f"  resueltos por vínculo ..... {desde_vinculo}")
        print(f"  al workspace por defecto .. {por_defecto}  ({args.workspace_id})")
        if ambiguos:
            print(f"  vínculos ambiguos ......... {len(ambiguos)} (van al workspace por defecto)")

        tiene_links = "workspace_id" in table_columns(conn, "clientes_empresas")
        enlaces_pendientes = 0
        if tiene_links:
            enlaces_pendientes = _count(
                conn, "SELECT COUNT(*) FROM clientes_empresas WHERE COALESCE(workspace_id, '') = ''"
            )
            print(f"Enlaces cliente-empresa sin workspace .. {enlaces_pendientes}")

        if not args.apply:
            print("\nEn seco: no se ha escrito nada. Añade --apply para ejecutarlo.")
            return 0

        if not _confirm_postgres_write(backend, args.yes):
            return 1

        try:
            _apply_backfill(conn, asignaciones, args.workspace_id, tiene_links)
            conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"\nERROR durante el backfill, se ha hecho ROLLBACK: {exc}", file=sys.stderr)
            return 1

        restantes = _count(conn, "SELECT COUNT(*) FROM clientes WHERE COALESCE(workspace_id, '') = ''")
        print(f"\nHecho. Clientes sin workspace tras el backfill: {restantes}")
        print(f"Respaldo en `{BACKUP_TABLE}`; para deshacer: --rollback --apply")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
