#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import tempfile
import sys
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from web.schema_support import apply_schema_file, ensure_column


DEFAULT_ROOT = Path(
    "/Volumes/Mac Satecchi/Mac/Downloads/OneDrive_2026-03-26/INMUEBLES VENDIDOS"
)
DEFAULT_DB = Path("data/erp_import2.sqlite")
DEFAULT_COMPANY = "Estudio Velazquez 2012 SL"

MONTH_NAMES = {
    "ENERO": "enero",
    "FEBRERO": "febrero",
    "MARZO": "marzo",
    "ABRIL": "abril",
    "MAYO": "mayo",
    "JUNIO": "junio",
    "JULIO": "julio",
    "AGOSTO": "agosto",
    "SEPTIEMBRE": "septiembre",
    "OCTUBRE": "octubre",
    "NOVIEMBRE": "noviembre",
    "DICIEMBRE": "diciembre",
}

NAME_STOPWORDS = {
    "ESTUDIO",
    "VELAZQUEZ",
    "TECNOCASA",
    "COMPRA",
    "VENTA",
    "CONTRATO",
    "PRIVADO",
    "NOTA",
    "SIMPLE",
    "PROPUESTA",
    "ESCRITURA",
    "ARRAS",
    "DOCUMENTACION",
    "FIRMA",
    "CATASTRO",
    "RECIBI",
    "JUSTIFICACION",
    "PRECIO",
    "COMPRADOR",
    "COMPRADORES",
    "VENDEDOR",
    "VENDEDORES",
    "DNI",
    "DNII",
    "EN",
    "A",
    "SEGUN",
    "SEGTIN",
    "ACREDITA",
    "DOCUMENTALMENTE",
    "SE",
    "COMPROMETE",
    "ADELANTE",
}

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
NIF_RE = re.compile(
    r"\b(?:"
    r"[XYZ][\s.-]*\d(?:[\s.-]*\d){6,7}[\s.-]*[A-Z]"
    r"|"
    r"\d(?:[\s.-]*\d){6,7}[\s.-]*[A-Z]"
    r"|"
    r"[ABCDEFGHJNPQRSUVW][\s.-]*\d(?:[\s.-]*\d){6,7}[\s.-]*[0-9A-J]"
    r")\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(r"(?<![A-Z0-9])(?:\+34\s*)?([6789]\d{8})(?![A-Z0-9])")
MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)(?:\s*€|\s*EUROS?)", re.IGNORECASE)
PLAIN_AMOUNT_RE = re.compile(r"(?<!\d)(\d{1,3}(?:[.\s]\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)(?!\d)")
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
CADASTRAL_RE = re.compile(r"\b[0-9A-Z]{20}\b")
PERSON_WITH_DNI_RE = re.compile(
    r"(?:\bDON\b|\bDOÑA\b|\bDONA\b|\bD\.\s*|\bDª\.?\s*|\bDº\.?\s*|\bDÑA\.?\s*)\s*"
    r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑa-záéíóúñ\s]+?)"
    r"(?:,?\s*MAYOR DE EDAD|,?\s*VECIN[OA]|,?\s*CON DOMICILIO|,?\s*Y PROVIST[OA])",
    re.IGNORECASE | re.DOTALL,
)

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}

SPANISH_NUMBER_WORDS = {
    "cero": 0,
    "un": 1,
    "uno": 1,
    "una": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiuno": 21,
    "veintidos": 22,
    "veintitres": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "treinta_y_uno": 31,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "trescientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
    "mil": 1000,
}


@dataclass
class CaseEntry:
    year: int
    month: str
    label: str
    case_path: Path
    files: list[Path]


