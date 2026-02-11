#!/usr/bin/env python3
import argparse
import base64
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import server as srv  # noqa: E402


VALID_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}
SKIP_KEYWORDS = (
    "CARNET",
    "DNI",
    "PASAPORTE",
    "NIE",
    "RECIBO",
    "JUSTIFICANTE",
    "TRANSFERENCIA",
)


def norm_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def norm_name(value):
    return norm_text(value)


def norm_policy(value):
    return srv.normalize_poliza_key(value)


def norm_company(value):
    return srv.normalize_company_key(value)


def list_policy_files(roots):
    files = []
    for root in roots:
        base = Path(root).expanduser()
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in VALID_EXTS:
                continue
            files.append(path)
    return sorted(files)


def is_policy_candidate(path):
    normalized = norm_text(str(path))
    return not any(k in normalized for k in SKIP_KEYWORDS)


def path_hints(path):
    text = norm_text(str(path))
    stem = Path(path).stem
    stem_norm = norm_text(stem)
    company = srv.detect_company_from_metadata(str(path))
    policy = ""
    token_candidates = re.findall(r"[A-Z0-9]{6,}", re.sub(r"[^A-Za-z0-9]+", " ", str(path).upper()))
    for token in token_candidates:
        pol = norm_policy(token)
        if len(pol) >= 6 and re.search(r"\d", pol):
            policy = pol
            break
    name = ""
    parts = [p.strip() for p in re.split(r"[-_/]+", stem_norm) if p.strip()]
    stop = {
        "POLIZA",
        "POLIZA AUTO",
        "POLIZA HOGAR",
        "SEGURO",
        "SEGUROS",
        "HOGAR",
        "AUTO",
        "COCHE",
        "MOTO",
        "MAPFRE",
        "AXA",
        "ALLIANZ",
        "REALE",
        "OCASO",
        "PELAYO",
        "SANTA LUCIA",
        "OCCIDENT",
        "MUTUA PROPIETARIOS",
    }
    for part in reversed(parts):
        if part in stop:
            continue
        if len(part) < 5:
            continue
        if re.search(r"\d", part):
            continue
        name = part
        break
    return {"tomador": name, "compania": company, "poliza_numero": policy}


def choose_unique(rows):
    if len(rows) == 1:
        return rows[0]
    return None


def month_es():
    months = [
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    ]
    return months[datetime.now().month - 1]


def build_indexes(rows):
    by_policy_company = defaultdict(list)
    by_policy = defaultdict(list)
    by_tomador_company = defaultdict(list)
    by_tomador = defaultdict(list)
    for row in rows:
        pol = norm_policy(row["poliza_numero"])
        comp = norm_company(row["compania"])
        tom = norm_name(row["tomador"])
        if pol and comp:
            by_policy_company[(pol, comp)].append(row)
        if pol:
            by_policy[pol].append(row)
        if tom and comp:
            by_tomador_company[(tom, comp)].append(row)
        if tom:
            by_tomador[tom].append(row)
    return by_policy_company, by_policy, by_tomador_company, by_tomador


def match_seguro(fields, indexes):
    by_policy_company, by_policy, by_tomador_company, by_tomador = indexes
    pol = norm_policy(fields.get("poliza_numero"))
    comp = norm_company(fields.get("compania"))
    tom = norm_name(fields.get("tomador"))
    if pol and comp:
        row = choose_unique(by_policy_company.get((pol, comp), []))
        if row:
            return row, "policy+company"
    if pol:
        row = choose_unique(by_policy.get(pol, []))
        if row:
            return row, "policy"
    if tom and comp:
        row = choose_unique(by_tomador_company.get((tom, comp), []))
        if row:
            return row, "tomador+company"
    if tom:
        row = choose_unique(by_tomador.get(tom, []))
        if row:
            return row, "tomador"
    return None, ""


def parse_policy_file(path, conn):
    data = path.read_bytes()
    payload = {
        "file_base64": base64.b64encode(data).decode("utf-8"),
        "filename": path.name,
        "source_hint": str(path),
    }
    return srv.process_seguros_ocr(payload, conn)


