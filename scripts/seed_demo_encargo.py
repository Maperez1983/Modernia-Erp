#!/usr/bin/env python3
import argparse
import os
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.db_backend import open_db_conn  # noqa: E402
from web.server import ensure_tables  # noqa: E402
from web.server import ensure_cliente_for_inmobiliaria  # noqa: E402
from web.server import ensure_inmueble_propietario_link  # noqa: E402
from web.server import ensure_captacion_for_inmueble  # noqa: E402


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_default_db_path() -> Path:
    configured = (os.environ.get("DB_PATH") or os.environ.get("DATABASE_PATH") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT / "data" / "erp_import2.sqlite"


def ensure_empresa(conn, nombre: str, now: str) -> str:
    nombre = str(nombre or "").strip()
    row = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (nombre,)).fetchone()
    if row:
        return str(row["id"])
    empresa_id = os.urandom(16).hex()
    conn.execute(
        """
        INSERT INTO empresas (id, nombre, activo, created_at, updated_at)
        VALUES (?, ?, 1, datetime(?), datetime(?))
        """,
        (empresa_id, nombre, now, now),
    )
    return empresa_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Genera un encargo DEMO para revisar el flujo.")
    parser.add_argument("--empresa", default="Estudio Velazquez 2012 SL", help="Nombre de la empresa inmobiliaria.")
    parser.add_argument(
        "--db-in",
        default=str(resolve_default_db_path()),
        help="Ruta de la base de datos origen (se copia si usas --db-out).",
    )
    parser.add_argument(
        "--db-out",
        default=str(ROOT / "data" / "erp_import2.demo.sqlite"),
        help="Ruta de la base de datos destino (copia).",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Escribe en la base de datos de --db-in sin copiar (no recomendado).",
    )
    args = parser.parse_args()

    db_in = Path(args.db_in).expanduser()
    db_out = Path(args.db_out).expanduser()
    if not db_in.exists():
        raise SystemExit(f"DB no encontrada: {db_in}")

    if args.in_place:
        db_path = db_in
    else:
        db_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(db_in, db_out)
        db_path = db_out

    ensure_tables(str(db_path))
    conn = open_db_conn(str(db_path), with_row_factory=True)
    try:
        now = utc_now_iso()
        empresa_id = ensure_empresa(conn, args.empresa, now)

        seed = os.urandom(4).hex().upper()
        direccion = f"DEMO Encargo {seed} · Calle Falsa {random.randint(1, 199)}"
        codigo_postal = str(random.choice(["28001", "28002", "28006", "28010", "28012"]))
        poblacion = "Madrid"
        provincia = "Madrid"
        zona = random.choice(["Salamanca", "Chamberí", "Retiro", "Centro"])
        tipo_inmueble = random.choice(["Piso", "Casa", "Local"])
        precio_objetivo = float(random.choice([285000, 320000, 450000, 575000, 690000]))
        precio_encargo = float(round(precio_objetivo * random.uniform(0.95, 1.08), 2))
        honorarios = float(round(precio_encargo * random.uniform(0.02, 0.05), 2))
        fecha_encargo = datetime.now().date().isoformat()

        propietario_telefono = f"6{random.randint(10000000, 99999999)}"
        propietario_email = f"demo_{seed.lower()}@example.com"
        propietario_nombre = random.choice(
            ["María García", "Juan Pérez", "Laura Martín", "Carlos Sánchez", "Ana López"]
        )
        propietario_nif = f"X{random.randint(1000000, 9999999)}A"
        propietario_id = ensure_cliente_for_inmobiliaria(
            conn,
            empresa_id,
            propietario_nombre,
            propietario_nif,
            now,
            {"telefono": propietario_telefono, "email": propietario_email},
        )

        inmueble_id = os.urandom(16).hex()
        conn.execute(
            """
            INSERT INTO inmuebles (
              id, empresa_id, titulo, direccion, codigo_postal, poblacion, provincia, zona,
              tipo_inmueble, precio_objetivo, precio_encargo, honorarios, estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                inmueble_id,
                empresa_id,
                direccion,
                direccion,
                codigo_postal,
                poblacion,
                provincia,
                zona,
                tipo_inmueble,
                precio_objetivo,
                precio_encargo,
                honorarios,
                "Noticia",
                now,
                now,
            ),
        )
        ensure_inmueble_propietario_link(conn, inmueble_id, propietario_id, now)

        captacion = ensure_captacion_for_inmueble(conn, empresa_id, inmueble_id, now)
        captacion_id = str(captacion["id"] if captacion else "").strip()

        operacion_id = os.urandom(16).hex()
        payload_json = (
            '{"origen":"seed_demo_encargo","nota":"Registro generado automáticamente para validar el flujo."}'
        )
        conn.execute(
            """
            INSERT INTO operaciones_inmobiliarias (
              id, empresa_id, tipo_operacion, estado, origen, origen_inmueble, anio, mes, inmueble_id,
              direccion, propietario1_id, propietario1_nombre, propietario1_nif, propietario1_telefono, propietario1_email,
              fecha_encargo, fecha_operacion, precio_encargo, num_visitas, honorarios, agente, responsable_gestion, oficina,
              estado_documental, calidad_ocr, notas, datos_extraidos_json,
              created_at, updated_at
            ) VALUES (
              ?, ?, 'venta', 'Manual', 'captacion_convertida', 'captacion',
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?,
              'Pendiente', 'manual', ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                operacion_id,
                empresa_id,
                int(fecha_encargo[:4]),
                fecha_encargo[:7],
                inmueble_id,
                direccion,
                propietario_id,
                propietario_nombre,
                propietario_nif,
                propietario_telefono,
                propietario_email,
                fecha_encargo,
                fecha_encargo,
                float(precio_encargo),
                float(honorarios),
                None,
                None,
                "Estudio Velazquez",
                "DEMO generado por scripts/seed_demo_encargo.py",
                payload_json,
                now,
                now,
            ),
        )

        # Alinea captación con estado "Encargo" para que el pipeline lo refleje igual que una conversión.
        if captacion_id:
            conn.execute(
                """
                UPDATE captaciones
                SET situacion_comercial = 'Encargo', etapa = 'Encargo', fecha_conversion = ?, updated_at = datetime(?)
                WHERE id = ?
                """,
                (now, now, captacion_id),
            )
        conn.execute(
            "UPDATE inmuebles SET estado = 'Encargo', updated_at = datetime(?) WHERE id = ?",
            (now, inmueble_id),
        )
        conn.commit()

        print("")
        print("✅ Encargo DEMO creado")
        print(f"- DB: {db_path}")
        print(f"- Inmueble: {inmueble_id}")
        print(f"- Captación: {captacion_id or '(sin captación)'}")
        print(f"- Operación: {operacion_id}")
        print(f"- Dirección: {direccion}")
        print("")
        print("Cómo verlo:")
        print("1) Arranca el servidor apuntando a esta DB:")
        print(f"   DB_PATH='{db_path}' python3 web/server.py")
        print("2) Entra en CRM Inmo → Compraventas y busca por 'DEMO Encargo'.")
        print(f"3) Si quieres abrir el inmueble directo: /?crm=inmo&inmueble={inmueble_id}")
        print("")
        return 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
