import json
import os
import sys
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row


def _nonempty(value):
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
    return str(value).strip()


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
            empresa_nombre = payload["empresa_nombre"]
            empresa = cur.execute("SELECT id FROM empresas WHERE nombre = %s LIMIT 1", (empresa_nombre,)).fetchone()
            if not empresa:
                raise SystemExit(f"Empresa no encontrada en Render: {empresa_nombre}")
            empresa_id = empresa["id"]

            # Migración ligera: evitar depender del orden de despliegue.
            cur.execute("ALTER TABLE clientes ADD COLUMN IF NOT EXISTS hijos_count integer")

            processed = 0
            for item in payload.get("items") or []:
                client = item.get("client") or {}
                gestoria = item.get("gestoria") or {}
                trabajo = item.get("trabajo") or None
                docs = item.get("docs") or []

                nif = _nonempty(client.get("nif")).upper().replace(" ", "")
                if not nif:
                    continue

                existing = cur.execute(
                    "SELECT id, hijos_count FROM clientes WHERE UPPER(COALESCE(nif,'')) = %s ORDER BY updated_at DESC LIMIT 1",
                    (nif,),
                ).fetchone()

                if existing:
                    cliente_id = existing["id"]
                    updates = {"empresa_id": empresa_id, "updated_at": now}
                    for key in (
                        "nombre",
                        "telefono",
                        "email",
                        "tipo",
                        "perfil",
                        "estado",
                        "fecha_nacimiento",
                        "direccion",
                        "tipo_persona",
                        "codigo_postal",
                        "poblacion",
                        "provincia",
                    ):
                        value = client.get(key)
                        if value is None:
                            continue
                        if isinstance(value, str):
                            value = value.strip()
                        if value == "":
                            continue
                        updates[key] = value
                    hijos_count = client.get("hijos_count")
                    if hijos_count is not None and existing.get("hijos_count") is None:
                        try:
                            updates["hijos_count"] = int(hijos_count)
                        except Exception:
                            pass
                    set_clause = ", ".join([f"{k} = %s" for k in updates.keys()])
                    cur.execute(
                        f"UPDATE clientes SET {set_clause} WHERE id = %s",
                        (*updates.values(), cliente_id),
                    )
                else:
                    cliente_id = uuid.uuid4().hex
                    cur.execute(
                        """
                        INSERT INTO clientes (
                          id, empresa_id, nombre, nif, telefono, email, tipo, perfil, estado,
                          created_at, updated_at, fecha_nacimiento, hijos_count, direccion, tipo_persona, codigo_postal, poblacion, provincia
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            cliente_id,
                            empresa_id,
                            client.get("nombre"),
                            nif,
                            client.get("telefono"),
                            client.get("email"),
                            client.get("tipo"),
                            client.get("perfil"),
                            client.get("estado"),
                            now,
                            now,
                            client.get("fecha_nacimiento"),
                            client.get("hijos_count"),
                            client.get("direccion"),
                            client.get("tipo_persona"),
                            client.get("codigo_postal"),
                            client.get("poblacion"),
                            client.get("provincia"),
                        ),
                    )

                # Vincular con la empresa en clientes_empresas (Gestoría).
                link = cur.execute(
                    """
                    SELECT id
                    FROM clientes_empresas
                    WHERE cliente_id = %s AND empresa_id = %s AND LOWER(COALESCE(servicio,'')) = 'gestoria'
                    LIMIT 1
                    """,
                    (cliente_id, empresa_id),
                ).fetchone()
                if link:
                    cur.execute(
                        "UPDATE clientes_empresas SET estado='Activo', fecha_fin=NULL, updated_at=%s WHERE id=%s",
                        (now, link["id"]),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO clientes_empresas (
                          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
                        ) VALUES (
                          %s, %s, %s, 'gestoria', 'Activo', %s, NULL, %s, %s
                        )
                        """,
                        (uuid.uuid4().hex, cliente_id, empresa_id, now, now, now),
                    )

                # IBAN (best effort, no bloquear el sync).
                iban = _nonempty(client.get("iban"))
                if iban:
                    try:
                        prof = cur.execute(
                            "SELECT id FROM cliente_profesional WHERE cliente_id=%s ORDER BY COALESCE(principal,0) DESC, created_at ASC LIMIT 1",
                            (cliente_id,),
                        ).fetchone()
                        if prof:
                            cur.execute(
                                "UPDATE cliente_profesional SET iban=%s, principal=COALESCE(principal,1), updated_at=%s WHERE id=%s",
                                (iban, now, prof["id"]),
                            )
                        else:
                            cur.execute(
                                """
                                INSERT INTO cliente_profesional (
                                  id, cliente_id, cnae, iae, actividad, iban, principal, created_at, updated_at
                                ) VALUES (
                                  %s, %s, '', '', '', %s, 1, %s, %s
                                )
                                """,
                                (uuid.uuid4().hex, cliente_id, iban, now, now),
                            )
                    except Exception:
                        conn.rollback()

                # cliente_gestoria
                cg = cur.execute("SELECT id FROM cliente_gestoria WHERE cliente_id = %s LIMIT 1", (cliente_id,)).fetchone()
                if cg:
                    cur.execute(
                        """
                        UPDATE cliente_gestoria
                        SET tipo_cliente=%s, mod_fiscal=%s, mod_laboral=%s, mod_contable=%s, mod_registro=%s,
                            mod_trafico=%s, mod_puntuales=%s, mod_renta=%s, renta_detalles=%s, updated_at=%s
                        WHERE cliente_id=%s
                        """,
                        (
                            gestoria.get("tipo_cliente"),
                            gestoria.get("mod_fiscal"),
                            gestoria.get("mod_laboral"),
                            gestoria.get("mod_contable"),
                            gestoria.get("mod_registro"),
                            gestoria.get("mod_trafico"),
                            gestoria.get("mod_puntuales"),
                            gestoria.get("mod_renta"),
                            gestoria.get("renta_detalles"),
                            now,
                            cliente_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO cliente_gestoria (
                          id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable, mod_registro, mod_trafico,
                          mod_puntuales, created_at, updated_at, mod_renta, renta_detalles
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            uuid.uuid4().hex,
                            cliente_id,
                            gestoria.get("tipo_cliente"),
                            gestoria.get("mod_fiscal"),
                            gestoria.get("mod_laboral"),
                            gestoria.get("mod_contable"),
                            gestoria.get("mod_registro"),
                            gestoria.get("mod_trafico"),
                            gestoria.get("mod_puntuales"),
                            now,
                            now,
                            gestoria.get("mod_renta"),
                            gestoria.get("renta_detalles"),
                        ),
                    )

                # gestoria_trabajos (Declaración en periodo)
                if trabajo:
                    row = cur.execute(
                        """
                        SELECT id FROM gestoria_trabajos
                        WHERE cliente_id=%s
                          AND (UPPER(COALESCE(tipo_trabajo,''))='DECLARACIÓN EN PERIODO' OR UPPER(COALESCE(tipo_trabajo,''))='DECLARACION EN PERIODO')
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (cliente_id,),
                    ).fetchone()
                    if row:
                        cur.execute(
                            """
                            UPDATE gestoria_trabajos SET
                              empresa_id=%s, estado=%s, fecha_inicio=%s, fecha_fin=%s, responsable=%s, importe=%s, notas=%s, updated_at=%s
                            WHERE id=%s
                            """,
                            (
                                empresa_id,
                                trabajo.get("estado"),
                                trabajo.get("fecha_inicio"),
                                trabajo.get("fecha_fin"),
                                trabajo.get("responsable"),
                                trabajo.get("importe"),
                                trabajo.get("notas"),
                                now,
                                row["id"],
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO gestoria_trabajos (
                              id, empresa_id, cliente_id, tipo_trabajo, estado, fecha_inicio, fecha_fin, responsable, importe, notas, created_at, updated_at
                            ) VALUES (
                              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            """,
                            (
                                uuid.uuid4().hex,
                                empresa_id,
                                cliente_id,
                                trabajo.get("tipo_trabajo") or "Declaración en periodo",
                                trabajo.get("estado"),
                                trabajo.get("fecha_inicio"),
                                trabajo.get("fecha_fin"),
                                trabajo.get("responsable"),
                                trabajo.get("importe"),
                                trabajo.get("notas"),
                                now,
                                now,
                            ),
                        )

                # Docs: solo si hay doc_url o doc_key real.
                for doc in docs:
                    doc_url = _nonempty(doc.get("doc_url"))
                    doc_key = _nonempty(doc.get("doc_key"))
                    if not doc_url and not doc_key:
                        continue

                    if doc_url:
                        existing_doc = cur.execute(
                            "SELECT id FROM gestoria_docs WHERE cliente_id=%s AND COALESCE(doc_url,'')=%s LIMIT 1",
                            (cliente_id, doc_url),
                        ).fetchone()
                    elif doc_key:
                        existing_doc = cur.execute(
                            "SELECT id FROM gestoria_docs WHERE cliente_id=%s AND COALESCE(doc_key,'')=%s LIMIT 1",
                            (cliente_id, doc_key),
                        ).fetchone()
                    else:
                        existing_doc = None

                    if existing_doc:
                        cur.execute(
                            """
                            UPDATE gestoria_docs SET
                              empresa_id=%s, referencia_tipo=%s, referencia_id=%s, nombre=%s, tipo=%s, fecha=%s, estado=%s,
                              notas=%s, doc_key=%s, doc_url=%s, updated_at=%s
                            WHERE id=%s
                            """,
                            (
                                empresa_id,
                                doc.get("referencia_tipo"),
                                doc.get("referencia_id"),
                                doc.get("nombre"),
                                doc.get("tipo"),
                                doc.get("fecha"),
                                doc.get("estado"),
                                doc.get("notas"),
                                doc_key or uuid.uuid4().hex,
                                doc_url,
                                now,
                                existing_doc["id"],
                            ),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO gestoria_docs (
                              id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                              nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at
                            ) VALUES (
                              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            )
                            """,
                            (
                                uuid.uuid4().hex,
                                empresa_id,
                                cliente_id,
                                doc.get("referencia_tipo"),
                                doc.get("referencia_id"),
                                doc.get("nombre"),
                                doc.get("tipo"),
                                doc.get("fecha"),
                                doc.get("estado"),
                                doc.get("notas"),
                                doc_key or uuid.uuid4().hex,
                                doc_url,
                                now,
                                now,
                            ),
                        )

                processed += 1

        conn.commit()
        print(json.dumps({"ok": True, "items": processed}, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
