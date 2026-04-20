#!/usr/bin/env python3
"""
Importa PDFs desde una carpeta local (OneDrive/iCloud) como documentos de Renta en Postgres (Render),
subiéndolos a S3 y creando/actualizando `gestoria_docs` con `doc_key` real.

Objetivo: que TODOS los PDFs del folder aparezcan en el CRM (Docs del cliente) y el botón "Ver/PDF"
funcione en producción (solo puede abrir S3, no rutas locales /Users/...).

Uso típico:
  set -a; source .env; set +a
  python3 scripts/import_rentas_folder_to_postgres.py \\
    --empresa-id a261... \\
    --source-dir "/Users/.../0000 RENTAS 2024" \\
    --ejercicio 2024 \\
    --estado Presentada \\
    --s3-prefix gestoria/rentas \\
    --apply

Primero probar:
  python3 scripts/import_rentas_folder_to_postgres.py ... --dry-run --limit 200
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


STOP_TOKENS = {
    "DE",
    "DEL",
    "LA",
    "LAS",
    "LO",
    "LOS",
    "Y",
    "E",
    "DA",
    "DO",
    "DOS",
    "SAN",
    "SANTA",
}


PLACEHOLDER_HEX_RE = re.compile(r"^[0-9a-fA-F]{32}$")


def compact_spaces(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def norm(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.strip().upper()


def tokenize_name(raw: object) -> set[str]:
    text = norm(raw)
    text = re.sub(r"[^A-Z0-9 ]+", " ", text)
    tokens = {t for t in text.split() if t and t not in STOP_TOKENS and len(t) >= 2}
    return tokens


def simplify_filename(stem: str) -> str:
    s = norm(stem)
    s = re.sub(r"\b\d{8}\b", " ", s)  # 28102025
    s = re.sub(r"\b\d{2}[_/-]?\d{2}[_/-]?\d{4}\b", " ", s)
    # Quita códigos tipo M91XHX, N4AH3B, etc. (mezcla letras+NÚMEROS).
    s = re.sub(r"\b(?=[A-Z0-9]{5,}\b)(?=.*\d)[A-Z0-9]+\b", " ", s)
    s = re.sub(
        r"\b(APORTACION|APORTACI[ÓO]N|RECTIFICATIVA|FIRMA|PAGO|PLAZO|SOLICITUD|FRACCIONAMIENTO|BORRADOR)\b",
        " ",
        s,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return s


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def s3_client():
    try:
        import boto3
    except Exception:
        return None
    region = env_first("AWS_REGION", "AWS_DEFAULT_REGION")
    return boto3.client("s3", region_name=region) if region else boto3.client("s3")


def safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "archivo.pdf"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "archivo.pdf"


def build_s3_key(prefix: str, filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(4).hex()
    pref = (prefix or "gestoria/rentas").strip().strip("/")
    return f"{pref}/{stamp}_{rand}_{safe_filename(filename)}"


def pg_connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise SystemExit(f"Postgres no disponible: falta psycopg. ({type(exc).__name__})")
    return psycopg.connect(dsn, row_factory=dict_row)


@dataclass(frozen=True)
class Client:
    id: str
    nombre: str
    nif: str
    tokens: frozenset[str]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return inter / union if union else 0.0


def build_inverted_index(clients: list[Client]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for i, c in enumerate(clients):
        for token in c.tokens:
            index.setdefault(token, []).append(i)
    return index


def best_match(tokens: set[str], clients: list[Client], inv: dict[str, list[int]]) -> tuple[Client | None, float]:
    if not tokens:
        return None, 0.0
    candidates: set[int] = set()
    for t in tokens:
        for idx in inv.get(t, []):
            candidates.add(idx)
    if not candidates:
        return None, 0.0
    best_client: Client | None = None
    best_score = 0.0
    for idx in candidates:
        c = clients[idx]
        score = jaccard(tokens, set(c.tokens))
        if score > best_score:
            best_score = score
            best_client = c
    return best_client, best_score


def fetch_clients(conn, empresa_id: str) -> list[Client]:
    # Cargamos TODOS los clientes vinculados a la empresa en clientes_empresas (sin filtrar por servicio)
    # porque el objetivo es “meter todos los PDFs” y luego ya se ordena/filtra en UI.
    with conn.cursor() as cur:
        cols = cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name='clientes'
            """
        ).fetchall()
        has_apellidos = any(r["column_name"] == "apellidos" for r in cols)

        select_name = "COALESCE(c.nombre,'')"
        if has_apellidos:
            select_name = "TRIM(COALESCE(c.nombre,'') || ' ' || COALESCE(c.apellidos,''))"

        rows = cur.execute(
            f"""
            SELECT DISTINCT c.id, {select_name} AS full_name, c.nif
            FROM clientes c
            JOIN clientes_empresas ce ON ce.cliente_id = c.id
            WHERE ce.empresa_id = %s
            """,
            (empresa_id,),
        ).fetchall()

    out: list[Client] = []
    for r in rows:
        name = compact_spaces(r.get("full_name") or "")
        toks = tokenize_name(name)
        if not toks:
            continue
        out.append(
            Client(
                id=str(r["id"]),
                nombre=name,
                nif=norm(r.get("nif")),
                tokens=frozenset(toks),
            )
        )
    return out


