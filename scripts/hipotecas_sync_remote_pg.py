import json
import os
import re
import sys
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


FIN_EMPRESA_NOMBRE = "Financiaciones Modernia"


def _nonempty(value):
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
    return str(value).strip()


def _normalize_nif(value):
    raw = _nonempty(value).upper()
    raw = raw.replace(" ", "").replace(".", "").replace("-", "")
    return re.sub(r"[^0-9A-Z]", "", raw)


def ensure_cliente_servicio_link(cur, cliente_id, empresa_id, servicio, now, estado="Activo"):
    if not cliente_id or not empresa_id or not servicio:
        return
    existing = cur.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = %s AND empresa_id = %s AND LOWER(servicio) = LOWER(%s)
        LIMIT 1
        """,
        (cliente_id, empresa_id, servicio),
    ).fetchone()
    if existing:
        return
    cur.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (
          gen_random_uuid()::text, %s, %s, %s, %s, NULL, NULL, %s, %s
        )
        """,
        (cliente_id, empresa_id, servicio, estado, now, now),
    )


def upsert_cliente(cur, empresa_id, cliente, now):
    """
    Mantiene aislamiento por empresa: busca por (empresa_id,nif). Si no existe, crea uno nuevo aunque exista en otra empresa.
    """
    nif = _normalize_nif(cliente.get("nif"))
    nombre = _nonempty(cliente.get("nombre")) or nif or "Cliente"
    email = _nonempty(cliente.get("email"))
    telefono = _nonempty(cliente.get("telefono"))
    direccion = _nonempty(cliente.get("direccion"))
    movil = _nonempty(cliente.get("movil"))
    otro_telefono = _nonempty(cliente.get("otro_telefono"))
    codigo_postal = _nonempty(cliente.get("codigo_postal"))
    poblacion = _nonempty(cliente.get("poblacion"))
    provincia = _nonempty(cliente.get("provincia"))
    localidad = _nonempty(cliente.get("localidad"))
    direccion_numero = _nonempty(cliente.get("direccion_numero"))

    existing = None
    if nif:
        existing = cur.execute(
            """
            SELECT id FROM clientes
            WHERE empresa_id = %s
              AND REPLACE(REPLACE(REPLACE(UPPER(COALESCE(nif,'')), ' ', ''), '-', ''), '.', '') = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (empresa_id, nif),
        ).fetchone()
    if existing:
        cliente_id = existing["id"]
        cur.execute(
            """
            UPDATE clientes
            SET nombre = COALESCE(NULLIF(%s, ''), nombre),
                nif = COALESCE(NULLIF(%s, ''), nif),
                email = COALESCE(NULLIF(%s, ''), email),
                telefono = COALESCE(NULLIF(%s, ''), telefono),
                direccion = COALESCE(NULLIF(%s, ''), direccion),
                movil = COALESCE(NULLIF(%s, ''), movil),
                otro_telefono = COALESCE(NULLIF(%s, ''), otro_telefono),
                codigo_postal = COALESCE(NULLIF(%s, ''), codigo_postal),
                poblacion = COALESCE(NULLIF(%s, ''), poblacion),
                provincia = COALESCE(NULLIF(%s, ''), provincia),
                localidad = COALESCE(NULLIF(%s, ''), localidad),
                direccion_numero = COALESCE(NULLIF(%s, ''), direccion_numero),
                updated_at = %s
            WHERE id = %s
            """,
            (
                nombre,
                nif,
                email,
                telefono,
                direccion,
                movil,
                otro_telefono,
                codigo_postal,
                poblacion,
                provincia,
                localidad,
                direccion_numero,
                now,
                cliente_id,
            ),
        )
        ensure_cliente_servicio_link(cur, cliente_id, empresa_id, "financiaciones", now, estado="Activo")
        return cliente_id

    cliente_id = cur.execute("SELECT gen_random_uuid()::text AS id").fetchone()["id"]
    cur.execute(
        """
        INSERT INTO clientes (
          id, empresa_id, nombre, nif, telefono, email, tipo, perfil, estado,
          direccion, movil, otro_telefono, codigo_postal, poblacion, provincia, localidad, direccion_numero,
          created_at, updated_at
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s, %s,
          %s, %s
        )
        """,
        (
            cliente_id,
            empresa_id,
            nombre,
            nif or None,
            telefono or None,
            email or None,
            _nonempty(cliente.get("tipo")) or "Física",
            _nonempty(cliente.get("perfil")) or "Autónomo",
            _nonempty(cliente.get("estado")) or "Activo",
            direccion or None,
            movil or None,
            otro_telefono or None,
            codigo_postal or None,
            poblacion or None,
            provincia or None,
            localidad or None,
            direccion_numero or None,
            now,
            now,
        ),
    )
    ensure_cliente_servicio_link(cur, cliente_id, empresa_id, "financiaciones", now, estado="Activo")
    return cliente_id


def upsert_hipoteca(cur, empresa_id, hipoteca, now):
    cliente_name = _nonempty(hipoteca.get("cliente")) or "Cliente"
    fecha_encargo = _nonempty(hipoteca.get("fecha_encargo"))
    importe = hipoteca.get("importe_hipoteca")

    existing = cur.execute(
        """
        SELECT id
        FROM hipotecas
        WHERE empresa_id = %s
          AND LOWER(TRIM(COALESCE(cliente,''))) = LOWER(TRIM(%s))
          AND COALESCE(fecha_encargo, '') = COALESCE(%s, '')
          AND COALESCE(importe_hipoteca, 0) = COALESCE(%s, 0)
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (empresa_id, cliente_name, fecha_encargo or None, importe),
    ).fetchone()

    # Asegura columnas nuevas (deploy-order safe).
    cur.execute("ALTER TABLE hipotecas ADD COLUMN IF NOT EXISTS cliente_id text")
    cur.execute("ALTER TABLE hipotecas ADD COLUMN IF NOT EXISTS cliente_inmueble_json text")
    cur.execute("ALTER TABLE hipotecas ADD COLUMN IF NOT EXISTS hipoteca_detalle_json text")
    cur.execute("ALTER TABLE hipotecas ADD COLUMN IF NOT EXISTS liquidacion_json text")

    allowed = {
        "cliente": cliente_name,
        "cliente_id": hipoteca.get("cliente_id") or None,
        "banco": _nonempty(hipoteca.get("banco")) or None,
        "precio": hipoteca.get("precio"),
        "importe_hipoteca": hipoteca.get("importe_hipoteca"),
        "porcentaje": hipoteca.get("porcentaje"),
        "entrada": hipoteca.get("entrada"),
        "comision": hipoteca.get("comision"),
        "oficina": _nonempty(hipoteca.get("oficina")) or None,
        "fecha_encargo": fecha_encargo or None,
        "encargo": _nonempty(hipoteca.get("encargo")) or None,
        "tipo_hipoteca": _nonempty(hipoteca.get("tipo_hipoteca")) or None,
        "fecha_firma": _nonempty(hipoteca.get("fecha_firma")) or None,
        "cesion": hipoteca.get("cesion"),
        "comision_juan": hipoteca.get("comision_juan"),
        "comision_modernia": hipoteca.get("comision_modernia"),
        "inmobiliaria_compra": _nonempty(hipoteca.get("inmobiliaria_compra")) or None,
        "asesor": _nonempty(hipoteca.get("asesor")) or None,
        "estado": _nonempty(hipoteca.get("estado")) or None,
        "anio": hipoteca.get("anio"),
        "cliente_inmueble_json": hipoteca.get("cliente_inmueble_json") or None,
        "hipoteca_detalle_json": hipoteca.get("hipoteca_detalle_json") or None,
        "liquidacion_json": hipoteca.get("liquidacion_json") or None,
    }

    if existing:
        hipoteca_id = existing["id"]
        cur.execute(
            """
            UPDATE hipotecas SET
              cliente = COALESCE(NULLIF(%s,''), cliente),
              cliente_id = COALESCE(%s, cliente_id),
              banco = COALESCE(%s, banco),
              precio = COALESCE(%s, precio),
              importe_hipoteca = COALESCE(%s, importe_hipoteca),
              porcentaje = COALESCE(%s, porcentaje),
              entrada = COALESCE(%s, entrada),
              comision = COALESCE(%s, comision),
              oficina = COALESCE(%s, oficina),
              fecha_encargo = COALESCE(%s, fecha_encargo),
              encargo = COALESCE(%s, encargo),
              tipo_hipoteca = COALESCE(%s, tipo_hipoteca),
              fecha_firma = COALESCE(%s, fecha_firma),
              cesion = COALESCE(%s, cesion),
              comision_juan = COALESCE(%s, comision_juan),
              comision_modernia = COALESCE(%s, comision_modernia),
              inmobiliaria_compra = COALESCE(%s, inmobiliaria_compra),
              asesor = COALESCE(%s, asesor),
              estado = COALESCE(%s, estado),
              anio = COALESCE(%s, anio),
              cliente_inmueble_json = COALESCE(%s, cliente_inmueble_json),
              hipoteca_detalle_json = COALESCE(%s, hipoteca_detalle_json),
              liquidacion_json = COALESCE(%s, liquidacion_json),
              updated_at = %s
            WHERE id = %s
            """,
            (
                allowed["cliente"],
                allowed["cliente_id"],
                allowed["banco"],
                allowed["precio"],
                allowed["importe_hipoteca"],
                allowed["porcentaje"],
                allowed["entrada"],
                allowed["comision"],
                allowed["oficina"],
                allowed["fecha_encargo"],
                allowed["encargo"],
                allowed["tipo_hipoteca"],
                allowed["fecha_firma"],
                allowed["cesion"],
                allowed["comision_juan"],
                allowed["comision_modernia"],
                allowed["inmobiliaria_compra"],
                allowed["asesor"],
                allowed["estado"],
                allowed["anio"],
                allowed["cliente_inmueble_json"],
                allowed["hipoteca_detalle_json"],
                allowed["liquidacion_json"],
                now,
                hipoteca_id,
            ),
        )
        return hipoteca_id, False

    hipoteca_id = cur.execute("SELECT gen_random_uuid()::text AS id").fetchone()["id"]
    cur.execute(
        """
        INSERT INTO hipotecas (
          id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca,
          porcentaje, entrada, comision, oficina, fecha_encargo, encargo, tipo_hipoteca,
          fecha_firma, cesion, comision_juan, comision_modernia, inmobiliaria_compra, asesor,
          estado, anio, created_at, updated_at, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json
        ) VALUES (
          %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s,
          %s, %s, %s, %s, %s, %s, %s
        )
        """,
        (
            hipoteca_id,
            empresa_id,
            allowed["cliente"],
            allowed["cliente_id"],
            allowed["banco"],
            allowed["precio"],
            allowed["importe_hipoteca"],
            allowed["porcentaje"],
            allowed["entrada"],
            allowed["comision"],
            allowed["oficina"],
            allowed["fecha_encargo"],
            allowed["encargo"],
            allowed["tipo_hipoteca"],
            allowed["fecha_firma"],
            allowed["cesion"],
            allowed["comision_juan"],
            allowed["comision_modernia"],
            allowed["inmobiliaria_compra"],
            allowed["asesor"],
            allowed["estado"],
            allowed["anio"],
            now,
            now,
            allowed["cliente_inmueble_json"],
            allowed["hipoteca_detalle_json"],
            allowed["liquidacion_json"],
        ),
    )
    return hipoteca_id, True


