import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web.server import (
    _iivtnu_extract_from_pdf,
    _iivtnu_load_tipo_gravamen_malaga,
    _iivtnu_max_coefs_for_devengo,
    _iivtnu_objective_coef,
    PdfReader,
    parse_iso_date,
)
from io import BytesIO


DOC_TYPES = {
    "simulacion_ayuda",
    "autoliquidacion",
    "carta_pago",
    "guia_autoliquidacion",
    "solicitud_inexistencia_incremento",
}


def money_or_none(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def near(a, b, tol=0.03):
    if a is None or b is None:
        return None
    try:
        a = float(a)
        b = float(b)
    except Exception:
        return None
    return abs(a - b) <= tol


def pick_participacion(parsed):
    for key in ("participacion_pct", "subdivision_pct"):
        v = money_or_none(parsed.get(key))
        if v is None:
            continue
        if v <= 0:
            continue
        if v > 100.0 and v <= 10000:
            # OCR: a veces se captura 100,0000 como 1000000
            v = v / 1000.0
        return max(0.0, min(100.0, v))
    return 100.0


def derecho_factor(parsed):
    raw = str(parsed.get("derecho_transmitido") or "").strip().lower()
    if not raw:
        return 1.0, "pleno(assumed)"
    if "pleno" in raw:
        return 1.0, "pleno"
    # Para nuda/usufructo se requiere edad/duración; si no hay, no asumimos.
    if "nuda" in raw:
        return None, "nuda(sin edad)"
    if "usuf" in raw:
        return None, "usufructo(sin edad/duración)"
    if "uso" in raw or "habit" in raw:
        return None, "uso/habitación(sin edad)"
    return 1.0, "pleno(unknown)"


def tipo_malaga_por_ine(ine: str, devengo: date):
    if not ine or not str(ine).zfill(5).startswith("29"):
        return None, "", ""
    data = _iivtnu_load_tipo_gravamen_malaga() or {}
    years = data.get("years") if isinstance(data, dict) else {}
    src_map = data.get("source") if isinstance(data, dict) else {}
    year_key = str(int(getattr(devengo, "year", 0) or 0))
    used_year = year_key
    cand_years = [year_key]
    if year_key == "2025":
        cand_years.append("2024")
    if year_key == "2024":
        cand_years.append("2025")
    tipo = None
    for y in cand_years:
        ymap = years.get(y) if isinstance(years, dict) else None
        if not isinstance(ymap, dict):
            continue
        v = ymap.get(str(ine).zfill(5))
        if v is None and str(ine).isdigit():
            try:
                v = ymap.get(str(int(str(ine))))
            except Exception:
                v = None
        if v is None:
            continue
        try:
            fv = float(v)
        except Exception:
            continue
        if fv > 0:
            tipo = fv
            used_year = y
            break
    label = ""
    url = ""
    src = src_map.get(used_year) if isinstance(src_map, dict) else None
    if isinstance(src, dict):
        label = str(src.get("label") or "").strip()
        url = str(src.get("url") or "").strip()
        if used_year != year_key:
            label = f"{label} (proxy para {year_key}; sin dato {year_key})".strip()
    return tipo, label, url


@dataclass
class CalcResult:
    coef_obj: float
    years: int
    months: int
    valor_suelo_usado: float
    base_obj: float
    tipo: Optional[float]
    cuota_bruta: Optional[float]
    bonif_pct: Optional[float]
    cuota_neta: Optional[float]
    notes: str


def calc_objetivo(parsed):
    acq = parse_iso_date(parsed.get("fecha_adquisicion") or "")
    dev = parse_iso_date(parsed.get("fecha_transmision") or "")
    vs = money_or_none(parsed.get("valor_suelo"))
    if not acq or not dev or not vs or vs <= 0:
        return None
    coef_red = money_or_none(parsed.get("coef_reduccion"))
    vs_red = money_or_none(parsed.get("valor_suelo_reducido"))
    vs_used = vs
    if vs_red and vs_red > 0:
        vs_used = vs_red
    elif coef_red is not None and coef_red > 0:
        c = float(coef_red)
        if c > 1.5:
            c = c / 100.0
        c = max(0.0, min(1.0, c))
        vs_used = vs * c

    coefs, _src = _iivtnu_max_coefs_for_devengo(dev)
    info = _iivtnu_objective_coef(acq, dev, coefs or {})
    coef_obj = float(info.get("coef_objetivo") or 0.0)

    factor_pct = pick_participacion(parsed)
    d_factor, d_note = derecho_factor(parsed)
    if d_factor is None:
        return CalcResult(
            coef_obj=coef_obj,
            years=int(info.get("years") or 0),
            months=int(info.get("months") or 0),
            valor_suelo_usado=round(vs_used + 1e-9, 2),
            base_obj=None,
            tipo=None,
            cuota_bruta=None,
            bonif_pct=None,
            cuota_neta=None,
            notes=f"falta factor derecho ({d_note})",
        )
    base = round(vs_used * coef_obj * (factor_pct / 100.0) * float(d_factor) + 1e-9, 2)

    tipo = money_or_none(parsed.get("tipo_gravamen_pct"))
    tipo_note = "tipo_from_pdf"
    if tipo is None and dev:
        tipo2, label, _url = tipo_malaga_por_ine(str(parsed.get("municipio_ine") or ""), dev)
        if tipo2 is not None:
            tipo = float(tipo2)
            tipo_note = f"tipo_catalog({label})" if label else "tipo_catalog"
    cuota_bruta = None
    if tipo is not None:
        cuota_bruta = round(base * float(tipo) / 100.0 + 1e-9, 2)

    bonif = money_or_none(parsed.get("bonificacion_pct"))
    cuota_neta = None
    if cuota_bruta is not None and bonif is not None:
        bon = float(bonif)
        if bon > 1.5 and bon <= 100.0:
            bon = bon
        bon = max(0.0, min(100.0, bon))
        cuota_neta = round(cuota_bruta * (1.0 - bon / 100.0) + 1e-9, 2)

    return CalcResult(
        coef_obj=coef_obj,
        years=int(info.get("years") or 0),
        months=int(info.get("months") or 0),
        valor_suelo_usado=round(vs_used + 1e-9, 2),
        base_obj=base,
        tipo=tipo,
        cuota_bruta=cuota_bruta,
        bonif_pct=bonif,
        cuota_neta=cuota_neta,
        notes=f"ok ({tipo_note}, {d_note})",
    )


def is_candidate_path(path: Path) -> bool:
    name = path.name.lower()
    if any(x in name for x in ("plusvalia", "plusvalía", "iivtnu", "autoliquid", "carta de pago", "documento de pago")):
        return True
    parts = [p.lower() for p in path.parts]
    if any("plusvalia" in p or "plusvlaia" in p for p in parts):
        return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="Carpeta a analizar (p.ej. /Volumes/.../Downloads/2025)")
    ap.add_argument("--out", default="reports/iivtnu_analysis.csv")
    ap.add_argument(
        "--deep-scan",
        action="store_true",
        help="Escanea todos los PDFs por texto (pypdf) buscando palabras clave IIVTNU, además de la heurística por ruta.",
    )
    args = ap.parse_args()

    root = Path(args.root).expanduser()
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parents[1] / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pdfs = {p for p in root.rglob("*.pdf") if is_candidate_path(p)}
    if args.deep_scan and PdfReader is not None:
        keywords = (
            "INCREMENTO DEL VALOR DE LOS TERRENOS",
            "NATURALEZA URBANA",
            "MODELO 004",
            "MOD. 004",
            "AUTOLIQUIDAC",
            "DECLARACIÓN-LIQUIDACIÓN",
            "DECLARACION-LIQUIDACION",
            "PROGRAMA DE AYUDA AL CÁLCULO",
            "ESTIMACIÓN DEL IMPORTE A PAGAR",
            "IMPOST INCREMENT VALOR TERRENYS",
            "QUOTA LIQ",
            "GESTRISAM",
            "PLUSVALIA",
        )
        for p in root.rglob("*.pdf"):
            if p in pdfs:
                continue
            try:
                data = p.read_bytes()
            except Exception:
                continue
            try:
                r = PdfReader(BytesIO(data))
                pages = list(r.pages or [])
                sample = ""
                for page in pages[:2]:
                    try:
                        sample += "\n" + (page.extract_text() or "")
                    except Exception:
                        continue
                up = sample.upper()
                if up and any(k in up for k in keywords):
                    pdfs.add(p)
            except Exception:
                continue
    pdfs = sorted(pdfs)
    rows = []
    for p in pdfs:
        try:
            parsed = _iivtnu_extract_from_pdf(p.read_bytes(), filename=p.name) or {}
        except Exception as exc:
            rows.append(
                {
                    "path": str(p),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        doc_type = str(parsed.get("doc_type") or "").strip()
        if doc_type and doc_type not in DOC_TYPES:
            continue
        if not doc_type:
            # no parece IIVTNU
            continue
        calc = calc_objetivo(parsed)
        base_pdf = money_or_none(parsed.get("base_imponible"))
        cuota_pdf = money_or_none(parsed.get("cuota_tributaria"))
        total_pdf = money_or_none(parsed.get("importe_total"))
        base_ok = near(base_pdf, getattr(calc, "base_obj", None)) if calc else None
        cuota_ok = near(cuota_pdf, getattr(calc, "cuota_bruta", None)) if calc else None
        total_ok = near(total_pdf, getattr(calc, "cuota_neta", None)) if calc and calc.cuota_neta is not None else None
        if total_ok is None:
            total_ok = near(total_pdf, getattr(calc, "cuota_bruta", None)) if calc else None

        row = {
            "path": str(p),
            "doc_type": doc_type,
            "municipio": parsed.get("municipio") or "",
            "provincia": parsed.get("provincia") or "",
            "ine": str(parsed.get("municipio_ine") or ""),
            "cp": parsed.get("codigo_postal") or "",
            "refcat": parsed.get("referencia_catastral") or "",
            "fecha_adq": parsed.get("fecha_adquisicion") or "",
            "fecha_tx": parsed.get("fecha_transmision") or "",
            "valor_suelo": parsed.get("valor_suelo"),
            "valor_suelo_reducido": parsed.get("valor_suelo_reducido"),
            "coef_reduccion": parsed.get("coef_reduccion"),
            "valor_catastral_total": parsed.get("valor_catastral_total"),
            "porcentaje_suelo_ba": parsed.get("porcentaje_suelo"),
            "participacion_pct": parsed.get("participacion_pct"),
            "subdivision_pct": parsed.get("subdivision_pct"),
            "tipo_gravamen_pct_pdf": parsed.get("tipo_gravamen_pct"),
            "bonificacion_pct_pdf": parsed.get("bonificacion_pct"),
            "base_pdf": base_pdf,
            "cuota_pdf": cuota_pdf,
            "total_pdf": total_pdf,
            "coef_obj": getattr(calc, "coef_obj", None) if calc else None,
            "years": getattr(calc, "years", None) if calc else None,
            "months": getattr(calc, "months", None) if calc else None,
            "valor_suelo_usado": getattr(calc, "valor_suelo_usado", None) if calc else None,
            "tipo_usado": getattr(calc, "tipo", None) if calc else None,
            "base_calc": getattr(calc, "base_obj", None) if calc else None,
            "cuota_calc_bruta": getattr(calc, "cuota_bruta", None) if calc else None,
            "cuota_calc_neta": getattr(calc, "cuota_neta", None) if calc else None,
            "base_ok": base_ok,
            "cuota_ok": cuota_ok,
            "total_ok": total_ok,
            "notes": getattr(calc, "notes", "") if calc else "faltan datos mínimos",
            "error": "",
            "raw_json": json.dumps({k: v for k, v in parsed.items() if not str(k).startswith('_')}, ensure_ascii=False),
        }
        rows.append(row)

    fieldnames = []
    for row in rows:
        for k in row.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"PDFs candidatos: {len(pdfs)}")
    print(f"Registros IIVTNU: {len(rows)}")
    print(f"Informe: {out_path}")


if __name__ == "__main__":
    main()
