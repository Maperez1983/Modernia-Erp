#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path


KNOWN_COMPANIES = {
    "MAPFRE": "Mapfre",
    "ALLIANZ": "Allianz",
    "AXA": "AXA",
    "GENERALI": "Generali",
    "REALE": "Reale",
    "OCASO": "Ocaso",
    "PELAYO": "Pelayo",
    "SANTALUCIA": "Santa Lucia",
    "SANTA LUCIA": "Santa Lucia",
    "FIATC": "Fiatc",
    "LINEA DIRECTA": "Línea Directa",
    "LIBERTY": "Liberty",
    "MUTUA MADRILENA": "Mutua Madrileña",
    "MUTUA MADRILEÑA": "Mutua Madrileña",
    "CAJA RURAL": "Caja Rural",
    "CASER": "Caser",
    "PLUS ULTRA": "Plus Ultra",
    "FENIX DIRECTO": "Fénix Directo",
    "DIRECT SEGUROS": "Direct Seguros",
    "HELVETIA": "Helvetia",
    "GROUPAMA": "Groupama",
    "NATIONALE NEDERLANDEN": "Nationale Nederlanden",
    "DAS": "DAS",
    "ARAG": "ARAG",
    "PREVISORA GENERAL": "Previsora General",
    "SANITAS": "Sanitas",
    "DKV": "DKV",
    "ADESLAS": "Adeslas",
    "ASISA": "Asisa",
    "CATALANA OCCIDENTE": "Catalana Occidente",
    "NORTEHISPANA": "NorteHispana",
    "SEGUROS BILBAO": "Seguros Bilbao",
    "ZURICH": "Zurich",
}


def norm_text(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def guess_company(path_text):
    value = norm_text(path_text)
    for token, company in sorted(KNOWN_COMPANIES.items(), key=lambda it: len(it[0]), reverse=True):
        if token in value:
            return company
    return ""


def main():
    parser = argparse.ArgumentParser(description="Build company hints from policy file names/folders.")
    parser.add_argument("--root", required=True, help="Root folder containing issued policies.")
    parser.add_argument("--out", default="data/seguros_company_hints.json", help="Output JSON path.")
    args = parser.parse_args()

    root = Path(args.root).expanduser()
    out = Path(args.out)
    exts = {".pdf", ".jpg", ".jpeg", ".png"}

    hint_counts = Counter()
    company_counts = Counter()
    files = 0

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in exts:
            continue
        files += 1
        rel = str(path.relative_to(root))
        company = guess_company(rel)
        if not company:
            continue
        company_counts[company] += 1
        norm_rel = norm_text(rel)
        for token in KNOWN_COMPANIES:
            if token in norm_rel and KNOWN_COMPANIES[token] == company:
                hint_counts[token] += 1

    hints = {token: KNOWN_COMPANIES[token] for token, count in hint_counts.items() if count >= 1}
    payload = {
        "source_root": str(root),
        "total_files": files,
        "companies": dict(company_counts.most_common()),
        "hints": hints,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out} with {len(hints)} hints from {files} files.")


if __name__ == "__main__":
    main()