def must_replace(col, current, incoming, overwrite):
    cur = str(current or "").strip()
    inc = str(incoming or "").strip()
    if not inc:
        return False
    if not cur:
        return True
    if not overwrite:
        return False
    if col == "poliza_numero":
        return norm_policy(cur) != norm_policy(inc)
    if col == "compania":
        return norm_company(cur) != norm_company(inc)
    if col == "tomador":
        return norm_name(cur) != norm_name(inc)
    return cur != inc


def ensure_link(conn, cliente_id, empresa_id):
    if not cliente_id or not empresa_id:
        return
    existing = conn.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(servicio) IN ('seguros')
        LIMIT 1
        """,
        (cliente_id, empresa_id),
    ).fetchone()
    if existing:
        return
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (?, ?, ?, 'seguros', 'Activo', NULL, NULL, datetime(?), datetime(?))
        """,
        (os.urandom(16).hex(), cliente_id, empresa_id, now, now),
    )


def main():
    parser = argparse.ArgumentParser(description="Conciliar pólizas contra BDT de seguros.")
    parser.add_argument("--db", required=True, help="SQLite DB path.")
    parser.add_argument("--empresa-id", default="", help="Empresa ID.")
    parser.add_argument("--empresa-nombre-like", default="FINCAS", help="Resolver empresa por nombre LIKE.")
    parser.add_argument("--polizas-root", action="append", default=[], help="Root folder. Repetir para varias rutas.")
    parser.add_argument("--max-files", type=int, default=0, help="Limita archivos a procesar.")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribe datos distintos si OCR aporta valor.")
    parser.add_argument("--create-missing-seguros", action="store_true", help="Crea registro nuevo si no hay match.")
    parser.add_argument("--apply", action="store_true", help="Aplicar cambios (default dry-run).")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    empresa_id = args.empresa_id
    if not empresa_id and args.empresa_nombre_like:
        row = conn.execute(
            "SELECT id FROM empresas WHERE UPPER(nombre) LIKE UPPER(?) ORDER BY nombre LIMIT 1",
            (f"%{args.empresa_nombre_like}%",),
        ).fetchone()
        if row:
            empresa_id = row["id"]
    if not empresa_id:
        raise SystemExit("No se pudo resolver empresa_id")

    files = list_policy_files(args.polizas_root)
    if args.max_files and args.max_files > 0:
        files = files[: args.max_files]
    if not files:
        raise SystemExit("No se encontraron archivos de póliza en las rutas dadas")

    seguros = conn.execute(
        """
        SELECT *
        FROM seguros
        WHERE empresa_id = ?
        """,
        (empresa_id,),
    ).fetchall()
    indexes = build_indexes(seguros)

    stats = defaultdict(int)
    unresolved = []
    now = datetime.now(timezone.utc).isoformat()

    for path in files:
        if not is_policy_candidate(path):
            stats["skipped_non_policy"] += 1
            continue
        stats["files_total"] += 1
        try:
            result = parse_policy_file(path, conn)
        except Exception:
            stats["ocr_error"] += 1
            unresolved.append((str(path), "ocr_error"))
            continue
        fields = (result or {}).get("fields") or {}
        hints = path_hints(path)
        if hints.get("compania") and not fields.get("compania"):
            fields["compania"] = hints["compania"]
        if hints.get("poliza_numero") and not fields.get("poliza_numero"):
            fields["poliza_numero"] = hints["poliza_numero"]
        if hints.get("tomador") and not fields.get("tomador"):
            fields["tomador"] = hints["tomador"]
        if not any(str(v or "").strip() for v in fields.values()):
            stats["empty_fields"] += 1
            unresolved.append((str(path), "empty_fields"))
            continue

        row, reason = match_seguro(fields, indexes)
        if not row and args.create_missing_seguros:
            cliente_id = None
            if args.apply and fields.get("tomador"):
                cliente_id = srv.ensure_cliente_for_seguro(
                    conn,
                    empresa_id,
                    fields.get("tomador"),
                    fields.get("nif") or fields.get("dni"),
                    now,
                    {
                        "telefono": fields.get("telefono"),
                        "email": fields.get("email"),
                        "fecha_nacimiento": fields.get("fecha_nacimiento"),
                        "direccion": fields.get("direccion"),
                    },
                )
            if args.apply and cliente_id:
                ensure_link(conn, cliente_id, empresa_id)
            if args.apply:
                seguro_id = os.urandom(16).hex()
                conn.execute(
                    """
                    INSERT INTO seguros (
                      id, empresa_id, cliente_id, mes_creacion, fecha_efecto, fecha_vencimiento,
                      tomador, compania, ramo, poliza_numero, prima_neta, prima_total,
                      estado, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        seguro_id,
                        empresa_id,
                        cliente_id,
                        month_es(),
                        fields.get("fecha_efecto"),
                        fields.get("fecha_vencimiento"),
                        fields.get("tomador"),
                        fields.get("compania"),
                        fields.get("ramo"),
                        fields.get("poliza_numero"),
                        fields.get("prima_neta"),
                        fields.get("prima_total"),
                        "En vigor",
                        now,
                        now,
                    ),
                )
            stats["created_seguros"] += 1
            continue
        if not row:
            stats["unmatched"] += 1
            unresolved.append((str(path), "unmatched"))
            continue

        stats[f"matched_{reason}"] += 1
        updates = {}
        map_fields = (
            "tomador",
            "compania",
            "ramo",
            "poliza_numero",
            "prima_neta",
            "prima_total",
            "fecha_efecto",
            "fecha_vencimiento",
        )
        for col in map_fields:
            if must_replace(col, row[col], fields.get(col), args.overwrite):
                updates[col] = fields.get(col)
        cliente_id = row["cliente_id"]
        if not cliente_id and fields.get("tomador"):
            stats["missing_cliente_before"] += 1
            if args.apply:
                cliente_id = srv.ensure_cliente_for_seguro(
                    conn,
                    empresa_id,
                    fields.get("tomador"),
                    fields.get("nif") or fields.get("dni"),
                    now,
                    {
                        "telefono": fields.get("telefono"),
                        "email": fields.get("email"),
                        "fecha_nacimiento": fields.get("fecha_nacimiento"),
                        "direccion": fields.get("direccion"),
                    },
                )
            if cliente_id:
                updates["cliente_id"] = cliente_id

        if updates:
            stats["rows_updated"] += 1
            stats["fields_updated"] += len(updates)
            if args.apply:
                set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values()) + [now, row["id"]]
                conn.execute(
                    f"UPDATE seguros SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                    values,
                )
                if updates.get("cliente_id"):
                    ensure_link(conn, updates["cliente_id"], empresa_id)
        else:
            stats["rows_unchanged"] += 1

    if args.apply:
        conn.commit()
    else:
        conn.rollback()
    conn.close()

    print(f"empresa_id={empresa_id}")
    print(f"files_total={stats['files_total']}")
    print(f"skipped_non_policy={stats['skipped_non_policy']}")
    print(f"rows_updated={stats['rows_updated']}")
    print(f"fields_updated={stats['fields_updated']}")
    print(f"rows_unchanged={stats['rows_unchanged']}")
    print(f"missing_cliente_before={stats['missing_cliente_before']}")
    print(f"created_seguros={stats['created_seguros']}")
    print(f"unmatched={stats['unmatched']}")
    print(f"ocr_error={stats['ocr_error']}")
    print(f"empty_fields={stats['empty_fields']}")
    for key in sorted(k for k in stats.keys() if k.startswith("matched_")):
        print(f"{key}={stats[key]}")
    if unresolved:
        print("\nUnresolved sample (up to 25):")
        for item in unresolved[:25]:
            print(f"- {item[1]} | {item[0]}")


if __name__ == "__main__":
    main()
