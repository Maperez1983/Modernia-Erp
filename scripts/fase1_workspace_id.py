#!/usr/bin/env python3
"""Fase 1 del ámbito por workspace: que todo dato de negocio lleve su `workspace_id`.

Por qué
-------
El 2026-09-18 se decidió (con el usuario) que un dato es del workspace y la empresa es
solo un atributo. Hasta ahora era al revés en media aplicación: un dato "era de
Modernia" si su empresa estaba vinculada a Modernia. Como las empresas se comparten
entre workspaces, eso cruzaba datos entre workspaces y escondía los que no tenían
empresa. Cada auditoría arreglaba una pantalla y el fallo volvía por otra.

Medido ese día en producción: 409 pólizas, 111 hipotecas, 38 operaciones, 61
captaciones y 139 acciones sin `workspace_id`, y unas 30 tablas —todo gestoría,
alquileres, movimientos, inversores, las hijas de seguros— sin la columna siquiera.

Qué hace
--------
1. Añade `workspace_id` (y su índice) a las tablas de negocio que tienen `empresa_id`
   y no la tienen.
2. Rellena las filas sin workspace:
   a. por su empresa, descartando el workspace de plataforma (`workspaces_propios_de_
      empresa`): sin él, cada empresa cuelga de uno solo;
   b. si no tiene empresa o la empresa es la técnica de plataforma, por su cliente
      (`cliente_id` → `clientes.workspace_id`), si el cliente no es de plataforma;
   c. si sigue sin saberse, **se deja como está** y se informa. Estampar el workspace
      equivocado mezcla tenants; dejarlo vacío mantiene lo que ya funciona.
3. Mueve a Modernia los 5 clientes que estaban en Verifika² con la empresa técnica
   (confirmado por el usuario el 2026-09-18: "todos son de Modernia").
4. Instala en Postgres un disparador BEFORE INSERT por tabla: una fila que entre sin
   `workspace_id` lo recibe de su empresa con la misma regla. Así el hueco no se
   vuelve a abrir por ninguna de las cientos de vías de alta del código antiguo
   mientras la fase 2 cambia las consultas.

Cada cambio de valor queda en `ambito_workspace_backfill_log` (tabla, fila, antes,
después, motivo, lote): se puede deshacer con `--deshacer LOTE`.

Uso
---
    python scripts/fase1_workspace_id.py                  # ensayo: cuenta, no escribe
    python scripts/fase1_workspace_id.py --aplicar        # escribe (pide confirmación)
    python scripts/fase1_workspace_id.py --deshacer LOTE  # revierte los valores de un lote
"""

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

# Tablas con `empresa_id` que NO son datos de negocio de un workspace: vínculos entre
# workspace y empresa, configuración por empresa y copias de seguridad.
EXCLUIDAS = {
    "workspace_empresas",
    "workspace_companies",
    "workspace_servicio_empresas",
    "empresa_aliases",
    "clientes_empresas",
    "ambito_workspace_backfill_log",
}
# El registro horario ya lleva workspace en todas sus filas, y las de Verifika² son
# fichajes históricos con cadena de integridad: no se reescriben.
PREFIJOS_EXCLUIDOS = ("workspace_registro_",)

# Confirmado por el usuario el 2026-09-18.
CLIENTES_DE_MODERNIA = (
    "3e8209f4bf822906f99f262fe7a159eb",
    "8d8b10a7cc1e0e5118a0d56076495a3e",
    "bdfdcf85c083201db78f4a97645ee9c2",
    "fa63bef6555660bdcce66597ebea29d5",
    "8e987903e2806f2af77fe8bb6f7f7670",
)
SLUG_MODERNIA = "modernia"

LOG = "ambito_workspace_backfill_log"


def _lee_env():
    """Lo justo de `.env` para conectar, sin importar `web.server` (tarda minutos)."""
    env = RAIZ / ".env"
    if not env.exists():
        return
    for linea in env.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def es_tabla_de_negocio(nombre):
    if nombre in EXCLUIDAS:
        return False
    if nombre.startswith(PREFIJOS_EXCLUIDOS):
        return False
    if "backup" in nombre or "_bak" in nombre:
        return False
    return True


def decide_workspace(empresa_id, cliente_id, *, mapa_empresa, ws_de_cliente, plataforma):
    """Workspace que corresponde a una fila y por qué, o ("", motivo) si no se sabe.

    Pura para poder probarla sin base: `mapa_empresa` es {empresa_id: [workspaces sin
    plataforma]} y `ws_de_cliente` es {cliente_id: workspace_id}.
    """
    eid = str(empresa_id or "").strip()
    if eid:
        candidatos = [w for w in mapa_empresa.get(eid, []) if w and w != plataforma]
        if len(candidatos) == 1:
            return candidatos[0], "empresa"
        if len(candidatos) > 1:
            return "", "empresa_ambigua"
    cid = str(cliente_id or "").strip()
    if cid:
        ws = str(ws_de_cliente.get(cid) or "").strip()
        if ws and ws != plataforma:
            return ws, "cliente"
    if eid:
        return "", "empresa_de_plataforma_o_sin_vinculo"
    return "", "sin_empresa_ni_cliente"