def main() -> None:
    payload_path = sys.argv[1]
    now = datetime.now(timezone.utc).isoformat()
    dsn = (os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or "").strip()
    if not dsn.lower().startswith("postgres"):
        raise SystemExit("DATABASE_URL/POSTGRES_URL no apunta a Postgres.")

    with open(payload_path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    conn = psycopg.connect(dsn, row_factory=dict_row)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            empresa = cur.execute("SELECT id FROM empresas WHERE nombre = %s LIMIT 1", (FIN_EMPRESA_NOMBRE,)).fetchone()
            if not empresa:
                raise SystemExit(f"Empresa no encontrada en Render: {FIN_EMPRESA_NOMBRE}")
            empresa_id = empresa["id"]

            processed = 0
            created = 0
            updated = 0
            for item in payload.get("items") or []:
                cliente = item.get("cliente") or {}
                hipoteca = item.get("hipoteca") or {}
                # upsert cliente en empresa financiaciones
                cliente_id = upsert_cliente(cur, empresa_id, cliente, now)
                hipoteca["cliente_id"] = cliente_id
                hipoteca_id, was_created = upsert_hipoteca(cur, empresa_id, hipoteca, now)
                processed += 1
                if was_created:
                    created += 1
                else:
                    updated += 1
            conn.commit()
            print(json.dumps({"ok": True, "processed": processed, "created": created, "updated": updated}, ensure_ascii=False))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()