def compact_spaces(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm_text(value: object) -> str:
    text = compact_spaces(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm_text(value)).strip("_")


def normalize_name(value: object) -> str:
    text = compact_spaces(value)
    if not text:
        return ""
    text = re.sub(r"(?i)\bdni+i?\b", "", text)
    text = compact_spaces(text)
    if not text:
        return ""
    words = [w for w in re.split(r"\s+", text) if w]
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def normalize_nif(value: object) -> str:
    raw = compact_spaces(value).upper()
    normalized = re.sub(r"[^A-Z0-9]", "", raw)
    if re.match(r"^Y[\s.-]+\d", raw) and re.fullmatch(r"Y\d{8}[A-Z]", normalized):
        return normalized[1:]
    return normalized


def parse_money(value: object) -> float | None:
    text = compact_spaces(value)
    if not text:
        return None
    text = text.replace("EUR", "").replace("EUROS", "").replace("EURO", "").replace("€", "")
    text = text.replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text and "," not in text and re.fullmatch(r"\d{1,3}(?:\.\d{3})+", text):
        text = text.replace(".", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def parse_date(value: object) -> str:
    text = compact_spaces(value)
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.date().isoformat()
        except ValueError:
            continue
    match = re.search(
        r"\b(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        day = int(match.group(1))
        month = SPANISH_MONTHS.get(match.group(2).lower())
        year = int(match.group(3))
        if month:
            return datetime(year, month, day).date().isoformat()
    written = parse_written_spanish_date(text)
    if written:
        return written
    return ""


def parse_spanish_number_words(value: object) -> int | None:
    text = norm_text(value).replace("-", " ").replace(" y ", "_y_")
    tokens = [token for token in text.split() if token]
    if not tokens:
        return None
    total = 0
    current = 0
    matched = False
    for token in tokens:
        if token not in SPANISH_NUMBER_WORDS:
            return None
        matched = True
        value_num = SPANISH_NUMBER_WORDS[token]
        if token == "mil":
            current = max(current, 1) * 1000
            total += current
            current = 0
        else:
            current += value_num
    total += current
    return total if matched else None


def parse_written_spanish_date(value: object) -> str:
    text = compact_spaces(value)
    match = re.search(
        r"\b([a-záéíóúñ\s-]+?)\s+de\s+"
        r"(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)"
        r"\s+de\s+([a-záéíóúñ\s-]+)\b",
        text,
        re.IGNORECASE,
    )
    if not match:
        return ""
    day = parse_spanish_number_words(match.group(1))
    month = SPANISH_MONTHS.get(norm_text(match.group(2)))
    year = parse_spanish_number_words(match.group(3))
    if not day or not month or not year:
        return ""
    if year < 100:
        year += 2000
    if year < 1900 or year > 2100 or day < 1 or day > 31:
        return ""
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def first_unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = compact_spaces(item)
        if not cleaned:
            continue
        key = norm_text(cleaned)
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def command_exists(name: str) -> bool:
    return subprocess.run(["which", name], capture_output=True, text=True, check=False).returncode == 0


def read_doc_text(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix in {".doc", ".docx"}:
        proc = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.stdout or "", "text"
    return "", "binary"


def read_image_ocr(path: Path) -> tuple[str, str]:
    if not command_exists("tesseract"):
        return "", "missing_tesseract"
    proc = subprocess.run(
        ["tesseract", str(path), "stdout", "-l", "spa+eng"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout or "", "ocr"


def read_pdf_text(path: Path, max_ocr_pages: int) -> tuple[str, str]:
    proc = subprocess.run(
        ["pdftotext", "-f", "1", "-l", str(max_ocr_pages), str(path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout or ""
    if compact_spaces(text):
        return text, "text"
    if not command_exists("pdftoppm") or not command_exists("tesseract"):
        return "", "empty"
    with tempfile.TemporaryDirectory() as tmpdir:
        prefix = Path(tmpdir) / "page"
        render = subprocess.run(
            ["pdftoppm", "-f", "1", "-l", str(max_ocr_pages), "-r", "180", "-png", str(path), str(prefix)],
            capture_output=True,
            text=True,
            check=False,
        )
        if render.returncode != 0:
            return "", "empty"
        chunks: list[str] = []
        for image_path in sorted(Path(tmpdir).glob("*.png")):
            ocr = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "spa+eng"],
                capture_output=True,
                text=True,
                check=False,
            )
            if compact_spaces(ocr.stdout):
                chunks.append(ocr.stdout)
        return "\n".join(chunks), "ocr" if chunks else "empty"


def read_file_text(path: Path, doc_type: str) -> tuple[str, str]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        max_pages = 14 if doc_type in {"escritura", "copia_simple"} else 3 if doc_type == "propuesta" else 2
        return read_pdf_text(path, max_pages)
    if suffix in {".doc", ".docx"}:
        return read_doc_text(path)
    if suffix in {".jpg", ".jpeg", ".png", ".bmp"}:
        return read_image_ocr(path)
    return "", "binary"


def classify_file(path: Path) -> str | None:
    text = norm_text(path.stem)
    if "nota de encargo" in text or text == "n e" or text.startswith("n.e"):
        return "encargo"
    if "contrato privado" in text:
        return "contrato_privado"
    if "propuesta" in text:
        return "propuesta"
    if "reserva" in text:
        return "propuesta"
    if "arras" in text or "reserva" in text:
        return "arras"
    if "escritura" in text:
        return "escritura"
    if "copia simple" in text:
        return "copia_simple"
    if "nota simple" in text:
        return "nota_simple"
    if "parte de visita" in text or "hoja de visita" in text or ("visita" in text and "parte" in text):
        return "parte_visita"
    if "catastro" in text or "catastr" in text:
        return "catastro"
    if "dni" in text or "pasaporte" in text:
        return "dni"
    return None


def rank_file(path: Path, doc_type: str) -> tuple[int, int, str]:
    ext = path.suffix.lower()
    if doc_type == "dni":
        ext_score = {".docx": 4, ".doc": 3, ".pdf": 2, ".jpg": 1, ".jpeg": 1, ".png": 1}.get(ext, 0)
    elif doc_type in {"propuesta", "arras", "contrato_privado", "parte_visita"}:
        ext_score = {".docx": 4, ".doc": 3, ".pdf": 2, ".jpg": 1, ".jpeg": 1, ".png": 1}.get(ext, 0)
    else:
        ext_score = {".pdf": 4, ".docx": 3, ".doc": 2, ".jpg": 1, ".jpeg": 1, ".png": 1}.get(ext, 0)
    name = norm_text(path.name)
    bonus = 1 if doc_type in name else 0
    if doc_type == "contrato_privado" and "contrato privado" in name:
        bonus += 3
    if doc_type == "propuesta" and "propuesta" in name:
        bonus += 2
    if doc_type == "arras" and "arras" in name:
        bonus += 2
    return (ext_score, bonus, path.name)


def candidate_map(files: list[Path]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for path in files:
        doc_type = classify_file(path)
        if not doc_type:
            continue
        grouped.setdefault(doc_type, []).append(path)
    for doc_type in grouped:
        grouped[doc_type] = sorted(grouped[doc_type], key=lambda p: rank_file(p, doc_type), reverse=True)
    return grouped


def infer_month_from_name(value: str) -> str:
    upper = value.upper()
    for token, month in MONTH_NAMES.items():
        if token in upper:
            return month
    return ""


def gather_cases(root: Path, default_year: int = 0, default_month: str = "") -> list[CaseEntry]:
    cases: list[CaseEntry] = []
    year_dirs = sorted(p for p in root.iterdir() if p.is_dir() and p.name.isdigit())
    if not year_dirs:
        month = default_month or infer_month_from_name(root.name)
        for child in sorted(root.iterdir()):
            if child.is_file():
                cases.append(
                    CaseEntry(
                        year=default_year,
                        month=month,
                        label=child.stem,
                        case_path=child,
                        files=[child],
                    )
                )
                continue
            if child.is_dir():
                cases.append(
                    CaseEntry(
                        year=default_year,
                        month=month,
                        label=child.name,
                        case_path=child,
                        files=sorted(p for p in child.rglob("*") if p.is_file()),
                    )
                )
        return cases

    for year_dir in year_dirs:
        year = int(year_dir.name)
        for child in sorted(year_dir.iterdir()):
            if child.is_file():
                cases.append(
                    CaseEntry(
                        year=year,
                        month="",
                        label=child.stem,
                        case_path=child,
                        files=[child],
                    )
                )
                continue
            if not child.is_dir():
                continue
            direct_files = [p for p in child.iterdir() if p.is_file()]
            if direct_files:
                cases.append(
                    CaseEntry(
                        year=year,
                        month="",
                        label=child.name,
                        case_path=child,
                        files=sorted(p for p in child.rglob("*") if p.is_file()),
                    )
                )
                continue
            month = MONTH_NAMES.get(child.name.upper(), child.name)
            for grand in sorted(child.iterdir()):
                if grand.is_file():
                    cases.append(
                        CaseEntry(
                            year=year,
                            month=month,
                            label=grand.stem,
                            case_path=grand,
                            files=[grand],
                        )
                    )
                elif grand.is_dir():
                    cases.append(
                        CaseEntry(
                            year=year,
                            month=month,
                            label=grand.name,
                            case_path=grand,
                            files=sorted(p for p in grand.rglob("*") if p.is_file()),
                        )
                    )
    return cases


def clean_filename_name(stem: str) -> list[str]:
    text = stem
    text = re.sub(r"(?i)\bdni\b", "", text)
    text = re.sub(r"(?i)\bpasaporte\b", "", text)
    text = re.sub(r"[_.,;:()\[\]-]+", " ", text)
    text = compact_spaces(text)
    if not text:
        return []
    parts = re.split(r"\s+y\s+|\s+e\s+", text, flags=re.IGNORECASE)
    cleaned = []
    for part in parts:
        part = compact_spaces(part)
        if not part:
            continue
        tokens = []
        for token in part.split():
            token = re.sub(r"^\d+|\d+$", "", token)
            token = compact_spaces(token)
            if not token or token.upper() in NAME_STOPWORDS:
                continue
            tokens.append(token)
        if not tokens:
            continue
        cleaned.append(normalize_name(" ".join(tokens)))
    return first_unique(cleaned)


def extract_name_matches(text: str, patterns: Iterable[str]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            captured = normalize_name(match.group(1))
            if len(captured) < 4:
                continue
            if any(token.upper() in NAME_STOPWORDS for token in captured.split()):
                continue
            matches.append(captured)
    return first_unique(matches)


def extract_nifs(text: str) -> list[str]:
    return first_unique(normalize_nif(match.group(0)) for match in NIF_RE.finditer(text or ""))


def extract_emails(text: str) -> list[str]:
    return first_unique(
        email
        for email in (match.group(0).lower() for match in EMAIL_RE.finditer(text or ""))
        if not email.endswith("@tecnocasa.es") and "numeroverde@" not in email
    )


def extract_phones(text: str) -> list[str]:
    return first_unique(match.group(1) for match in PHONE_RE.finditer(text or ""))


def extract_dates(text: str) -> list[str]:
    values: list[tuple[int, str]] = []
    for match in DATE_RE.finditer(text or ""):
        parsed = parse_date(match.group(1))
        if parsed:
            values.append((match.start(), parsed))
    for match in re.finditer(
        r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+de\s+\d{4}\b",
        text or "",
        re.IGNORECASE,
    ):
        parsed = parse_date(match.group(0))
        if parsed:
            values.append((match.start(), parsed))
    values.sort(key=lambda item: item[0])
    return first_unique(value for _, value in values)


def extract_people_and_nifs(fragment: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for match in PERSON_WITH_DNI_RE.finditer(fragment or ""):
        name = normalize_name(match.group(1))
        if not name or any(token.upper() in NAME_STOPWORDS for token in name.split()):
            continue
        tail = fragment[match.end() : match.end() + 220]
        nif_match = NIF_RE.search(tail)
        nif = normalize_nif(nif_match.group(0)) if nif_match else ""
        results.append((name, nif))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, nif in results:
        key = f"{norm_text(name)}|{nif}"
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, nif))
    return unique


def extract_people_with_inline_nif(fragment: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r"(?:\bDON\b|\bDOÑA\b|\bDONA\b|\bD\.\s*|\bDÑA\.?\s*)\s*"
        r"([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}?)"
        r"\s*,.{0,220}?"
        r"(?:D\.?\s*N\.?\s*I\.?|DOCUMENTO\S*\s+NACIONAL\S*\s+DE\s+IDENTIDAD)"
        r".{0,40}?"
        r"([0-9][0-9.\s-]*[A-Z])",
        re.IGNORECASE | re.DOTALL,
    )
    pairs = []
    for match in pattern.finditer(fragment or ""):
        name = normalize_name(match.group(1))
        nif = normalize_nif(match.group(2))
        if not name or any(token.upper() in NAME_STOPWORDS for token in name.split()):
            continue
        if nif:
            pairs.append((name, nif))
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, nif in pairs:
        key = f"{norm_text(name)}|{nif}"
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, nif))
    return unique


def extract_party_people_with_ordered_nifs(fragment: str) -> list[tuple[str, str]]:
    if not fragment:
        return []
    names: list[str] = []
    for match in re.finditer(
        r"(?:\bDON\b|\bDOÑA\b|\bDONA\b|\bD\.\s*|\bDÑA\.?\s*)\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}?)"
        r"(?=,|\s+y\s+(?:don|doña|dona|dña\.?)|\s+mayores?\s+de\s+edad|\s+mayor\s+de\s+edad|\s+con\s+sus|\s+con\s+su)",
        fragment,
        re.IGNORECASE | re.DOTALL,
    ):
        name = normalize_name(match.group(1))
        if not name or any(token.upper() in NAME_STOPWORDS for token in name.split()):
            continue
        names.append(name)
    names = first_unique(names)
    if not names:
        return []
    nifs = extract_nifs(fragment)
    if not nifs:
        return [(name, "") for name in names]
    pairs: list[tuple[str, str]] = []
    for index, name in enumerate(names):
        nif = nifs[index] if index < len(nifs) else ""
        pairs.append((name, nif))
    return pairs


def find_nif_for_name(text: str, name: str) -> str:
    tokens = [re.escape(token) for token in compact_spaces(name).split() if len(token) > 1]
    if not text or len(tokens) < 2:
        return ""
    joined = r"\W+".join(tokens)
    patterns = [
        rf"\b{joined}\b(?P<tail>.{{0,220}})",
        rf"(?P<head>.{{0,120}})\b{joined}\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            scope = match.groupdict().get("tail") or match.groupdict().get("head") or ""
            nif_match = NIF_RE.search(scope)
            if nif_match:
                return normalize_nif(nif_match.group(0))
    return ""


def align_nifs_with_names(names: list[str], nifs: list[str], sources: Iterable[str]) -> list[str]:
    aligned = list(nifs)
    source_texts = [text for text in sources if compact_spaces(text)]
    for index, name in enumerate(names):
        while len(aligned) <= index:
            aligned.append("")
        if aligned[index]:
            continue
        for text in source_texts:
            nif = find_nif_for_name(text, name)
            if nif:
                aligned[index] = nif
                break
    return first_unique(aligned)


def extract_contract_party(text: str, role: str) -> list[tuple[str, str]]:
    patterns = {
        "compradora": r"de una parte,(.+?)\(\s*en adelante,\s*la parte\s+COMPRADORA\)",
        "vendedora": r"de otra parte,(.+?)\(\s*en adelante,\s*la parte\s+VENDEDORA\)",
    }
    pattern = patterns.get(role)
    if not pattern:
        return []
    match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    return extract_people_and_nifs(match.group(1))


def extract_escritura_party(text: str, role: str) -> list[tuple[str, str]]:
    patterns = {
        "vendedora": [
            r"(?:COMO|GOME)\s+(?:PARTE\s+)?VENDEDOR(?:A|/A)?[:\s_-]+(.+?)Y[_\s]+COMO\s+(?:PARTE\s+)?COMPRADOR(?:A|/A)?",
            r"(?:COMO|GOME)\s+(?:PARTE\s+)?VENDEDOR(?:A|/A)?[:\s_-]+(.+?)(?:COMO\s+PARTE\s+COMPRADOR(?:A|/A)?|INTERVIENEN|INTERVIENE|EXPONEN)",
        ],
        "compradora": [
            r"Y[_\s]+COMO\s+(?:PARTE\s+)?COMPRADOR(?:A|/A)?[:\s_-]+(.+?)(?:I\s*N\s*T\s*E\s*R\s*V\s*I\s*E\s*N|INTERVIENE|INTERVIENEN|EXPONEN|E\s*X\s*P\s*O\s*N\s*E\s*N)",
            r"COMO\s+(?:PARTE\s+)?COMPRADOR(?:A|/A)?[:\s_-]+(.+?)(?:I\s*N\s*T\s*E\s*R\s*V\s*I\s*E\s*N|INTERVIENE|INTERVIENEN|EXPONEN|E\s*X\s*P\s*O\s*N\s*E\s*N)",
        ],
    }
    pattern_list = patterns.get(role)
    if not pattern_list:
        return []
    for pattern in pattern_list:
        match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        fragment = match.group(1)
        ordered_pairs = extract_party_people_with_ordered_nifs(fragment)
        if ordered_pairs:
            return ordered_pairs
        pairs = extract_people_with_inline_nif(fragment)
        if pairs:
            return pairs
        pairs = extract_people_and_nifs(fragment)
        if pairs:
            return pairs
    compareciente = extract_escritura_compareciente(text, role)
    if compareciente:
        return compareciente
    titled = extract_escritura_title_party(text, role)
    if titled:
        return titled
    return []


def extract_escritura_compareciente(text: str, role: str) -> list[tuple[str, str]]:
    opening = text[:2500]
    role_token = "vendedor" if role == "vendedora" else "comprador"
    pattern = re.compile(
        rf"(?:como|gome)\s+(?:parte\s+)?{role_token}(?:a|/a)?[:\s_-]+"
        r"(?:don|doña|dona|dña\.?)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s*,"
        r".{0,260}?"
        r"(?:D\.?\s*N\.?\s*I\.?|DOCUMENTO\S*\s+NACIONAL\S*\s+DE\s+IDENTIDAD)"
        r".{0,60}?([0-9][0-9.\s-]*[A-Z])",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(opening)
    if not match:
        return []
    return [(normalize_name(match.group(1)), normalize_nif(match.group(2)))]


def extract_escritura_title_party(text: str, role: str) -> list[tuple[str, str]]:
    opening = compact_spaces(text[:600])
    match = re.search(
        r"OTORGADA\s+POR\s+(.+?)\s+A\s+FAVOR\s+DE\s+(.+?)(?:NUMERO|EN\s+MALAGA|EN\s+MÁLAGA)",
        opening,
        re.IGNORECASE,
    )
    if not match:
        return []
    fragment = match.group(1) if role == "vendedora" else match.group(2)
    fragment = fragment.replace('"', " ").replace("“", " ").replace("”", " ")
    names = []
    for part in re.split(r"\s+y\s+|,", fragment, flags=re.IGNORECASE):
        part = normalize_name(re.sub(r"(?i)\bDONA?\b|\bDOÑA\b|\bDÑA\.?\b", "", part))
        if part and not any(token.upper() in NAME_STOPWORDS for token in part.split()):
            names.append(part)
    return [(name, "") for name in first_unique(names)]


def filter_relevant_dates(values: list[str], case_year: int) -> list[str]:
    if not case_year:
        return values
    filtered = []
    for value in values:
        try:
            year = int(value[:4])
        except (TypeError, ValueError):
            continue
        if case_year - 2 <= year <= case_year + 1:
            filtered.append(value)
    return filtered


def extract_represented_sellers(text: str) -> list[tuple[str, str]]:
    matches = []
    explicit_match = re.search(
        r"representaci[oó]n\s+como\s+mandatario\s+verbal\s+de:\s*(.+?)(?:Advierto|Especialmente advierto|2\.-|Y la parte compradora)",
        text or "",
        re.IGNORECASE | re.DOTALL,
    )
    if explicit_match:
        matches.append(explicit_match.group(1))
    for match in re.finditer(
        r"en\s+nombre\s+y\s+representaci[oó]n\s+de\s+(?:su\s+\w+\s+)?"
        r"(?:DON|DOÑA|DONA|D\.\s*|DÑA\.?\s*)\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{3,}?)"
        r"\s*,.{0,220}?"
        r"(?:D\.?\s*N\.?\s*I\.?|DOCUMENTO\S*\s+NACIONAL\S*\s+DE\s+IDENTIDAD)"
        r".{0,40}?([0-9][0-9.\s-]*[A-Z])",
        text or "",
        re.IGNORECASE | re.DOTALL,
    ):
        name = normalize_name(match.group(1))
        nif = normalize_nif(match.group(2))
        if not name or any(token.upper() in NAME_STOPWORDS for token in name.split()):
            continue
        matches.append(f"{name} {nif}".strip())
    pairs: list[tuple[str, str]] = []
    for fragment in matches:
        found = extract_people_with_inline_nif(fragment)
        if not found:
            found = extract_people_and_nifs(fragment)
        if not found and isinstance(fragment, str):
            parts = compact_spaces(fragment).rsplit(" ", 1)
            if len(parts) == 2 and normalize_nif(parts[1]):
                found = [(normalize_name(parts[0]), normalize_nif(parts[1]))]
        pairs.extend(found)
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, nif in pairs:
        key = f"{norm_text(name)}|{nif}"
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, nif))
    return unique


def should_use_dni_names(owner_names: list[str], contract_sellers: list[tuple[str, str]], escritura_sellers: list[tuple[str, str]], represented_sellers: list[tuple[str, str]]) -> bool:
    if owner_names or contract_sellers or escritura_sellers or represented_sellers:
        return False
    return True


def extract_names_after_fdo(text: str) -> list[str]:
    if "fdo" not in norm_text(text):
        return []
    tail = re.split(r"fdo\.\s*", text, maxsplit=1, flags=re.IGNORECASE)
    if len(tail) < 2:
        return []
    raw = tail[1][:600]
    candidates: list[str] = []
    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            continue
        parts = [compact_spaces(part) for part in re.split(r"\s{2,}", line) if compact_spaces(part)]
        if len(parts) > 1:
            candidates.extend(parts)
    if not candidates:
        candidates = re.findall(r"\b[A-ZÁÉÍÓÚÑ]{2,}(?:\s+[A-ZÁÉÍÓÚÑ]{2,}){1,4}\b", raw)
    normalized = []
    for candidate in candidates:
        name = normalize_name(candidate)
        if any(token.upper() in NAME_STOPWORDS for token in name.split()):
            continue
        normalized.append(name)
    return first_unique(normalized)


def extract_reference_catastral(text: str) -> str:
    for match in CADASTRAL_RE.finditer((text or "").upper()):
        value = match.group(0)
        if any(ch.isdigit() for ch in value) and any(ch.isalpha() for ch in value):
            return value
    return ""


def money_candidates(text: str) -> list[float]:
    values: list[float] = []
    for match in MONEY_RE.finditer(text or ""):
        value = parse_money(match.group(1))
        if value is None:
            continue
        if value < 100 or value > 2_000_000:
            continue
        values.append(value)
    return values


def numeric_amount_candidates(text: str) -> list[float]:
    values: list[float] = []
    for match in PLAIN_AMOUNT_RE.finditer(text or ""):
        value = parse_money(match.group(1))
        if value is None or value < 1000 or value > 2_000_000:
            continue
        values.append(value)
    return values


def find_money_near_keywords(text: str, keywords: Iterable[str]) -> float | None:
    if not text:
        return None
    lowered = norm_text(text)
    matches: list[float] = []
    for keyword in keywords:
        keyword_norm = norm_text(keyword)
        start_pos = 0
        while True:
            pos = lowered.find(keyword_norm, start_pos)
            if pos < 0:
                break
            start = max(0, pos - 120)
            end = min(len(text), pos + 420)
            values = money_candidates(text[start:end]) + numeric_amount_candidates(text[start:end])
            matches.extend(value for value in values if value >= 1000)
            start_pos = pos + len(keyword_norm)
    return max(matches) if matches else None


def extract_encargo_price(text: str) -> float | None:
    if not text:
        return None
    value = find_money_near_keywords(
        text,
        (
            "fija el precio",
            "precio del inmueble",
            "precio de venta",
            "precio total",
            "se fija en la cantidad",
            "se fija en",
            "cantidad de",
            "precio",
        ),
    )
    if value is not None:
        return value
    opening = text[:2500]
    candidates = [amount for amount in money_candidates(opening) + numeric_amount_candidates(opening) if amount >= 1000]
    if not candidates:
        return None
    unique = sorted(set(round(amount, 2) for amount in candidates))
    if len(unique) == 1:
        return unique[0]
    if len(unique) <= 4:
        return max(unique)
    return None


def extract_escritura_date(text: str) -> str:
    if not text:
        return ""
    opening = text[:2500]
    patterns = [
        r"En\s+[^\n]{0,160}?,\s+a\s+(.{0,80}?)\s*(?:Ante|COMPARECEN)",
        r"En\s+[^\n]{0,160}?,\s+a\s+(.{0,80}?)\s*\n",
    ]
    for pattern in patterns:
        match = re.search(pattern, opening, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        candidate = compact_spaces(match.group(1)).strip(" .,-")
        parsed = parse_date(candidate)
        if parsed:
            return parsed
    return ""


def extract_escritura_price(text: str) -> float | None:
    if not text:
        return None
    patterns = [
        r"por el precio de.{0,180}",
        r"precio de esta venta es de.{0,220}",
        r"precio(?: total)? de compraventa.{0,180}",
        r"precio convenido.{0,180}",
        r"precio que se fija para la transmision.{0,180}",
        r"precio que se fija para la transmisión.{0,180}",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
            values = [value for value in numeric_amount_candidates(match.group(0)) if value >= 1000]
            if values:
                return max(values)
    return None


def first_or_empty(values: list[str]) -> str:
    return values[0] if values else ""


def split_pipe_values(value: object) -> list[str]:
    return [compact_spaces(chunk) for chunk in str(value or "").split("|") if compact_spaces(chunk)]


def value_at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def pick_document_path(chosen_docs: dict[str, object], doc_type: str) -> str:
    chosen = chosen_docs.get(doc_type)
    if isinstance(chosen, list):
        return compact_spaces(chosen[0]) if chosen else ""
    return compact_spaces(chosen)


def join_document_paths(paths: list[Path], root: Path) -> str:
    return " | ".join(str(path.relative_to(root)) for path in paths if path.exists())


def calculate_percentage_delta(source_price: float | None, sale_price: float | None) -> float | None:
    if source_price is None or sale_price is None or not source_price:
        return None
    return round(((source_price - sale_price) / source_price) * 100.0, 2)


def calculate_days_between(start_date: str, end_date: str) -> int | None:
    if not start_date or not end_date:
        return None
    try:
        return (datetime.fromisoformat(end_date).date() - datetime.fromisoformat(start_date).date()).days
    except ValueError:
        return None


def infer_documental_status(chosen_docs: dict[str, object]) -> str:
    checks = [
        ("nota de encargo", compact_spaces(chosen_docs.get("encargo"))),
        ("propuesta", compact_spaces(chosen_docs.get("propuesta")) or compact_spaces(chosen_docs.get("arras"))),
        ("escritura", compact_spaces(chosen_docs.get("escritura")) or compact_spaces(chosen_docs.get("copia_simple"))),
        ("nota simple", compact_spaces(chosen_docs.get("nota_simple"))),
    ]
    missing = [label for label, value in checks if not value]
    return "Completo" if not missing else f"Falta: {', '.join(missing)}"


def infer_person_type(nif: str) -> str:
    nif_norm = normalize_nif(nif)
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", nif_norm):
        return "Juridica"
    return "Fisica"


def infer_origen_inmueble(*texts: str) -> str:
    merged = norm_text(" ".join(compact_spaces(text) for text in texts if compact_spaces(text)))
    if not merged:
        return ""
    origin_keywords = [
        ("referido", ("referido por", "cliente referido", "viene referido")),
        ("oficina", ("captado en oficina", "vino a oficina", "entrada oficina")),
        ("llamada", ("llamada entrante", "captacion telefonica", "telefono de contacto captacion")),
        ("web", ("idealista", "fotocasa", "captacion web", "portal inmobiliario")),
        ("captacion directa", ("captacion directa", "puerta fria")),
    ]
    for label, keywords in origin_keywords:
        if any(keyword in merged for keyword in keywords):
            return label
    return ""


def pick_richer_text(*values: str) -> str:
    candidates = [(len(compact_spaces(value)), value) for value in values if compact_spaces(value)]
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def extract_case_data(case: CaseEntry, root: Path) -> dict[str, object]:
    grouped = candidate_map(case.files)
    texts: dict[str, str] = {}
    quality_marks: list[str] = []
    chosen_docs: dict[str, str] = {}
    for doc_type, files in grouped.items():
        if not files:
            continue
        selected = files[:4] if doc_type == "dni" else files[:1]
        chunks: list[str] = []
        selected_paths: list[str] = []
        local_marks: list[str] = []
        for chosen in selected:
            text, quality = read_file_text(chosen, doc_type)
            if compact_spaces(text):
                chunks.append(text)
            local_marks.append(quality)
            selected_paths.append(str(chosen.relative_to(root)))
        texts[doc_type] = "\n".join(chunks)
        quality_marks.extend(local_marks)
        chosen_docs[doc_type] = selected_paths[0] if len(selected_paths) == 1 else selected_paths

    contract_buyers = extract_contract_party(texts.get("contrato_privado", ""), "compradora")
    contract_sellers = extract_contract_party(texts.get("contrato_privado", ""), "vendedora")
    arras_people = extract_people_and_nifs(texts.get("arras", ""))
    propuesta_signers = extract_names_after_fdo(texts.get("propuesta", ""))
    escritura_text = texts.get("copia_simple", "") or texts.get("escritura", "")
    escritura_buyers = extract_escritura_party(escritura_text, "compradora")
    escritura_sellers = extract_escritura_party(escritura_text, "vendedora")
    represented_sellers = extract_represented_sellers(escritura_text)

    owner_name_patterns = [
        r"propiedad de\s+d\.?/?d?[ªa]?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,| con| provisto| y\s+de)",
        r"nota de encargo.*?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)\s*,?\s*mayor de edad",
        r"declara recibir de\s+d(?:on|ona)?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,| con dni| mayor de edad)",
    ]
    counterparty_patterns = [
        r"recibir de\s+d(?:on|ona)?\s+([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,| con dni| mayor de edad)",
        r"proponente o comprador.*?([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]+?)(?:,| con domicilio| telefono)",
    ]

    owner_names = []
    owner_names.extend(name for name, _ in contract_sellers)
    if not owner_names:
        owner_names.extend(name for name, _ in escritura_sellers)
        owner_names.extend(name for name, _ in represented_sellers)
    if should_use_dni_names(owner_names, contract_sellers, escritura_sellers, represented_sellers):
        for path in grouped.get("dni", []):
            owner_names.extend(clean_filename_name(path.stem))
        owner_names.extend(extract_name_matches(texts.get("encargo", ""), owner_name_patterns))
    if contract_sellers:
        pass
    elif propuesta_signers:
        owner_names.extend(propuesta_signers[-1:])
    else:
        owner_names.extend(extract_name_matches(texts.get("propuesta", ""), owner_name_patterns))
    owner_names = first_unique(owner_names)

    counterparty_names = [name for name, _ in contract_buyers]
    if not counterparty_names:
        counterparty_names = [name for name, _ in escritura_buyers]
    if not counterparty_names:
        counterparty_names = [name for name, _ in arras_people]
    if not counterparty_names:
        counterparty_names = extract_name_matches(texts.get("propuesta", ""), counterparty_patterns)
    if not counterparty_names:
        counterparty_names = extract_name_matches(texts.get("escritura", ""), counterparty_patterns)
    if not counterparty_names and propuesta_signers:
        counterparty_names = propuesta_signers[:-1] if len(propuesta_signers) > 1 else propuesta_signers

    owner_nifs = [nif for _, nif in contract_sellers if nif]
    if not owner_nifs:
        owner_nifs = [nif for _, nif in escritura_sellers if nif] + [nif for _, nif in represented_sellers if nif]
    if not owner_nifs:
        owner_nifs = extract_nifs(texts.get("encargo", "")) or extract_nifs(texts.get("propuesta", ""))
    counterparty_nifs = (
        [nif for _, nif in contract_buyers if nif]
        or [nif for _, nif in escritura_buyers if nif]
        or [nif for _, nif in arras_people if nif]
        or extract_nifs(texts.get("propuesta", ""))
    )
    owner_nifs = align_nifs_with_names(
        owner_names,
        owner_nifs,
        [
            texts.get("contrato_privado", ""),
            texts.get("encargo", ""),
            texts.get("dni", ""),
            escritura_text,
            texts.get("nota_simple", ""),
        ],
    )
    counterparty_nifs = align_nifs_with_names(
        counterparty_names,
        counterparty_nifs,
        [
            texts.get("contrato_privado", ""),
            texts.get("arras", ""),
            texts.get("propuesta", ""),
            texts.get("dni", ""),
            escritura_text,
        ],
    )

    owner_emails = extract_emails(texts.get("encargo", "")) + extract_emails(texts.get("contrato_privado", ""))
    owner_phones = extract_phones(texts.get("encargo", "")) + extract_phones(texts.get("contrato_privado", ""))
    counterparty_emails = extract_emails(texts.get("propuesta", "")) + extract_emails(texts.get("contrato_privado", ""))
    counterparty_phones = extract_phones(texts.get("propuesta", "")) + extract_phones(texts.get("contrato_privado", "")) + extract_phones(texts.get("arras", ""))
    owner_emails = first_unique(owner_emails)
    owner_phones = first_unique(owner_phones)
    counterparty_emails = first_unique(counterparty_emails)
    counterparty_phones = first_unique(counterparty_phones)

    encargo_dates = filter_relevant_dates(extract_dates(texts.get("encargo", "")), case.year)
    propuesta_dates = filter_relevant_dates(extract_dates(texts.get("propuesta", "")), case.year)
    arras_dates = filter_relevant_dates(extract_dates(texts.get("arras", "")), case.year)
    contrato_dates = filter_relevant_dates(extract_dates(texts.get("contrato_privado", "")), case.year)
    escritura_date = extract_escritura_date(escritura_text)
    escritura_dates = filter_relevant_dates([escritura_date] if escritura_date else [], case.year)

    reference_catastral = (
        extract_reference_catastral(texts.get("contrato_privado", ""))
        or extract_reference_catastral(texts.get("copia_simple", ""))
        or extract_reference_catastral(texts.get("catastro", ""))
        or extract_reference_catastral(texts.get("nota_simple", ""))
        or extract_reference_catastral(texts.get("propuesta", ""))
        or extract_reference_catastral(texts.get("encargo", ""))
    )

    price_encargo = extract_encargo_price(texts.get("encargo", ""))
    price_propuesta = find_money_near_keywords(
        texts.get("propuesta", ""),
        ("precio propuesto", "precio propuesto para la compra", "precio queda fijado"),
    )
    if price_propuesta is None and not texts.get("contrato_privado", ""):
        price_propuesta = find_money_near_keywords(
            texts.get("arras", ""),
            ("propuesta de compraventa", "reserva", "arras"),
        )
    price_contrato = find_money_near_keywords(
        texts.get("contrato_privado", ""),
        ("precio que se fija para la transmision", "precio que se fija para la transmisión", "precio para la transmisión"),
    )
    price_escritura = extract_escritura_price(escritura_text)
    honorarios = (
        find_money_near_keywords(texts.get("encargo", ""), ("honorarios", "comision", "intermediacion"))
        or find_money_near_keywords(texts.get("contrato_privado", ""), ("honorarios", "comision", "intermediacion"))
        or find_money_near_keywords(texts.get("propuesta", ""), ("honorarios", "comision", "intermediacion"))
    )
    sale_price = price_propuesta if price_propuesta is not None else price_contrato if price_contrato is not None else price_escritura
    desviacion_euros = round(price_encargo - sale_price, 2) if price_encargo is not None and sale_price is not None else None
    desviacion_pct = calculate_percentage_delta(price_encargo, sale_price)
    fecha_encargo = first_or_empty(encargo_dates[:1])
    fecha_escritura = first_or_empty(escritura_dates[:1])
    fecha_operacion = fecha_escritura or first_or_empty(contrato_dates[:1]) or first_or_empty(propuesta_dates[:1]) or first_or_empty(arras_dates[:1])
    dias_hasta_venta = calculate_days_between(fecha_encargo, fecha_operacion)
    num_visitas = len(grouped.get("parte_visita", []))
    estado_documental = infer_documental_status(chosen_docs)
    origen_inmueble = infer_origen_inmueble(texts.get("encargo", ""), texts.get("propuesta", ""), texts.get("contrato_privado", ""))
    doc_nota_encargo_path = pick_document_path(chosen_docs, "encargo")
    doc_propuesta_path = pick_document_path(chosen_docs, "propuesta") or pick_document_path(chosen_docs, "arras")
    doc_escritura_path = pick_document_path(chosen_docs, "copia_simple") or pick_document_path(chosen_docs, "escritura")
    doc_nota_simple_path = pick_document_path(chosen_docs, "nota_simple")
    doc_partes_visita_paths = join_document_paths(grouped.get("parte_visita", []), root)

    quality = "mixed"
    if quality_marks and all(mark == "text" for mark in quality_marks):
        quality = "text"
    elif quality_marks and all(mark in {"ocr", "empty"} for mark in quality_marks):
        quality = "ocr"

    return {
        "tipo_operacion": "venta",
        "estado": "Importado historico",
        "origen": "inmuebles_vendidos",
        "origen_inmueble": origen_inmueble,
        "expediente_path": str(case.case_path.relative_to(root)),
        "expediente_hash": hashlib.md5(str(case.case_path.relative_to(root)).encode("utf-8")).hexdigest(),
        "anio": case.year,
        "mes": case.month,
        "direccion": case.label,
        "referencia_catastral": reference_catastral,
        "propietario1_nombre": first_or_empty(owner_names[:1]),
        "propietario1_nif": first_or_empty(owner_nifs[:1]),
        "propietario1_telefono": first_or_empty(owner_phones[:1]),
        "propietario1_email": first_or_empty(owner_emails[:1]),
        "propietario1_fecha_nacimiento": "",
        "propietario2_nombre": first_or_empty(owner_names[1:2]),
        "propietario2_nif": first_or_empty(owner_nifs[1:2]),
        "propietario2_telefono": first_or_empty(owner_phones[1:2]),
        "propietario2_email": first_or_empty(owner_emails[1:2]),
        "propietario2_fecha_nacimiento": "",
        "contraparte_nombre": " | ".join(counterparty_names),
        "contraparte_nif": " | ".join(counterparty_nifs),
        "contraparte_telefono": " | ".join(counterparty_phones),
        "contraparte_email": " | ".join(counterparty_emails),
        "contraparte_fecha_nacimiento": "",
        "fecha_encargo": fecha_encargo,
        "fecha_propuesta": first_or_empty(propuesta_dates[:1]) or ("" if texts.get("contrato_privado", "") else first_or_empty(arras_dates[:1])),
        "fecha_contrato": first_or_empty(contrato_dates[:1]),
        "fecha_escritura": fecha_escritura,
        "fecha_operacion": fecha_operacion,
        "precio_encargo": price_encargo,
        "precio_propuesta": price_propuesta,
        "precio_contrato": price_contrato,
        "precio_escritura": price_escritura,
        "precio_renta": None,
        "desviacion_euros": desviacion_euros,
        "desviacion_pct": desviacion_pct,
        "dias_hasta_venta": dias_hasta_venta,
        "num_visitas": num_visitas,
        "honorarios": honorarios,
        "agente": "",
        "responsable_gestion": "",
        "oficina": "",
        "doc_nota_encargo_path": doc_nota_encargo_path,
        "doc_propuesta_path": doc_propuesta_path,
        "doc_escritura_path": doc_escritura_path,
        "doc_nota_simple_path": doc_nota_simple_path,
        "doc_partes_visita_paths": doc_partes_visita_paths,
        "estado_documental": estado_documental,
        "calidad_ocr": quality,
        "notas": "",
        "datos_extraidos_json": json.dumps(
            {
                "documentos": chosen_docs,
                "estado_documental": estado_documental,
                "num_visitas": num_visitas,
                "owner_names_detected": owner_names,
                "counterparty_names_detected": counterparty_names,
                "owner_nifs_detected": owner_nifs,
                "counterparty_nifs_detected": counterparty_nifs,
                "owner_phones_detected": owner_phones,
                "counterparty_phones_detected": counterparty_phones,
                "owner_emails_detected": owner_emails,
                "counterparty_emails_detected": counterparty_emails,
                "fechas_detectadas": {
                    "encargo": encargo_dates,
                    "propuesta": propuesta_dates,
                    "escritura": escritura_dates,
                },
                "precios_detectados": {
                    "encargo": price_encargo,
                    "propuesta": price_propuesta,
                    "contrato": price_contrato,
                    "escritura": price_escritura,
                },
                "metricas": {
                    "desviacion_euros": desviacion_euros,
                    "desviacion_pct": desviacion_pct,
                    "dias_hasta_venta": dias_hasta_venta,
                    "honorarios": honorarios,
                },
            },
            ensure_ascii=False,
        ),
    }


def ensure_schema(conn: sqlite3.Connection, repo_root: Path) -> None:
    apply_schema_file(conn, repo_root / "schema.sql")
    ensure_column(conn, "inmuebles", "referencia_catastral", "referencia_catastral TEXT")
    for column_name, column_sql in {
        "origen_inmueble": "origen_inmueble TEXT",
        "contraparte1_id": "contraparte1_id TEXT",
        "contraparte2_id": "contraparte2_id TEXT",
        "desviacion_euros": "desviacion_euros REAL",
        "desviacion_pct": "desviacion_pct REAL",
        "dias_hasta_venta": "dias_hasta_venta INTEGER",
        "num_visitas": "num_visitas INTEGER",
        "honorarios": "honorarios REAL",
        "responsable_gestion": "responsable_gestion TEXT",
        "doc_nota_encargo_path": "doc_nota_encargo_path TEXT",
        "doc_propuesta_path": "doc_propuesta_path TEXT",
        "doc_escritura_path": "doc_escritura_path TEXT",
        "doc_nota_simple_path": "doc_nota_simple_path TEXT",
        "doc_partes_visita_paths": "doc_partes_visita_paths TEXT",
        "estado_documental": "estado_documental TEXT",
    }.items():
        ensure_column(conn, "operaciones_inmobiliarias", column_name, column_sql)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS operaciones_inmobiliarias (
          id TEXT PRIMARY KEY,
          empresa_id TEXT NOT NULL,
          tipo_operacion TEXT NOT NULL,
          estado TEXT,
          origen TEXT,
          origen_inmueble TEXT,
          expediente_path TEXT,
          expediente_hash TEXT UNIQUE,
          anio INTEGER,
          mes TEXT,
          inmueble_id TEXT,
          direccion TEXT,
          referencia_catastral TEXT,
          propietario1_id TEXT,
          propietario1_nombre TEXT,
          propietario1_nif TEXT,
          propietario1_telefono TEXT,
          propietario1_email TEXT,
          propietario1_fecha_nacimiento TEXT,
          propietario2_id TEXT,
          propietario2_nombre TEXT,
          propietario2_nif TEXT,
          propietario2_telefono TEXT,
          propietario2_email TEXT,
          propietario2_fecha_nacimiento TEXT,
          contraparte1_id TEXT,
          contraparte2_id TEXT,
          contraparte_nombre TEXT,
          contraparte_nif TEXT,
          contraparte_telefono TEXT,
          contraparte_email TEXT,
          contraparte_fecha_nacimiento TEXT,
          fecha_encargo TEXT,
          fecha_propuesta TEXT,
          fecha_contrato TEXT,
          fecha_escritura TEXT,
          fecha_operacion TEXT,
          precio_encargo REAL,
          precio_propuesta REAL,
          precio_contrato REAL,
          precio_escritura REAL,
          precio_renta REAL,
          desviacion_euros REAL,
          desviacion_pct REAL,
          dias_hasta_venta INTEGER,
          num_visitas INTEGER,
          honorarios REAL,
          agente TEXT,
          responsable_gestion TEXT,
          oficina TEXT,
          doc_nota_encargo_path TEXT,
          doc_propuesta_path TEXT,
          doc_escritura_path TEXT,
          doc_nota_simple_path TEXT,
          doc_partes_visita_paths TEXT,
          estado_documental TEXT,
          calidad_ocr TEXT,
          notas TEXT,
          datos_extraidos_json TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def ensure_company(conn: sqlite3.Connection, company_name: str) -> sqlite3.Row:
    row = conn.execute("SELECT id, nombre FROM empresas WHERE nombre = ?", (company_name,)).fetchone()
    if not row:
        raise RuntimeError(f"No existe la empresa '{company_name}' en la base.")
    return row


def find_cliente(conn: sqlite3.Connection, nif: str, name: str) -> sqlite3.Row | None:
    if nif:
        row = conn.execute(
            "SELECT * FROM clientes WHERE UPPER(COALESCE(nif, '')) = UPPER(?) ORDER BY created_at DESC LIMIT 1",
            (nif,),
        ).fetchone()
        if row:
            return row
    if name:
        row = conn.execute(
            "SELECT * FROM clientes WHERE UPPER(COALESCE(nombre, '')) = UPPER(?) ORDER BY created_at DESC LIMIT 1",
            (name,),
        ).fetchone()
        if row:
            return row
    return None


def ensure_cliente_empresa(
    conn: sqlite3.Connection,
    cliente_id: str,
    empresa_id: str,
    now: str,
    servicio: str = "inmobiliaria",
    estado: str = "Activo",
) -> None:
    row = conn.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND LOWER(servicio) = LOWER(?)
        """,
        (cliente_id, empresa_id, servicio),
    ).fetchone()
    if row:
        return
    conn.execute(
        """
        INSERT INTO clientes_empresas (
          id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, cliente_id, empresa_id, servicio, estado, now, None, now, now),
    )


def upsert_cliente(conn: sqlite3.Connection, empresa_id: str, payload: dict[str, str], now: str) -> str | None:
    name = normalize_name(payload.get("nombre"))
    nif = normalize_nif(payload.get("nif"))
    if not name and not nif:
        return None
    existing = find_cliente(conn, nif, name)
    if existing:
        updates: dict[str, object] = {}
        if name and not compact_spaces(existing["nombre"]):
            updates["nombre"] = name
        if nif and not compact_spaces(existing["nif"]):
            updates["nif"] = nif
        for field in ("telefono", "email", "fecha_nacimiento", "direccion"):
            incoming = compact_spaces(payload.get(field))
            if incoming and not compact_spaces(existing[field]):
                updates[field] = incoming
        if updates:
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE clientes SET {set_clause}, updated_at = ? WHERE id = ?",
                (*updates.values(), now, existing["id"]),
            )
        ensure_cliente_empresa(conn, existing["id"], empresa_id, now, servicio="inmobiliaria", estado="Activo")
        return existing["id"]

    cliente_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO clientes (
          id, empresa_id, nombre, tipo_persona, nif, telefono, email, fecha_nacimiento,
          direccion, estado, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cliente_id,
            empresa_id,
            name or nif or "Cliente importado",
            infer_person_type(nif),
            nif,
            compact_spaces(payload.get("telefono")),
            compact_spaces(payload.get("email")).lower(),
            compact_spaces(payload.get("fecha_nacimiento")),
            compact_spaces(payload.get("direccion")),
            "Inactivo",
            now,
            now,
        ),
    )
    ensure_cliente_empresa(conn, cliente_id, empresa_id, now, servicio="inmobiliaria", estado="Activo")
    return cliente_id


def find_inmueble(conn: sqlite3.Connection, empresa_id: str, direccion: str, referencia_catastral: str) -> sqlite3.Row | None:
    if referencia_catastral:
        row = conn.execute(
            """
            SELECT *
            FROM inmuebles
            WHERE empresa_id = ? AND UPPER(COALESCE(referencia_catastral, '')) = UPPER(?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (empresa_id, referencia_catastral),
        ).fetchone()
        if row:
            return row
    if direccion:
        row = conn.execute(
            """
            SELECT *
            FROM inmuebles
            WHERE empresa_id = ? AND UPPER(COALESCE(direccion, '')) = UPPER(?)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (empresa_id, direccion),
        ).fetchone()
        if row:
            return row
    return None


def upsert_inmueble(conn: sqlite3.Connection, empresa_id: str, record: dict[str, object], now: str) -> str:
    direccion = compact_spaces(record.get("direccion"))
    referencia_catastral = compact_spaces(record.get("referencia_catastral"))
    existing = find_inmueble(conn, empresa_id, direccion, referencia_catastral)
    if existing:
        updates: dict[str, object] = {}
        if referencia_catastral and not compact_spaces(existing["referencia_catastral"]):
            updates["referencia_catastral"] = referencia_catastral
        if record.get("precio_encargo") and not existing["precio_objetivo"]:
            updates["precio_objetivo"] = record.get("precio_encargo")
        if updates:
            set_clause = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"UPDATE inmuebles SET {set_clause}, updated_at = ? WHERE id = ?",
                (*updates.values(), now, existing["id"]),
            )
        return str(existing["id"])

    inmueble_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO inmuebles (
          id, empresa_id, referencia, direccion, referencia_catastral, tipo_inmueble,
          precio_objetivo, estado, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inmueble_id,
            empresa_id,
            slug(direccion) or slug(record.get("expediente_path")),
            direccion,
            referencia_catastral,
            "",
            record.get("precio_encargo"),
            "Historico vendido",
            now,
            now,
        ),
    )
    return inmueble_id


def ensure_propietario_link(conn: sqlite3.Connection, inmueble_id: str, cliente_id: str, now: str) -> None:
    if not cliente_id:
        return
    row = conn.execute(
        "SELECT id FROM inmueble_propietarios WHERE inmueble_id = ? AND cliente_id = ?",
        (inmueble_id, cliente_id),
    ).fetchone()
    if row:
        return
    conn.execute(
        """
        INSERT INTO inmueble_propietarios (id, inmueble_id, cliente_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, inmueble_id, cliente_id, now, now),
    )


def sync_propietario_links(conn: sqlite3.Connection, inmueble_id: str, cliente_ids: list[str], now: str) -> None:
    normalized = [cliente_id for cliente_id in cliente_ids if cliente_id]
    existing = [
        row["cliente_id"]
        for row in conn.execute(
            "SELECT cliente_id FROM inmueble_propietarios WHERE inmueble_id = ?",
            (inmueble_id,),
        ).fetchall()
    ]
    keep = set(normalized)
    for cliente_id in existing:
        if cliente_id not in keep:
            conn.execute(
                "DELETE FROM inmueble_propietarios WHERE inmueble_id = ? AND cliente_id = ?",
                (inmueble_id, cliente_id),
            )
    for cliente_id in normalized:
        ensure_propietario_link(conn, inmueble_id, cliente_id, now)


def upsert_operacion(
    conn: sqlite3.Connection,
    empresa_id: str,
    record: dict[str, object],
    inmueble_id: str,
    propietario1_id: str | None,
    propietario2_id: str | None,
    contraparte1_id: str | None,
    contraparte2_id: str | None,
    now: str,
) -> str:
    existing = conn.execute(
        "SELECT id FROM operaciones_inmobiliarias WHERE expediente_hash = ?",
        (record["expediente_hash"],),
    ).fetchone()
    payload = {
        **record,
        "empresa_id": empresa_id,
        "inmueble_id": inmueble_id,
        "propietario1_id": propietario1_id,
        "propietario2_id": propietario2_id,
        "contraparte1_id": contraparte1_id,
        "contraparte2_id": contraparte2_id,
    }
    columns = [
        "empresa_id",
        "tipo_operacion",
        "estado",
        "origen",
        "origen_inmueble",
        "expediente_path",
        "expediente_hash",
        "anio",
        "mes",
        "inmueble_id",
        "direccion",
        "referencia_catastral",
        "propietario1_id",
        "propietario1_nombre",
        "propietario1_nif",
        "propietario1_telefono",
        "propietario1_email",
        "propietario1_fecha_nacimiento",
        "propietario2_id",
        "propietario2_nombre",
        "propietario2_nif",
        "propietario2_telefono",
        "propietario2_email",
        "propietario2_fecha_nacimiento",
        "contraparte1_id",
        "contraparte2_id",
        "contraparte_nombre",
        "contraparte_nif",
        "contraparte_telefono",
        "contraparte_email",
        "contraparte_fecha_nacimiento",
        "fecha_encargo",
        "fecha_propuesta",
        "fecha_contrato",
        "fecha_escritura",
        "fecha_operacion",
        "precio_encargo",
        "precio_propuesta",
        "precio_contrato",
        "precio_escritura",
        "precio_renta",
        "desviacion_euros",
        "desviacion_pct",
        "dias_hasta_venta",
        "num_visitas",
        "honorarios",
        "agente",
        "responsable_gestion",
        "oficina",
        "doc_nota_encargo_path",
        "doc_propuesta_path",
        "doc_escritura_path",
        "doc_nota_simple_path",
        "doc_partes_visita_paths",
        "estado_documental",
        "calidad_ocr",
        "notas",
        "datos_extraidos_json",
    ]
    values = [payload.get(column) for column in columns]
    if existing:
        set_clause = ", ".join(f"{column} = ?" for column in columns if column != "expediente_hash")
        update_values = [payload.get(column) for column in columns if column != "expediente_hash"]
        conn.execute(
            f"UPDATE operaciones_inmobiliarias SET {set_clause}, updated_at = ? WHERE id = ?",
            (*update_values, now, existing["id"]),
        )
        return str(existing["id"])

    op_id = uuid.uuid4().hex
    placeholders = ", ".join(["?"] * (len(columns) + 3))
    conn.execute(
        f"""
        INSERT INTO operaciones_inmobiliarias (
          id, {", ".join(columns)}, created_at, updated_at
        ) VALUES ({placeholders})
        """,
        (op_id, *values, now, now),
    )
    return op_id


def import_case(conn: sqlite3.Connection, empresa_id: str, case: CaseEntry, root: Path, now: str) -> dict[str, object]:
    record = extract_case_data(case, root)
    propietario1_id = upsert_cliente(
        conn,
        empresa_id,
        {
            "nombre": str(record.get("propietario1_nombre") or ""),
            "nif": str(record.get("propietario1_nif") or ""),
            "telefono": str(record.get("propietario1_telefono") or ""),
            "email": str(record.get("propietario1_email") or ""),
            "fecha_nacimiento": str(record.get("propietario1_fecha_nacimiento") or ""),
            "direccion": "",
        },
        now,
    )
    propietario2_id = upsert_cliente(
        conn,
        empresa_id,
        {
            "nombre": str(record.get("propietario2_nombre") or ""),
            "nif": str(record.get("propietario2_nif") or ""),
            "telefono": str(record.get("propietario2_telefono") or ""),
            "email": str(record.get("propietario2_email") or ""),
            "fecha_nacimiento": str(record.get("propietario2_fecha_nacimiento") or ""),
            "direccion": "",
        },
        now,
    )
    contraparte_names = split_pipe_values(record.get("contraparte_nombre"))
    contraparte_nifs = split_pipe_values(record.get("contraparte_nif"))
    contraparte_phones = split_pipe_values(record.get("contraparte_telefono"))
    contraparte_emails = split_pipe_values(record.get("contraparte_email"))
    contraparte_birth_dates = split_pipe_values(record.get("contraparte_fecha_nacimiento"))
    contraparte1_id = upsert_cliente(
        conn,
        empresa_id,
        {
            "nombre": value_at(contraparte_names, 0),
            "nif": value_at(contraparte_nifs, 0),
            "telefono": value_at(contraparte_phones, 0),
            "email": value_at(contraparte_emails, 0),
            "fecha_nacimiento": value_at(contraparte_birth_dates, 0),
            "direccion": "",
        },
        now,
    )
    contraparte2_id = upsert_cliente(
        conn,
        empresa_id,
        {
            "nombre": value_at(contraparte_names, 1),
            "nif": value_at(contraparte_nifs, 1),
            "telefono": value_at(contraparte_phones, 1),
            "email": value_at(contraparte_emails, 1),
            "fecha_nacimiento": value_at(contraparte_birth_dates, 1),
            "direccion": "",
        },
        now,
    )
    inmueble_id = upsert_inmueble(conn, empresa_id, record, now)
    sync_propietario_links(conn, inmueble_id, [propietario1_id or "", propietario2_id or ""], now)
    operacion_id = upsert_operacion(
        conn,
        empresa_id,
        record,
        inmueble_id,
        propietario1_id,
        propietario2_id,
        contraparte1_id,
        contraparte2_id,
        now,
    )
    return {
        "operacion_id": operacion_id,
        "inmueble_id": inmueble_id,
        "propietario1_id": propietario1_id,
        "propietario2_id": propietario2_id,
        "contraparte1_id": contraparte1_id,
        "contraparte2_id": contraparte2_id,
        "direccion": record.get("direccion"),
        "propietario1_nombre": record.get("propietario1_nombre"),
        "contraparte_nombre": record.get("contraparte_nombre"),
        "precio_encargo": record.get("precio_encargo"),
        "precio_propuesta": record.get("precio_propuesta"),
        "precio_escritura": record.get("precio_escritura"),
        "estado_documental": record.get("estado_documental"),
        "num_visitas": record.get("num_visitas"),
        "calidad_ocr": record.get("calidad_ocr"),
        "expediente_path": record.get("expediente_path"),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Importa expedientes historicos de inmuebles vendidos al CRM.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Ruta raiz de INMUEBLES VENDIDOS.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Ruta de la base sqlite del CRM.")
    parser.add_argument("--company", default=DEFAULT_COMPANY, help="Empresa destino en el CRM.")
    parser.add_argument("--default-year", type=int, default=0, help="Año por defecto si la carpeta no viene organizada por años.")
    parser.add_argument("--default-month", default="", help="Mes por defecto si la carpeta no viene organizada por años.")
    parser.add_argument("--year-from", type=int, default=0, help="Procesa solo expedientes desde este año inclusive.")
    parser.add_argument("--year-to", type=int, default=0, help="Procesa solo expedientes hasta este año inclusive.")
    parser.add_argument("--limit", type=int, default=0, help="Limita el numero de expedientes procesados.")
    parser.add_argument("--filter", default="", help="Procesa solo expedientes cuya ruta contenga este texto.")
    parser.add_argument("--apply", action="store_true", help="Aplica cambios en la base. Sin esto, solo simula.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    root = args.root.resolve()
    db_path = (REPO_ROOT / args.db).resolve() if not args.db.is_absolute() else args.db.resolve()
    if not root.exists():
        raise SystemExit(f"No existe la ruta {root}")
    if not db_path.exists():
        raise SystemExit(f"No existe la base {db_path}")

    cases = gather_cases(root, default_year=args.default_year, default_month=args.default_month)
    if args.year_from:
        cases = [case for case in cases if case.year >= args.year_from]
    if args.year_to:
        cases = [case for case in cases if case.year <= args.year_to]
    if args.filter:
        needle = norm_text(args.filter)
        cases = [case for case in cases if needle in norm_text(str(case.case_path.relative_to(root)))]
    if args.limit > 0:
        cases = cases[: args.limit]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_schema(conn, REPO_ROOT)
    company = ensure_company(conn, args.company)
    now = datetime.now(timezone.utc).isoformat()

    imported: list[dict[str, object]] = []
    try:
        for case in cases:
            imported.append(import_case(conn, company["id"], case, root, now))
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    finally:
        conn.close()

    summary = {
        "root": str(root),
        "db": str(db_path),
        "company": args.company,
        "apply": args.apply,
        "processed": len(imported),
        "with_owner": sum(1 for row in imported if compact_spaces(row.get("propietario1_nombre"))),
        "with_counterparty": sum(1 for row in imported if compact_spaces(row.get("contraparte_nombre"))),
        "with_encargo_price": sum(1 for row in imported if row.get("precio_encargo") is not None),
        "with_propuesta_price": sum(1 for row in imported if row.get("precio_propuesta") is not None),
        "with_escritura_price": sum(1 for row in imported if row.get("precio_escritura") is not None),
        "with_documentacion_completa": sum(1 for row in imported if row.get("estado_documental") == "Completo"),
        "total_visitas_detectadas": sum(int(row.get("num_visitas") or 0) for row in imported),
        "ocr_quality": {
            "text": sum(1 for row in imported if row.get("calidad_ocr") == "text"),
            "ocr": sum(1 for row in imported if row.get("calidad_ocr") == "ocr"),
            "mixed": sum(1 for row in imported if row.get("calidad_ocr") == "mixed"),
        },
        "sample": imported[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