def upsert_doc(
    conn,
    *,
    empresa_id: str,
    cliente_id: str,
    referencia_id: str,
    nombre: str,
    tipo: str,
    estado: str,
    notas: str,
    doc_key: str,
    campos_ocr: str,
) -> tuple[bool, bool]:
    """Returns (created, updated)."""
    with conn.cursor() as cur:
        existing = cur.execute(
            """
            SELECT id, doc_key
            FROM gestoria_docs
            WHERE empresa_id = %s
              AND cliente_id = %s
              AND LOWER(COALESCE(referencia_tipo,''))='renta'
              AND LOWER(COALESCE(nombre,'')) = LOWER(%s)
            LIMIT 1
            """,
            (empresa_id, cliente_id, nombre),
        ).fetchone()
        if existing:
            existing_key = str(existing.get("doc_key") or "").strip()
            needs_key = not existing_key or PLACEHOLDER_HEX_RE.fullmatch(existing_key or "") is not None
            if needs_key and doc_key:
                cur.execute(
                    """
                    UPDATE gestoria_docs
                    SET doc_key = %s,
                        tipo = %s,
                        estado = %s,
                        notas = COALESCE(NULLIF(%s,''), notas),
                        referencia_id = %s,
                        campos_ocr = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (doc_key, tipo, estado, notas, referencia_id, campos_ocr, existing["id"]),
                )
                return False, True
            return False, False

        cur.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id,
              nombre, tipo, fecha, estado, notas, doc_key, doc_url,
              calidad_ocr, campos_ocr, created_at, updated_at
            ) VALUES (
              %s, %s, %s, 'renta', %s,
              %s, %s, '', %s, %s, %s, '',
              0, %s, NOW(), NOW()
            )
            """,
            (
                uuid.uuid4().hex,
                empresa_id,
                cliente_id,
                referencia_id,
                nombre,
                tipo,
                estado,
                notas,
                doc_key,
                campos_ocr,
            ),
        )
        return True, False


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa PDFs de una carpeta como docs de Renta (Postgres+S3).")
    parser.add_argument("--source-dir", required=True, help="Carpeta con PDFs (se recorre recursivamente).")
    parser.add_argument("--empresa-id", required=True, help="empresa_id destino (Postgres).")
    parser.add_argument("--ejercicio", default="2024", help="Ejercicio fiscal para el nombre del doc.")
    parser.add_argument("--estado", default="Presentada", choices=("Borrador", "Presentada"), help="Estado del doc.")
    parser.add_argument("--min-score", type=float, default=0.72, help="Umbral mínimo del match por nombre.")
    parser.add_argument("--s3-prefix", default="gestoria/rentas", help="Prefijo S3 donde subir los PDFs.")
    parser.add_argument("--limit", type=int, default=0, help="Máximo de PDFs a procesar (0=sin límite).")
    parser.add_argument("--dry-run", action="store_true", help="No sube a S3 ni escribe en DB.")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios (si no, actúa como dry-run).")
    parser.add_argument("--out-review", default="reports/rentas_folder_import_review.json", help="JSON con casos no enlazados.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser()
    if not source_dir.exists():
        raise SystemExit(f"No existe: {source_dir}")

    do_apply = bool(args.apply) and (not args.dry_run)
    if not do_apply:
        args.dry_run = True

    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.lower().startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL (postgres...).")
    bucket = env_first("AWS_S3_BUCKET", "S3_BUCKET")
    if do_apply and not bucket:
        raise SystemExit("Falta AWS_S3_BUCKET/S3_BUCKET para subir a S3.")

    s3 = s3_client() if do_apply else None
    if do_apply and not s3:
        raise SystemExit("No se pudo inicializar S3 (falta boto3 o región).")

    conn = pg_connect(dsn)
    conn.autocommit = False
    try:
        clients = fetch_clients(conn, args.empresa_id)
        inv = build_inverted_index(clients)
        print(f"[rentas_folder] clientes_indexados={len(clients)}", file=sys.stderr)

        pdfs = sorted([p for p in source_dir.rglob("*.pdf") if not p.name.startswith("._")])
        if args.limit:
            pdfs = pdfs[: max(0, int(args.limit or 0))]
        total = len(pdfs)

        inserted = 0
        updated = 0
        skipped = 0
        review: list[dict] = []

        for idx, pdf in enumerate(pdfs, start=1):
            if idx == 1 or idx % 200 == 0 or idx == total:
                print(f"[rentas_folder] {idx}/{total}: {pdf.name}", file=sys.stderr)

            stem = simplify_filename(pdf.stem)
            tokens = tokenize_name(stem)
            client, score = best_match(tokens, clients, inv)
            if (not client) or score < float(args.min_score or 0.0):
                review.append(
                    {
                        "pdf": str(pdf),
                        "stem": pdf.stem,
                        "simplified": stem,
                        "tokens": sorted(tokens),
                        "best": {"id": client.id, "nombre": client.nombre, "nif": client.nif, "score": score} if client else None,
                    }
                )
                continue

            doc_name = f"Renta {compact_spaces(args.ejercicio)} · {compact_spaces(args.estado)} · {pdf.name}"
            referencia_id = f"renta-{compact_spaces(args.ejercicio)}-{client.nif or client.id}"
            tipo = f"Renta {compact_spaces(args.estado)}"
            campos_ocr = json.dumps(
                {"match_score": score, "match_nombre": client.nombre, "match_nif": client.nif},
                ensure_ascii=False,
            )

            if args.dry_run:
                inserted += 1
                continue

            key = build_s3_key(args.s3_prefix, doc_name)
            try:
                s3.upload_file(str(pdf), bucket, key, ExtraArgs={"ContentType": "application/pdf"})
            except Exception as exc:
                review.append(
                    {
                        "pdf": str(pdf),
                        "error": f"s3_upload_failed: {type(exc).__name__}: {exc}",
                        "client": {"id": client.id, "nombre": client.nombre, "nif": client.nif, "score": score},
                    }
                )
                continue

            created, did_update = upsert_doc(
                conn,
                empresa_id=args.empresa_id,
                cliente_id=client.id,
                referencia_id=referencia_id,
                nombre=doc_name,
                tipo=tipo,
                estado=compact_spaces(args.estado),
                notas=str(pdf),
                doc_key=key,
                campos_ocr=campos_ocr,
            )
            if created:
                inserted += 1
            elif did_update:
                updated += 1
            else:
                skipped += 1

        if do_apply:
            conn.commit()

        out_path = Path(args.out_review).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

        print(
            json.dumps(
                {
                    "pdf_total": total,
                    "created": inserted,
                    "updated": updated,
                    "skipped": skipped,
                    "review_count": len(review),
                    "review_out": str(out_path),
                    "dry_run": bool(args.dry_run),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)

