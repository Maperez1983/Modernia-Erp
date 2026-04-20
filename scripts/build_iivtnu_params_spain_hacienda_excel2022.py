import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def parse_float_es(value: object):
    raw = str(value or "").strip()
    if not raw:
        return None
    # 29,00 -> 29.00 ; 1.234,56 -> 1234.56
    raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None


def max_coefs_list_for_year(year: int):
    # Orden: <1, 1, 2, ..., 19, 20+
    # Para 2024+ se usa RDL 8/2023 en el motor actual.
    # Fuente: BOE-A-2023-26452 (coeficientes máximos desde 01/01/2024).
    return [
        0.15,  # <1
        0.15,  # 1
        0.14,  # 2
        0.14,  # 3
        0.16,  # 4
        0.18,  # 5
        0.19,  # 6
        0.20,  # 7
        0.19,  # 8
        0.15,  # 9
        0.12,  # 10
        0.10,  # 11
        0.09,  # 12
        0.09,  # 13
        0.09,  # 14
        0.09,  # 15
        0.10,  # 16
        0.13,  # 17
        0.17,  # 18
        0.23,  # 19
        0.40,  # 20+
    ]


def is_close_list(a, b, tol=1e-8):
    if a is None or b is None:
        return False
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x is None or y is None:
            return False
        if abs(float(x) - float(y)) > tol:
            return False
    return True


def parse_hacienda_excel2022_html(path: Path):
    """
    Hacienda SGFAL ConsultaTipos:
    `ImpuestosExcel2022.aspx?provincia=TODAS&anosel=YYYY`

    Es HTML “para Excel” con una tabla. Estructura esperada (colspans en primera fila):
    - Datos (4): código, ayuntamiento, provincia, población
    - IBI (5)
    - IAE (2)
    - IVTM (24)
    - IIVTNU (44): 21 coeficientes, 21 tipos (repetidos), % reducción art.107.3, coef reductor art.107.2 a)
    - ICIO (1)
    """
    try:
        from bs4 import BeautifulSoup
    except Exception as exc:
        raise SystemExit(f"bs4 requerido: {exc}")

    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return [], {"error": "no_table"}
    trs = table.find_all("tr")
    if len(trs) < 4:
        return [], {"error": "no_rows"}

    # Deriva límites por colspans.
    groups = []
    total_cols = 0
    for td in trs[0].find_all("td"):
        title = td.get_text(" ", strip=True)
        colspan = int(td.get("colspan") or 1)
        groups.append((title, total_cols, total_cols + colspan))
        total_cols += colspan
    if total_cols < 60:
        return [], {"error": "unexpected_cols", "total_cols": total_cols}

    def find_group(title_contains: str):
        needle = str(title_contains or "").strip().lower()
        for title, start, end in groups:
            if needle and needle in str(title or "").strip().lower():
                return start, end
        return None, None

    datos_start, datos_end = find_group("Datos")
    iivtnu_start, iivtnu_end = find_group("I.V.T.N.U")
    if iivtnu_start is None:
        iivtnu_start, iivtnu_end = find_group("IIVTNU")
    icio_start, icio_end = find_group("ICIO")
    if datos_start is None or iivtnu_start is None or icio_start is None:
        return [], {"error": "group_not_found", "groups": groups}

    expected_total = total_cols
    expected_iivtnu_len = int((iivtnu_end or 0) - (iivtnu_start or 0))
    stats = {"rows": 0, "ok": 0, "bad_code": 0, "missing_tipo": 0, "unexpected_cols": 0}
    out = []

    for tr in trs[3:]:
        tds = tr.find_all("td")
        if not tds:
            continue
        if len(tds) != expected_total:
            stats["unexpected_cols"] += 1
            continue
        stats["rows"] += 1

        code = tds[0].get_text(" ", strip=True)
        parts = [p.strip() for p in str(code or "").split("-") if p.strip()]
        if len(parts) < 3:
            stats["bad_code"] += 1
            continue
        prov = parts[-2].zfill(2)
        muni = parts[-1].zfill(3)
        if not (prov.isdigit() and muni.isdigit()):
            stats["bad_code"] += 1
            continue
        ine = f"{prov}{muni}".zfill(5)

        block = [td.get_text(" ", strip=True) for td in tds[iivtnu_start:iivtnu_end]]
        if len(block) != expected_iivtnu_len or expected_iivtnu_len != 44:
            stats["unexpected_cols"] += 1
            continue
        coef_raw = block[0:21]
        tipo_raw = block[21:42]
        reduccion_raw = block[42]
        reductor_raw = block[43]

        coefs = []
        for v in coef_raw:
            fv = parse_float_es(v)
            coefs.append(fv if fv is not None else 0.0)
        tipo = None
        for v in tipo_raw:
            fv = parse_float_es(v)
            if fv is not None and fv > 0:
                tipo = float(fv)
                break
        if tipo is None or tipo <= 0:
            stats["missing_tipo"] += 1
            continue

        reduccion_pct = parse_float_es(reduccion_raw) or 0.0
        coef_reductor = parse_float_es(reductor_raw) or 0.0

        out.append(
            {
                "ine": ine,
                "tipo": round(tipo, 4),
                "coefs": [round(float(x or 0.0), 6) for x in coefs],
                "reduccion_pct": round(float(reduccion_pct), 6) if reduccion_pct else 0.0,
                "coef_reductor": round(float(coef_reductor), 6) if coef_reductor else 0.0,
            }
        )
        stats["ok"] += 1

    return out, stats


