#!/usr/bin/env python3
"""Deja una sola ficha por cliente, sin perder nada de lo que colgaba de las otras.

De dónde vienen los duplicados
------------------------------
De `alta_titulares_como_clientes.py`, que cargaba el índice de clientes una vez antes
de decidir y no lo actualizaba al crear: diez pólizas del mismo tomador sin ficha
consultaban las diez el mismo índice vacío y salían diez fichas idénticas. Dos tandas,
el 2026-04-21 y el 2026-08-04. Aquello ya está arreglado; esto limpia lo que dejó.

Qué hace
--------
1. Agrupa por nombre normalizado —sin tildes, sin signos, palabras ordenadas y
   **conservando los números**, porque «Sierra Bermeja 5» y «Sierra Bermeja 7» son dos
   comunidades distintas—.
2. **Descarta el grupo si sus fichas tienen documentos distintos.** Dos NIF distintos
   son dos personas mientras nadie diga lo contrario, y mezclarlas no se deshace
   mirando la base. Un `NIEESX9702310J` y un `X9702310J` sí son el mismo documento: el
   prefijo sobra.
3. Elige la ficha que se queda: la que tiene NIF; a igualdad, la más antigua. La más
   antigua con NIF es la que viene de la importación buena del 2026-03-24, donde los
   619 clientes traían su documento.
4. Mueve a la ficha que se queda **todo lo que colgaba de las demás** —pólizas,
   hipotecas, expedientes de gestoría, contabilidad, modelos—, buscando las columnas
   en el esquema en vez de darlas por sabidas. Las tablas de copia de seguridad no se
   tocan: son una foto de lo que había.
5. Rellena los huecos de la que se queda con lo que sólo tenían las otras (NIF,
   teléfono, email, dirección). **Nunca pisa un valor que ya esté.**
6. Borra las sobrantes.

Seguridad
---------
- En seco por defecto: sin `--apply` no escribe nada.
- Todo en una transacción: o entra entero o no entra nada.
- Respaldo en `clientes_fusion_backup` con la fila completa de cada ficha borrada y de
  cada referencia movida, para poder deshacerlo.
- Contra Postgres pregunta antes de escribir, salvo `--yes`.

Uso
---
    python scripts/fusiona_clientes_duplicados.py --workspace-id <ws>            # informe
    python scripts/fusiona_clientes_duplicados.py --workspace-id <ws> --apply
"""

from __future__ import annotations

import argparse
import json
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


def _rollback_best_effort(conn):
    """El adaptador pone un punto de retorno por sentencia; esto es el cinturón."""
    try:
        conn.execute("SELECT 1")
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass

TABLA_RESPALDO = "clientes_fusion_backup"
# Lo que se rellena del que se va al que se queda, si el que se queda lo tiene vacío.
CAMPOS_QUE_SE_HEREDAN = ("nif", "telefono", "movil", "email", "direccion", "codigo_postal",
                         "localidad", "poblacion", "provincia", "tipo", "tipo_persona",
                         "fecha_nacimiento")


def clave_de_nombre(valor):
    """Igual que en `alta_titulares_como_clientes.py`, números incluidos.

    Si aquí se quitaran los dígitos, la fusión juntaría dos comunidades vecinas.
    """
    texto = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-z0-9 ]", " ", texto.lower())
    return " ".join(sorted(texto.split()))


def documento(valor):
    """El NIF comparable. `NIEESX9702310J` y `X9702310J` son el mismo documento."""
    d = re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())
    return d[5:] if d.startswith("NIEES") else d


