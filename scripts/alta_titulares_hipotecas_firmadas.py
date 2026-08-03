#!/usr/bin/env python3
"""Da de alta como cliente al titular de cada hipoteca firmada que no lo tenga.

Contexto
--------
En el CRM financiero, la hipoteca guarda el nombre del titular en `hipotecas.cliente`
(texto suelto) y el vínculo a su ficha en `hipotecas.cliente_id`. Auditado en
producción el 2026-08-03: 37 hipotecas **firmadas** tenían el nombre pero no la
ficha, así que desde la hipoteca no se podía abrir el cliente, y esas personas no
aparecían en ninguna lista de clientes pese a haber firmado con la casa.

Regla de negocio (usuario, 2026-08-03): *a todas las hipotecas firmadas el titular
debe darse de alta como cliente*. Solo las firmadas: una hipoteca en estudio o
cancelada no crea ficha.

Qué hace
--------
Por cada hipoteca firmada sin `cliente_id`:

1. Busca una ficha que ya exista con el mismo nombre normalizado (sin tildes, sin
   signos y con las palabras ordenadas, para que "MOHAMED BOUZYANE" encuentre a
   "BOUZYANE MOHAMED"). Si la encuentra, **enlaza y no crea nada**.
2. Si hay varias candidatas, no elige: lo deja sin tocar y lo informa. Elegir mal
   mezcla a dos personas distintas, y eso no se deshace solo.
3. Si no hay ninguna, crea la ficha con el nombre del titular, la empresa de la
   hipoteca, el workspace y el servicio `financiaciones`, y la enlaza.

Lo que NO hace: inventar NIF, teléfono ni email. La ficha nace con lo único que
consta de verdad, que es el nombre.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada, solo informa.
- Transaccional: si algo falla, ROLLBACK y no queda una ficha a medias.
- Reversible: los ids creados y los enlaces quedan en `hipotecas_titulares_alta_backup`,
  y `--rollback` deshace exactamente eso y nada más.
- Idempotente: solo mira hipotecas firmadas con `cliente_id` vacío, así que
  repetirlo no duplica.

Uso
---
    python scripts/alta_titulares_hipotecas_firmadas.py --backend postgres \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0            # informe
    python scripts/alta_titulares_hipotecas_firmadas.py --backend postgres \\
        --workspace-id 6e63e1d1205c4c2a85dde7e20d5409f0 --apply
    python scripts/alta_titulares_hipotecas_firmadas.py --backend postgres --rollback --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402

SERVICIO = "financiaciones"
ESTADOS_FIRMADOS = ("firmada", "firmado")
TABLA_RESPALDO = "hipotecas_titulares_alta_backup"


def clave_de_nombre(valor):
    """Nombre comparable: sin tildes, sin signos, en minúsculas y con las palabras ordenadas.

    Ordenar las palabras es lo que hace que "MOHAMED BOUZYANE" y "BOUZYANE MOHAMED"
    sean la misma clave. En este CRM el orden nombre/apellido no es fiable.
    """
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z ]", " ", texto.lower())
    return " ".join(sorted(texto.split()))


def nuevo_id():
    return os.urandom(16).hex()


def cargar_indice_de_clientes(conn, workspace_id):
    filas = conn.execute(
        """
        SELECT id, nombre
        FROM clientes
        WHERE COALESCE(workspace_id, '') = ?
        """,
        (workspace_id,),
    ).fetchall()
    indice = {}
    for fila in filas:
        indice.setdefault(clave_de_nombre(fila["nombre"]), []).append(str(fila["id"]))
    return indice


def pendientes(conn, workspace_id):
    marcas = ",".join(["?"] * len(ESTADOS_FIRMADOS))
    return conn.execute(
        f"""
        SELECT id, cliente, empresa_id, estado, fecha_firma
        FROM hipotecas
        WHERE LOWER(TRIM(COALESCE(estado, ''))) IN ({marcas})
          AND COALESCE(TRIM(COALESCE(cliente_id, '')), '') = ''
          AND TRIM(COALESCE(cliente, '')) <> ''
          AND (COALESCE(workspace_id, '') = ? OR empresa_id IN (
                SELECT empresa_id FROM workspace_empresas WHERE workspace_id = ?
              ))
        ORDER BY fecha_firma
        """,
        (*ESTADOS_FIRMADOS, workspace_id, workspace_id),
    ).fetchall()


def asegurar_respaldo(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA_RESPALDO} (
            hipoteca_id TEXT,
            cliente_id TEXT,
            cliente_creado INTEGER,
            vinculo_id TEXT,
            creado_en TEXT
        )
        """
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "crm.sqlite"))
    parser.add_argument("--backend", choices=["auto", "sqlite", "postgres"], default="auto")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    parser.add_argument("--rollback", action="store_true", help="Deshace lo que hizo este script.")
    parser.add_argument("--yes", action="store_true", help="No preguntar antes de escribir en Postgres.")
    args = parser.parse_args(argv)

    if args.backend in ("sqlite", "postgres"):
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    print(f"Base de datos ............... {backend}")

    # Caer a SQLite con el DSN puesto es la forma más fácil de creer que has migrado
    # producción cuando has tocado la copia local.
    if backend == "sqlite" and args.backend != "sqlite":
        indicios = [n for n in ("DATABASE_URL", "POSTGRES_URL") if (os.environ.get(n) or "").strip()]
        if indicios:
            print(f"ERROR: hay {', '.join(indicios)} en el entorno pero se iría a SQLite.")
            return 2

    # Con with_row_factory las filas se leen por nombre de columna en los dos backends.
    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        asegurar_respaldo(conn)

        if args.rollback:
            filas = conn.execute(f"SELECT * FROM {TABLA_RESPALDO}").fetchall()
            print(f"Anotaciones de respaldo ..... {len(filas)}")
            if not args.apply:
                print("(en seco: no se toca nada)")
                return 0
            for fila in filas:
                conn.execute(
                    "UPDATE hipotecas SET cliente_id = '' WHERE id = ?", (fila["hipoteca_id"],)
                )
                if fila["vinculo_id"]:
                    conn.execute("DELETE FROM clientes_empresas WHERE id = ?", (fila["vinculo_id"],))
                if int(fila["cliente_creado"] or 0):
                    conn.execute("DELETE FROM clientes WHERE id = ?", (fila["cliente_id"],))
            conn.execute(f"DELETE FROM {TABLA_RESPALDO}")
            conn.commit()
            print(f"Deshecho .................... {len(filas)}")
            return 0

        indice = cargar_indice_de_clientes(conn, args.workspace_id)
        filas = pendientes(conn, args.workspace_id)
        print(f"Hipotecas firmadas sin ficha  {len(filas)}")

        a_enlazar, a_crear, ambiguas = [], [], []
        for fila in filas:
            candidatos = indice.get(clave_de_nombre(fila["cliente"]), [])
            if len(candidatos) == 1:
                a_enlazar.append((fila, candidatos[0]))
            elif len(candidatos) > 1:
                ambiguas.append((fila, candidatos))
            else:
                a_crear.append(fila)

        print(f"  se enlazan a una ficha ya existente  {len(a_enlazar)}")
        print(f"  se crean fichas nuevas               {len(a_crear)}")
        print(f"  ambiguas, se dejan como están        {len(ambiguas)}")
        for fila, candidatos in ambiguas:
            print(f"     ! {fila['cliente']}: {len(candidatos)} fichas con ese nombre")

        if not args.apply:
            print("\n(en seco: no se ha escrito nada; usa --apply)")
            return 0

        if backend == "postgres" and not args.yes:
            if input('Vas a escribir en PRODUCCIÓN. Escribe "si" para seguir: ').strip().lower() != "si":
                print("Cancelado.")
                return 1

        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        creados = enlazados = 0
        for fila, cliente_id in a_enlazar:
            conn.execute(
                "UPDATE hipotecas SET cliente_id = ?, updated_at = ? WHERE id = ?",
                (cliente_id, ahora, fila["id"]),
            )
            conn.execute(
                f"INSERT INTO {TABLA_RESPALDO} (hipoteca_id, cliente_id, cliente_creado, vinculo_id, creado_en)"
                " VALUES (?, ?, 0, '', ?)",
                (fila["id"], cliente_id, ahora),
            )
            enlazados += 1

        for fila in a_crear:
            cliente_id = nuevo_id()
            vinculo_id = nuevo_id()
            conn.execute(
                """
                INSERT INTO clientes (id, empresa_id, nombre, estado, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, 'Activo', ?, ?, ?)
                """,
                (cliente_id, fila["empresa_id"], fila["cliente"], args.workspace_id, ahora, ahora),
            )
            conn.execute(
                """
                INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, workspace_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'Activo', ?, ?, ?)
                """,
                (vinculo_id, cliente_id, fila["empresa_id"], SERVICIO, args.workspace_id, ahora, ahora),
            )
            conn.execute(
                "UPDATE hipotecas SET cliente_id = ?, updated_at = ? WHERE id = ?",
                (cliente_id, ahora, fila["id"]),
            )
            conn.execute(
                f"INSERT INTO {TABLA_RESPALDO} (hipoteca_id, cliente_id, cliente_creado, vinculo_id, creado_en)"
                " VALUES (?, ?, 1, ?, ?)",
                (fila["id"], cliente_id, vinculo_id, ahora),
            )
            creados += 1

        conn.commit()
        print(f"\nFichas creadas .............. {creados}")
        print(f"Hipotecas enlazadas ......... {creados + enlazados}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
