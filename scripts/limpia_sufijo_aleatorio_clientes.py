#!/usr/bin/env python3
"""Quita el código aleatorio que se coló en `clientes.nombre` al crear fichas desde
carpetas de OneDrive.

Contexto
--------
Auditado en producción el 2026-08-26: cientos de fichas de "Fincas Velazquez"
tienen el nombre bien pero con un código pegado al final, p. ej.
`Acuna Barea Francisca 3Vcybh` o `Alcocer Santaella Antonio T3Sb3R T6Llq2`.

Rastreado a `scripts/assign_rentas_docs_create_clients.py` (commit `2251cdb`,
2026-04-21): ese guion crea un cliente por cada documento de Renta sin asignar,
adivinando el nombre de la carpeta de OneDrive que lo contiene
(`guess_cliente_name_from_doc`) cuando el PDF no trae NIF. Muchas de esas
carpetas tenían un sufijo interno de la gestoría (para no chocar con carpetas
de nombre repetido en el disco), y el guion lo usó tal cual como nombre del
cliente. `clean_candidate_name()` le aplicaba `.title()` a la carpeta entera,
así que un sufijo como `m91xhx` salía `M91Xhx` — que es justo la forma que
tienen estos códigos (`.title()` capitaliza tras cada dígito).

Los timestamps lo confirman: 332 fichas de esta empresa comparten el mismo
`created_at` al microsegundo (`2026-04-21 09:11:41.354307+00`), que es lo que
hace `NOW()` de Postgres dentro de una única transacción con muchos INSERT —
la firma de una pasada por lotes, no de altas manuales.

**El guion que lo causó ya no está en el repo** (ese commit no sigue en la
rama actual; no hay `import` que "arreglar" hoy). Esto es solo la limpieza
correctiva de lo que dejó. Si en el futuro se vuelve a asignar documentos por
nombre de carpeta, sanear el candidato ANTES de crear el cliente con la misma
`es_token_basura()` de aquí evita que vuelva a pasar.

Qué considera "basura"
-----------------------
Una palabra de 5 a 8 caracteres alfanuméricos que mezcla letras y dígitos
(nunca los dos por separado: ni sólo letras, ni sólo dígitos). Un nombre real
no lleva dígitos, así que mezclar letra+dígito es la señal segura — la misma
que ya uso en mi propio script de cotejo. Con eso:

- Se quita como palabra suelta ("... Patricia M91Xhx" -> "... Patricia").
- Se quita si va pegada al final de una palabra más larga sin espacio
  ("Concepcion2Jd1K7" -> "Concepcion"), pero SÓLO si lo que queda delante son
  letras: si delante hay dígitos (una fecha pegada, tipo
  "23042029Rnm6Z2") no se toca nada y se avisa, porque ahí no hay forma
  fiable de saber dónde acaba la fecha y empieza el código.

Lo que esto **no** toca a propósito, aunque tenga dígitos:
- `Exp<fecha>` (expediente) y refs de documento extranjero tipo `E24142767`
  o `C04480058` (9 caracteres: quedan fuera del rango 5-8).
- Fechas sueltas ("21 09 2025") y anotaciones en texto libre que se colaron
  en el nombre por el mismo motivo (notas de la carpeta) — limpiarlas es un
  problema aparte, no el de este código aleatorio.
- Un código sin dígito (sólo letras, tipo "Pvgekr") no se puede distinguir
  con garantías de un apellido real poco común, así que se deja y sólo se
  avisa en el informe si tiene muy pocas vocales.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada, sólo informa fila a fila.
- Reversible: cada cambio queda en `clientes_nombre_limpieza_backup` con el
  nombre anterior; `--rollback` lo restaura exactamente.
- Contra Postgres con `--apply` pide confirmación tecleada, salvo `--yes`.
- Idempotente: una fila ya limpia no vuelve a aparecer como candidata.

Uso
---
    python scripts/limpia_sufijo_aleatorio_clientes.py \\
        --empresa-id a261e552-8b9c-4da4-a279-a21c33277789          # informe
    python scripts/limpia_sufijo_aleatorio_clientes.py \\
        --empresa-id a261e552-8b9c-4da4-a279-a21c33277789 --apply
    python scripts/limpia_sufijo_aleatorio_clientes.py --rollback --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import load_env_file, table_columns  # noqa: E402

TABLA_RESPALDO = "clientes_nombre_limpieza_backup"
VOCALES = set("aeiouAEIOUáéíóúÁÉÍÓÚ")


def valor(fila, clave, defecto=None):
    try:
        return fila[clave]
    except Exception:
        return defecto


def es_token_basura(palabra):
    """5-8 alfanuméricos, con letra Y dígito a la vez. Un nombre real no mezcla eso."""
    return (
        5 <= len(palabra) <= 8
        and palabra.isalnum()
        and any(c.isdigit() for c in palabra)
        and any(c.isalpha() for c in palabra)
    )


def limpia_nombre(nombre):
    """Devuelve (nombre_limpio, se_tocó_algo)."""
    palabras = str(nombre or "").split(" ")
    salida = []
    cambiado = False
    for palabra in palabras:
        if es_token_basura(palabra):
            cambiado = True
            continue
        # Pegado sin espacio al final de una palabra más larga: sólo se separa
        # si delante queda una palabra de verdad (letras), nunca si delante
        # quedan dígitos (ahí puede haber una fecha pegada, y cortar a ciegas
        # se come parte de ella).
        recortada = False
        if len(palabra) > 8 and palabra.isalnum():
            for corte in (8, 7, 6, 5):
                prefijo, cola = palabra[:-corte], palabra[-corte:]
                if es_token_basura(cola) and len(prefijo) >= 3 and prefijo.isalpha():
                    salida.append(prefijo)
                    cambiado = True
                    recortada = True
                    break
        if not recortada:
            salida.append(palabra)
    limpio = re.sub(r"\s{2,}", " ", " ".join(salida)).strip()
    return limpio, cambiado


def palabra_sospechosa_sin_digito(palabra):
    """Aviso, no acción: última palabra corta, sólo letras, casi sin vocales."""
    if not (5 <= len(palabra) <= 8) or not palabra.isalpha():
        return False
    vocales = sum(1 for c in palabra if c in VOCALES)
    return vocales <= 1


def candidatos(conn, empresa_id):
    filas = conn.execute(
        """
        SELECT DISTINCT c.id, c.nombre
        FROM clientes c
        LEFT JOIN clientes_empresas ce ON ce.cliente_id = c.id
        WHERE (c.empresa_id = ? OR ce.empresa_id = ?)
          AND TRIM(COALESCE(c.nombre, '')) <> ''
        ORDER BY c.nombre
        """,
        (empresa_id, empresa_id),
    ).fetchall()
    out = []
    for f in filas:
        nombre = str(valor(f, "nombre") or "")
        limpio, cambiado = limpia_nombre(nombre)
        if cambiado:
            out.append((str(valor(f, "id")), nombre, limpio))
    return out


def asegura_respaldo(conn):
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLA_RESPALDO} (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            nombre_anterior TEXT,
            nombre_nuevo TEXT,
            limpiado_en TEXT
        )
        """
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "crm.sqlite"))
    ap.add_argument("--backend", choices=["auto", "sqlite", "postgres"], default="auto")
    ap.add_argument("--empresa-id", help="Requerido salvo con --rollback.")
    ap.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    ap.add_argument("--rollback", action="store_true", help="Deshace lo que hizo este script.")
    ap.add_argument("--yes", action="store_true", help="No preguntar antes de escribir en Postgres.")
    ap.add_argument("--max-print", type=int, default=400, help="Filas a listar en el informe.")
    args = ap.parse_args(argv)

    load_env_file()
    if args.backend in ("sqlite", "postgres"):
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    print(f"Base de datos ............... {backend}")

    # Caer a SQLite con el DSN puesto es la forma más fácil de creer que se ha
    # tocado producción cuando sólo se ha tocado la copia local.
    if backend == "sqlite" and args.backend != "sqlite":
        indicios = [n for n in ("DATABASE_URL", "POSTGRES_URL") if (os.environ.get(n) or "").strip()]
        if indicios:
            print(f"ERROR: hay {', '.join(indicios)} en el entorno pero se iría a SQLite.")
            return 2

    if not args.rollback and not args.empresa_id:
        print("ERROR: falta --empresa-id (o usa --rollback).")
        return 2

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        asegura_respaldo(conn)

        if args.rollback:
            filas = conn.execute(f"SELECT * FROM {TABLA_RESPALDO}").fetchall()
            print(f"Anotaciones de respaldo ..... {len(filas)}")
            if not args.apply:
                print("(en seco: no se toca nada; repite con --apply)")
                return 0
            for f in filas:
                conn.execute(
                    "UPDATE clientes SET nombre = ? WHERE id = ? AND nombre = ?",
                    (valor(f, "nombre_anterior"), valor(f, "cliente_id"), valor(f, "nombre_nuevo")),
                )
            conn.execute(f"DELETE FROM {TABLA_RESPALDO}")
            conn.commit()
            print(f"Deshechas .................... {len(filas)}")
            return 0

        cols = table_columns(conn, "clientes") or set()
        if "empresa_id" not in cols:
            print("ERROR: la tabla clientes no tiene empresa_id en esta base.")
            return 2

        cambios = candidatos(conn, args.empresa_id)
        print(f"Fichas con sufijo a limpiar .. {len(cambios)}\n")

        con_digitos = []
        sospechosas = []
        for cliente_id, antes, despues in cambios:
            ultima = despues.split(" ")[-1] if despues else ""
            avisos = []
            if any(c.isdigit() for c in despues):
                avisos.append("quedan dígitos")
                con_digitos.append((antes, despues))
            if palabra_sospechosa_sin_digito(ultima):
                avisos.append(f"'{ultima}' sospechosa, pocas vocales")
                sospechosas.append((antes, despues))
            marca = f"   << {'; '.join(avisos)}" if avisos else ""
            print(f"  {antes[:55]:57} -> {despues[:55]}{marca}")

        sin_aviso = len(cambios) - len({a for a, _ in con_digitos} | {a for a, _ in sospechosas})
        print(f"\nSe limpian sin más aviso ..... {sin_aviso}")
        print(f"Quedan dígitos, revisar a mano  {len(con_digitos)}")
        print(f"Palabra final sospechosa ..... {len(sospechosas)}")
        print("(en los dos avisos se aplica igual la parte que sí se detectó con")
        print(" garantías; lo que queda son restos que este guion no toca a ciegas)")

        if not cambios:
            print("\nNada que hacer.")
            return 0

        if not args.apply:
            print("\n(en seco: no se ha escrito nada; usa --apply)")
            return 0

        if backend == "postgres" and not args.yes:
            if input('Vas a escribir en PRODUCCIÓN. Escribe "si" para seguir: ').strip().lower() not in ("si", "sí"):
                print("Cancelado.")
                return 1

        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        hechos = 0
        for cliente_id, antes, despues in cambios:
            conn.execute(
                "UPDATE clientes SET nombre = ?, updated_at = ? WHERE id = ? AND nombre = ?",
                (despues, ahora, cliente_id, antes),
            )
            conn.execute(
                f"INSERT INTO {TABLA_RESPALDO} (id, cliente_id, nombre_anterior, nombre_nuevo, limpiado_en) "
                "VALUES (?, ?, ?, ?, ?)",
                (os.urandom(16).hex(), cliente_id, antes, despues, ahora),
            )
            hechos += 1
        conn.commit()
        print(f"\nLimpiadas ..................... {hechos}")
        print("Para deshacer: --rollback --apply")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
