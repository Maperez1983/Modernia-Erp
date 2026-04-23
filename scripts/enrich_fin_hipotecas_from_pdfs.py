#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import server  # noqa: E402

from scripts.import_fin_hipotecas_from_folders import extract_from_pdf  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _is_valid_nif(value: str) -> bool:
    raw = _compact(value).upper()
    return bool(
        re.fullmatch(r"[0-9]{8}[A-Z]", raw)
        or re.fullmatch(r"[XYZ][0-9]{7}[A-Z]", raw)
        or re.fullmatch(r"[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-Z]", raw)
    )


def _filename_to_name(pdf_path: Path) -> str:
    stem = str(pdf_path.stem or "").strip()
    if not stem:
        return ""
    stem = re.sub(r"[_-]?[0-9]{8,}$", "", stem)
    stem = stem.replace("_", " ")
    return _compact(stem)


def find_cliente_candidates(conn, empresa_id: str, *, nombre: str, nif: str) -> list[dict]:
    empresa_id = str(empresa_id or "").strip()
    nombre_norm = server.normalize_person_name(nombre or "")
    nif_norm = server.normalize_nif(nif or "")
    rows: list[dict] = []

    if nif_norm:
        rows = conn.execute(
            """
            SELECT
              c.id,
              COALESCE(NULLIF(TRIM(COALESCE(c.nombre,'')), ''), '') AS nombre,
              COALESCE(NULLIF(TRIM(COALESCE(c.nif,'')), ''), '') AS nif,
              COALESCE(NULLIF(TRIM(COALESCE(c.empresa_id,'')), ''), '') AS empresa_id,
              COALESCE(c.created_at, '') AS created_at,
              COALESCE(c.updated_at, '') AS updated_at
            FROM clientes c
            LEFT JOIN clientes_empresas ce
              ON ce.cliente_id = c.id
             AND ce.empresa_id = ?
             AND LOWER(TRIM(COALESCE(ce.servicio, ''))) = 'financiaciones'
            WHERE c.nif = ?
              AND (c.empresa_id = ? OR ce.id IS NOT NULL OR COALESCE(TRIM(c.empresa_id), '') = '')
            ORDER BY COALESCE(NULLIF(TRIM(COALESCE(c.nif,'')), ''), '') DESC,
                     COALESCE(c.updated_at, c.created_at) DESC
            """,
            (empresa_id, nif_norm, empresa_id),
        ).fetchall()
        rows = [dict(r) for r in (rows or [])]

    if not rows and nombre_norm:
        rows = conn.execute(
            """
            SELECT
              c.id,
              COALESCE(NULLIF(TRIM(COALESCE(c.nombre,'')), ''), '') AS nombre,
              COALESCE(NULLIF(TRIM(COALESCE(c.nif,'')), ''), '') AS nif,
              COALESCE(NULLIF(TRIM(COALESCE(c.empresa_id,'')), ''), '') AS empresa_id,
              COALESCE(c.created_at, '') AS created_at,
              COALESCE(c.updated_at, '') AS updated_at
            FROM clientes c
            LEFT JOIN clientes_empresas ce
              ON ce.cliente_id = c.id
             AND ce.empresa_id = ?
             AND LOWER(TRIM(COALESCE(ce.servicio, ''))) = 'financiaciones'
            WHERE LOWER(TRIM(COALESCE(c.nombre, ''))) = LOWER(TRIM(?))
              AND (c.empresa_id = ? OR ce.id IS NOT NULL OR COALESCE(TRIM(c.empresa_id), '') = '')
            ORDER BY COALESCE(NULLIF(TRIM(COALESCE(c.nif,'')), ''), '') DESC,
                     COALESCE(c.updated_at, c.created_at) DESC
            """,
            (empresa_id, nombre_norm, empresa_id),
        ).fetchall()
        rows = [dict(r) for r in (rows or [])]

    return rows


