#!/usr/bin/env python3
"""
Re-asigna documentos de Renta (gestoria_docs) desde el cliente "SIN ASIGNAR" al cliente real,
extrayendo el NIF/NIE desde:
  1) nombre del PDF
  2) texto embebido del PDF (pypdf)
  3) (opcional) OCR ligero (no implementado por defecto)

Esto permite “cuadrar” la importación masiva: todos los PDFs están en el sistema, y ahora intentamos
asignarlos automáticamente al cliente correcto usando su DNI/NIF.

Uso:
  set -a; source .env; set +a
  python3 scripts/assign_rentas_docs_by_nif.py --empresa-id <empresa_id> --apply

Primero probar:
  python3 scripts/assign_rentas_docs_by_nif.py --empresa-id <empresa_id> --dry-run --limit 50
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


def env_first(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or ""
        if value.strip():
            return value.strip()
    return ""


def pg_connect(dsn: str):
    try:
        import psycopg
        from psycopg.rows import dict_row
    except Exception as exc:
        raise SystemExit(f"Postgres no disponible: falta psycopg. ({type(exc).__name__})")
    return psycopg.connect(dsn, row_factory=dict_row)


NIF_RE = re.compile(r"\b(\d{8}[A-Z])\b")
NIE_RE = re.compile(r"\b([XYZ]\d{7}[A-Z])\b")


def normalize_nif(value: object) -> str:
    text = str(value or "").strip().upper()
    text = re.sub(r"[^0-9A-Z]", "", text)
    return text


def extract_nif_from_text(text: str) -> str:
    raw = normalize_nif(text)
    if not raw:
        return ""
    m = NIF_RE.search(raw)
    if m:
        return m.group(1)
    m = NIE_RE.search(raw)
    if m:
        return m.group(1)
    return ""


def extract_nif_from_filename(name: str) -> str:
    return extract_nif_from_text(name or "")


def extract_text_from_pdf(pdf_path: Path, *, max_pages: int = 2) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return ""
    out = []
    pages = reader.pages[: max(0, int(max_pages or 0))] if max_pages else reader.pages
    for page in pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(out)

def ocr_first_page(pdf_path: Path, *, dpi: int = 250, timeout_s: int = 60) -> str:
    """
    OCR rápido de la primera página: pdftoppm -> tesseract.
    Devuelve texto (puede estar vacío).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        prefix = tmp / "page"
        img = tmp / "page-1.png"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-r",
                    str(int(dpi)),
                    "-png",
                    str(pdf_path),
                    str(prefix),
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
            )
        except Exception:
            return ""
        if not img.exists():
            # En algunos builds el sufijo puede ser -01
            alt = tmp / "page-01.png"
            if alt.exists():
                img = alt
        if not img.exists():
            return ""
        try:
            proc = subprocess.run(
                ["tesseract", str(img), "stdout", "-l", "spa"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                text=True,
            )
            return str(proc.stdout or "")
        except Exception:
            return ""


@dataclass(frozen=True)
class DocRow:
    id: str
    nombre: str
    notas: str
    doc_key: str


def main() -> None:
    parser = argparse.ArgumentParser(description="Asigna docs de renta a clientes por NIF (Postgres).")
    parser.add_argument("--empresa-id", required=True)
    parser.add_argument("--unassigned-client-name", default="RENTAS 2024 · SIN ASIGNAR")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--pdf-pages", type=int, default=2, help="Páginas a extraer con pypdf (rápido).")
    parser.add_argument("--ocr", action="store_true", help="Si no hay texto, intenta OCR de la primera página.")
    parser.add_argument("--ocr-dpi", type=int, default=250)
    args = parser.parse_args()

    do_apply = bool(args.apply) and (not args.dry_run)
    if not do_apply:
        args.dry_run = True

    dsn = env_first("POSTGRES_URL", "DATABASE_URL")
    if not dsn.lower().startswith("postgres"):
        raise SystemExit("Falta POSTGRES_URL/DATABASE_URL (postgres...).")

    conn = pg_connect(dsn)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            unassigned = cur.execute(
                """
                SELECT id
                FROM clientes
                WHERE empresa_id = %s AND LOWER(COALESCE(nombre,'')) = LOWER(%s)
                LIMIT 1
                """,
                (args.empresa_id, args.unassigned_client_name),
            ).fetchone()
        if not unassigned:
            raise SystemExit("No existe el cliente SIN ASIGNAR para esa empresa.")
        unassigned_id = str(unassigned["id"])

        with conn.cursor() as cur:
            rows = cur.execute(
                """
                SELECT id, nombre, notas, doc_key
                FROM gestoria_docs
                WHERE empresa_id = %s
                  AND cliente_id = %s
                  AND LOWER(COALESCE(referencia_tipo,'')) = 'renta'
                ORDER BY updated_at DESC
                """,
                (args.empresa_id, unassigned_id),
            ).fetchall()

        docs = [DocRow(id=str(r["id"]), nombre=str(r["nombre"] or ""), notas=str(r["notas"] or ""), doc_key=str(r["doc_key"] or "")) for r in rows]
        if args.limit and int(args.limit) > 0:
            docs = docs[: int(args.limit)]

        processed = 0
        assigned = 0
        skipped = 0
        missing_file = 0
        no_nif = 0
        no_client = 0

        for doc in docs:
            processed += 1
            pdf_path = Path(doc.notas).expanduser() if doc.notas else None
            nif = extract_nif_from_filename(Path(doc.nombre).name) or extract_nif_from_filename(doc.notas)
            text = ""
            if not nif and pdf_path and pdf_path.exists():
                text = extract_text_from_pdf(pdf_path, max_pages=int(args.pdf_pages or 0))
                nif = extract_nif_from_text(text)
            if not nif and args.ocr and pdf_path and pdf_path.exists():
                ocr_text = ocr_first_page(pdf_path, dpi=int(args.ocr_dpi or 250))
                nif = extract_nif_from_text(ocr_text)
            if not nif:
                no_nif += 1
                continue

            # Busca cliente por NIF en esta empresa (preferimos clientes.empresa_id por seguridad).
            with conn.cursor() as cur:
                target = cur.execute(
                    """
                    SELECT id, nombre, nif
                    FROM clientes
                    WHERE empresa_id = %s
                      AND REPLACE(REPLACE(UPPER(COALESCE(nif,'')), ' ', ''), '-', '') = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (args.empresa_id, nif),
                ).fetchone()
            if not target:
                no_client += 1
                continue
            target_id = str(target["id"])

            if args.dry_run:
                print(f"[dry-run] {doc.id}: {doc.nombre} -> {target_id} ({target.get('nombre')}) [{nif}]")
                assigned += 1
                continue

            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE gestoria_docs
                    SET cliente_id = %s, updated_at = NOW()
                    WHERE id = %s AND empresa_id = %s
                    """,
                    (target_id, doc.id, args.empresa_id),
                )
                # Asegura vínculo en clientes_empresas para que sea visible en módulos de gestoría.
                cur.execute(
                    """
                    INSERT INTO clientes_empresas (id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at)
                    SELECT %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                    WHERE NOT EXISTS (
                      SELECT 1 FROM clientes_empresas WHERE cliente_id=%s AND empresa_id=%s AND LOWER(COALESCE(servicio,'')) IN ('gestoria','gestoría')
                    )
                    """,
                    (
                        uuid.uuid4().hex,
                        target_id,
                        args.empresa_id,
                        "gestoria",
                        "Activo",
                        "",
                        "",
                        target_id,
                        args.empresa_id,
                    ),
                )
            assigned += 1

        if do_apply:
            conn.commit()

        print(
            {
                "processed": processed,
                "assigned": assigned,
                "skipped": skipped,
                "missing_file": missing_file,
                "no_nif": no_nif,
                "no_client": no_client,
                "dry_run": bool(args.dry_run),
                "unassigned_client_id": unassigned_id,
            }
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
