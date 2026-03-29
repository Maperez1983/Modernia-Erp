#!/usr/bin/env python3
"""
Reconstruye documentos de renta visibles en CRM Gestoría a partir de source_files.

Uso:
  python3 scripts/rebuild_renta_docs.py --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "erp_import2.sqlite"
DEFAULT_ICLOUD_ROOT = Path("/Volumes/Mac Satecchi/Mac/Library/Mobile Documents/com~apple~CloudDocs")
DEFAULT_UPLOADS_ROOT = Path(
    os.environ.get("UPLOADS_DIR")
    or ("/var/data/uploads" if Path("/var/data").exists() else str(ROOT / "web" / "uploads"))
)
UPLOADS_RENTAS_DIR = DEFAULT_UPLOADS_ROOT / "rentas"
ICLOUD_MARKER = "/Library/Mobile Documents/com~apple~CloudDocs/"


def normalize_text(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_renta_payload(raw: object) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {"notes": "", "entries": []}
    try:
        payload = json.loads(text)
    except Exception:
        return {"notes": text, "entries": []}
    if isinstance(payload, list):
        return {"notes": "", "entries": payload}
    if not isinstance(payload, dict):
        return {"notes": "", "entries": []}
    entries = payload.get("entries")
    return {
        "notes": str(payload.get("notes") or "").strip(),
        "entries": entries if isinstance(entries, list) else [],
    }


def resolve_source_file(raw_path: object, icloud_root: Path, cache: dict[str, str | None]) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    direct = Path(text).expanduser()
    if direct.exists():
        return direct
    if ICLOUD_MARKER in text:
        suffix = text.split(ICLOUD_MARKER, 1)[1]
        candidate = icloud_root / suffix
        if candidate.exists():
            return candidate
    basename = Path(text).name
    if basename in cache:
        cached = cache[basename]
        return Path(cached) if cached else None
    matches = list(icloud_root.rglob(basename))
    cache[basename] = str(matches[0]) if matches else None
    return Path(cache[basename]) if cache[basename] else None


def build_target_filename(cliente_nombre: str, cliente_nif: str, ejercicio: str, source_path: Path) -> str:
    stem = normalize_text(cliente_nif) or normalize_text(cliente_nombre) or "renta"
    digest = hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:10]
    ext = source_path.suffix.lower() or ".pdf"
    return f"{stem}-{ejercicio or '2024'}-{digest}{ext}"


def upsert_renta_doc(
    conn: sqlite3.Connection,
    empresa_id: str,
    cliente_id: str,
    entry: dict,
    source_path: Path,
    target_path: Path,
    now: str,
) -> tuple[str, bool]:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not target_path.exists() or target_path.stat().st_size != source_path.stat().st_size:
        shutil.copy2(source_path, target_path)
    relative = target_path.relative_to(DEFAULT_UPLOADS_ROOT).as_posix()
    doc_url = f"/uploads/{relative}"
    doc_name = f"Renta {entry.get('ejercicio') or '2024'} · {entry.get('cliente_nombre') or source_path.stem}.pdf"
    fecha = str(entry.get("presentacion_fecha") or "").strip()
    notas = f"Importado desde renta · origen: {source_path}"
    existing = conn.execute(
        """
        SELECT id
        FROM gestoria_docs
        WHERE cliente_id = ? AND COALESCE(doc_url, '') = ?
        LIMIT 1
        """,
        (cliente_id, doc_url),
    ).fetchone()
    payload = (
        empresa_id,
        cliente_id,
        "renta",
        str(entry.get("id") or ""),
        doc_name,
        "Renta",
        fecha,
        "Recibido",
        notas,
        doc_url,
        now,
    )
    if existing:
        conn.execute(
            """
            UPDATE gestoria_docs
            SET empresa_id = ?, cliente_id = ?, referencia_tipo = ?, referencia_id = ?,
                nombre = ?, tipo = ?, fecha = ?, estado = ?, notas = ?, doc_url = ?,
                updated_at = datetime(?)
            WHERE id = ?
            """,
            (*payload, existing["id"]),
        )
        return existing["id"], False
    doc_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO gestoria_docs (
          id, empresa_id, cliente_id, referencia_tipo, referencia_id,
          nombre, tipo, fecha, estado, notas, doc_url, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            doc_id,
            empresa_id,
            cliente_id,
            "renta",
            str(entry.get("id") or ""),
            doc_name,
            "Renta",
            fecha,
            "Recibido",
            notas,
            doc_url,
            now,
            now,
        ),
    )
    return doc_id, True


def rebuild_docs(db_path: Path, icloud_root: Path, apply_changes: bool) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    path_cache: dict[str, str | None] = {}
    summary = {
        "clientes": 0,
        "entries": 0,
        "docs_created": 0,
        "docs_updated": 0,
        "missing_files": 0,
        "copied_files": 0,
    }
    now = datetime.now(timezone.utc).isoformat()
    try:
        rows = conn.execute(
            """
            SELECT cg.cliente_id, cg.renta_detalles, c.nombre, c.nif, c.empresa_id
            FROM cliente_gestoria cg
            JOIN clientes c ON c.id = cg.cliente_id
            WHERE COALESCE(cg.mod_renta, 0) = 1
            ORDER BY c.updated_at DESC
            """
        ).fetchall()
        for row in rows:
            payload = parse_renta_payload(row["renta_detalles"])
            entries = payload.get("entries") or []
            if not entries:
                continue
            summary["clientes"] += 1
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                summary["entries"] += 1
                source_files = entry.get("source_files") or []
                if not isinstance(source_files, list):
                    continue
                ejercicio = str(entry.get("ejercicio") or "2024").strip() or "2024"
                for raw_source in source_files:
                    source_path = resolve_source_file(raw_source, icloud_root, path_cache)
                    if not source_path:
                        summary["missing_files"] += 1
                        continue
                    filename = build_target_filename(
                        str(entry.get("cliente_nombre") or row["nombre"] or ""),
                        str(entry.get("cliente_nif") or row["nif"] or ""),
                        ejercicio,
                        source_path,
                    )
                    target_path = UPLOADS_RENTAS_DIR / ejercicio / filename
                    file_was_missing = not target_path.exists()
                    if apply_changes:
                        _, created = upsert_renta_doc(
                            conn,
                            row["empresa_id"],
                            row["cliente_id"],
                            entry,
                            source_path,
                            target_path,
                            now,
                        )
                        if created:
                            summary["docs_created"] += 1
                        else:
                            summary["docs_updated"] += 1
                        if file_was_missing:
                            summary["copied_files"] += 1
                    else:
                        if file_was_missing:
                            summary["copied_files"] += 1
                        exists = conn.execute(
                            """
                            SELECT 1
                            FROM gestoria_docs
                            WHERE cliente_id = ? AND COALESCE(doc_url, '') = ?
                            LIMIT 1
                            """,
                            (
                                row["cliente_id"],
                                f"/uploads/rentas/{ejercicio}/{filename}",
                            ),
                        ).fetchone()
                        if exists:
                            summary["docs_updated"] += 1
                        else:
                            summary["docs_created"] += 1
        if apply_changes:
            conn.commit()
    finally:
        conn.close()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconstruye documentos de renta visibles en CRM.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ruta a la base SQLite del CRM.")
    parser.add_argument(
        "--icloud-root",
        default=str(DEFAULT_ICLOUD_ROOT),
        help="Raíz local equivalente a iCloud Drive para resolver source_files.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica cambios: copia PDFs y crea/actualiza gestoria_docs.",
    )
    args = parser.parse_args()

    db_path = Path(args.db).expanduser().resolve()
    icloud_root = Path(args.icloud_root).expanduser().resolve()
    if not db_path.exists():
        raise SystemExit(f"No existe la base: {db_path}")
    if not icloud_root.exists():
        raise SystemExit(f"No existe la raíz de iCloud: {icloud_root}")

    summary = rebuild_docs(db_path, icloud_root, apply_changes=args.apply)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
