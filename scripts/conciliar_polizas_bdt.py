#!/usr/bin/env python3
import argparse
import base64
import csv
import json
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
HINT_STOPWORDS = {
    "POLIZA",
    "POLIZA",
    "SEGURO",
    "SEGUROS",
    "HOGAR",
    "AUTO",
    "COCHE",
    "MOTO",
    "RC",
    "RECIBO",
    "DNI",
    "NIF",
    "CIF",
    "IMG",
    "PDF",
    "JPG",
    "JPEG",
    "PNG",
    "MANDATO",
    "BANCO",
    "IMPAGO",
    "ANEXO",
}


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


def path_company_tokens(path):
    text = norm_text(str(path))
    words = [w for w in text.split() if len(w) >= 3 and not w.isdigit()]
    words = [w for w in words if w not in HINT_STOPWORDS]
    tokens = set()
    for i in range(len(words)):
        tokens.add(words[i])
        if i + 1 < len(words):
            tokens.add(f"{words[i]} {words[i + 1]}")
        if i + 2 < len(words):
            tokens.add(f"{words[i]} {words[i + 1]} {words[i + 2]}")
    return tokens


def safe_value(value):
    return "" if value is None else str(value)


def write_report_json(path, payload):
    if not path:
        return
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report_csv(path, rows):
    if not path:
        return
    out = Path(path).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "file",
        "status",
        "match_reason",
        "seguro_id",
        "seguro_company",
        "ocr_company",
        "seguro_policy",
        "ocr_policy",
        "seguro_tomador",
        "ocr_tomador",
        "missing_required",
        "ocr_error",
        "ai_used",
        "ai_error",
    ]
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: safe_value(row.get(col, "")) for col in columns})


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
    parser.add_argument("--report-out", default="", help="JSON report output path.")
    parser.add_argument("--report-csv", default="", help="CSV report output path.")
    parser.add_argument("--learn-hints-out", default="", help="Guardar hints aprendidos de compania en JSON.")
    parser.add_argument("--learn-min-count", type=int, default=2, help="Min apariciones token->compania para hint.")
    parser.add_argument("--learn-min-ratio", type=float, default=0.85, help="Min ratio dominio token->compania.")
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
    detailed_rows = []
    required_keys = ("tomador", "poliza_numero", "compania", "fecha_efecto")
    hint_votes = defaultdict(lambda: defaultdict(int))
    now = datetime.now(timezone.utc).isoformat()

    for path in files:
        if not is_policy_candidate(path):
            stats["skipped_non_policy"] += 1
            continue
        stats["files_total"] += 1
        try:
            result = parse_policy_file(path, conn)
        except Exception as exc:
            stats["ocr_error"] += 1
            unresolved.append((str(path), "ocr_error"))
            detailed_rows.append(
                {
                    "file": str(path),
                    "status": "ocr_error",
                    "ocr_error": str(exc),
                    "missing_required": ",".join(required_keys),
                    "ai_used": "",
                    "ai_error": "",
                }
            )
            continue
        fields = (result or {}).get("fields") or {}
        ai_used = bool((result or {}).get("ai_used"))
        ai_error = (result or {}).get("ai_error") or ""
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
            detailed_rows.append(
                {
                    "file": str(path),
                    "status": "empty_fields",
                    "match_reason": "",
                    "missing_required": ",".join(required_keys),
                    "ocr_error": "",
                    "ai_used": "1" if ai_used else "0",
                    "ai_error": ai_error,
                }
            )
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
            detailed_rows.append(
                {
                    "file": str(path),
                    "status": "created",
                    "match_reason": "create_missing",
                    "seguro_id": seguro_id if args.apply else "",
                    "seguro_company": fields.get("compania") or "",
                    "ocr_company": fields.get("compania") or "",
                    "seguro_policy": fields.get("poliza_numero") or "",
                    "ocr_policy": fields.get("poliza_numero") or "",
                    "seguro_tomador": fields.get("tomador") or "",
                    "ocr_tomador": fields.get("tomador") or "",
                    "missing_required": ",".join([k for k in required_keys if not str(fields.get(k) or "").strip()]),
                    "ocr_error": "",
                    "ai_used": "1" if ai_used else "0",
                    "ai_error": ai_error,
                }
            )
            stats["created_seguros"] += 1
            continue
        if not row:
            stats["unmatched"] += 1
            unresolved.append((str(path), "unmatched"))
            detailed_rows.append(
                {
                    "file": str(path),
                    "status": "unmatched",
                    "match_reason": "",
                    "seguro_id": "",
                    "seguro_company": "",
                    "ocr_company": fields.get("compania") or "",
                    "seguro_policy": "",
                    "ocr_policy": fields.get("poliza_numero") or "",
                    "seguro_tomador": "",
                    "ocr_tomador": fields.get("tomador") or "",
                    "missing_required": ",".join([k for k in required_keys if not str(fields.get(k) or "").strip()]),
                    "ocr_error": "",
                    "ai_used": "1" if ai_used else "0",
                    "ai_error": ai_error,
                }
            )
            continue

        stats[f"matched_{reason}"] += 1
        row_company = row["compania"] or ""
        for token in path_company_tokens(path):
            if token and row_company:
                hint_votes[token][row_company] += 1
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
        detailed_rows.append(
            {
                "file": str(path),
                "status": "updated" if updates else "matched_unchanged",
                "match_reason": reason,
                "seguro_id": row["id"],
                "seguro_company": row["compania"] or "",
                "ocr_company": fields.get("compania") or "",
                "seguro_policy": row["poliza_numero"] or "",
                "ocr_policy": fields.get("poliza_numero") or "",
                "seguro_tomador": row["tomador"] or "",
                "ocr_tomador": fields.get("tomador") or "",
                "missing_required": ",".join([k for k in required_keys if not str(fields.get(k) or "").strip()]),
                "ocr_error": "",
                "ai_used": "1" if ai_used else "0",
                "ai_error": ai_error,
            }
        )

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

    company_summary = defaultdict(lambda: defaultdict(int))
    for row in detailed_rows:
        company = row.get("seguro_company") or row.get("ocr_company") or "(sin_compania)"
        company_summary[company]["total"] += 1
        company_summary[company][row.get("status") or "unknown"] += 1

    learned_hints = {}
    for token, votes in hint_votes.items():
        total = sum(votes.values())
        if total < max(1, args.learn_min_count):
            continue
        best_company, best_count = max(votes.items(), key=lambda it: it[1])
        ratio = best_count / total
        if ratio < args.learn_min_ratio:
            continue
        learned_hints[token] = {"company": best_company, "count": best_count, "total": total, "ratio": round(ratio, 3)}

    report_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "empresa_id": empresa_id,
        "stats": dict(stats),
        "by_company": {k: dict(v) for k, v in sorted(company_summary.items(), key=lambda it: it[0])},
        "learned_hints": learned_hints,
        "rows": detailed_rows,
    }
    write_report_json(args.report_out, report_payload)
    write_report_csv(args.report_csv, detailed_rows)
    if args.learn_hints_out:
        hints_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "conciliar_polizas_bdt.py",
            "total_hints": len(learned_hints),
            "hints": {token: data["company"] for token, data in sorted(learned_hints.items())},
            "meta": learned_hints,
        }
        write_report_json(args.learn_hints_out, hints_payload)


if __name__ == "__main__":
    main()
