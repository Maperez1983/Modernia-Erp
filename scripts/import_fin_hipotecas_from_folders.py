#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import server  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compact(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "archivo.pdf"))
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return cleaned or "archivo.pdf"


def _env_first(*keys: str) -> str:
    for k in keys:
        v = os.environ.get(k) or ""
        if v.strip():
            return v.strip()
    return ""


def _parse_ddmmyy(value: str) -> str:
    raw = _compact(value)
    if not raw:
        return ""
    m = re.search(r"\b([0-3]?\d)[/.-]([01]?\d)[/.-]([0-9]{2,4})\b", raw)
    if not m:
        return ""
    d, mo, y = m.groups()
    y_int = int(y)
    if y_int < 100:
        y_int = 2000 + y_int
    try:
        return f"{y_int:04d}-{int(mo):02d}-{int(d):02d}"
    except Exception:
        return ""


def extract_fecha_firma(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\u00a0", " ").split())
    if not cleaned:
        return ""
    for pat in (
        r"FECHA\s+Y\s+HORA\s+DE\s+FIRMA\s*[:\-]?\s*([0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4})",
        r"\b(?:LUNES|MARTES|MI[EÉ]RCOLES|JUEVES|VIERNES|S[ÁA]BADO|DOMINGO)\s+([0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4})\b",
    ):
        m = re.search(pat, cleaned, re.IGNORECASE)
        if m:
            iso = _parse_ddmmyy(m.group(1))
            if iso:
                return iso
    return ""


@dataclass
class Extracted:
    cliente1_nombre: str = ""
    cliente1_nif: str = ""
    cliente2_nombre: str = ""
    cliente2_nif: str = ""
    precio_compra: float | None = None
    importe_prestamo: float | None = None
    tipo_interes: str = ""
    fecha_firma: str = ""
    ocr_text: str = ""
    ocr_error: str = ""


def _pick_float(text: str, patterns: tuple[str, ...]) -> float | None:
    cleaned = " ".join(str(text or "").replace("\u00a0", " ").split())
    if not cleaned:
        return None
    def _parse_amount(raw_value: str) -> float | None:
        raw_value = str(raw_value or "").strip()
        if not raw_value:
            return None
        raw_value = re.sub(r"[^0-9,\\.]", "", raw_value)
        if not raw_value:
            return None
        # OCR a veces mete un dígito “suelto” al final de miles: 100.0006 -> 100.000
        if re.match(r"^[0-9]{1,3}(?:\.[0-9]{3})[0-9]$", raw_value) and "," not in raw_value:
            raw_value = raw_value[:-1]
        if "," in raw_value:
            # 212.000,00 -> 212000.00
            raw_value = raw_value.replace(".", "").replace(",", ".")
        else:
            # 212.000 -> 212000 (miles)
            if re.match(r"^[0-9]{1,3}(?:\.[0-9]{3})+$", raw_value):
                raw_value = raw_value.replace(".", "")
        try:
            val = float(raw_value)
        except Exception:
            return None
        return val if val > 0 else None
    for pat in patterns:
        m = re.search(pat, cleaned, re.IGNORECASE)
        if not m:
            continue
        val = _parse_amount(m.group(1))
        if val is not None:
            return val
    return None


def extract_from_pdf(pdf_path: Path) -> Extracted:
    text, err = server.ocr_pdf_all_pages(str(pdf_path), use_external=False)
    text = text or ""
    fields = server.parse_asesoramiento_text(text)
    cliente1_nombre = _compact(fields.get("cliente1_nombre") or "")
    cliente1_nif = server.normalize_nif(fields.get("cliente1_dni") or fields.get("cliente1_nif") or "")
    cliente2_nombre = _compact(fields.get("cliente2_nombre") or "")
    cliente2_nif = server.normalize_nif(fields.get("cliente2_dni") or fields.get("cliente2_nif") or "")

    precio = _pick_float(
        text,
        (
            r"PRECIO\s+DE\s+COMPRAVENTA.*?(?:ESCRITURADO|ESCRITURAC[IO]N|ESCRIT\w*)\s*[:\-]?\s*([0-9\.,]+)",
            r"PRECIO\s+DE\s+COMPRAVENTA\s*[:\-]?\s*([0-9\.,]+)",
            r"\bESCRITURADO\s*[:\-]?\s*([0-9\.,]+)",
        ),
    )
    importe = _pick_float(
        text,
        (
            r"IMPORTE\s+DEL\s+PRESTAMO\s*[:\-]?\s*(?:MAXIMO\s*)?([0-9\.,]+)",
            r"PRESTAMO\s+CONCEDID[OA]\s*[:\-]?\s*([0-9\.,]+)",
            r"\bCAPITAL\s*[:\-]?\s*([0-9\.,]+)",
        ),
    )
    tipo = ""
    for pat in (
        r"\bTIPO\s+SALIDA\s*[:\-]?\s*([0-9]{1,2}[\\.,][0-9]{1,3})\s*%?",
        r"\bTIPO\s+BONIFICADO\s*[:\-]?\s*([0-9]{1,2}[\\.,][0-9]{1,3})\s*%?",
        r"\bINTER[ÉE]S\s*[:\-]?\s*([0-9]{1,2}[\\.,][0-9]{1,3})\s*%?",
    ):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            tipo = f"{m.group(1).strip()}%"
            break

    return Extracted(
        cliente1_nombre=cliente1_nombre,
        cliente1_nif=cliente1_nif,
        cliente2_nombre=cliente2_nombre,
        cliente2_nif=cliente2_nif,
        precio_compra=precio,
        importe_prestamo=importe,
        tipo_interes=tipo,
        fecha_firma=extract_fecha_firma(text),
        ocr_text=text,
        ocr_error=_compact(err),
    )


def build_s3_key(prefix: str, filename: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(4).hex()
    pref = (prefix or "financiaciones/hipotecas").strip().strip("/")
    return f"{pref}/{stamp}_{rand}_{_safe_filename(filename)}"


def ensure_empresa_id(conn, empresa_id: str, empresa_nombre: str) -> str:
    empresa_id = _compact(empresa_id)
    if empresa_id:
        return empresa_id
    empresa_nombre = _compact(empresa_nombre)
    if not empresa_nombre:
        raise SystemExit("Pasa --empresa-id o --empresa-nombre")
    row = conn.execute("SELECT id FROM empresas WHERE nombre = ? LIMIT 1", (empresa_nombre,)).fetchone()
    if not row:
        raise SystemExit(f"No encuentro empresa '{empresa_nombre}' en empresas")
    return row["id"]


def upsert_hipoteca(conn, empresa_id: str, extracted: Extracted, now: str, *, dry_run: bool) -> str:
    cliente_id = server.ensure_cliente_for_financiacion(
        conn,
        empresa_id,
        extracted.cliente1_nombre,
        extracted.cliente1_nif,
        now,
        extra={},
    )
    if not cliente_id:
        raise RuntimeError("No se pudo resolver/crear cliente principal")

    # Buscar hipoteca existente (best-effort) por cliente_id + fecha_firma o por cliente_id.
    existing = None
    if extracted.fecha_firma:
        existing = conn.execute(
            """
            SELECT id
            FROM hipotecas
            WHERE empresa_id = ?
              AND cliente_id = ?
              AND COALESCE(NULLIF(TRIM(COALESCE(fecha_firma, '')), ''), '') = ?
            ORDER BY COALESCE(NULLIF(fecha_firma,''), NULLIF(fecha_encargo,''), updated_at, created_at) DESC
            LIMIT 1
            """,
            (empresa_id, cliente_id, extracted.fecha_firma),
        ).fetchone()
    if not existing:
        existing = conn.execute(
            """
            SELECT id
            FROM hipotecas
            WHERE empresa_id = ?
              AND cliente_id = ?
            ORDER BY COALESCE(NULLIF(fecha_firma,''), NULLIF(fecha_encargo,''), updated_at, created_at) DESC
            LIMIT 1
            """,
            (empresa_id, cliente_id),
        ).fetchone()
    if existing:
        return existing["id"]

    hipoteca_id = os.urandom(16).hex()
    payload = (
        hipoteca_id,
        empresa_id,
        extracted.cliente1_nombre or "",
        cliente_id,
        None,
        extracted.precio_compra,
        extracted.importe_prestamo,
        None,
        None,
        None,
        None,
        None,
        None,
        extracted.tipo_interes or None,
        extracted.fecha_firma or None,
        None,
        None,
        None,
        None,
        None,
        "FIRMADA" if extracted.fecha_firma else "Pendiente",
        int((extracted.fecha_firma or "0000")[:4]) if extracted.fecha_firma else None,
        now,
        now,
    )
    if dry_run:
        return hipoteca_id
    conn.execute(
        """
        INSERT INTO hipotecas (
          id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca, porcentaje,
          entrada, comision, oficina, fecha_encargo, encargo, tipo_hipoteca,
          fecha_firma, cesion, comision_juan, comision_modernia, inmobiliaria_compra,
          asesor, estado, anio, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        payload,
    )
    return hipoteca_id


def attach_pdf_doc(
    conn,
    *,
    empresa_id: str,
    cliente_id: str,
    hipoteca_id: str,
    pdf_path: Path,
    s3_key: str,
    now: str,
    dry_run: bool,
) -> str:
    doc_id = os.urandom(16).hex()
    nombre = f"Hipoteca · {pdf_path.name}"
    if dry_run:
        return doc_id
    conn.execute(
        """
        INSERT INTO gestoria_docs (
          id, empresa_id, cliente_id, referencia_tipo, referencia_id,
          nombre, tipo, fecha, estado, notas, doc_key, doc_url, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            doc_id,
            empresa_id,
            cliente_id,
            "hipoteca",
            hipoteca_id,
            nombre,
            "Hipoteca",
            "",
            "Firmada",
            str(pdf_path),
            s3_key,
            "",
            now,
            now,
        ),
    )
    return doc_id


def upload_pdf_to_s3(pdf_path: Path, *, prefix: str) -> tuple[str, str]:
    bucket = _env_first("AWS_S3_BUCKET", "S3_BUCKET")
    if not bucket:
        raise RuntimeError("Falta AWS_S3_BUCKET/S3_BUCKET")
    client = server.s3_client()
    if not client:
        raise RuntimeError("No se pudo crear cliente S3 (boto3?)")
    key = build_s3_key(prefix, pdf_path.name)
    body = pdf_path.read_bytes()
    client.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/pdf")
    return key, bucket


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa PDFs (hipotecas) desde carpetas al CRM (Postgres/SQLite).")
    parser.add_argument("--source-dir", action="append", required=True, help="Carpeta con PDFs (repetible)")
    parser.add_argument("--empresa-id", default="", help="empresa_id de Financiaciones/Hipotecas")
    parser.add_argument("--empresa-nombre", default="", help="Nombre empresa para resolver empresa_id si no se pasa --empresa-id")
    parser.add_argument("--s3-prefix", default="financiaciones/hipotecas", help="Prefijo S3 para los PDFs")
    parser.add_argument("--limit", type=int, default=0, help="Procesa solo N PDFs (0=todos)")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en BD ni sube a S3; solo reporta")
    parser.add_argument("--out", default="reports/import_fin_hipotecas_report.json", help="Salida JSON del reporte")
    args = parser.parse_args()

    source_dirs = [Path(d).expanduser() for d in (args.source_dir or [])]
    for d in source_dirs:
        if not d.exists():
            raise SystemExit(f"No existe: {d}")

    pdfs: list[Path] = []
    for d in source_dirs:
        pdfs.extend([p for p in d.rglob("*.pdf") if p.is_file() and not p.name.startswith("._")])
    pdfs = sorted(pdfs)
    if args.limit and args.limit > 0:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        raise SystemExit("No hay PDFs")

    now = _now_iso()
    report: dict = {"now": now, "total": len(pdfs), "items": []}

    conn = None
    if not args.dry_run:
        conn = server.get_db(str(server.DB_CONFIGURED))
        empresa_id = ensure_empresa_id(conn, args.empresa_id, args.empresa_nombre)
    else:
        empresa_id = _compact(args.empresa_id) or "<empresa_id>"

    for idx, pdf in enumerate(pdfs, start=1):
        extracted = extract_from_pdf(pdf)
        item = {
            "pdf": str(pdf),
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

        if idx == 1 or idx % 5 == 0 or idx == len(pdfs):
            print(f"[hipotecas] {idx}/{len(pdfs)} {pdf.name}")

        if args.dry_run:
            report["items"].append(item)
            continue

        try:
            hipoteca_id = upsert_hipoteca(conn, empresa_id, extracted, now, dry_run=False)
            cliente_id = conn.execute(
                "SELECT cliente_id FROM hipotecas WHERE id = ? LIMIT 1",
                (hipoteca_id,),
            ).fetchone()["cliente_id"]
            s3_key, _bucket = upload_pdf_to_s3(pdf, prefix=args.s3_prefix)
            doc_id = attach_pdf_doc(
                conn,
                empresa_id=empresa_id,
                cliente_id=cliente_id,
                hipoteca_id=hipoteca_id,
                pdf_path=pdf,
                s3_key=s3_key,
                now=now,
                dry_run=False,
            )
            conn.commit()
            item.update({"hipoteca_id": hipoteca_id, "cliente_id": cliente_id, "doc_id": doc_id, "s3_key": s3_key})
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                pass
            item["error"] = str(exc)

        report["items"].append(item)

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[hipotecas] reporte: {out}")


if __name__ == "__main__":
    main()
