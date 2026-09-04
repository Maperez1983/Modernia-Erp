#!/usr/bin/env python3
"""Da de alta como cliente al titular de un expediente que no lo tenga.

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
4. Si el mismo titular sale otra vez **en este mismo lote**, se enlaza a la ficha
   que se acaba de crear. Una ficha por titular, no una por expediente.

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

Lo que salió mal el 2026-08-04
------------------------------
El índice de clientes se carga una vez, antes de decidir. Diez pólizas del mismo
tomador sin ficha consultaban las diez el mismo índice vacío, las diez caían en «no
existe» y salían **diez fichas idénticas con una póliza cada una**. Dejó 49 fichas de
más: GARCISA MASAE diez veces, JUAN RAMOS ocho, JOSE LUIS TORRES seis.

El guion ya se cuidaba de no elegir mal entre varias candidatas —eso mezcla a dos
personas y no se deshace— pero no de fabricar él mismo esas candidatas. Arreglado en el
punto 4 de arriba.

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

ESTADOS_FIRMADOS = ("firmada", "firmado")
TABLA_RESPALDO = "hipotecas_titulares_alta_backup"

# Cada CRM guarda el titular en una columna distinta y lo vincula por `cliente_id`.
# El resto del guion es idéntico, así que se parametriza en vez de copiarse.
MODULOS = {
    "hipotecas": {
        "tabla": "hipotecas",
        "columna_nombre": "cliente",
        "servicio": "financiaciones",
        "orden": "COALESCE(NULLIF(fecha_firma, ''), '9999')",
    },
    "seguros": {
        "tabla": "seguros",
        "columna_nombre": "tomador",
        "servicio": "seguros",
        "orden": "COALESCE(NULLIF(fecha_efecto, ''), '9999')",
    },
}


def clave_de_nombre(valor):
    """Nombre comparable: sin tildes, sin signos, en minúsculas y con las palabras ordenadas.

    Ordenar las palabras es lo que hace que "MOHAMED BOUZYANE" y "BOUZYANE MOHAMED"
    sean la misma clave. En este CRM el orden nombre/apellido no es fiable.

    **Los números se conservan.** Antes se quitaban junto con los signos, y en una
    administración de fincas eso es justo lo que no se puede hacer: las comunidades se
    llaman calle y número. "Sierra Bermeja 5" y "Sierra Bermeja 7" daban la misma clave,
    igual que "Emilio Prados 26" y "Emilio Prados 6", o "Barcenillas 6" y "Barcenillas
    12". Y este guion **enlaza sin preguntar cuando encuentra una sola candidata**: la
    póliza de un edificio se habría colgado del edificio de al lado, en silencio.

    Comprobado en producción el 2026-08-25: no ha llegado a pasar —ninguna póliza ni
    hipoteca está enlazada a una ficha que sólo difiera en el número—, así que esto
    quita la trampa antes de pisarla.

    Conservarlos hace la clave más estricta, y en esa dirección se falla bien: como
    mucho deja una ficha duplicada, que se ve y se arregla. Enlazar a quien no es no se
    ve.
    """
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9 ]", " ", texto.lower())
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


def pendientes(conn, workspace_id, todos_los_estados=False, modulo="hipotecas"):
    """Hipotecas del workspace cuyo titular no tiene ficha de cliente.

    Por defecto solo las firmadas, que es la regla de negocio original. Con
    `todos_los_estados` entran también las pendientes, canceladas y las de
    indemnización: el titular de un expediente existe aunque la operación no llegara
    a firmarse, y si no está de alta no se le puede buscar ni volver a llamar.
    """
    cfg = MODULOS[modulo]
    tabla, columna, orden = cfg["tabla"], cfg["columna_nombre"], cfg["orden"]
    filtro_estado = ""
    valores = []
    if not todos_los_estados:
        marcas = ",".join(["?"] * len(ESTADOS_FIRMADOS))
        filtro_estado = f"AND LOWER(TRIM(COALESCE(estado, ''))) IN ({marcas})"
        valores.extend(ESTADOS_FIRMADOS)
    return conn.execute(
        f"""
        SELECT id, {columna} AS cliente, empresa_id, estado
        FROM {tabla}
        WHERE COALESCE(TRIM(COALESCE(cliente_id, '')), '') = ''
          AND TRIM(COALESCE({columna}, '')) <> ''
          {filtro_estado}
          AND (COALESCE(workspace_id, '') = ? OR empresa_id IN (
                SELECT empresa_id FROM workspace_empresas WHERE workspace_id = ?
              ))
        ORDER BY {orden}, {columna}
        """,
        (*valores, workspace_id, workspace_id),
    ).fetchall()


def asegurar_respaldo(conn):
    """Crea el respaldo y le añade `tabla_origen` si viene de antes de los módulos.

    Las 45 anotaciones que ya existían son todas de hipotecas: se rellenan con ese
    valor para que el rollback siga sabiendo dónde deshacerlas.
    """
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
    try:
        conn.execute(f"ALTER TABLE {TABLA_RESPALDO} ADD COLUMN tabla_origen TEXT")
    except Exception:
        pass
    try:
        conn.execute(
            f"UPDATE {TABLA_RESPALDO} SET tabla_origen = 'hipotecas'"
            " WHERE COALESCE(tabla_origen, '') = ''"
        )
    except Exception:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(REPO_ROOT / "data" / "crm.sqlite"))
    parser.add_argument("--backend", choices=["auto", "sqlite", "postgres"], default="auto")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--modulo", choices=sorted(MODULOS), default="hipotecas")
    parser.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    parser.add_argument("--rollback", action="store_true", help="Deshace lo que hizo este script.")
    parser.add_argument("--yes", action="store_true", help="No preguntar antes de escribir en Postgres.")
    parser.add_argument(
        "--todos-los-estados",
        action="store_true",
        help="No limitarse a las firmadas: dar de alta al titular de cualquier expediente.",
    )
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

        cfg = MODULOS[args.modulo]
        if args.rollback:
            filas = conn.execute(f"SELECT * FROM {TABLA_RESPALDO}").fetchall()
            print(f"Anotaciones de respaldo ..... {len(filas)}")
            if not args.apply:
                print("(en seco: no se toca nada)")
                return 0
            for fila in filas:
                origen = str(fila["tabla_origen"] or "hipotecas")
                if origen not in {cfg["tabla"] for cfg in MODULOS.values()}:
                    continue
                conn.execute(
                    f"UPDATE {origen} SET cliente_id = '' WHERE id = ?", (fila["hipoteca_id"],)
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
        filas = pendientes(conn, args.workspace_id, args.todos_los_estados, args.modulo)
        cfg = MODULOS[args.modulo]
        etiqueta = f"{cfg['tabla'].capitalize()} sin ficha"
        print(f"{etiqueta:<30}{len(filas)}")

        a_enlazar, a_crear, ambiguas = [], [], []
        for fila in filas:
            candidatos = indice.get(clave_de_nombre(fila["cliente"]), [])
            if len(candidatos) == 1:
                a_enlazar.append((fila, candidatos[0]))
            elif len(candidatos) > 1:
                ambiguas.append((fila, candidatos))
            else:
                a_crear.append(fila)

        # Cuántas fichas se van a crear DE VERDAD: los titulares distintos que hay en
        # `a_crear`, no las filas. Si en el resumen se cuentan las filas, un lote con
        # diez pólizas del mismo señor anuncia diez fichas y crea una.
        nombres_nuevos = {clave_de_nombre(f["cliente"]) for f in a_crear}
        print(f"  se enlazan a una ficha ya existente  {len(a_enlazar)}")
        print(f"  se crean fichas nuevas               {len(nombres_nuevos)}")
        if len(a_crear) > len(nombres_nuevos):
            print(f"     ({len(a_crear) - len(nombres_nuevos)} expedientes más comparten "
                  f"titular con otro de este mismo lote y se enlazan a la ficha nueva)")
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
                f"UPDATE {cfg['tabla']} SET cliente_id = ?, updated_at = ? WHERE id = ?",
                (cliente_id, ahora, fila["id"]),
            )
            conn.execute(
                f"INSERT INTO {TABLA_RESPALDO} (hipoteca_id, cliente_id, cliente_creado, vinculo_id, creado_en, tabla_origen)"
                " VALUES (?, ?, 0, '', ?, ?)",
                (fila["id"], cliente_id, ahora, cfg["tabla"]),
            )
            enlazados += 1

        # Una ficha por titular, no una por expediente.
        #
        # El índice de clientes se carga UNA vez, antes de decidir. Si el mismo titular
        # aparece en diez pólizas y no tenía ficha, las diez consultan el mismo índice
        # vacío, las diez caen en «no existe» y se creaban diez fichas idénticas. Pasó:
        # el 2026-08-04 este guion dejó 49 fichas de más, entre ellas GARCISA MASAE diez
        # veces y JUAN RAMOS ocho, cada una con exactamente una póliza colgando.
        #
        # El guion ya se cuidaba de no elegir mal entre varias candidatas —eso mezcla a
        # dos personas y no se deshace— pero no de fabricar él mismo esas candidatas.
        #
        # La primera fila de cada nombre crea la ficha; las demás se enlazan a ella,
        # igual que si ya hubiera existido.
        creadas_en_esta_pasada = {}
        for fila in a_crear:
            clave = clave_de_nombre(fila["cliente"])
            gemela = creadas_en_esta_pasada.get(clave)
            if gemela:
                conn.execute(
                    f"UPDATE {cfg['tabla']} SET cliente_id = ?, updated_at = ? WHERE id = ?",
                    (gemela, ahora, fila["id"]),
                )
                conn.execute(
                    f"INSERT INTO {TABLA_RESPALDO} (hipoteca_id, cliente_id, cliente_creado, vinculo_id, creado_en, tabla_origen)"
                    " VALUES (?, ?, 0, '', ?, ?)",
                    (fila["id"], gemela, ahora, cfg["tabla"]),
                )
                enlazados += 1
                continue
            cliente_id = nuevo_id()
            vinculo_id = nuevo_id()
            creadas_en_esta_pasada[clave] = cliente_id
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
                (vinculo_id, cliente_id, fila["empresa_id"], cfg["servicio"], args.workspace_id, ahora, ahora),
            )
            conn.execute(
                f"UPDATE {cfg['tabla']} SET cliente_id = ?, updated_at = ? WHERE id = ?",
                (cliente_id, ahora, fila["id"]),
            )
            conn.execute(
                f"INSERT INTO {TABLA_RESPALDO} (hipoteca_id, cliente_id, cliente_creado, vinculo_id, creado_en, tabla_origen)"
                " VALUES (?, ?, 1, ?, ?, ?)",
                (fila["id"], cliente_id, vinculo_id, ahora, cfg["tabla"]),
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