def _cols(conn, tabla):
    filas = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name = %s",
        (tabla,),
    ).fetchall()
    return {r[0] for r in filas}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--aplicar", action="store_true", help="escribe (por defecto solo informa)")
    ap.add_argument("--deshacer", metavar="LOTE", help="revierte los valores escritos por un lote")
    ap.add_argument("--si", action="store_true", help="no preguntar antes de aplicar")
    args = ap.parse_args()

    import psycopg

    _lee_env()
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL") or ""
    if not dsn:
        print("Sin DATABASE_URL: este script es para la base Postgres.")
        return 2
    host = dsn.split("@")[-1].split("/")[0]
    print(f"Base: Postgres en {host}")
    escribe = bool(args.aplicar or args.deshacer)
    print(f"Modo: {'DESHACER ' + args.deshacer if args.deshacer else ('APLICAR' if args.aplicar else 'ensayo (no escribe)')}\n")

    conn = psycopg.connect(dsn, autocommit=False)
    if not escribe:
        conn.execute("SET TRANSACTION READ ONLY")

    if args.deshacer:
        return deshacer(conn, args.deshacer, args.si)

    # Workspaces y plataforma.
    ws_por_slug = {r[1]: r[0] for r in conn.execute("SELECT id, slug FROM workspaces").fetchall()}
    modernia = ws_por_slug.get(SLUG_MODERNIA, "")
    fila = conn.execute(
        """
        SELECT we.workspace_id FROM workspace_empresas we JOIN empresas e ON e.id::text = we.empresa_id::text
        WHERE e.nombre = 'Verifika2' LIMIT 1
        """
    ).fetchone()
    plataforma = fila[0] if fila else ""
    if not modernia or not plataforma:
        print(f"No se encuentra Modernia ({modernia!r}) o la plataforma ({plataforma!r}). Paro.")
        return 2
    nombre_ws = {v: k for k, v in ws_por_slug.items()}

    mapa_empresa = defaultdict(list)
    for eid, wid in conn.execute("SELECT empresa_id::text, workspace_id FROM workspace_empresas").fetchall():
        if wid not in mapa_empresa[eid]:
            mapa_empresa[eid].append(wid)
    ws_de_cliente = {
        r[0]: r[1] for r in conn.execute("SELECT id::text, workspace_id FROM clientes WHERE COALESCE(workspace_id,'') <> ''").fetchall()
    }
    print("Empresas → workspace (sin plataforma):")
    for eid, (nombre,) in sorted(
        {r[0]: (r[1],) for r in conn.execute("SELECT id::text, nombre FROM empresas").fetchall()}.items(),
        key=lambda kv: kv[1][0],
    ):
        cands = [nombre_ws.get(w, w) for w in mapa_empresa.get(eid, []) if w != plataforma]
        print(f"  {nombre:32} → {', '.join(cands) or '(solo plataforma)'}")
    print()

    tablas = [
        r[0]
        for r in conn.execute(
            """
            SELECT t.table_name FROM information_schema.tables t
            JOIN information_schema.columns c ON c.table_schema = t.table_schema AND c.table_name = t.table_name
            WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.column_name = 'empresa_id'
            ORDER BY t.table_name
            """
        ).fetchall()
        if es_tabla_de_negocio(r[0])
    ]

    lote = datetime.now(timezone.utc).strftime("fase1-%Y%m%dT%H%M%SZ")
    plan = []  # (tabla, fila_id, antes, despues, motivo)
    columnas_nuevas = []
    sin_resolver = Counter()
    sin_id = []
    for tabla in tablas:
        cols = _cols(conn, tabla)
        if "id" not in cols:
            sin_id.append(tabla)
            continue
        tiene_ws = "workspace_id" in cols
        if not tiene_ws:
            columnas_nuevas.append(tabla)
        tiene_cliente = "cliente_id" in cols
        sel_ws = "COALESCE(workspace_id, '')" if tiene_ws else "''"
        sel_cli = "cliente_id::text" if tiene_cliente else "NULL"
        filas = conn.execute(
            f"SELECT id::text, empresa_id::text, {sel_cli}, {sel_ws} FROM {tabla} WHERE {sel_ws} = ''"  # nosec B608 - nombres de information_schema
        ).fetchall()
        for fid, eid, cid, antes in filas:
            ws, motivo = decide_workspace(eid, cid, mapa_empresa=mapa_empresa, ws_de_cliente=ws_de_cliente, plataforma=plataforma)
            if ws:
                plan.append((tabla, fid, antes or None, ws, motivo))
            else:
                sin_resolver[(tabla, motivo)] += 1

    for cid in CLIENTES_DE_MODERNIA:
        fila = conn.execute("SELECT workspace_id FROM clientes WHERE id = %s", (cid,)).fetchone()
        if fila and fila[0] != modernia:
            plan.append(("clientes", cid, fila[0], modernia, "confirmado_por_el_usuario"))

    por_tabla = Counter((t, nombre_ws.get(ws, ws), m) for t, _f, _a, ws, m in plan)
    print(f"Columna workspace_id nueva en {len(columnas_nuevas)} tablas:")
    print("  " + ", ".join(columnas_nuevas) if columnas_nuevas else "  (ninguna)")
    print(f"\nFilas a rellenar: {len(plan)}")
    for (t, ws, m), n in sorted(por_tabla.items()):
        print(f"  {t:40} {n:6}  → {ws} (por {m})")
    print(f"\nSin resolver (se quedan como están): {sum(sin_resolver.values())}")
    for (t, m), n in sorted(sin_resolver.items()):
        print(f"  {t:40} {n:6}  ({m})")
    if sin_id:
        print(f"\nTablas sin columna id (no se tocan): {', '.join(sin_id)}")

    if not args.aplicar:
        print("\nEnsayo: no se ha escrito nada. Para aplicar: --aplicar")
        conn.rollback()
        return 0
    if not args.si:
        resp = input(f"\n¿Aplicar lote {lote} en {host}? Escribe APLICAR: ").strip()
        if resp != "APLICAR":
            print("Cancelado.")
            conn.rollback()
            return 1

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {LOG} (
          id BIGSERIAL PRIMARY KEY, lote TEXT NOT NULL, tabla TEXT NOT NULL, fila_id TEXT NOT NULL,
          antes TEXT, despues TEXT, motivo TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for tabla in columnas_nuevas:
        conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS workspace_id TEXT")  # nosec B608
    for tabla in tablas:
        if tabla in sin_id:
            continue
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{tabla}_workspace_id ON {tabla} (workspace_id)")  # nosec B608
    for tabla, fid, antes, ws, motivo in plan:
        conn.execute(f"UPDATE {tabla} SET workspace_id = %s WHERE id::text = %s", (ws, fid))  # nosec B608
        conn.execute(
            f"INSERT INTO {LOG} (lote, tabla, fila_id, antes, despues, motivo) VALUES (%s, %s, %s, %s, %s, %s)",
            (lote, tabla, fid, antes, ws, motivo),
        )
    instala_disparadores(conn, [t for t in tablas if t not in sin_id], plataforma)
    conn.commit()
    print(f"\nAplicado. Lote: {lote}. Para deshacer los valores: --deshacer {lote}")
    return 0


FUNCION = "ambito_workspace_desde_empresa"


def instala_disparadores(conn, tablas, plataforma):
    """Una fila nueva sin workspace lo recibe de su empresa, descartando la plataforma.

    Solo si la empresa cuelga de un único workspace fuera de la plataforma: si hay
    duda, no estampa nada, igual que el relleno.
    """
    conn.execute(
        f"""
        CREATE OR REPLACE FUNCTION {FUNCION}() RETURNS trigger AS $$
        DECLARE
          candidatos TEXT[];
        BEGIN
          IF COALESCE(NEW.workspace_id, '') = '' AND COALESCE(NEW.empresa_id::text, '') <> '' THEN
            SELECT array_agg(DISTINCT workspace_id) INTO candidatos
            FROM workspace_empresas
            WHERE empresa_id::text = NEW.empresa_id::text AND workspace_id <> '{plataforma}';
            IF array_length(candidatos, 1) = 1 THEN
              NEW.workspace_id := candidatos[1];
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for tabla in tablas:
        conn.execute(f"DROP TRIGGER IF EXISTS trg_{tabla}_workspace ON {tabla}")  # nosec B608
        conn.execute(
            f"CREATE TRIGGER trg_{tabla}_workspace BEFORE INSERT ON {tabla} "  # nosec B608
            f"FOR EACH ROW EXECUTE FUNCTION {FUNCION}()"
        )


def deshacer(conn, lote, sin_preguntar):
    filas = conn.execute(
        f"SELECT tabla, fila_id, antes, despues FROM {LOG} WHERE lote = %s ORDER BY id DESC", (lote,)
    ).fetchall()
    if not filas:
        print(f"No hay nada en el lote {lote}.")
        return 1
    print(f"Se restaurarán {len(filas)} valores de workspace_id del lote {lote}.")
    print("Las columnas y los disparadores se mantienen (no borran nada y no cambian lo existente).")
    if not sin_preguntar and input("Escribe DESHACER: ").strip() != "DESHACER":
        print("Cancelado.")
        conn.rollback()
        return 1
    for tabla, fid, antes, despues in filas:
        conn.execute(
            f"UPDATE {tabla} SET workspace_id = %s WHERE id::text = %s AND workspace_id = %s",  # nosec B608
            (antes, fid, despues),
        )
    conn.commit()
    print("Hecho.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
