#!/usr/bin/env python3
"""Pasa las columnas de dinero de `real` a `numeric(14,2)`.

El problema
-----------
Todas las columnas de importe eran `real`: coma flotante de precisión simple, unos
7 dígitos significativos. Para cifras de seis dígitos con céntimos eso ya no llega,
y el error se acumula al sumar. Medido en producción el 2026-08-03 sobre las
hipotecas firmadas, la misma suma daba 9.351.707,00 o 9.351.707,40 según cómo se
sumara. En un CRM financiero eso no es un detalle.

La trampa de la conversión
--------------------------
`ALTER TABLE ... TYPE numeric USING columna::numeric` **se come los céntimos**:

    real 108374.63  ->  numeric 108375
    real  82630.39  ->  numeric  82630.4

Porque el cast directo arrastra la precisión del float4. Hay que pasar por texto,
`columna::text::numeric`, que usa la representación decimal más corta que
round-trip el float —es decir, el número que se tecleó— y conserva 108374.63.

Es un fallo silencioso: la migración diría "hecho" y la base perdería los céntimos
de todo el histórico sin un solo error.

Qué convierte
-------------
Solo columnas de dinero, elegidas por nombre. NO toca latitudes, porcentajes,
confianzas de OCR, metros cuadrados, coeficientes ni las marcas de tiempo que
algunas tablas guardan como float. Convertir esas sería otro error distinto.

Solo Postgres: SQLite es de tipado dinámico y no distingue.

Seguridad
---------
- En seco por defecto: sin `--apply` solo informa, y enseña qué valores cambiarían.
- Transaccional por tabla.
- Reversible: guarda el tipo anterior en `dinero_numeric_migracion_backup`.
  `--rollback` devuelve las columnas a `real`. Ojo: volver a `real` vuelve a perder
  precisión, así que el rollback es para emergencias, no para ir y venir.
- Idempotente: las columnas que ya son numeric se saltan.

Uso
---
    python scripts/migrar_dinero_a_numeric.py --tabla hipotecas          # informe
    python scripts/migrar_dinero_a_numeric.py --tabla hipotecas --apply
    python scripts/migrar_dinero_a_numeric.py --todas                    # informe
    python scripts/migrar_dinero_a_numeric.py --todas --apply --yes
    python scripts/migrar_dinero_a_numeric.py --rollback --apply
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TABLA_RESPALDO = "dinero_numeric_migracion_backup"

# Nombres que SÍ son dinero. Se comparan por palabra completa o prefijo claro.
ES_DINERO = re.compile(
    r"^(importe|precio|comision|prima|total|subtotal|impuestos|entrada|cesion|honorarios"
    r"|base_imponible|base_exenta|base_no_sujeta|base_detectada|cuota_iva|cuota_irpf"
    r"|aportacion|capital|capital_social|saldo|bruto|neto|ss_empresa|ss_trabajador"
    r"|coste_estimado|tarifa_mensual|cuota_mensual|cuota_sugerida|valor_transmision"
    r"|valor_residual|valor_referencia|valor_maximo_piso|amortizacion_acumulada"
    r"|desviacion_euros|entrega_2|interes|precio_unitario|total_linea|importe_objetivo"
    r"|importe_a_pagar|importe_final|importe_liquidacion|importe_pagado|importe_reserva"
    r"|importe_base|importe_cobrado|importe_propuesta|total_detectado|cuota_iva_detectada"
    r"|precio_base|comision_fija|ingresos|ingresos_conjuntos|prestamo_resto"
    r"|cliente1_ingresos|cliente2_ingresos|cliente1_prestamo_resto|cliente2_prestamo_resto)"
    r"(_[a-z0-9_]+)?$"
)

# Nombres que NO son dinero aunque el patrón de arriba los roce.
NO_ES_DINERO = re.compile(
    r"(_pct|_pc|porcentaje|probabilidad|coeficiente|participaciones|confianza|confidence"
    r"|score|^lat$|^lon$|^m2$|_lat$|_lon$|_acc$|dias|horas|anios|vida_util"
    r"|created_at|updated_at|expires_at|locked_until|window_started_at|numero_)"
)


def es_columna_de_dinero(nombre: str) -> bool:
    if NO_ES_DINERO.search(nombre):
        return False
    return bool(ES_DINERO.match(nombre))


def columnas_flotantes(cur):
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public' AND data_type IN ('real', 'double precision')
        ORDER BY table_name, column_name
        """
    )
    return cur.fetchall()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tabla", help="Convertir solo esta tabla.")
    parser.add_argument("--todas", action="store_true", help="Todas las tablas.")
    parser.add_argument("--apply", action="store_true", help="Escribe. Sin esto va en seco.")
    parser.add_argument("--rollback", action="store_true", help="Devuelve las columnas a real.")
    parser.add_argument("--yes", action="store_true", help="No preguntar antes de escribir.")
    args = parser.parse_args(argv)

    if not (args.tabla or args.todas or args.rollback):
        parser.error("indica --tabla, --todas o --rollback")

    try:
        import psycopg
    except ImportError:
        print("ERROR: hace falta psycopg (esta migración es solo de Postgres).")
        return 2

    dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn:
        for linea in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if linea.startswith(("DATABASE_URL=", "POSTGRES_URL=")):
                dsn = linea.split("=", 1)[1].strip().strip('"').strip("'")
    if not dsn:
        print("ERROR: no hay DATABASE_URL ni POSTGRES_URL.")
        return 2

    con = psycopg.connect(dsn)
    cur = con.cursor()
    try:
        cur.execute(
            f"""CREATE TABLE IF NOT EXISTS {TABLA_RESPALDO} (
                    tabla TEXT, columna TEXT, tipo_anterior TEXT, migrado_en TEXT
                )"""
        )
        con.commit()

        if args.rollback:
            cur.execute(f"SELECT tabla, columna, tipo_anterior FROM {TABLA_RESPALDO}")
            filas = cur.fetchall()
            print(f"Columnas migradas anotadas ... {len(filas)}")
            if not args.apply:
                print("(en seco: no se toca nada)")
                return 0
            for tabla, columna, tipo in filas:
                cur.execute(f'ALTER TABLE "{tabla}" ALTER COLUMN "{columna}" TYPE {tipo}')
                print(f"   {tabla}.{columna} -> {tipo}")
            cur.execute(f"DELETE FROM {TABLA_RESPALDO}")
            con.commit()
            print("Rollback hecho.")
            return 0

        objetivo = []
        for tabla, columna, tipo in columnas_flotantes(cur):
            if args.tabla and tabla != args.tabla:
                continue
            if not es_columna_de_dinero(columna):
                continue
            objetivo.append((tabla, columna, tipo))

        print(f"Columnas de dinero a convertir . {len(objetivo)}")
        if not objetivo:
            print("(nada que hacer)")
            return 0

        # Enseñar qué valores cambiarían de verdad, que es lo que importa.
        tocados = 0
        for tabla, columna, _tipo in objetivo:
            cur.execute(
                f'''SELECT COUNT(*) FROM "{tabla}"
                    WHERE "{columna}" IS NOT NULL
                      AND "{columna}"::numeric <> ROUND("{columna}"::text::numeric, 2)'''
            )
            distintos = cur.fetchone()[0]
            cur.execute(f'SELECT COUNT(*) FROM "{tabla}" WHERE "{columna}" IS NOT NULL')
            con_valor = cur.fetchone()[0]
            marca = f"  <-- {distintos} perderían céntimos con el cast directo" if distintos else ""
            print(f"   {tabla}.{columna:<24} {con_valor:>7} valores{marca}")
            tocados += con_valor

        if not args.apply:
            print("\n(en seco: no se ha escrito nada; usa --apply)")
            return 0

        if not args.yes:
            if input('Vas a alterar el esquema de PRODUCCIÓN. Escribe "si" para seguir: ').strip().lower() != "si":
                print("Cancelado.")
                return 1

        for tabla, columna, tipo in objetivo:
            cur.execute(
                f"INSERT INTO {TABLA_RESPALDO} (tabla, columna, tipo_anterior, migrado_en)"
                " VALUES (%s, %s, %s, NOW()::text)",
                (tabla, columna, tipo),
            )
            # ::text::numeric, NO ::numeric. Ver la cabecera: el cast directo redondea
            # a la precisión del float4 y se lleva los céntimos por delante.
            cur.execute(
                f'''ALTER TABLE "{tabla}"
                    ALTER COLUMN "{columna}" TYPE numeric(14,2)
                    USING ROUND("{columna}"::text::numeric, 2)'''
            )
            print(f"   {tabla}.{columna} -> numeric(14,2)")
        con.commit()
        print(f"\nHecho: {len(objetivo)} columnas.")
        return 0
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
