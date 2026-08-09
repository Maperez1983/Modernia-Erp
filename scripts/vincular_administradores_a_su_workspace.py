#!/usr/bin/env python3
"""Da de alta como miembro a quien ya trabaja en un workspace sin constar en él.

Contexto
--------
`workspace_session_is_privileged()` da paso libre a cualquier sesión cuyo rol sea
Administrador, Admin, Dirección, Control o Administración, y
`workspace_actor_is_privileged()` lo respeta porque `APP_SUPERADMIN_ENFORCE` vale
`0`, su valor por defecto. Resultado: 9 de los 17 usuarios activos leen y escriben
en los 4 workspaces, sean miembros o no.

Verificado en vivo el 2026-08-09 levantando el servidor con la estructura real:
D.Garcia, miembro sólo de Modernia, modificó una cita de DEMOCASA. El control
inverso confirma que no es un fallo de la guarda de pertenencia sino ese atajo:
B.salazar, con rol «Inmobiliaria» y tampoco miembro, recibió 403 en la misma
operación.

Hoy no hay fuga hacia fuera —los nueve son cuentas de la casa—, pero el día que un
cliente tenga una cuenta de Administrador en su propio workspace verá los demás.

El arreglo es poner `APP_SUPERADMIN_ENFORCE=1`, y entonces sólo queda privilegiado
el usuario de la allowlist (`APP_SUPERADMIN_USERNAMES`, «Mperez» por defecto). Pero
antes hay que asegurarse de que cada administrador es miembro de los workspaces
donde de verdad trabaja, o perderá acceso a lo suyo. Eso es lo que hace este script.

Qué hace
--------
1. Busca, para cada usuario con rol privilegiado, en qué workspaces ha dejado
   rastro: citas de las que es responsable, inmuebles y captaciones que creó o
   lleva, presupuestos, fichajes y su ficha de personal.
2. Compara con `workspace_miembros` y propone el alta que falte.
3. Con `--apply`, inserta esas filas con rol «Miembro».

No calcula la lista a mano: sale de los datos, así que sigue siendo correcta si
cambian.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada.
- Idempotente: sólo inserta la pertenencia que no existe.
- Reversible: apunta lo insertado en `workspace_miembros_altas_backup` y
  `--rollback` lo deshace.
- Contra Postgres con `--apply` pide confirmación tecleada.

Uso
---
    python scripts/vincular_administradores_a_su_workspace.py                 # informe
    python scripts/vincular_administradores_a_su_workspace.py --apply
    python scripts/vincular_administradores_a_su_workspace.py --rollback
"""

import argparse
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import load_env_file, table_columns  # noqa: E402

# Los mismos que reconoce `workspace_session_is_privileged` en server.py.
ROLES_PRIVILEGIADOS = {"ADMINISTRADOR", "ADMIN", "DIRECCION", "CONTROL", "ADMINISTRACION"}

# Dónde buscar rastro: (tabla, columna que identifica a la persona).
# Se prueban el id, el nombre de usuario y el nombre completo, porque el CRM guarda
# el responsable de tres formas distintas según la pantalla que lo creara.
RASTROS = [
    ("acciones", "responsable"),
    ("inmuebles", "responsable"),
    ("inmuebles", "created_by"),
    ("captaciones", "responsable"),
    ("captaciones", "created_by"),
    ("demandas", "responsable"),
    ("workspace_presupuestos", "responsable"),
    ("workspace_registro_horario", "usuario_id"),
    ("workspace_registro_personal", "usuario_id"),
]


def normaliza(valor):
    crudo = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", crudo).strip().upper()


def columnas(conn, tabla):
    """El helper del servidor, que ya sabe de los dos backends.

    Mi primera versión probaba `pragma table_info` y caía a `information_schema` si
    fallaba. Contra Postgres el `pragma` no sólo falla: **deja la transacción
    abortada**, así que la consulta de respaldo fallaba también y devolvía un
    conjunto vacío. El efecto era un informe en blanco que parecía decir «no hay nada
    que hacer».
    """
    return table_columns(conn, tabla) or set()


