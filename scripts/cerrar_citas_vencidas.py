#!/usr/bin/env python3
"""Cierra las citas pendientes cuya fecha ya pasó.

Contexto
--------
Auditando la agenda del CRM inmobiliario el 2026-08-09 salieron 75 citas en estado
«Pendiente» y **todas con fecha pasada**: la más reciente del 12 de junio, ninguna
futura en toda la agenda. Nadie las había cerrado desde entonces, así que arrastraban
la vista y ensuciaban los contadores de caducadas.

El usuario decidió, estando el programa en pruebas, darlas por realizadas.

Qué hace
--------
Pasa a «Completada» las acciones del servicio indicado que estén en «Pendiente» con
fecha anterior a hoy.

**No inventa el resultado de cierre.** De las 75, nueve son de tipos que el servidor
exige cerrar con un resultado —«Cita de adquisición» pide Positivo/Negativo, «Cita
contraoferta» pide Aceptada/Rechazada—, y elegir uno sería inventarse un desenlace
comercial. Se quedan sin resultado: la ficha se lo pedirá a quien la abra, que es
justo lo que debe pasar. Las otras 66 no lo necesitan.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada.
- Reversible: guarda el estado previo de cada fila en `acciones_cierre_backup` y
  `--rollback` lo restaura.
- Acotado: sólo un servicio (por defecto inmobiliaria) y sólo fechas pasadas.
- Contra Postgres con `--apply` pide confirmación tecleada.

Uso
---
    python scripts/cerrar_citas_vencidas.py                      # informe
    python scripts/cerrar_citas_vencidas.py --apply
    python scripts/cerrar_citas_vencidas.py --rollback
"""

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import load_env_file  # noqa: E402


def valor(fila, clave, defecto=None):
    try:
        return fila[clave]
    except Exception:
        return defecto


def asegura_backup(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS acciones_cierre_backup (
             id TEXT PRIMARY KEY,
             estado_previo TEXT,
             cerrado_en TEXT
           )"""
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (por defecto va en seco)")
    ap.add_argument("--rollback", action="store_true", help="devuelve las citas a Pendiente")
    ap.add_argument("--servicio", default="inmobiliaria")
    ap.add_argument("--hasta", default="", help="fecha límite (por defecto, hoy)")
    ap.add_argument("--backend", choices=("sqlite", "postgres"))
    ap.add_argument("--db", default="data/crm.sqlite")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    load_env_file()
    if args.backend:
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    if backend == "sqlite" and args.backend != "sqlite":
        indicios = [n for n in ("DATABASE_URL", "POSTGRES_URL") if (os.environ.get(n) or "").strip()]
        if indicios:
            print(f"ERROR: hay {' y '.join(indicios)} pero no se reconoce como Postgres.", file=sys.stderr)
            return 2

    conn = open_db_conn(args.db, with_row_factory=True)
    hasta = args.hasta.strip() or date.today().isoformat()
    print(f"Base: {'Postgres' if backend == 'postgres' else 'SQLite ' + args.db}")
    print(f"Servicio: {args.servicio} · citas pendientes con fecha anterior a {hasta}\n")

    if args.rollback:
        asegura_backup(conn)
        filas = conn.execute("SELECT id, estado_previo FROM acciones_cierre_backup").fetchall()
        if not filas:
            print("No hay cierres que deshacer.")
            return 0
        for f in filas:
            conn.execute(
                "UPDATE acciones SET estado = ? WHERE id = ?",
                (str(valor(f, "estado_previo") or "Pendiente"), str(valor(f, "id"))),
            )
        conn.execute("DELETE FROM acciones_cierre_backup")
        conn.commit()
        print(f"Devueltas a su estado anterior: {len(filas)} citas.")
        return 0

    filas = conn.execute(
        """SELECT id, fecha, hora, COALESCE(tipo,'') AS tipo, COALESCE(asunto,'') AS asunto,
                  COALESCE(responsable,'') AS responsable, COALESCE(resultado_cierre,'') AS resultado
           FROM acciones
           WHERE servicio = ? AND estado = 'Pendiente' AND fecha < ?
           ORDER BY fecha""",
        (args.servicio, hasta),
    ).fetchall()

    if not filas:
        print("No hay citas pendientes vencidas.")
        return 0

    por_responsable = {}
    for f in filas:
        por_responsable.setdefault(str(valor(f, "responsable") or "(sin responsable)"), []).append(f)
    print(f"{len(filas)} citas se cerrarán, repartidas así:")
    for resp, grupo in sorted(por_responsable.items(), key=lambda x: -len(x[1])):
        fechas = sorted(str(valor(g, "fecha")) for g in grupo)
        print(f"   {len(grupo):>3}  {resp:<22} de {fechas[0]} a {fechas[-1]}")

    # Las que el servidor exigirá cerrar con resultado cuando alguien las reabra.
    from web.server import INMO_ACTION_RESULT_OPTIONS, normalize_inmo_action_type

    piden_resultado = [
        f for f in filas
        if normalize_inmo_action_type(valor(f, "tipo")) in INMO_ACTION_RESULT_OPTIONS
        and not str(valor(f, "resultado") or "").strip()
    ]
    if piden_resultado:
        print(f"\nDe ellas, {len(piden_resultado)} son de tipos que piden un resultado de cierre.")
        print("No se les inventa ninguno: la ficha lo pedirá a quien la abra.")
        for f in piden_resultado:
            opciones = sorted(INMO_ACTION_RESULT_OPTIONS[normalize_inmo_action_type(valor(f, "tipo"))])
            print(f"   {valor(f,'fecha')}  {str(valor(f,'tipo'))[:28]:<29} {opciones}")

    if not args.apply:
        print("\nEn seco: no se ha escrito nada. Repite con --apply.")
        return 0

    if backend == "postgres" and not args.yes:
        print("\nVas a ESCRIBIR en Postgres. Esto normalmente es producción.")
        print("Escribe 'si' para continuar: ", end="", flush=True)
        try:
            if input().strip().lower() not in {"si", "sí"}:
                print("Aborto.")
                return 1
        except EOFError:
            print("\nSin confirmación. Aborto. Usa --yes si es intencionado.")
            return 1

    asegura_backup(conn)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    try:
        for f in filas:
            fid = str(valor(f, "id"))
            conn.execute(
                "INSERT INTO acciones_cierre_backup (id, estado_previo, cerrado_en) VALUES (?, ?, ?)",
                (fid, "Pendiente", ahora),
            )
            conn.execute(
                "UPDATE acciones SET estado = 'Completada', updated_at = datetime(?) WHERE id = ?",
                (ahora, fid),
            )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"\nFalló y se ha deshecho todo: {exc}")
        raise
    print(f"\n{len(filas)} citas cerradas. Para deshacerlo: --rollback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
