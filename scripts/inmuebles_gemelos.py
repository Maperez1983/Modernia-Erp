#!/usr/bin/env python3
"""Busca inmuebles y operaciones que se han vuelto gemelos después del alta.

Contexto
--------
El CRM comprueba duplicados **sólo al crear**: compara dirección, referencia
catastral y NIF de los propietarios contra lo que ya hay de esa empresa, y avisa
—no bloquea— salvo que se reenvíe con `allow_duplicate`.

Eso deja un hueco: si dos fichas se separan al nacer y luego convergen —porque
alguien corrige una dirección, rellena el catastro más tarde o escribe la puerta de
otra forma— nadie vuelve a mirar. Pasó de verdad: «Avenida las Postas Nº22 bajo 3g»
y «bajo 6g» tenían la MISMA referencia catastral y generaron dos operaciones de la
misma venta, con los mismos compradores, el mismo precio y los mismos honorarios.
209.000 € contados dos veces en el volumen de cierre, y nadie se enteró.

Qué mira
--------
Los mismos tres criterios que el alta, pero sobre todo lo que ya existe:

1. Misma dirección normalizada (con el mapa de tipos de vía: CALLE = CL = C/).
2. Misma referencia catastral.
3. Mismo NIF de propietario.

Y además cruza `operaciones_inmobiliarias`, que es donde se cuenta el dinero.

No escribe nada: es un informe. Fusionar dos fichas es una decisión de negocio
—cuál se queda, qué documentos se mueven— y no debe hacerla un script a ciegas.

Uso
---
    python scripts/inmuebles_gemelos.py
    python scripts/inmuebles_gemelos.py --backend sqlite --db data/crm.sqlite
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from web.db_backend import is_postgres_enabled, open_db_conn  # noqa: E402
from web.server import (  # noqa: E402
    clean_catastro_reference,
    load_env_file,
    normalize_inmobiliaria_address,
    normalize_nif,
)


def valor(fila, clave, defecto=None):
    try:
        return fila[clave]
    except Exception:
        return defecto


def agrupa(filas, clave_de):
    grupos = defaultdict(list)
    for fila in filas:
        clave = clave_de(fila)
        if clave:
            grupos[clave].append(fila)
    return {k: v for k, v in grupos.items() if len(v) > 1}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("sqlite", "postgres"))
    ap.add_argument("--db", default="data/crm.sqlite")
    args = ap.parse_args()

    load_env_file()
    if args.backend:
        os.environ["APP_DB_BACKEND"] = args.backend
    backend = "postgres" if is_postgres_enabled() else "sqlite"
    conn = open_db_conn(args.db, with_row_factory=True)
    print(f"Base: {'Postgres' if backend == 'postgres' else 'SQLite ' + args.db}\n")

    inmuebles = conn.execute(
        """SELECT i.id, i.empresa_id, COALESCE(i.direccion,'') AS direccion,
                  COALESCE(i.referencia_catastral,'') AS refcat, COALESCE(i.estado,'') AS estado,
                  COALESCE(i.tipo_operacion,'') AS tipo_operacion
           FROM inmuebles i"""
    ).fetchall()

    hallazgos = 0

    def informa(titulo, grupos, pinta):
        nonlocal hallazgos
        print(f"── {titulo} ──")
        if not grupos:
            print("   nada\n")
            return
        for clave, filas in grupos.items():
            # Una venta y un alquiler del mismo local no son un duplicado.
            tipos = {str(valor(f, "tipo_operacion", "") or "").lower() for f in filas}
            if len(tipos) > 1 and "" not in tipos:
                continue
            hallazgos += 1
            print(f"   «{clave[1] if isinstance(clave, tuple) else clave}»")
            for f in filas:
                print("      " + pinta(f))
        print()

    informa(
        "Misma dirección (normalizada)",
        agrupa(inmuebles, lambda f: (valor(f, "empresa_id"), normalize_inmobiliaria_address(valor(f, "direccion")))),
        lambda f: f"{str(valor(f,'direccion'))[:38]:<40} {valor(f,'estado'):<24} "
                  f"op={valor(f,'tipo_operacion') or '-':<9} catastro={valor(f,'refcat') or '-'}",
    )

    informa(
        "Misma referencia catastral",
        agrupa(inmuebles, lambda f: (valor(f, "empresa_id"), clean_catastro_reference(valor(f, "refcat")))),
        lambda f: f"{str(valor(f,'direccion'))[:38]:<40} {valor(f,'estado'):<24} op={valor(f,'tipo_operacion') or '-'}",
    )

    try:
        propietarios = conn.execute(
            """SELECT ip.inmueble_id, i.empresa_id, COALESCE(i.direccion,'') AS direccion,
                      COALESCE(c.nif,'') AS nif, COALESCE(c.nombre,'') AS nombre
               FROM inmueble_propietarios ip
               JOIN inmuebles i ON i.id = ip.inmueble_id
               JOIN clientes c ON c.id = ip.cliente_id
               WHERE COALESCE(c.nif,'') <> ''"""
        ).fetchall()
    except Exception:
        propietarios = []
    # Un propietario con dos inmuebles es normal; lo que llama la atención es el mismo
    # NIF sobre la misma dirección, y eso ya lo cazan los dos bloques de arriba. Aquí
    # sólo se informa de quién acumula fichas, por si alguna es la misma repetida.
    por_nif = defaultdict(set)
    for f in propietarios:
        por_nif[(valor(f, "empresa_id"), normalize_nif(valor(f, "nif")), valor(f, "nombre"))].add(
            str(valor(f, "direccion"))
        )
    repetidos = {k: v for k, v in por_nif.items() if len(v) > 1}
    print("── Propietarios con varias fichas (informativo, no es un duplicado) ──")
    if not repetidos:
        print("   nada\n")
    else:
        for (_emp, nif, nombre), direcciones in sorted(repetidos.items(), key=lambda x: -len(x[1]))[:10]:
            print(f"   {nombre[:30]:<32} {nif}  ({len(direcciones)} inmuebles)")
        print()

    operaciones = conn.execute(
        """SELECT id, empresa_id, COALESCE(direccion,'') AS direccion,
                  COALESCE(referencia_catastral,'') AS refcat,
                  COALESCE(precio_escritura,0) AS precio,
                  COALESCE(fecha_escritura,'') AS fecha,
                  COALESCE(contraparte_nombre,'') AS comprador
           FROM operaciones_inmobiliarias"""
    ).fetchall()
    print("── Operaciones gemelas (aquí es donde se cuenta el dinero dos veces) ──")

    def clave_operacion(f):
        # Sin catastro y sin importe no hay nada que comparar: 18 importaciones
        # históricas comparten «vacío» y agruparlas todas juntas es ruido, no un
        # hallazgo. Se exige al menos uno de los dos, y el otro como refuerzo.
        refcat = clean_catastro_reference(valor(f, "refcat"))
        try:
            precio = float(valor(f, "precio") or 0)
        except (TypeError, ValueError):
            precio = 0.0
        direccion = normalize_inmobiliaria_address(valor(f, "direccion"))
        if refcat:
            return (valor(f, "empresa_id"), refcat, f"{precio:.2f}")
        if precio > 0 and direccion:
            return (valor(f, "empresa_id"), direccion, f"{precio:.2f}")
        return None

    grupos = agrupa(operaciones, clave_operacion)
    if not grupos:
        print("   nada\n")
    else:
        for clave, filas in grupos.items():
            hallazgos += 1
            print(f"   catastro {clave[1]} · importe {clave[2]}")
            for f in filas:
                print(f"      {str(valor(f,'direccion'))[:36]:<38} escritura={valor(f,'fecha') or '-':<12} "
                      f"comprador={str(valor(f,'comprador'))[:26] or '-'}")
        print()

    print(f"{'═' * 70}")
    if hallazgos:
        print(f"{hallazgos} grupos que merece la pena mirar.")
        print("Fusionar es decisión de negocio: cuál se queda y qué documentos se mueven.")
    else:
        print("Sin fichas gemelas.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main() or 0)