def valor(fila, clave, defecto=None):
    try:
        return fila[clave]
    except Exception:
        return defecto


def reune_datos(conn):
    usuarios = conn.execute(
        "SELECT id, usuario, nombre, rol FROM usuarios WHERE activo = 1"
    ).fetchall()
    workspaces = {
        str(valor(f, "id")): str(valor(f, "nombre") or "")
        for f in conn.execute("SELECT id, nombre FROM workspaces").fetchall()
    }
    miembros = defaultdict(set)
    for f in conn.execute("SELECT usuario_id, workspace_id FROM workspace_miembros").fetchall():
        miembros[str(valor(f, "usuario_id"))].add(str(valor(f, "workspace_id")))
    return usuarios, workspaces, miembros


def rastro_por_workspace(conn, claves):
    """Cuenta filas por workspace para cualquiera de las formas del nombre."""
    encontrado = defaultdict(int)
    claves = [c for c in claves if str(c or "").strip()]
    if not claves:
        return encontrado
    for tabla, campo in RASTROS:
        cols = columnas(conn, tabla)
        if not cols or campo not in cols or "workspace_id" not in cols:
            continue
        hueco = ",".join("?" * len(claves))
        try:
            filas = conn.execute(
                f"""SELECT workspace_id, COUNT(*) AS n FROM {tabla}
                    WHERE COALESCE({campo}, '') <> '' AND {campo} IN ({hueco})
                      AND COALESCE(workspace_id, '') <> ''
                    GROUP BY workspace_id""",
                tuple(claves),
            ).fetchall()
        except Exception:
            continue
        for f in filas:
            encontrado[str(valor(f, "workspace_id") or valor(f, 0))] += int(
                valor(f, "n", 0) or valor(f, 1) or 0
            )
    return encontrado


def calcula_altas(conn):
    usuarios, workspaces, miembros = reune_datos(conn)
    altas, informe = [], []
    for u in usuarios:
        uid = str(valor(u, "id") or "")
        usuario = str(valor(u, "usuario") or "")
        nombre = str(valor(u, "nombre") or "")
        rol = str(valor(u, "rol") or "")
        if normaliza(rol) not in ROLES_PRIVILEGIADOS:
            continue
        suyos = miembros.get(uid, set())
        actua = rastro_por_workspace(conn, [uid, usuario, nombre])
        faltan = {w: n for w, n in actua.items() if w not in suyos and w in workspaces}
        informe.append({
            "usuario": usuario, "rol": rol, "uid": uid,
            "miembro": sorted(workspaces.get(w, w) for w in suyos),
            "actua": {workspaces.get(w, w): n for w, n in sorted(actua.items())},
            "faltan": {workspaces.get(w, w): n for w, n in sorted(faltan.items())},
        })
        for w, n in sorted(faltan.items()):
            altas.append({"usuario_id": uid, "usuario": usuario,
                          "workspace_id": w, "workspace": workspaces.get(w, w), "rastro": n})
    return altas, informe