def main():
    ap = argparse.ArgumentParser(description="Construye catálogo nacional IIVTNU desde Hacienda (ImpuestosExcel2022).")
    ap.add_argument("--year", required=True, type=int)
    ap.add_argument("--input", required=True, help="Ruta al HTML/XLS descargado (ImpuestosExcel2022.aspx)")
    ap.add_argument("--out", default="data/catalogos/iivtnu_params_spain_hacienda_excel2022.min.json")
    ap.add_argument(
        "--source-url",
        default="https://serviciostelematicosext.hacienda.gob.es/SGFAL/ConsultaTipos/aspx/ImpuestosExcel2022.aspx?provincia=TODAS&anosel={year}",
    )
    args = ap.parse_args()

    year = int(args.year)
    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"No existe: {input_path}")

    rows, stats = parse_hacienda_excel2022_html(input_path)
    max_list = max_coefs_list_for_year(year)

    mapping = {}
    for r in rows:
        ine = str(r["ine"]).zfill(5)
        tipo = float(r["tipo"])
        coefs = list(r["coefs"] or [])
        reduccion = float(r.get("reduccion_pct") or 0.0)
        reductor = float(r.get("coef_reductor") or 0.0)

        entry = [round(tipo, 4), None, None, None]
        if coefs and len(coefs) == 21 and not is_close_list(coefs, max_list):
            entry[1] = [round(float(x), 6) for x in coefs]
        if reduccion:
            entry[2] = round(reduccion, 6)
        if reductor:
            entry[3] = round(reductor, 6)
        mapping[ine] = entry

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path(__file__).resolve().parents[1] / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {}
    if out_path.exists():
        try:
            payload = json.loads(out_path.read_text(encoding="utf-8")) or {}
        except Exception:
            payload = {}

    years = payload.get("years") if isinstance(payload, dict) else None
    if not isinstance(years, dict):
        years = {}
    years[str(year)] = mapping

    source = payload.get("source") if isinstance(payload, dict) else None
    if not isinstance(source, dict):
        source = {}
    source[str(year)] = {
        "label": f"Hacienda (SGFAL ConsultaTipos) · ImpuestosExcel2022 {year} (TODAS) (HTML para Excel)",
        "url": str(args.source_url).format(year=year),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "max_coefs_default": max_list,
        "schema_entry": "[tipo_gravamen_pct, coefs_list_if_diff, reduccion_pct, coef_reductor]",
    }

    out_obj = {
        "scope": "España (municipios; Hacienda SGFAL ConsultaTipos) · IIVTNU coeficientes + tipo (ImpuestosExcel2022)",
        "source": source,
        "years": years,
    }
    out_path.write_text(json.dumps(out_obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"OK: {out_path} ({year}={len(mapping)}; rows_ok={stats.get('ok')})")


if __name__ == "__main__":
    main()

