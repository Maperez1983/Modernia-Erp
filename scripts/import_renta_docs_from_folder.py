#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
import uuid
from dataclasses import dataclass
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
    s = re.sub(r"\b[A-Z0-9]{5,}\b", " ", s)  # codes like M91XHX
    s = re.sub(r"\b(APORTACION|APORTACI[ÓO]N|RECTIFICATIVA|FIRMA|PAGO|PLAZO|SOLICITUD|FRACCIONAMIENTO|BORRADOR)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


@dataclass(frozen=True)
class Match:
    cliente_id: str
    score: float
    cliente_nombre: str
    cliente_nif: str


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter <= 0:
        return 0.0
    union = len(a | b)
    return inter / union if union else 0.0


def best_client_match(name_tokens: set[str], clients: list[dict]) -> Match | None:
    best: Match | None = None
    for c in clients:
        score = jaccard(name_tokens, c["tokens"])
        if best is None or score > best.score:
            best = Match(
                cliente_id=c["id"],
                score=score,
                cliente_nombre=c["full_name"],
                cliente_nif=c["nif"],
            )
    return best


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa TODOS los PDFs de una carpeta como gestoria_docs (renta), enlazando por similitud de nombre."
    )
    parser.add_argument("--source-dir", required=True, help="Carpeta con PDFs")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite del CRM")
    parser.add_argument("--empresa-id", default="", help="empresa_id a usar en gestoria_docs (si vacío intenta resolver por nombre)")
    parser.add_argument("--empresa-nombre", default="Fincas Velazquez", help="Nombre de empresa para resolver empresa_id si no se pasa --empresa-id")
    parser.add_argument("--ejercicio", default="2024", help="Ejercicio fiscal a escribir en el nombre del doc")
    parser.add_argument("--estado", default="Presentada", choices=("Borrador", "Presentada"), help="Estado del doc")
    parser.add_argument("--min-score", type=float, default=0.72, help="Umbral mínimo de match por nombre (Jaccard)")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en BD, solo reporta")
    parser.add_argument("--out-review", default="reports/renta_docs_name_match_review.json", help="Salida JSON con casos dudosos")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser()
    if not source_dir.exists():
        raise SystemExit(f"No existe: {source_dir}")
    db_path = Path(args.db).expanduser()
    ejercicio = compact_spaces(args.ejercicio) or "2024"
    estado = compact_spaces(args.estado) or "Presentada"
    min_score = float(args.min_score or 0.0)
    review_out = Path(args.out_review).expanduser()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        empresa_id = compact_spaces(args.empresa_id)
        if not empresa_id:
            row = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (args.empresa_nombre,)).fetchone()
            if not row:
                raise SystemExit(f"No encuentro empresa '{args.empresa_nombre}' en empresas")
            empresa_id = row["id"]

        columns = {r[1] for r in conn.execute("PRAGMA table_info(clientes)").fetchall()}
        has_apellidos = "apellidos" in columns
        if has_apellidos:
            query = "SELECT id, nombre, apellidos, nif FROM clientes"
        else:
            query = "SELECT id, nombre, nif FROM clientes"
        clients = []
        for row in conn.execute(query):
            if has_apellidos:
                full = f"{compact_spaces(row['nombre'])} {compact_spaces(row['apellidos'])}".strip()
            else:
                full = compact_spaces(row["nombre"])
            tokens = tokenize_name(full)
            nif = norm(row["nif"])
            if not tokens:
                continue
            clients.append({"id": row["id"], "full_name": full, "tokens": tokens, "nif": nif})

        pdfs = sorted([p for p in source_dir.rglob("*.pdf") if not p.name.startswith("._")])
        total = len(pdfs)
        inserted = 0
        skipped_existing = 0
        review = []
        for idx, pdf in enumerate(pdfs, start=1):
            if idx == 1 or idx % 200 == 0 or idx == total:
                print(f"[renta_docs] {idx}/{total}: {pdf.name}")
            stem = simplify_filename(pdf.stem)
            tokens = tokenize_name(stem)
            if not tokens:
                review.append({"pdf": str(pdf), "reason": "no_tokens", "stem": pdf.stem})
                continue
            match = best_client_match(tokens, clients)
            if not match or match.score < min_score:
                review.append(
                    {
                        "pdf": str(pdf),
                        "reason": "low_score",
                        "stem": pdf.stem,
                        "tokens": sorted(tokens),
                        "best": match.__dict__ if match else None,
                    }
                )
                continue

            doc_name = f"Renta {ejercicio} · {estado} · {pdf.name}"
            existing = conn.execute(
                """
                SELECT id FROM gestoria_docs
                WHERE cliente_id = ? AND LOWER(COALESCE(referencia_tipo,''))='renta' AND LOWER(COALESCE(nombre,''))=LOWER(?)
                LIMIT 1
                """,
                (match.cliente_id, doc_name),
            ).fetchone()
            if existing:
                skipped_existing += 1
                continue

            if args.dry_run:
                inserted += 1
                continue

            now = "datetime('now')"
            conn.execute(
                """
                INSERT INTO gestoria_docs (
                  id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                  nombre, tipo, fecha, estado, notas, doc_key, doc_url,
                  calidad_ocr, campos_ocr, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, 'renta', ?, ?, ?, '', ?, ?, ?, '',
                  0, ?, datetime('now'), datetime('now')
                )
                """,
                (
                    uuid.uuid4().hex,
                    empresa_id,
                    match.cliente_id,
                    f"renta-{ejercicio}-{match.cliente_nif or match.cliente_id}",
                    doc_name,
                    f"Renta {estado}",
                    estado,
                    str(pdf),
                    uuid.uuid4().hex,
                    json.dumps(
                        {
                            "match_score": match.score,
                            "match_cliente_nombre": match.cliente_nombre,
                            "match_cliente_nif": match.cliente_nif,
                            "source_dir": str(source_dir),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            inserted += 1

        if not args.dry_run:
            conn.commit()
    finally:
        conn.close()

    review_out.parent.mkdir(parents=True, exist_ok=True)
    review_out.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "pdf_total": total,
                "inserted": inserted,
                "skipped_existing": skipped_existing,
                "review_count": len(review),
                "review_out": str(review_out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