def asegura_backup(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS workspace_miembros_altas_backup (
             id TEXT PRIMARY KEY,
             usuario_id TEXT,
             workspace_id TEXT,
             creado_en TEXT
           )"""
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="escribe (por defecto va en seco)")
    ap.add_argument("--rollback", action="store_true", help="deshace las altas que hizo este script")
    ap.add_argument("--backend", choices=("sqlite", "postgres"))
    ap.add_argument("--db", default="data/crm.sqlite", help="ruta del SQLite, si se usa ese backend")
    ap.add_argument("--yes", action="store_true", help="no preguntar al escribir en Postgres")
    args = ap.parse_args()

    load_env_file()
    if args.backend:
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"

    # Caer a SQLite en silencio teniendo el DSN puesto es la forma más fácil de creer
    # que has tocado producción cuando has tocado la copia local.
    if backend == "sqlite" and args.backend != "sqlite":
        indicios = [n for n in ("DATABASE_URL", "POSTGRES_URL") if (os.environ.get(n) or "").strip()]
        if indicios:
            print(f"ERROR: hay {' y '.join(indicios)} en el entorno pero no se reconoce como Postgres.",
                  file=sys.stderr)
            return 2

    print(f"Base: {'Postgres' if backend == 'postgres' else 'SQLite ' + args.db}\n")
    conn = open_db_conn(args.db, with_row_factory=True)

    if args.rollback:
        asegura_backup(conn)
        filas = conn.execute("SELECT id, usuario_id, workspace_id FROM workspace_miembros_altas_backup").fetchall()
        if not filas:
            print("No hay altas que deshacer.")
            return 0
        for f in filas:
            conn.execute("DELETE FROM workspace_miembros WHERE id = ?", (str(valor(f, "id")),))
        conn.execute("DELETE FROM workspace_miembros_altas_backup")
        conn.commit()
        print(f"Deshechas {len(filas)} altas.")
        return 0

    altas, informe = calcula_altas(conn)

    print(f"{'usuario':<16}{'rol':<16}situación")
    for i in informe:
        print(f"{i['usuario']:<16}{i['rol']:<16}miembro de: {', '.join(i['miembro']) or '(ninguno)'}")
        if i["actua"]:
            print(f"{'':<32}actúa en  : " + ", ".join(f"{w} ({n})" for w, n in i["actua"].items()))
        if i["faltan"]:
            print(f"{'':<32}FALTA     : " + ", ".join(f"{w} ({n} registros)" for w, n in i["faltan"].items()))

    if not altas:
        print("\nNada que hacer: cada administrador ya es miembro de donde trabaja.")
        print("Se puede poner APP_SUPERADMIN_ENFORCE=1 sin dejar a nadie fuera.")
        return 0

    print(f"\n{len(altas)} altas propuestas:")
    for a in altas:
        print(f"   {a['usuario']} -> {a['workspace']}   (por {a['rastro']} registros suyos allí)")

    if not args.apply:
        print("\nEn seco: no se ha escrito nada. Repite con --apply.")
        return 0

    if backend == "postgres" and not args.yes:
        print("\nVas a ESCRIBIR en Postgres. Esto normalmente es producción.")
        print("Escribe 'si' para continuar (cualquier otra cosa aborta): ", end="", flush=True)
        try:
            respuesta = input().strip().lower()
        except EOFError:
            print("\nSin confirmación (stdin no interactivo). Aborto. Usa --yes si es intencionado.")
            return 1
        if respuesta not in {"si", "sí"}:
            print("Aborto.")
            return 1

    asegura_backup(conn)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    cols = columnas(conn, "workspace_miembros")
    hechas = 0
    try:
        for a in altas:
            nuevo = os.urandom(16).hex()
            fila = {"id": nuevo, "workspace_id": a["workspace_id"], "usuario_id": a["usuario_id"],
                    "rol": "Miembro", "created_at": ahora, "updated_at": ahora}
            fila = {k: v for k, v in fila.items() if k in cols}
            conn.execute(
                f"INSERT INTO workspace_miembros ({','.join(fila)}) VALUES ({','.join('?' * len(fila))})",
                tuple(fila.values()),
            )
            conn.execute(
                "INSERT INTO workspace_miembros_altas_backup (id, usuario_id, workspace_id, creado_en) "
                "VALUES (?, ?, ?, ?)",
                (nuevo, a["usuario_id"], a["workspace_id"], ahora),
            )
            hechas += 1
        conn.commit()
    except Exception as exc:
        conn.rollback()
        print(f"\nFalló y se ha deshecho todo: {exc}")
        raise
    print(f"\n{hechas} altas hechas. Para deshacerlas: --rollback")
    print("Ahora ya se puede poner APP_SUPERADMIN_ENFORCE=1.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
