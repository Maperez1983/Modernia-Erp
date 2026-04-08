#!/usr/bin/env python3
"""
Extracción masiva (local) de pólizas de Seguros desde un directorio de PDFs.

Objetivo:
  - Leer todos los PDFs en un árbol de carpetas
  - Extraer campos de póliza con el parser/OCR existente (web.server)
  - Generar un CSV y un JSON con:
      - campos (tomador, poliza_numero, compania, ramo, fechas, primas, comision, etc.)
      - metadatos (ruta, tamaño, método, calidad, errores)
      - detección de duplicados por (poliza_numero normalizado + compania)

No escribe en DB.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from web.server import (  # noqa: E402
    compute_ocr_quality,
    detect_company_from_metadata,
    extract_pdf_text,
    normalize_company_key,
    normalize_poliza_key,
    ocr_pdf_all_pages,
    parse_poliza_text,
)


DEFAULT_FIELDS = (
    "tomador",
    "nif",
    "dni",
    "poliza_numero",
    "compania",
    "ramo",
    "fecha_efecto",
    "fecha_vencimiento",
    "prima_neta",
    "prima_total",
    "comision",
    "produccion",
    "colaborador",
    "estado",
    "estado_poliza",
    "direccion_riesgo",
    "codigo_postal",
    "matricula",
)

DOC_KIND_RULES = (
    ("recibo", re.compile(r"(?i)\brecibo\b")),
    ("mandato", re.compile(r"(?i)\bmandato\b")),
    ("sepa", re.compile(r"(?i)\bsepa\b")),
    ("suplemento", re.compile(r"(?i)\bsuplemento\b")),
    ("anulacion", re.compile(r"(?i)\banulad[ao]\b|\bbaja\b|\bcancelad[ao]\b")),
    ("poliza", re.compile(r"(?i)\bpoliza\b|\bp[oó]liza\b")),
)


@dataclass
class ExtractResult:
    path: str
    size_bytes: int
    ok: bool
    method: str
    ocr_used: bool
    error: str
    confidence: float
    required_valid: int
    required_filled: int
    fields: dict

    def flat_row(self) -> dict:
        row = {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "ok": int(bool(self.ok)),
            "method": self.method,
            "ocr_used": int(bool(self.ocr_used)),
            "error": self.error,
            "confidence": self.confidence,
            "required_valid": self.required_valid,
            "required_filled": self.required_filled,
            "doc_kind": infer_doc_kind(self.path),
        }
        for key in DEFAULT_FIELDS:
            row[key] = str(self.fields.get(key) or "").strip()
        row["poliza_numero_norm"] = normalize_poliza_key(row.get("poliza_numero"))
        row["compania_norm"] = normalize_company_key(row.get("compania"))
        return row


def _should_exclude(path: Path, exclude_substrs: tuple[str, ...]) -> bool:
    if not exclude_substrs:
        return False
    s_fold = str(path).casefold()
    for sub in exclude_substrs:
        if sub and sub.casefold() in s_fold:
            return True
    return False


def iter_pdfs(root: Path, *, exclude_substrs: tuple[str, ...] = ()) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".pdf":
            continue
        if _should_exclude(p, exclude_substrs):
            continue
        out.append(p)
    return out


def infer_doc_kind(path: str) -> str:
    name = os.path.basename(path or "")
    for label, rx in DOC_KIND_RULES:
        if rx.search(name):
            return label
    return "documento"


def candidate_score(quality: dict) -> int:
    if not isinstance(quality, dict):
        return 0
    required_valid = len(quality.get("required_valid") or [])
    required_filled = len(quality.get("required_filled") or [])
    confidence = float(quality.get("confidence") or 0)
    return required_valid * 100 + required_filled * 10 + int(confidence * 100)


def guess_poliza_from_filename(filename: str) -> str:
    name = os.path.basename(filename or "")
    # 1) Nº cerca de la palabra "póliza" (alfanumérico, pero con al menos 1 dígito)
    m = re.search(r"(?i)\bpoliza\b[^A-Z0-9]{0,12}([A-Z0-9-]{6,24})\b", name)
    if m and re.search(r"\d", m.group(1) or ""):
        return m.group(1)

    # 2) Casos típicos AXA: 23-92198503
    candidates = re.findall(r"\b\d{2}-\d{7,10}\b", name)
    # 3) Tokens numéricos largos
    candidates += re.findall(r"\b[0-9]{6,16}\b", name)
    # 4) Tokens alfanuméricos (ej. GAG09412, BASWZ1733315598407A)
    candidates += re.findall(r"\b[A-Z]{2,8}[0-9]{4,18}[A-Z]?\b", name.upper())
    if not candidates:
        return ""

    normed: list[str] = []
    for c in candidates:
        c = str(c or "").strip()
        if not c:
            continue
        # Evita años/fechas sueltas
        if len(c) == 4 and c.startswith(("19", "20")):
            continue
        if len(c) == 8 and c.startswith(("19", "20")):
            continue
        if not re.search(r"\d", c):
            continue
        normed.append(c)
    if not normed:
        return ""

    normed = sorted(set(normed), key=lambda s: (len(s), s), reverse=True)
    return normed[0]


def extract_one(pdf_path: Path, *, use_ocr: bool, ocr_external: bool, required_keys: tuple[str, ...]) -> ExtractResult:
    size = 0
    try:
        size = pdf_path.stat().st_size
    except Exception:
        size = 0

    method = ""
    ocr_used = False
    err = ""
    fields = {}

    try:
        text, err_detail, base_method = extract_pdf_text(str(pdf_path))
        method = base_method or "pdftotext"
        err = err_detail or ""
        if text and text.strip():
            fields = parse_poliza_text(text, source_hint=str(pdf_path.name))

        hinted_company = detect_company_from_metadata(str(pdf_path.name))
        if hinted_company and not str(fields.get("compania") or "").strip():
            fields["compania"] = hinted_company
        if not str(fields.get("poliza_numero") or "").strip():
            guessed = guess_poliza_from_filename(str(pdf_path.name))
            if guessed:
                fields["poliza_numero"] = guessed

        best_quality = compute_ocr_quality(fields, required_keys)
        if use_ocr:
            missing_required = any(not str(fields.get(k) or "").strip() for k in required_keys)
            if missing_required or candidate_score(best_quality) < 280:
                ocr_text, ocr_err = ocr_pdf_all_pages(str(pdf_path), use_external=bool(ocr_external))
                if ocr_text and ocr_text.strip():
                    ocr_used = True
                    ocr_fields = parse_poliza_text(ocr_text, source_hint=str(pdf_path.name))
                    merged = dict(fields)
                    for k, v in (ocr_fields or {}).items():
                        if v and not str(merged.get(k) or "").strip():
                            merged[k] = v
                    merged_q = compute_ocr_quality(merged, required_keys)
                    if candidate_score(merged_q) >= candidate_score(best_quality):
                        fields = merged
                        best_quality = merged_q
                    method = f"{method}+ocr"
                elif ocr_err and not err:
                    err = ocr_err

        confidence = float(best_quality.get("confidence") or 0.0) if isinstance(best_quality, dict) else 0.0
        required_valid = len(best_quality.get("required_valid") or []) if isinstance(best_quality, dict) else 0
        required_filled = len(best_quality.get("required_filled") or []) if isinstance(best_quality, dict) else 0
        ok = bool(fields) and required_filled > 0
        return ExtractResult(
            path=str(pdf_path),
            size_bytes=int(size or 0),
            ok=ok,
            method=method,
            ocr_used=ocr_used,
            error=str(err or "").strip(),
            confidence=confidence,
            required_valid=required_valid,
            required_filled=required_filled,
            fields=fields or {},
        )
    except Exception as exc:
        return ExtractResult(
            path=str(pdf_path),
            size_bytes=int(size or 0),
            ok=False,
            method=method or "error",
            ocr_used=ocr_used,
            error=f"{type(exc).__name__}: {exc}",
            confidence=0.0,
            required_valid=0,
            required_filled=0,
            fields={},
        )


def write_csv(rows: list[dict], out_path: Path) -> None:
    if not rows:
        out_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser(description="Extrae campos de pólizas desde PDFs locales y genera CSV/JSON.")
    ap.add_argument("--root", required=True, help="Directorio raíz donde buscar PDFs.")
    ap.add_argument(
        "--include-years",
        default="",
        help="Si se indica (p.ej. 2024,2025,2026), solo analiza esas carpetas dentro de --root.",
    )
    ap.add_argument(
        "--exclude-path-substr",
        action="append",
        default=[],
        help="Excluye rutas que contengan este texto (repetible). Ej: --exclude-path-substr RECAPITULACION",
    )
    ap.add_argument("--out-dir", default=str(ROOT / "reports"), help="Directorio de salida (CSV/JSON).")
    ap.add_argument("--limit", type=int, default=0, help="Limita nº de PDFs a procesar (0=sin límite).")
    ap.add_argument("--use-ocr", action="store_true", help="Habilita OCR en fallback (más lento, más fiable).")
    ap.add_argument("--ocr-external", action="store_true", help="Permite OCR externo si está disponible (tesseract).")
    ap.add_argument("--min-confidence", type=float, default=0.0, help="Filtra resultados por confianza mínima en el CSV (0..1).")
    ap.add_argument(
        "--dedupe-require-poliza",
        action="store_true",
        help="Solo marca duplicados si hay nº de póliza (recomendado).",
    )
    ap.add_argument(
        "--required-keys",
        default="tomador,poliza_numero,compania,fecha_efecto",
        help="Claves mínimas para evaluar calidad (coma-separado).",
    )
    args = ap.parse_args()

    root = Path(args.root).expanduser().resolve()
    if not root.exists():
        raise SystemExit(f"No existe: {root}")

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    required_keys = tuple([k.strip() for k in str(args.required_keys or "").split(",") if k.strip()])
    if not required_keys:
        required_keys = ("tomador", "poliza_numero", "compania", "fecha_efecto")

    exclude_substrs = tuple([str(x or "").strip() for x in (args.exclude_path_substr or []) if str(x or "").strip()])
    include_years = [y.strip() for y in str(args.include_years or "").split(",") if y.strip()]

    roots: list[Path] = []
    if include_years:
        for y in include_years:
            yp = (root / y).resolve()
            if yp.exists():
                roots.append(yp)
    else:
        roots = [root]

    pdfs: list[Path] = []
    for rp in roots:
        pdfs.extend(iter_pdfs(rp, exclude_substrs=exclude_substrs))

    pdfs = sorted(set(pdfs))
    if args.limit and args.limit > 0:
        pdfs = pdfs[: int(args.limit)]

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"seguros_extract_{ts}"
    json_path = out_dir / f"{base}.json"
    csv_path = out_dir / f"{base}.csv"
    summary_path = out_dir / f"{base}_summary.json"

    results: list[ExtractResult] = []
    rows: list[dict] = []

    print(f"root={root}", flush=True)
    if include_years:
        print(f"include_years={','.join(include_years)}", flush=True)
    if exclude_substrs:
        print(f"exclude_path_substr={','.join(exclude_substrs)}", flush=True)
    print(f"pdfs={len(pdfs)} use_ocr={bool(args.use_ocr)} ocr_external={bool(args.ocr_external)}", flush=True)
    for idx, pdf in enumerate(pdfs, start=1):
        res = extract_one(pdf, use_ocr=bool(args.use_ocr), ocr_external=bool(args.ocr_external), required_keys=required_keys)
        results.append(res)
        if res.confidence >= float(args.min_confidence or 0.0):
            rows.append(res.flat_row())
        if idx % 10 == 0 or idx == 1 or idx == len(pdfs):
            ok_count = sum(1 for r in results if r.ok)
            print(f"[{idx}/{len(pdfs)}] ok={ok_count} last={pdf.name}", flush=True)

    duplicates = defaultdict(list)
    for r in rows:
        poliza_norm = r.get("poliza_numero_norm") or ""
        comp_norm = r.get("compania_norm") or ""
        if args.dedupe_require_poliza and not poliza_norm:
            continue
        key = (poliza_norm, comp_norm)
        if key == ("", ""):
            continue
        duplicates[key].append(r.get("path"))
    dup_groups = {f"{k[0]}|{k[1]}": v for k, v in duplicates.items() if len(v) > 1}

    method_counts = Counter([r.method for r in results])
    missing = Counter()
    for r in results:
        for k in required_keys:
            if not str(r.fields.get(k) or "").strip():
                missing[k] += 1

    summary = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "pdf_count": len(pdfs),
        "ok_count": sum(1 for r in results if r.ok),
        "ocr_used_count": sum(1 for r in results if r.ocr_used),
        "avg_confidence": round(sum(r.confidence for r in results) / max(1, len(results)), 4),
        "required_keys": list(required_keys),
        "missing_required_counts": dict(missing),
        "method_counts": dict(method_counts),
        "duplicate_groups": dup_groups,
        "outputs": {
            "json": str(json_path),
            "csv": str(csv_path),
            "summary": str(summary_path),
        },
    }

    json_path.write_text(json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(rows, csv_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("done", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