def pick_best_cliente(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None

    def score(row: dict) -> tuple[int, str]:
        has_nif = 1 if (row.get("nif") or "").strip() else 0
        created = str(row.get("created_at") or "")
        return (has_nif, created)

    return sorted(candidates, key=score, reverse=True)[0]


def compute_hipoteca_updates(conn, hipoteca_id: str, extracted, *, overwrite: bool) -> dict:
    row = conn.execute(
        """
        SELECT
          id,
          COALESCE(precio, NULL) AS precio,
          COALESCE(importe_hipoteca, NULL) AS importe_hipoteca,
          COALESCE(NULLIF(TRIM(COALESCE(tipo_hipoteca,'')), ''), '') AS tipo_hipoteca,
          COALESCE(NULLIF(TRIM(COALESCE(fecha_firma,'')), ''), '') AS fecha_firma,
          COALESCE(NULLIF(TRIM(COALESCE(estado,'')), ''), '') AS estado,
          COALESCE(anio, NULL) AS anio
        FROM hipotecas
        WHERE id = ?
        LIMIT 1
        """,
        (hipoteca_id,),
    ).fetchone()
    if not row:
        raise RuntimeError("Hipoteca no encontrada")

    updates: dict[str, object] = {}
    if extracted.precio_compra is not None and (overwrite or row["precio"] is None):
        updates["precio"] = extracted.precio_compra
    if extracted.importe_prestamo is not None and (overwrite or row["importe_hipoteca"] is None):
        updates["importe_hipoteca"] = extracted.importe_prestamo
    if extracted.tipo_interes and (overwrite or not row["tipo_hipoteca"]):
        updates["tipo_hipoteca"] = extracted.tipo_interes
    if extracted.fecha_firma and (overwrite or not row["fecha_firma"]):
        updates["fecha_firma"] = extracted.fecha_firma
    if extracted.fecha_firma:
        try:
            anio = int(str(extracted.fecha_firma)[:4])
        except Exception:
            anio = None
        if anio and (overwrite or not row["anio"]):
            updates["anio"] = anio
        if (row["estado"] or "").lower() in ("pendiente", ""):
            updates["estado"] = "FIRMADA"
    return updates


def apply_hipoteca_updates(conn, hipoteca_id: str, updates: dict, *, now: str) -> None:
    if not updates:
        return
    set_clause = ", ".join([f"{k} = ?" for k in updates.keys()])
    values = list(updates.values()) + [now, hipoteca_id]
    conn.execute(f"UPDATE hipotecas SET {set_clause}, updated_at = datetime(?) WHERE id = ?", values)


def relink_cliente(conn, *, empresa_id: str, hipoteca_id: str, doc_id: str, cliente_id: str, now: str) -> None:
    conn.execute("UPDATE hipotecas SET cliente_id = ?, updated_at = datetime(?) WHERE id = ?", (cliente_id, now, hipoteca_id))
    conn.execute("UPDATE gestoria_docs SET cliente_id = ?, updated_at = datetime(?) WHERE id = ?", (cliente_id, now, doc_id))
    link = conn.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(servicio) = 'financiaciones'
        LIMIT 1
        """,
        (cliente_id, empresa_id),
    ).fetchone()
    if not link:
        conn.execute(
            """
            INSERT INTO clientes_empresas (
              id, cliente_id, empresa_id, servicio, estado,
              fecha_inicio, fecha_fin, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                os.urandom(16).hex(),
                cliente_id,
                empresa_id,
                "financiaciones",
                "Activo",
                None,
                None,
                now,
                now,
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Rellena/actualiza hipotecas desde PDFs ya existentes (sin importar).")
    parser.add_argument("--empresa-id", required=True, help="empresa_id de Financiaciones/Hipotecas")
    parser.add_argument("--source-dir", action="append", required=True, help="Carpeta con PDFs (repetible)")
    parser.add_argument("--limit", type=int, default=0, help="Procesa solo N PDFs (0=todos)")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribe campos existentes (por defecto solo rellena vacíos)")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios en BD (por defecto dry-run)")
    parser.add_argument("--relink", action="store_true", help="Reenlaza hipoteca/doc a un cliente mejor (por defecto NO)")
    parser.add_argument("--out", default="/tmp/hipotecas_enrich_report.json", help="Salida JSON")
    args = parser.parse_args()

    empresa_id = str(args.empresa_id or "").strip()
    if not empresa_id:
        raise SystemExit("--empresa-id requerido")

    pdfs: list[Path] = []
    for d in [Path(x).expanduser() for x in (args.source_dir or [])]:
        if not d.exists():
            raise SystemExit(f"No existe: {d}")
        pdfs.extend([p for p in d.rglob("*.pdf") if p.is_file() and not p.name.startswith("._")])
    pdfs = sorted(pdfs)
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]

    now = _now_iso()
    report: dict = {
        "now": now,
        "total": len(pdfs),
        "apply": bool(args.apply),
        "items": [],
        "summary": {
            "updated_hipotecas": 0,
            "relinked": 0,
            "missing_doc": 0,
            "missing_hipoteca": 0,
            "errors": 0,
            "fields": {"precio": 0, "importe_hipoteca": 0, "tipo_hipoteca": 0, "fecha_firma": 0, "estado": 0, "anio": 0},
            "extractable": {"precio_compra": 0, "importe_prestamo": 0, "tipo_interes": 0, "fecha_firma": 0, "cliente1_nif": 0},
        },
    }

    conn = server.get_db(str(server.DB_CONFIGURED))

    for idx, pdf in enumerate(pdfs, start=1):
        item: dict = {"pdf": str(pdf)}
        try:
            extracted = extract_from_pdf(pdf)
            item["extracted"] = {
                "cliente1_nombre": extracted.cliente1_nombre,
                "cliente1_nif": extracted.cliente1_nif,
                "cliente2_nombre": extracted.cliente2_nombre,
                "cliente2_nif": extracted.cliente2_nif,
                "precio_compra": extracted.precio_compra,
                "importe_prestamo": extracted.importe_prestamo,
                "tipo_interes": extracted.tipo_interes,
                "fecha_firma": extracted.fecha_firma,
                "ocr_error": extracted.ocr_error,
            }
            if extracted.precio_compra is not None:
                report["summary"]["extractable"]["precio_compra"] += 1
            if extracted.importe_prestamo is not None:
                report["summary"]["extractable"]["importe_prestamo"] += 1
            if (extracted.tipo_interes or "").strip():
                report["summary"]["extractable"]["tipo_interes"] += 1
            if (extracted.fecha_firma or "").strip():
                report["summary"]["extractable"]["fecha_firma"] += 1
            if (extracted.cliente1_nif or "").strip():
                report["summary"]["extractable"]["cliente1_nif"] += 1

            doc = conn.execute(
                """
                SELECT id, cliente_id, referencia_id
                FROM gestoria_docs
                WHERE empresa_id = ?
                  AND referencia_tipo = 'hipoteca'
                  AND notas = ?
                LIMIT 1
                """,
                (empresa_id, str(pdf)),
            ).fetchone()
            if not doc:
                report["summary"]["missing_doc"] += 1
                item["error"] = "No existe gestoria_docs para este PDF (notas no coincide)"
                report["items"].append(item)
                continue

            doc_id = doc["id"]
            hipoteca_id = str(doc["referencia_id"] or "").strip()
            item["doc_id"] = doc_id
            item["hipoteca_id"] = hipoteca_id
            if not hipoteca_id:
                report["summary"]["missing_hipoteca"] += 1
                item["error"] = "gestoria_docs sin referencia_id (hipoteca_id)"
                report["items"].append(item)
                continue

            updates = compute_hipoteca_updates(conn, hipoteca_id, extracted, overwrite=bool(args.overwrite))
            if updates:
                item["hipoteca_updates"] = updates
                if args.apply:
                    apply_hipoteca_updates(conn, hipoteca_id, updates, now=now)
                    report["summary"]["updated_hipotecas"] += 1
                    for k in updates.keys():
                        if k in report["summary"]["fields"]:
                            report["summary"]["fields"][k] += 1

            if args.relink:
                nombre = extracted.cliente1_nombre or _filename_to_name(pdf)
                nif = extracted.cliente1_nif if _is_valid_nif(extracted.cliente1_nif or "") else ""
                current_cliente_id = str(doc["cliente_id"] or "").strip()
                candidates = find_cliente_candidates(conn, empresa_id, nombre=nombre, nif=nif)
                best = pick_best_cliente(candidates)
                if best and best["id"] and (not current_cliente_id or best["id"] != current_cliente_id):
                    item["cliente_candidate"] = {"id": best["id"], "nombre": best.get("nombre"), "nif": best.get("nif")}
                    if args.apply:
                        relink_cliente(conn, empresa_id=empresa_id, hipoteca_id=hipoteca_id, doc_id=doc_id, cliente_id=best["id"], now=now)
                        report["summary"]["relinked"] += 1

            if args.apply:
                conn.commit()
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            item["error"] = f"{type(exc).__name__}: {exc}"
            report["summary"]["errors"] += 1

        if idx == 1 or idx % 10 == 0 or idx == len(pdfs):
            print(f"[hipotecas-enrich] {idx}/{len(pdfs)} {pdf.name}")
        report["items"].append(item)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[hipotecas-enrich] reporte: {out}")


if __name__ == "__main__":
    main()