def columnas_que_apuntan_a_clientes(conn, backend="postgres"):
    """Dónde vive un `cliente_id`, preguntándoselo al esquema.

    Darlas por sabidas es cómo se deja una póliza colgando de un id que ya no existe:
    la primera versión de esto llevaba una lista escrita a mano y se dejó fuera
    `gestoria_contabilidad.cliente_ids_json`, que apunta a clientes dentro de un JSON.
    Tres apuntes acabaron nombrando a una ficha retirada.

    Las copias de seguridad se excluyen: son una foto y se quedan como están.
    """
    fuera = ("backup", "_bak")
    if backend != "postgres":
        columnas = []
        for t in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            tabla = str(valor(t, "name"))
            if tabla == "clientes" or any(x in tabla for x in fuera):
                continue
            for col in conn.execute(f'PRAGMA table_info("{tabla}")').fetchall():
                nombre = str(valor(col, "name"))
                if "cliente_id" in nombre:
                    columnas.append((tabla, nombre))
        return columnas
    filas = conn.execute(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND column_name LIKE '%cliente_id%'
          AND table_name <> 'clientes'
        ORDER BY table_name, column_name
        """
    ).fetchall()
    return [(f["table_name"], f["column_name"]) for f in filas
            if not any(x in f["table_name"] for x in fuera)]


def valor(fila, clave, defecto=None):
    try:
        return fila[clave]
    except Exception:
        return defecto


def agrupa(conn, workspace_id):
    filas = conn.execute(
        """
        SELECT * FROM clientes
        WHERE COALESCE(workspace_id, '') = ? AND TRIM(COALESCE(nombre, '')) <> ''
        ORDER BY created_at, id
        """,
        (workspace_id,),
    ).fetchall()
    grupos = {}
    for f in filas:
        k = clave_de_nombre(valor(f, "nombre"))
        if k:
            grupos.setdefault(k, []).append(f)
    return {k: v for k, v in grupos.items() if len(v) > 1}


def reparte(grupo):
    """Devuelve (la que se queda, las que se van) o (None, motivo) si no se puede."""
    docs = {documento(valor(g, "nif")) for g in grupo if str(valor(g, "nif") or "").strip()}
    docs.discard("")
    if len(docs) > 1:
        return None, f"documentos distintos: {sorted(docs)}"
    con_doc = [g for g in grupo if str(valor(g, "nif") or "").strip()]
    # La que tiene documento manda. A igualdad, la más antigua: es la de la importación
    # buena, la que trae los datos de verdad.
    candidatas = con_doc or list(grupo)
    candidatas = sorted(candidatas, key=lambda g: (str(valor(g, "created_at") or ""), str(valor(g, "id"))))
    se_queda = candidatas[0]
    se_van = [g for g in grupo if str(valor(g, "id")) != str(valor(se_queda, "id"))]
    return (se_queda, se_van), ""


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db", default=str(REPO_ROOT / "data" / "crm.sqlite"))
    p.add_argument("--backend", choices=["auto", "sqlite", "postgres"], default="auto")
    p.add_argument("--workspace-id", required=True)
    p.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    p.add_argument("--yes", action="store_true", help="No preguntar antes de escribir en Postgres.")
    args = p.parse_args(argv)

    if args.backend in ("sqlite", "postgres"):
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    print(f"Base de datos ............... {backend}")

    conn = open_db_conn(args.db, with_row_factory=True)
    try:
        grupos = agrupa(conn, args.workspace_id)
        refs = columnas_que_apuntan_a_clientes(conn, backend)
        print(f"Grupos con nombre repetido .. {len(grupos)}")
        print(f"Columnas que apuntan a clientes: {len(refs)}\n")

        plan, descartados = [], []
        for k, grupo in sorted(grupos.items()):
            reparto, motivo = reparte(grupo)
            if reparto is None:
                descartados.append((grupo, motivo))
                continue
            plan.append(reparto)

        print(f"  se fusionan ................ {len(plan)} grupos "
              f"({sum(len(v) for _, v in plan)} fichas se retiran)")
        print(f"  se dejan como están ........ {len(descartados)}")
        for grupo, motivo in descartados:
            print(f"     ! {valor(grupo[0], 'nombre')}: {motivo}")

        if not args.apply:
            print("\n  Detalle de lo que se movería:")
            for se_queda, se_van in plan[:8]:
                arrastre = []
                for tabla, col in refs:
                    n = sum(int(valor(conn.execute(
                        f'SELECT COUNT(*) AS n FROM "{tabla}" WHERE "{col}" = ?',
                        (str(valor(g, "id")),)).fetchone(), "n", 0) or 0) for g in se_van)
                    if n:
                        arrastre.append(f"{tabla}={n}")
                print(f"    {str(valor(se_queda,'nombre'))[:38]:40} "
                      f"se queda 1 de {len(se_van)+1} · mueve {', '.join(arrastre) or 'nada'}")
            if len(plan) > 8:
                print(f"    … y {len(plan) - 8} grupos más")
            print("\n(en seco: no se ha escrito nada; usa --apply)")
            return 0

        if backend == "postgres" and not args.yes:
            if input('Vas a escribir en PRODUCCIÓN. Escribe "si" para seguir: ').strip().lower() != "si":
                print("Cancelado.")
                return 1

        ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLA_RESPALDO} (
                fusion_en TEXT, se_queda TEXT, se_fue TEXT,
                ficha_json TEXT, referencias_json TEXT
            )
            """
        )
        # Qué tablas tienen algo de estas fichas, preguntado UNA vez por tabla.
        #
        # Antes se preguntaba por cada ficha y por cada tabla: 69 × 52 son 3.588
        # consultas, cada una con su punto de retorno, contra un servidor al otro lado
        # de Europa. La conexión se cayó a mitad —sin daño, porque va en una
        # transacción, pero sin terminar—. Una consulta por tabla son 52.
        todas_las_que_se_van = [str(valor(g, "id")) for _, se_van in plan for g in se_van]
        marcas = ", ".join(["?"] * len(todas_las_que_se_van))
        donde_hay = set()
        for tabla, col in refs:
            if tabla == "clientes":
                continue
            try:
                if col.endswith("_json") or col.endswith("_ids"):
                    condicion = " OR ".join([f'"{col}" LIKE ?'] * len(todas_las_que_se_van))
                    params = tuple(f"%{x}%" for x in todas_las_que_se_van)
                else:
                    condicion = f'"{col}" IN ({marcas})'
                    params = tuple(todas_las_que_se_van)
                n = valor(conn.execute(
                    f'SELECT COUNT(*) AS n FROM "{tabla}" WHERE {condicion}',
                    params).fetchone(), "n", 0)
            except Exception:
                _rollback_best_effort(conn)
                continue
            if int(n or 0):
                donde_hay.add((tabla, col))
        print(f"Tablas con algo que mover ... {len(donde_hay)} de {len(refs)}")

        movidas = borradas = heredados = descartadas = 0
        for se_queda, se_van in plan:
            destino = str(valor(se_queda, "id"))
            for g in se_van:
                origen = str(valor(g, "id"))
                movidas_de_esta = {}
                for tabla, col in refs:
                    if tabla == "clientes" or (tabla, col) not in donde_hay:
                        continue
                    comparacion = (f'"{col}" LIKE ?', f"%{origen}%") \
                        if (col.endswith("_json") or col.endswith("_ids")) \
                        else (f'"{col}" = ?', origen)
                    ids = [str(valor(x, "id")) for x in conn.execute(
                        f'SELECT id FROM "{tabla}" WHERE {comparacion[0]}',
                        (comparacion[1],)).fetchall()]
                    if not ids:
                        continue
                    movidas_de_esta[f"{tabla}.{col}"] = ids
                    if col.endswith("_json") or col.endswith("_ids"):
                        # Una columna que guarda una LISTA de ids —`cliente_ids_json`
                        # tiene `["abc…"]`— no se cambia con un UPDATE de igualdad: el
                        # valor nunca es el id pelado. Se reemplaza dentro del texto y
                        # se comprueba que siga siendo JSON válido antes de escribirlo.
                        #
                        # Se me pasó en la primera pasada y dejó tres apuntes de
                        # contabilidad nombrando a una ficha que ya no existía.
                        for rid in ids:
                            fila = conn.execute(f'SELECT "{col}" AS v FROM "{tabla}" WHERE id = ?',
                                                (rid,)).fetchone()
                            crudo = str(valor(fila, "v") or "")
                            if origen not in crudo:
                                continue
                            nuevo = crudo.replace(origen, destino)
                            try:
                                json.loads(nuevo)
                            except Exception:
                                print(f"     ! {tabla}.{col} de {rid[:10]}… no queda como JSON "
                                      f"válido al sustituir; se deja y se avisa")
                                continue
                            conn.execute(f'UPDATE "{tabla}" SET "{col}" = ? WHERE id = ?',
                                         (nuevo, rid))
                            movidas += 1
                        continue
                    for rid in ids:
                        try:
                            conn.execute(f'UPDATE "{tabla}" SET "{col}" = ? WHERE id = ?',
                                         (destino, rid))
                            movidas += 1
                            continue
                        except Exception:
                            pass
                        # Choca con una restricción única: la ficha que se queda ya
                        # tiene su fila equivalente. Pasa en `cliente_gestoria`,
                        # `seguros_preferencias`, `gestoria_conta_config`… — tablas de
                        # una fila por cliente.
                        #
                        # Lo normal es que la de la ficha retirada esté vacía (la creó
                        # la importación) y la buena tenga los datos de verdad: la renta
                        # con su OCR, la configuración contable. Pero eso se comprueba,
                        # no se supone: si la que se iba a descartar tiene MÁS datos que
                        # la que se queda, esto para el grupo entero y lo dice. Tirar la
                        # fila con la declaración de la renta dentro no se arregla luego.
                        _rollback_best_effort(conn)
                        sobra = conn.execute(f'SELECT * FROM "{tabla}" WHERE id = ?',
                                             (rid,)).fetchone()
                        gemela = conn.execute(
                            f'SELECT * FROM "{tabla}" WHERE "{col}" = ? LIMIT 1',
                            (destino,)).fetchone()
                        peso = lambda f: sum(  # noqa: E731
                            1 for v in dict(f).values() if str(v or "").strip() not in ("", "0"))
                        if gemela is not None and peso(sobra) > peso(gemela):
                            raise SystemExit(
                                f"\n  PARADO en «{valor(se_queda, 'nombre')}»: en {tabla} la fila "
                                f"de la ficha que se retira ({origen[:12]}…) tiene más datos "
                                f"({peso(sobra)} campos) que la de la que se queda "
                                f"({peso(gemela)}). Míralo a mano antes de fusionar este grupo.\n"
                                f"  No se ha escrito nada."
                            )
                        conn.execute(
                            f"INSERT INTO {TABLA_RESPALDO} (fusion_en, se_queda, se_fue,"
                            " ficha_json, referencias_json) VALUES (?, ?, ?, ?, ?)",
                            (ahora, destino, origen,
                             json.dumps({k: str(v)[:4000] for k, v in dict(sobra).items()},
                                        ensure_ascii=False),
                             json.dumps({"descartada_de": f"{tabla}.{col}"}, ensure_ascii=False)))
                        conn.execute(f'DELETE FROM "{tabla}" WHERE id = ?', (rid,))
                        descartadas += 1
                # lo que sólo tenía la que se va y a la que se queda le falta
                for campo in CAMPOS_QUE_SE_HEREDAN:
                    v = str(valor(g, campo) or "").strip()
                    if v and not str(valor(se_queda, campo) or "").strip():
                        try:
                            conn.execute(f'UPDATE clientes SET "{campo}" = ? WHERE id = ?',
                                         (v, destino))
                            se_queda = conn.execute("SELECT * FROM clientes WHERE id = ?",
                                                    (destino,)).fetchone()
                            heredados += 1
                        except Exception:
                            pass
                conn.execute(
                    f"INSERT INTO {TABLA_RESPALDO} (fusion_en, se_queda, se_fue, ficha_json,"
                    " referencias_json) VALUES (?, ?, ?, ?, ?)",
                    (ahora, destino, origen,
                     json.dumps({k: str(v) for k, v in dict(g).items()}, ensure_ascii=False),
                     json.dumps(movidas_de_esta, ensure_ascii=False)),
                )
                conn.execute("DELETE FROM clientes WHERE id = ?", (origen,))
                borradas += 1

        # Un vínculo con la misma empresa y servicio, repetido, ya no aporta.
        conn.execute(
            """
            DELETE FROM clientes_empresas WHERE id IN (
              SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                  PARTITION BY cliente_id, COALESCE(empresa_id,''), COALESCE(servicio,'')
                  ORDER BY created_at, id) AS n
                FROM clientes_empresas) t
              WHERE t.n > 1)
            """
        )
        conn.commit()
        print(f"\nFichas retiradas ............ {borradas}")
        print(f"Referencias movidas ......... {movidas}")
        print(f"Filas de una-por-cliente descartadas: {descartadas}")
        print(f"Datos heredados ............. {heredados}")
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
