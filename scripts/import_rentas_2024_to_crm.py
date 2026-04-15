#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import shutil
import sys
import tempfile
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


GESTORIA_COMPANY = "Fincas Velazquez"
RENTA_SERVICE = "gestoria"
RENTA_ACTIVITY_TYPE = "Declaración en periodo"
DEFAULT_EJERCICIO = str(datetime.now(timezone.utc).year - 1)
DEFAULT_SOURCE_DIR_BASE = (
    Path.home()
    / "Library"
    / "Mobile Documents"
    / "com~apple~CloudDocs"
    / "MIGUE TRABAJO"
)


def guess_default_source_dir(ejercicio: str) -> str:
    base = DEFAULT_SOURCE_DIR_BASE
    preferred = base / f"RENTAS {ejercicio}"
    if preferred.exists():
        return str(preferred)
    candidates: list[tuple[int, Path]] = []
    if base.exists():
        for path in base.glob("RENTAS 20[0-9][0-9]"):
            normalized_name = re.sub(r"\s+", " ", str(path.name or "").strip())
            match = re.fullmatch(r"RENTAS\s+(20[0-9]{2})", normalized_name, re.IGNORECASE)
            if not match:
                continue
            try:
                year = int(match.group(1))
            except ValueError:
                continue
            if path.exists():
                candidates.append((year, path))
    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        return str(candidates[0][1])
    return str(preferred)


DEFAULT_SOURCE_DIR = guess_default_source_dir(DEFAULT_EJERCICIO)
PDFTOTEXT_TIMEOUT_SECONDS = 20
TESSERACT_TIMEOUT_SECONDS = 45
PDFTOPPM_TIMEOUT_SECONDS = 45
RENTA_USE_OCRMYPDF = str(os.environ.get("RENTA_USE_OCRMYPDF", "") or "").strip().lower() in {"1", "true", "yes", "si", "sí"}
RENTA_OCR_HEAD_PAGES = max(1, int(os.environ.get("RENTA_OCR_HEAD_PAGES", "2") or 2))
RENTA_OCR_TAIL_PAGES = max(0, int(os.environ.get("RENTA_OCR_TAIL_PAGES", "2") or 2))
RENTA_OCR_DPI = max(120, int(os.environ.get("RENTA_OCR_DPI", "300") or 300))
RENTA_OCR_RESCUE_DPI = max(RENTA_OCR_DPI, int(os.environ.get("RENTA_OCR_RESCUE_DPI", "400") or 400))
RENTA_OCR_PSMS_RAW = os.environ.get("RENTA_OCR_PSMS", "6,11,4")
CRITICAL_FIELDS = (
    "cliente_nombre",
    "cliente_nif",
    "cliente_fecha_nacimiento",
    "ingresos_principales_total",
    "resultado_declaracion",
)
RENTA_MAX_REASONABLE_AMOUNT = 1_000_000.0
RENTA_OUTLIER_RATIO = 50.0
RENTA_MAJOR_AMOUNT_FLOOR = 1000.0


def norm_text(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm_text(value)).strip("_")


def compact_spaces(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_int_tuple(raw: str, default: tuple[int, ...]) -> tuple[int, ...]:
    cleaned = compact_spaces(raw).replace(" ", "")
    if not cleaned:
        return default
    items: list[int] = []
    for chunk in cleaned.split(","):
        if not chunk:
            continue
        try:
            value = int(chunk)
        except ValueError:
            continue
        if value not in items:
            items.append(value)
    return tuple(items) if items else default


RENTA_OCR_PSMS = parse_int_tuple(RENTA_OCR_PSMS_RAW, (6, 11, 4))


def command_exists(name: str) -> bool:
    cmd = shutil.which(name)
    return bool(cmd and os.path.exists(cmd))

def pdf_page_count(pdf_path: Path) -> int:
    cmd = shutil.which("pdfinfo") or "/opt/homebrew/bin/pdfinfo" or "/usr/local/bin/pdfinfo"
    if not cmd or not os.path.exists(cmd):
        return 0
    try:
        proc = subprocess.run(
            [cmd, str(pdf_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=8,
        )
    except Exception:
        return 0
    if proc.returncode != 0:
        return 0
    match = re.search(r"^Pages:\s+(\d+)\s*$", proc.stdout or "", re.MULTILINE)
    if not match:
        return 0
    try:
        return max(0, int(match.group(1)))
    except ValueError:
        return 0


def score_renta_ocr_text(text: str) -> int:
    normalized = norm_text(text)
    if not normalized:
        return 0
    score = min(len(normalized), 2600) // 13
    for token, weight in (
        ("agencia tributaria", 30),
        ("modelo 100", 60),
        ("impuesto sobre la renta", 55),
        ("resultado de la declaracion", 35),
        ("codigo seguro de verificacion", 25),
        ("expediente", 18),
        ("nif", 14),
        ("declarante", 10),
        ("euros", 8),
    ):
        if token in normalized:
            score += weight
    if re.search(r"\b[0-9]{2}/[0-9]{2}/[0-9]{4}\b", text):
        score += 12
    if re.search(r"\b[0-9]{8}[A-Z]\b", text):
        score += 12
    if re.search(r"(?<![0-9])[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}(?![0-9])", text):
        score += 14
    return score


def tesseract_stdout(image_path: Path, timeout_seconds: int = 20, psm: int = 6) -> tuple[str, str]:
    cmd = shutil.which("tesseract") or "/opt/homebrew/bin/tesseract" or "/usr/local/bin/tesseract"
    if not cmd or not os.path.exists(cmd):
        return "", "tesseract no encontrado"
    try:
        result = subprocess.run(
            [cmd, str(image_path), "stdout", "-l", "spa+eng", "--oem", "1", "--psm", str(psm), "-c", "preserve_interword_spaces=1"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
        return result.stdout or "", ""
    except subprocess.TimeoutExpired:
        return "", "tesseract timeout"
    except subprocess.CalledProcessError as exc:
        return "", (exc.stderr or "").strip()


def best_tesseract_text(image_path: Path, timeout_seconds: int = 20, psms: tuple[int, ...] = (6, 11, 4)) -> tuple[str, str]:
    best_text = ""
    best_err = ""
    best_score = -1
    for psm in psms:
        text, err = tesseract_stdout(image_path, timeout_seconds=timeout_seconds, psm=psm)
        score = score_renta_ocr_text(text)
        if score > best_score:
            best_text, best_err, best_score = text, err, score
        if best_score >= 170:
            break
    return best_text, best_err


def sips_transform(src: Path, out: Path, rotate: int | None = None, max_size: int | None = None) -> bool:
    if not os.path.exists("/usr/bin/sips"):
        return False
    cmd = ["/usr/bin/sips"]
    if rotate is not None:
        cmd.extend(["-r", str(rotate)])
    if max_size is not None:
        cmd.extend(["-Z", str(max_size)])
    cmd.extend([str(src), "--out", str(out)])
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
        return out.exists()
    except Exception:
        return False


def clean_ocr_text_value(value: object) -> str:
    text = compact_spaces(value)
    if not text:
        return ""
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"[|]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return compact_spaces(text)


def normalize_nif_candidate(value: object) -> str:
    text = compact_spaces(value).upper().replace(" ", "").replace(".", "").replace("-", "")
    return text


def looks_like_nif(value: object) -> bool:
    text = normalize_nif_candidate(value)
    if not re.fullmatch(r"[A-Z0-9]{8,10}", text):
        return False
    if not any(ch.isdigit() for ch in text):
        return False
    if text in {"DECLARANTE", "CONYUGE"}:
        return False
    return True


def parse_money(raw: object) -> float | None:
    text = compact_spaces(raw)
    if not text:
        return None
    text = text.replace("€", "").replace("%", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def is_reasonable_renta_amount(value: object, allow_zero: bool = True) -> bool:
    number = parse_money(value) if not isinstance(value, (int, float)) else round(float(value), 2)
    if number is None:
        return False
    if allow_zero and abs(number) < 0.0001:
        return True
    return abs(number) <= RENTA_MAX_REASONABLE_AMOUNT


def is_renta_amount_outlier(value: object, reference: object) -> bool:
    candidate = parse_money(value) if not isinstance(value, (int, float)) else round(float(value), 2)
    ref = parse_money(reference) if not isinstance(reference, (int, float)) else round(float(reference), 2)
    if candidate is None or ref is None:
        return False
    if abs(candidate) < 0.0001 or abs(ref) < RENTA_MAJOR_AMOUNT_FLOOR:
        return False
    ratio = max(abs(candidate), abs(ref)) / max(min(abs(candidate), abs(ref)), 0.01)
    return ratio > RENTA_OUTLIER_RATIO and min(abs(candidate), abs(ref)) < RENTA_MAJOR_AMOUNT_FLOOR


def first_reasonable_renta_amount(values: list[object], reference: object = None, allow_zero: bool = True) -> float | None:
    for raw in values:
        number = parse_money(raw) if not isinstance(raw, (int, float)) else round(float(raw), 2)
        if number is None:
            continue
        if not is_reasonable_renta_amount(number, allow_zero=allow_zero):
            continue
        if reference is not None and is_renta_amount_outlier(number, reference):
            continue
        return number
    return None


def max_reasonable_renta_amount(values: list[object], reference: object = None, allow_zero: bool = True) -> float | None:
    candidates: list[float] = []
    for raw in values:
        number = parse_money(raw) if not isinstance(raw, (int, float)) else round(float(raw), 2)
        if number is None:
            continue
        if not is_reasonable_renta_amount(number, allow_zero=allow_zero):
            continue
        if reference is not None and is_renta_amount_outlier(number, reference):
            continue
        candidates.append(number)
    if not candidates:
        return None
    return max(candidates)


def normalize_renta_amounts(data: dict) -> dict:
    result = dict(data or {})
    raw_work = result.get("rendimientos_trabajo_total")
    raw_activities = result.get("rendimientos_actividades_economicas_total")
    raw_cap_inm = result.get("rendimientos_capital_inmobiliario_total")
    raw_cap_mob = result.get("rendimientos_capital_mobiliario_total")
    raw_base_general = result.get("base_imponible_general")
    raw_base_liquidable = result.get("base_liquidable_general")
    raw_casilla_505 = result.get("casilla_505")

    major_reference = first_reasonable_renta_amount(
        [
            raw_casilla_505,
            raw_base_liquidable,
            raw_base_general,
            raw_work,
            raw_activities,
            raw_cap_inm,
            raw_cap_mob,
        ],
        allow_zero=False,
    )

    result["rendimientos_trabajo_total"] = first_reasonable_renta_amount([raw_work], reference=major_reference)
    result["rendimientos_actividades_economicas_total"] = first_reasonable_renta_amount([raw_activities], reference=major_reference)
    result["rendimientos_capital_inmobiliario_total"] = first_reasonable_renta_amount([raw_cap_inm], reference=major_reference)
    result["rendimientos_capital_mobiliario_total"] = first_reasonable_renta_amount([raw_cap_mob], reference=major_reference)
    result["base_imponible_general"] = first_reasonable_renta_amount([raw_base_general])
    result["base_liquidable_general"] = first_reasonable_renta_amount([raw_base_liquidable])
    income_reference = first_reasonable_renta_amount(
        [
            result.get("rendimientos_trabajo_total"),
            result.get("rendimientos_actividades_economicas_total"),
            result.get("rendimientos_capital_inmobiliario_total"),
            result.get("rendimientos_capital_mobiliario_total"),
            result.get("base_liquidable_general"),
            result.get("base_imponible_general"),
            raw_casilla_505,
        ],
        allow_zero=False,
    )
    result["casilla_505"] = first_reasonable_renta_amount(
        [raw_casilla_505, raw_base_liquidable, raw_base_general],
        reference=income_reference,
    )
    result["resultado_declaracion"] = first_reasonable_renta_amount([result.get("resultado_declaracion")])
    result["ingresos_principales_total"] = max_reasonable_renta_amount(
        [
            result.get("ingresos_principales_total"),
            result.get("rendimientos_trabajo_total"),
            result.get("rendimientos_actividades_economicas_total"),
            result.get("rendimientos_capital_inmobiliario_total"),
            result.get("rendimientos_capital_mobiliario_total"),
            result.get("casilla_505"),
            result.get("base_liquidable_general"),
            result.get("base_imponible_general"),
        ],
        reference=result.get("casilla_505") or major_reference,
    )
    return result


def renta_validation_flags(record: dict) -> list[str]:
    flags: list[str] = []
    incomes = [
        record.get("rendimientos_trabajo_total"),
        record.get("rendimientos_actividades_economicas_total"),
        record.get("rendimientos_capital_inmobiliario_total"),
        record.get("rendimientos_capital_mobiliario_total"),
    ]
    present_incomes = [value for value in incomes if value not in (None, "")]
    if any(not is_reasonable_renta_amount(value) for value in present_incomes):
        flags.append("importe_fuera_rango")
    casilla_505 = record.get("casilla_505")
    if casilla_505 not in (None, "") and not is_reasonable_renta_amount(casilla_505):
        flags.append("casilla_505_fuera_rango")
    resultado = record.get("resultado_declaracion")
    if resultado not in (None, "") and not is_reasonable_renta_amount(resultado):
        flags.append("resultado_fuera_rango")
    if casilla_505 not in (None, ""):
        for value in present_incomes:
            if is_renta_amount_outlier(value, casilla_505):
                flags.append("renta_incoherente")
                break
    return flags


def renta_normalization_changed(original: dict, normalized: dict) -> bool:
    fields = (
        "ingresos_principales_total",
        "rendimientos_trabajo_total",
        "rendimientos_actividades_economicas_total",
        "rendimientos_capital_inmobiliario_total",
        "rendimientos_capital_mobiliario_total",
        "casilla_505",
        "base_imponible_general",
        "base_liquidable_general",
        "resultado_declaracion",
    )
    for field in fields:
        before = original.get(field)
        if before in (None, "", [], {}):
            continue
        after = normalized.get(field)
        before_num = parse_money(before) if not isinstance(before, (int, float)) else round(float(before), 2)
        after_num = parse_money(after) if not isinstance(after, (int, float)) else round(float(after), 2)
        if before_num is None and after_num is None:
            continue
        if before_num != after_num:
            return True
    return False


def parse_date_ddmmyyyy(raw: object) -> str:
    text = compact_spaces(raw)
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d%m%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def format_iso_date_for_humans(raw: object) -> str:
    text = compact_spaces(raw)
    if not text:
        return ""
    try:
        return datetime.strptime(text, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return text


def extract_single_code_value(text: str, code: str, value_pattern: str = r"([^\n]+?)") -> str:
    match = re.search(rf"{value_pattern}\s+{code}\b", text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return compact_spaces(match.group(1))


def extract_label_date(text: str, label: str) -> str:
    match = re.search(rf"{label}\s*([0-9]{{2}}/[0-9]{{2}}/[0-9]{{4}})", text, re.IGNORECASE)
    if not match:
        return ""
    return parse_date_ddmmyyyy(match.group(1))


def extract_date_near_line(text: str, line_pattern: str, window: int = 3) -> str:
    lines = [compact_spaces(line) for line in str(text or "").splitlines()]
    for idx, line in enumerate(lines):
        if not re.search(line_pattern, line, re.IGNORECASE):
            continue
        for offset in range(window + 1):
            pos = idx + offset
            if pos >= len(lines):
                break
            match = re.search(r"([0-9]{2}/[0-9]{2}/[0-9]{4})", lines[pos])
            if match:
                return parse_date_ddmmyyyy(match.group(1))
    return ""


def extract_presentacion_fecha(text: str) -> str:
    raw = str(text or "")
    normalized = unicodedata.normalize("NFKD", raw)
    patterns = (
        r"Presentaci[oó]n realizada el\s*:?\s*([0-9]{2}[/-][0-9]{2}[/-][0-9]{4})",
        r"Presentacion realizada el\s*:?\s*([0-9]{2}[/-][0-9]{2}[/-][0-9]{4})",
        r"Presentaci[oó]n\s+realizada\s+el[\s\S]{0,20}?([0-9]{2}[/-][0-9]{2}[/-][0-9]{4})",
        r"Presentacion\s+realizada\s+el[\s\S]{0,20}?([0-9]{2}[/-][0-9]{2}[/-][0-9]{4})",
    )
    for text_variant in (raw, normalized):
        for pattern in patterns:
            match = re.search(pattern, text_variant, re.IGNORECASE)
            if match:
                value = parse_date_ddmmyyyy(match.group(1).replace("-", "/"))
                if value:
                    return value
    return ""


def extract_primer_declarante_nif(text: str) -> str:
    raw = str(text or "")
    normalized = unicodedata.normalize("NFKD", raw)
    patterns = (
        r"Primer declarante[\s\S]{0,80}?NIF\s+([A-Z0-9 ]{8,12})",
        r"Primer declarante[\s\S]{0,120}?([A-Z0-9 ]{8,12})\s+\[?0*0*0*1\]?",
        r"Primer declarante[\s\S]{0,120}?([A-Z0-9 ]{8,12})\s+0001\b",
    )
    for text_variant in (raw, normalized):
        for pattern in patterns:
            match = re.search(pattern, text_variant, re.IGNORECASE)
            if not match:
                continue
            maybe = normalize_nif_candidate(match.group(1))
            if looks_like_nif(maybe):
                return maybe
    return ""


def extract_label_money(text: str, label: str) -> float | None:
    match = re.search(rf"{label}\s*([\-0-9\.,]+)", text, re.IGNORECASE)
    if not match:
        return None
    return parse_money(match.group(1))


def extract_money_near_line(text: str, line_pattern: str, window: int = 3) -> float | None:
    lines = [compact_spaces(line) for line in str(text or "").splitlines()]
    number_pattern = re.compile(r"[\-0-9][0-9\.,]*")
    for idx, line in enumerate(lines):
        if not re.search(line_pattern, line, re.IGNORECASE):
            continue
        for offset in range(window + 1):
            pos = idx + offset
            if pos >= len(lines):
                break
            matches = number_pattern.findall(lines[pos])
            for candidate in reversed(matches):
                if offset == 0 and "%" in lines[pos] and "." not in candidate and "," not in candidate:
                    continue
                if "." not in candidate and "," not in candidate and candidate not in ("0", "-0", "+0"):
                    continue
                value = parse_money(candidate)
                if value is not None:
                    return value
    return None


def extract_money_candidates_near_line(text: str, line_pattern: str, window: int = 6) -> list[float]:
    lines = [compact_spaces(line) for line in str(text or "").splitlines()]
    number_pattern = re.compile(r"[\-0-9][0-9\.,]*")
    candidates: list[float] = []
    for idx, line in enumerate(lines):
        if not re.search(line_pattern, line, re.IGNORECASE):
            continue
        for offset in range(window + 1):
            pos = idx + offset
            if pos >= len(lines):
                break
            for candidate in number_pattern.findall(lines[pos]):
                value = parse_money(candidate)
                if value is None or abs(value) < 0.005:
                    continue
                candidates.append(value)
    return candidates


def looks_like_person_name(value: object) -> bool:
    text = compact_spaces(value)
    if not text:
        return False
    lowered = norm_text(text)
    if any(token in lowered for token in ("direccion", "inmueble", "cuota", "resultado", "declaracion")):
        return False
    if re.search(r"\d", text):
        return False
    return True


def sanitize_person_name_candidate(value: object) -> str:
    text = clean_ocr_text_value(value)
    if not text:
        return ""
    text = re.sub(r"^(?:Apellidos y nombre|Apellidos y Nombre)\s+", "", text, flags=re.IGNORECASE)
    lowered = norm_text(text)
    if any(token in lowered for token in ("inmueble", "direccion", "referencia catastral", "vivienda habitual")):
        return ""
    if re.match(r"^(CL|AV|AVDA|AVENIDA|LG|CM|CR|PS|PZ|UR|CTRA|CALLE|CAMINO|LUGAR)\b", text, re.IGNORECASE):
        return ""
    if not looks_like_person_name(text):
        return ""
    return text


def extract_iban_accounts(text: str) -> list[str]:
    raw_matches = re.findall(r"\bES(?:\s*[0-9A-Z]){22}\b", str(text or ""), re.IGNORECASE)
    accounts = []
    for raw in raw_matches:
        normalized = re.sub(r"\s+", "", raw).upper()
        if re.fullmatch(r"ES[0-9A-Z]{22}", normalized) and normalized not in accounts:
            accounts.append(normalized)
    return accounts


def run_pdftotext(pdf_path: Path) -> str:
    cmd = shutil.which("pdftotext") or "/opt/homebrew/bin/pdftotext" or "/usr/local/bin/pdftotext"
    if not cmd or not os.path.exists(cmd):
        return ""
    try:
        proc = subprocess.run(
            [cmd, "-layout", "-nopgbrk", str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=PDFTOTEXT_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""

def run_ocrmypdf_text(pdf_path: Path) -> str:
    cmd = shutil.which("ocrmypdf")
    if not cmd:
        for candidate in ("/opt/homebrew/bin/ocrmypdf", "/usr/local/bin/ocrmypdf"):
            if os.path.exists(candidate):
                cmd = candidate
                break
    if not cmd:
        return ""
    if not command_exists("tesseract"):
        return ""
    with tempfile.TemporaryDirectory() as tmpdir:
        out_pdf = Path(tmpdir) / "ocr.pdf"
        try:
            proc = subprocess.run(
                [
                    cmd,
                    "--skip-text",
                    "--deskew",
                    "--rotate-pages",
                    "--clean",
                    "--remove-background",
                    "--optimize",
                    "0",
                    "--jobs",
                    "2",
                    "--language",
                    "spa+eng",
                    str(pdf_path),
                    str(out_pdf),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=max(60, PDFTOPPM_TIMEOUT_SECONDS * 2),
            )
        except subprocess.TimeoutExpired:
            return ""
        if proc.returncode != 0 or not out_pdf.exists():
            return ""
        return run_pdftotext(out_pdf)


def run_tesseract_ocr(pdf_path: Path) -> str:
    pdftoppm = shutil.which("pdftoppm") or "/opt/homebrew/bin/pdftoppm" or "/usr/local/bin/pdftoppm"
    if not pdftoppm or not os.path.exists(pdftoppm):
        return ""
    if not command_exists("tesseract"):
        return ""

    def ocr_with_dpi(dpi: int) -> str:
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                total_pages = pdf_page_count(pdf_path)
                head_pages = max(1, int(RENTA_OCR_HEAD_PAGES))
                tail_pages = max(0, int(RENTA_OCR_TAIL_PAGES))
                if total_pages <= 0:
                    total_pages = head_pages + tail_pages
                head_end = min(total_pages, head_pages)
                tail_start = max(1, total_pages - max(0, tail_pages) + 1)

                prefixes = []
                prefixes.append((Path(tmpdir) / "head", 1, head_end))
                if tail_pages > 0 and tail_start > head_end:
                    prefixes.append((Path(tmpdir) / "tail", tail_start, total_pages))

                for prefix, start_page, end_page in prefixes:
                    try:
                        proc = subprocess.run(
                            [
                                pdftoppm,
                                "-r",
                                str(max(120, int(dpi))),
                                "-png",
                                "-f",
                                str(start_page),
                                "-l",
                                str(end_page),
                                str(pdf_path),
                                str(prefix),
                            ],
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=PDFTOPPM_TIMEOUT_SECONDS,
                        )
                    except subprocess.TimeoutExpired:
                        continue
                    if proc.returncode != 0:
                        continue

                image_paths = list(Path(tmpdir).glob("*.png"))
                if not image_paths:
                    return ""
                def page_num(path: Path) -> int:
                    match = re.search(r"-([0-9]+)\\.png$", path.name)
                    if not match:
                        return 10**9
                    try:
                        return int(match.group(1))
                    except ValueError:
                        return 10**9
                image_paths = sorted(image_paths, key=page_num)
                chunks = []
                for image_path in image_paths:
                    best_text, best_err = best_tesseract_text(
                        image_path,
                        timeout_seconds=TESSERACT_TIMEOUT_SECONDS,
                        psms=RENTA_OCR_PSMS,
                    )
                    best_score = score_renta_ocr_text(best_text)
                    if best_score < 70:
                        candidates: list[tuple[str, str, int]] = [(best_text, best_err, best_score)]
                        big_path = Path(tmpdir) / f"{image_path.stem}_big.jpg"
                        if sips_transform(image_path, big_path, max_size=2600):
                            text2, err2 = best_tesseract_text(big_path, timeout_seconds=TESSERACT_TIMEOUT_SECONDS, psms=RENTA_OCR_PSMS)
                            candidates.append((text2, err2, score_renta_ocr_text(text2)))
                        for angle in (90, 270):
                            rotated = Path(tmpdir) / f"{image_path.stem}_rot_{angle}.jpg"
                            if sips_transform(image_path, rotated, rotate=angle, max_size=2600):
                                text3, err3 = best_tesseract_text(rotated, timeout_seconds=TESSERACT_TIMEOUT_SECONDS, psms=RENTA_OCR_PSMS)
                                candidates.append((text3, err3, score_renta_ocr_text(text3)))
                        best_text, best_err, best_score = max(candidates, key=lambda item: item[2])
                    if compact_spaces(best_text):
                        chunks.append(best_text)
                return "\n".join(chunks)
        except FileNotFoundError:
            return ""

    try:
        first = ocr_with_dpi(RENTA_OCR_DPI)
        if (not compact_spaces(first) or score_renta_ocr_text(first) < 60) and RENTA_OCR_RESCUE_DPI > RENTA_OCR_DPI:
            rescue = ocr_with_dpi(RENTA_OCR_RESCUE_DPI)
            if score_renta_ocr_text(rescue) > score_renta_ocr_text(first):
                return rescue
        return first
    except Exception:
        return ""


def get_pdf_text(pdf_path: Path) -> tuple[str, str]:
    text = run_pdftotext(pdf_path)
    if len(compact_spaces(text)) >= 40:
        return text, "pdftotext"
    if RENTA_USE_OCRMYPDF:
        ocrpdf = run_ocrmypdf_text(pdf_path)
        if len(compact_spaces(ocrpdf)) >= 80:
            return ocrpdf, "ocrmypdf"
    ocr_text = run_tesseract_ocr(pdf_path)
    if compact_spaces(ocr_text):
        return ocr_text, "ocr"
    return text, "empty"


def classify_pdf(text: str, pdf_path: Path) -> str:
    upper = norm_text(text)
    name = norm_text(pdf_path.name)
    if any(
        token in name
        for token in (
            "firma",
            "fraccionamiento",
            "aplazamiento",
            "aplaz",
            "pago",
            "modificacion cuenta",
            "mod cuenta",
            "mod cta",
            "compensacion",
            "no obligado",
            "presentacion documentos",
            "presentacion documentacion",
        )
    ):
        return "soporte_cliente"
    if "recibo de presentacion" in upper and "aportar documentacion complementaria" in upper:
        return "soporte_cliente"
    if "detalle de la solicitud" in upper and ("aplazamiento" in upper or "aplaz/fracc" in upper or "fracc" in upper):
        return "soporte_cliente"
    if "modelo dt2" in upper or "solicitud devolucion por aportaciones a mutualidades" in upper:
        return "soporte_cliente"
    if "consulta de datos fiscales" in upper:
        return "datos_fiscales"
    if "modelo 100" in upper and "impuesto sobre la renta de las personas fisicas" in upper:
        return "modelo_100"
    if re.search(r"\brenta\s+20[0-9]{2}\b", upper) and "adjuntos" in upper:
        return "notas"
    if "rentas clientes" in norm_text(str(pdf_path.parent)):
        return "soporte_cliente"
    return "pdf_desconocido"


def parse_label_block_value(text: str, label: str, code_pattern: str) -> str:
    pattern = re.compile(rf"{label}\s+(.+?)\s+{code_pattern}\b", re.IGNORECASE | re.DOTALL)
    match = pattern.search(text)
    if not match:
        return ""
    return compact_spaces(match.group(1))


def parse_modelo_100_text(text: str) -> dict:
    data: dict[str, object] = {"source_type": "modelo_100"}
    if not text:
        return data
    normalized = unicodedata.normalize("NFKD", text)
    data["presentacion_fecha"] = extract_presentacion_fecha(text)
    match = re.search(r"Expediente/Referencia .*?:\s*([A-Z0-9]+)", text)
    if match:
        data["expediente"] = match.group(1)
    match = re.search(r"Código Seguro de Verificación:\s*([A-Z0-9]+)", text)
    if match:
        data["csv"] = match.group(1)
    titular = re.search(
        r"\b([0-9A-Z]{8,10})\s+0001\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+0002\s+(Hombre|Mujer)\s+0005\s+(.+?)\s+000[6-9]\s+([0-9]{2}/[0-9]{2}/[0-9]{4})\s+0010\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if titular:
        data["cliente_nif"] = normalize_nif_candidate(titular.group(1))
        data["cliente_nombre"] = compact_spaces(titular.group(2))
        data["cliente_nif_source"] = "modelo_100"
        data["cliente_nombre_source"] = "modelo_100"
        data["cliente_estado_civil"] = re.sub(r"^\(\d+\)\s*", "", compact_spaces(titular.group(4))).strip()
        data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(titular.group(5))
    else:
        match = re.search(r"Primer declarante.*?\b([0-9A-Z]{8,10})\s+0001\b", text, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nif"] = normalize_nif_candidate(match.group(1))
            data["cliente_nif_source"] = "modelo_100"
        match = re.search(r"\b0001\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+0002\b", text, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nombre"] = compact_spaces(match.group(1))
            data["cliente_nombre_source"] = "modelo_100"
    if not looks_like_nif(data.get("cliente_nif")):
        data.pop("cliente_nif", None)
        data.pop("cliente_nif_source", None)
    if not data.get("cliente_nif"):
        primer_declarante_nif = extract_primer_declarante_nif(text)
        if primer_declarante_nif:
            data["cliente_nif"] = primer_declarante_nif
            data["cliente_nif_source"] = "modelo_100"
    estado_match = re.search(
        r"(Hombre|Mujer)\s+0005\s+(.+?)\s+000[6-9]\s+([0-9]{2}/[0-9]{2}/[0-9]{4})\s+0010\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if estado_match:
        estado = compact_spaces(estado_match.group(2))
        data["cliente_estado_civil"] = re.sub(r"^\(\d+\)\s*", "", estado).strip()
        data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(estado_match.group(3))
    if not data.get("cliente_nombre"):
        presentador = re.search(
            r"Apellidos y Nombre / Razón social:\s*(.+?)\s+En calidad de:",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if presentador:
            data["cliente_nombre"] = compact_spaces(presentador.group(1))
            data["cliente_nombre_source"] = "presentador"
    if not data.get("cliente_nif"):
        presentador_nif = re.search(r"NIF Presentador:\s*([A-Z0-9]{8,10})", text)
        if presentador_nif:
            data["cliente_nif"] = normalize_nif_candidate(presentador_nif.group(1))
            data["cliente_nif_source"] = "presentador"
    if not data.get("cliente_nif"):
        presentador_nif_relaxed = re.search(r"NIF Presentador:\s*([A-Z0-9 ]{8,12})", text, re.IGNORECASE)
        if presentador_nif_relaxed:
            maybe = normalize_nif_candidate(presentador_nif_relaxed.group(1))
            if looks_like_nif(maybe):
                data["cliente_nif"] = maybe
                data["cliente_nif_source"] = "presentador"
    if not data.get("cliente_nif"):
        nif_0001 = extract_single_code_value(text, "0001", r"([A-Z0-9]{8,10})")
        if nif_0001:
            data["cliente_nif"] = normalize_nif_candidate(nif_0001)
            data["cliente_nif_source"] = "modelo_100"
    if not data.get("cliente_nif"):
        relaxed_nif = re.search(r"NIF\s+([A-Z0-9 ]{8,12})\s+\[?o*0*0*1\]?", normalized, re.IGNORECASE)
        if relaxed_nif:
            maybe = normalize_nif_candidate(relaxed_nif.group(1))
            if looks_like_nif(maybe):
                data["cliente_nif"] = maybe
                data["cliente_nif_source"] = "modelo_100"
    if not data.get("cliente_nombre") or data.get("cliente_nombre_source") == "presentador":
        nombre_0002 = extract_single_code_value(text, "0002", r"([A-ZÁÉÍÓÚÜÑ ,'./-]+?)")
        if nombre_0002:
            data["cliente_nombre"] = nombre_0002
            data["cliente_nombre_source"] = "modelo_100"
    if not data.get("cliente_estado_civil"):
        estado_0006 = extract_single_code_value(text, "0006", r"(\(\d+\)\s*.+?)")
        estado_0007 = extract_single_code_value(text, "0007", r"(\(\d+\)\s*.+?)")
        estado = estado_0006 or estado_0007
        if estado:
            data["cliente_estado_civil"] = re.sub(r"^\(\d+\)\s*", "", estado).strip()
    if not data.get("cliente_fecha_nacimiento"):
        nacimiento = extract_single_code_value(text, "0010", r"([0-9]{2}/[0-9]{2}/[0-9]{4})")
        if nacimiento:
            data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(nacimiento)
    if not data.get("cliente_nif"):
        match = re.search(r"Primer declarante\s+NIF\s+([A-Z0-9]{8,10})", normalized, re.IGNORECASE)
        if match:
            data["cliente_nif"] = compact_spaces(match.group(1)).upper()
            data["cliente_nif_source"] = "modelo_100"
    if not data.get("cliente_nif"):
        match = re.search(r"NIF Presentador:\s*([A-Z0-9]{8,10})", normalized, re.IGNORECASE)
        if match:
            data["cliente_nif"] = compact_spaces(match.group(1)).upper()
            data["cliente_nif_source"] = "presentador"
    if not data.get("cliente_nombre") or data.get("cliente_nombre_source") == "presentador":
        match = re.search(r"Apellidos y nombre\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+Sexo del primer declarante", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nombre"] = compact_spaces(match.group(1))
            data["cliente_nombre_source"] = "modelo_100"
    if not data.get("cliente_nombre"):
        match = re.search(r"Apellidos y Nombre / Razon social:\s*(.+?)\s+En calidad de:", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nombre"] = compact_spaces(match.group(1))
            data["cliente_nombre_source"] = "presentador"
    if not data.get("cliente_estado_civil"):
        match = re.search(r"Estado civil .*?\)\s*(\(\d+\)\s*.+?)\s+Fecha de nacimiento", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_estado_civil"] = re.sub(r"^\(\d+\)\s*", "", compact_spaces(match.group(1))).strip()
    if not data.get("cliente_fecha_nacimiento"):
        nacimiento = extract_label_date(normalized, r"Fecha de nacimiento")
        if nacimiento:
            data["cliente_fecha_nacimiento"] = nacimiento
    if not data.get("cliente_fecha_nacimiento"):
        nacimiento = extract_date_near_line(normalized, r"Fecha de nacimiento", window=2)
        if nacimiento:
            data["cliente_fecha_nacimiento"] = nacimiento
    if not data.get("cliente_fecha_nacimiento"):
        match = re.search(r"Fecha de nacimiento\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", normalized, re.IGNORECASE)
        if match:
            data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(match.group(1))
    if not data.get("cliente_fecha_nacimiento"):
        match = re.search(
            r"Fecha de nacimiento[\s\S]{0,160}?([0-9]{2}/[0-9]{2}/[0-9]{4})",
            normalized,
            re.IGNORECASE,
        )
        if match:
            data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(match.group(1))
    if not looks_like_person_name(data.get("cliente_nombre")):
        presentador = compact_spaces(data.get("cliente_nombre")) if data.get("cliente_nombre_source") == "presentador" else ""
        if not presentador:
            match = re.search(r"Apellidos y Nombre / Razon social:\s*(.+?)\s+En calidad de:", normalized, re.IGNORECASE | re.DOTALL)
            if match:
                presentador = compact_spaces(match.group(1))
        if looks_like_person_name(presentador):
            data["cliente_nombre"] = presentador
            data["cliente_nombre_source"] = "presentador"
    cliente_name_clean = sanitize_person_name_candidate(data.get("cliente_nombre"))
    if cliente_name_clean:
        data["cliente_nombre"] = cliente_name_clean
    conyuge_nif = re.search(r"(?:Cónyuge.*?NIF\s+)?([A-Z0-9]{8,10})\s+0013\b", text, re.IGNORECASE | re.DOTALL)
    if conyuge_nif:
        data["conyuge_nif"] = normalize_nif_candidate(conyuge_nif.group(1))
    conyuge_nombre = re.search(r"(?:Apellidos y nombre\s+)?([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+0014\b", text, re.IGNORECASE | re.DOTALL)
    if conyuge_nombre:
        nombre = sanitize_person_name_candidate(conyuge_nombre.group(1))
        if nombre and "primer declarante" not in norm_text(nombre):
            data["conyuge_nombre"] = nombre
    conyuge_fecha = re.search(r"Fecha de nacimiento del cónyuge\s+([0-9]{2}/[0-9]{2}/[0-9]{4})\s+0060\b", text)
    if conyuge_fecha:
        data["conyuge_fecha_nacimiento"] = parse_date_ddmmyyyy(conyuge_fecha.group(1))
    if not data.get("conyuge_nif"):
        match = re.search(r"C[oó]nyuge .*?NIF\s+([A-Z0-9]{8,10})", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["conyuge_nif"] = normalize_nif_candidate(match.group(1))
    if not data.get("conyuge_nombre"):
        match = re.search(r"C[oó]nyuge .*?Apellidos y nombre\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+Sexo del c[oó]nyuge", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["conyuge_nombre"] = sanitize_person_name_candidate(match.group(1))
    if not data.get("conyuge_fecha_nacimiento"):
        match = re.search(r"Fecha de nacimiento del c[oó]nyuge\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", normalized, re.IGNORECASE)
        if match:
            data["conyuge_fecha_nacimiento"] = parse_date_ddmmyyyy(match.group(1))
    conyuge_name_clean = sanitize_person_name_candidate(data.get("conyuge_nombre"))
    if conyuge_name_clean:
        data["conyuge_nombre"] = conyuge_name_clean
    elif data.get("conyuge_nombre"):
        data.pop("conyuge_nombre", None)
    comunidad = re.search(r"\n([A-ZÁÉÍÓÚÜÑ ]+)\s+0070\b", text)
    if comunidad:
        data["comunidad_autonoma"] = compact_spaces(comunidad.group(1))
    cuentas = extract_iban_accounts(text)
    if cuentas:
        data["cuentas_detectadas"] = cuentas

    hijos_section = ""
    section_match = re.search(r"Situación familiar(.*?)Rendimientos del trabajo", text, re.IGNORECASE | re.DOTALL)
    if section_match:
        hijos_section = section_match.group(1)
    hijos = []
    if hijos_section:
        pattern = re.compile(r"(?:NIF\s+([A-Z0-9]{8,10})\s+0075\s+)?Apellidos y nombre\s+(.+?)\s+0076\s+Fecha de nacimiento\s+([0-9]{2}/[0-9]{2}/[0-9]{4})\s+0077", re.IGNORECASE | re.DOTALL)
        seen_children = set()
        for nif, nombre, fecha in pattern.findall(hijos_section):
            marker = f"{compact_spaces(nombre)}|{fecha}"
            if marker in seen_children:
                continue
            seen_children.add(marker)
            hijos.append(
                {
                    "nif": compact_spaces(nif),
                    "nombre": compact_spaces(nombre),
                    "fecha_nacimiento": parse_date_ddmmyyyy(fecha),
                }
            )
    data["hijos"] = hijos
    data["hijos_count"] = len(hijos)

    casillas = {
        "rendimientos_trabajo_total": "0012",
        "seguridad_social": "0013",
        "rendimiento_neto_trabajo": "0022",
        "rendimiento_neto_reducido": "0025",
        "base_imponible_general": "0432",
        "base_imponible_ahorro": "0460",
        "base_liquidable_general": "0500",
        "casilla_505": "0505",
        "base_liquidable_ahorro": "0510",
        "cuota_resultante_autoliquidacion": "0595",
        "pagos_a_cuenta_total": "0609",
        "resultado_declaracion": "0670",
    }
    for field, code in casillas.items():
        match = re.search(rf"([\-0-9\.,]+)\s+{code}\b", text)
        if match:
            data[field] = parse_money(match.group(1))
    trabajo_candidates = []
    if data.get("rendimientos_trabajo_total") is not None:
        trabajo_candidates.append(data.get("rendimientos_trabajo_total"))
    label_value = extract_label_money(
        normalized,
        r"Total ingresos integros computables.*?\]\s*",
    )
    if label_value is not None:
        trabajo_candidates.append(label_value)
    label_value = extract_label_money(
        normalized,
        r"Retribuciones dinerarias\s*",
    )
    if label_value is not None:
        trabajo_candidates.append(label_value)
    trabajo_window = extract_money_candidates_near_line(
        normalized,
        r"Total ingresos integros computables|Retribuciones dinerarias",
        window=4,
    )
    if trabajo_window:
        trabajo_candidates.append(max(trabajo_window))
    if trabajo_candidates:
        data["rendimientos_trabajo_total"] = max(trabajo_candidates)
    actividades = []
    for code in ("1484", "1482"):
        match = re.search(rf"([\-0-9\.,]+)\s+{code}\b", text)
        if match:
            value = parse_money(match.group(1))
            if value is not None:
                actividades.append(value)
    actividad_label = extract_label_money(
        normalized,
        r"Rendimiento neto reducido total de actividades econ[oó]micas.*?\s*",
    )
    if actividad_label is not None:
        actividades.append(actividad_label)
    actividad_window = extract_money_candidates_near_line(
        normalized,
        r"Suma del rendimiento neto reducido total de las actividades econ[oó]micas en estimaci[oó]n directa",
        window=8,
    )
    if actividad_window:
        actividades.append(max(actividad_window))
    actividad_window = extract_money_candidates_near_line(
        normalized,
        r"Rendimiento neto reducido|Suma de rendimientos netos reducidos",
        window=8,
    )
    if actividad_window:
        actividades.append(max(actividad_window))
    if actividades:
        data["rendimientos_actividades_economicas_total"] = max(actividades)
    rend_cap_mob = []
    for code in ("0041", "0040", "0038", "0429"):
        match = re.search(rf"([\-0-9\.,]+)\s+{code}\b", text)
        if match:
            value = parse_money(match.group(1))
            if value is not None:
                rend_cap_mob.append(value)
    capital_mob_label = extract_label_money(
        normalized,
        r"Suma de rendimientos de capital mobiliario a integrar en la base imponible del ahorro\s*",
    )
    if capital_mob_label is not None:
        rend_cap_mob.append(capital_mob_label)
    if rend_cap_mob:
        data["rendimientos_capital_mobiliario_total"] = max(rend_cap_mob)
    alquileres = [parse_money(item) for item in re.findall(r"([\-0-9\.,]+)\s+0149\b", text)]
    alquileres = [item for item in alquileres if item is not None]
    if alquileres:
        data["rendimientos_capital_inmobiliario_total"] = round(sum(alquileres), 2)
    if data.get("rendimientos_capital_inmobiliario_total") is None:
        label_value = extract_label_money(normalized, r"Suma de imputaciones de rentas inmobiliarias\s*")
        if label_value is not None:
            data["rendimientos_capital_inmobiliario_total"] = label_value
    if data.get("base_imponible_general") is None:
        data["base_imponible_general"] = extract_label_money(
            normalized,
            r"Base imponible general .*?\]\s*",
        )
    if data.get("casilla_505") is None:
        data["casilla_505"] = (
            data.get("base_liquidable_general")
            if data.get("base_liquidable_general") is not None
            else data.get("base_imponible_general")
        )
    if data.get("resultado_declaracion") is None:
        data["resultado_declaracion"] = extract_label_money(
            normalized,
            r"Resultado de la declaraci[oó]n\s*",
        )
    if data.get("resultado_declaracion") is None:
        data["resultado_declaracion"] = extract_money_near_line(
            normalized,
            r"Resultado de la declaraci[oó]n|Resultado a ingresar(?:\s+[o0])?\s+devolver|Resultado a ingresar o devolver",
            window=4,
        )
    if data.get("resultado_declaracion") is None:
        match = re.search(r"Resultado de la declara[^\n\r]*?([\-]?[0-9][0-9\.,]*)", normalized, re.IGNORECASE)
        if match:
            data["resultado_declaracion"] = parse_money(match.group(1))
    if data.get("resultado_declaracion") is None:
        match = re.search(r"Importe total de la declaraci[oó]n:\s*([\-0-9\.,]+)\s*euros", normalized, re.IGNORECASE)
        if match:
            data["resultado_declaracion"] = parse_money(match.group(1))
    if data.get("resultado_declaracion") is None:
        primer_plazo = extract_money_near_line(
            normalized,
            r"Importe del primer plazo",
            window=3,
        )
        segundo_plazo = extract_money_near_line(
            normalized,
            r"Importe del segundo plazo",
            window=3,
        )
        if primer_plazo is not None and segundo_plazo is not None:
            data["resultado_declaracion"] = round(primer_plazo + segundo_plazo, 2)
        elif primer_plazo is not None:
            data["resultado_declaracion"] = round(primer_plazo / 0.60, 2)
        elif segundo_plazo is not None:
            data["resultado_declaracion"] = round(segundo_plazo / 0.40, 2)
    if (
        data.get("resultado_declaracion") is None
        and "negativa/sin actividad/resultado cero" in norm_text(text)
    ):
        data["resultado_declaracion"] = 0.0
    data["ingresos_principales_total"] = (
        data.get("rendimientos_trabajo_total")
        or data.get("rendimientos_actividades_economicas_total")
        or data.get("rendimientos_capital_inmobiliario_total")
        or data.get("rendimientos_capital_mobiliario_total")
        or None
    )
    if data.get("ingresos_principales_total") is None:
        ganancias = []
        for code in ("1833", "1836", "1840", "1841", "0301", "0306", "0418", "0420"):
            match = re.search(rf"([\-]?[0-9][0-9\.,]*)\s+(?:\[?{code.lower()}|\[?{code}|\b{code}\b)", normalized, re.IGNORECASE)
            if match:
                value = parse_money(match.group(1))
                if value is not None:
                    ganancias.append(abs(value))
        if ganancias:
            data["ingresos_principales_total"] = max(ganancias)
    if data.get("ingresos_principales_total") is None:
        match = re.search(r"Importe total de la declaraci[oó]n:\s*([\-0-9\.,]+)\s*euros", normalized, re.IGNORECASE)
        if match:
            data["ingresos_principales_total"] = parse_money(match.group(1))
    if data.get("ingresos_principales_total") is None and "negativa/sin actividad/resultado cero" in norm_text(text):
        data["ingresos_principales_total"] = 0.0

    inmueble = re.search(
        r"Dirección del inmueble\s+(.+?)\s+0069\b",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if inmueble:
        data["direccion_inmueble_principal"] = compact_spaces(inmueble.group(1))
    ref_catastral = re.search(r"Referencia catastral\.\s+([A-Z0-9]+)\s+0066\b", text)
    if ref_catastral:
        data["referencia_catastral_principal"] = ref_catastral.group(1)
    prestamo = re.search(r"Nº de identificación del préstamo hipotecario\s+([A-Z0-9]+)\s+0709\b", text)
    if prestamo:
        data["prestamo_hipotecario_id"] = prestamo.group(1)
    return normalize_renta_amounts(data)


def parse_datos_fiscales_text(text: str) -> dict:
    data: dict[str, object] = {"source_type": "datos_fiscales"}
    if not text:
        return data
    flat = compact_spaces(text.replace("\n", " "))
    match = re.search(r"NIF:\s*([A-Z0-9]+)", text)
    if match:
        data["cliente_nif"] = match.group(1)
        data["cliente_nif_source"] = "datos_fiscales"
    match = re.search(r"NOMBRE:\s*(.+?)(?:\n\s*\n|DOMICILIO FISCAL)", text, re.DOTALL)
    if match:
        data["cliente_nombre"] = compact_spaces(match.group(1))
        data["cliente_nombre_source"] = "datos_fiscales"
    via = re.search(r"Tipo Vía\s+([A-ZÁÉÍÓÚÜÑ ]+)", text)
    nombre_via = re.search(r"Nombre largo Vía\s+([A-ZÁÉÍÓÚÜÑ0-9 ]+)", text)
    numero = re.search(r"\nNUM\s+([0-9A-Z]+)", text)
    poblacion = re.search(r"Código Postal Municipio\s+([0-9]{5})\s+(.+?)\n", text, re.DOTALL)
    provincia = re.search(r"Provincia\s+([A-ZÁÉÍÓÚÜÑ ]+)", text)
    if via or nombre_via or numero:
        parts = [
            compact_spaces(via.group(1)) if via else "",
            compact_spaces(nombre_via.group(1)) if nombre_via else "",
            compact_spaces(numero.group(1)) if numero else "",
        ]
        data["direccion"] = compact_spaces(" ".join([p for p in parts if p]))
    if not data.get("direccion"):
        via_flat = re.search(r"Tipo V[ií]a\s+([A-ZÁÉÍÓÚÜÑ ]+?)\s+Nombre largo V[ií]a", flat, re.IGNORECASE)
        nombre_flat = re.search(
            r"Nombre largo V[ií]a\s+(.+?)\s+(?:Tipo Numer|NUM\b|N[uú]me|Datos Complementarios|Localidad / Poblaci[oó]n|C[oó]digo Post Municipio)",
            flat,
            re.IGNORECASE,
        )
        numero_flat = re.search(r"N[uú]mero\s+([0-9A-Z]+)\b", flat, re.IGNORECASE)
        if via_flat or nombre_flat or numero_flat:
            parts = [
                compact_spaces(via_flat.group(1)) if via_flat else "",
                compact_spaces(nombre_flat.group(1)) if nombre_flat else "",
                compact_spaces(numero_flat.group(1)) if numero_flat else "",
            ]
            data["direccion"] = compact_spaces(" ".join([p for p in parts if p]))
    if poblacion:
        data["codigo_postal"] = poblacion.group(1)
        data["poblacion"] = compact_spaces(poblacion.group(2))
    if not data.get("codigo_postal") or not data.get("poblacion"):
        poblacion_flat = re.search(
            r"C[oó]digo Post Municipio\s+(?:al\s+)?([A-ZÁÉÍÓÚÜÑ' ]+?)\s+([0-9]{5})\s+Provincia",
            flat,
            re.IGNORECASE,
        )
        if poblacion_flat:
            data["poblacion"] = compact_spaces(poblacion_flat.group(1))
            data["codigo_postal"] = poblacion_flat.group(2)
    if provincia:
        data["provincia"] = compact_spaces(provincia.group(1))
    if not data.get("provincia"):
        provincia_flat = re.search(r"Provincia\s+([A-ZÁÉÍÓÚÜÑ ]+)", flat, re.IGNORECASE)
        if provincia_flat:
            data["provincia"] = compact_spaces(provincia_flat.group(1))
    ref = re.search(r"Referencia Catastral\s+([A-Z0-9]+)", text)
    if ref:
        data["referencia_catastral"] = ref.group(1)
    cuentas = sorted(set(re.findall(r"\b[0-9]{10,20}\b", text)))
    if cuentas:
        data["cuentas_detectadas"] = cuentas
    ibans = extract_iban_accounts(text)
    if ibans:
        current = list(data.get("cuentas_detectadas") or [])
        for account in ibans:
            if account not in current:
                current.append(account)
        data["cuentas_detectadas"] = current
    pagadores = sorted(set(re.findall(r"\b[A-Z][0-9A-Z]{7,}\s+([A-ZÁÉÍÓÚÜÑ ,\.]+?)\s+(?:\d{6,}|AU|SA|SL|S)\b", text)))
    pagadores = [compact_spaces(item) for item in pagadores if compact_spaces(item)]
    if pagadores:
        data["pagadores_detectados"] = pagadores
    total_rend_bancarios = re.search(r"TOTAL\s+([0-9\.,]+)\s+([0-9\.,]+)\s+Cuenta", text, re.DOTALL)
    if total_rend_bancarios:
        data["rendimientos_bancarios_total"] = parse_money(total_rend_bancarios.group(1))
        data["retenciones_bancarias_total"] = parse_money(total_rend_bancarios.group(2))
    seguros = re.search(r"TOTAL\s+([0-9\.,]+)\s+([0-9\.,]+)\s+([0-9\.,]+)\s+CASILLAS", text, re.DOTALL)
    if seguros:
        data["rendimientos_seguros_total"] = parse_money(seguros.group(1))
        data["base_retenciones_seguros_total"] = parse_money(seguros.group(2))
        data["retenciones_seguros_total"] = parse_money(seguros.group(3))
    ayudas_block = re.search(
        r"OTRAS SUBVENCIONES, AUXILIOS Y AYUDAS SATISFECHOS POR LAS ADMINISTRACIONES P[ÚU]BLICAS(.*?)(?:PAGOS FRACCIONADOS|CASILLAS DECLARACI[ÓO]N RENTA|$)",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if ayudas_block:
        ayudas_vals = [
            parse_money(item)
            for item in re.findall(
                r"\b([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}|[0-9]+\.[0-9]{2}|[0-9]+,[0-9]{2})\b",
                ayudas_block.group(1),
            )
        ]
        ayudas_vals = [item for item in ayudas_vals if item is not None]
        if ayudas_vals:
            data["rendimientos_actividades_economicas_total"] = round(max(ayudas_vals), 2)
            data["ingresos_principales_total"] = data["rendimientos_actividades_economicas_total"]
    return data


def parse_notas_text(text: str) -> dict:
    data: dict[str, object] = {"source_type": "notas"}
    if not text:
        return data
    names = re.findall(r"([A-ZÁÉÍÓÚÜÑ ]+MORALES)", text, re.IGNORECASE)
    if names:
        data["nombres_mencionados"] = [compact_spaces(n) for n in names]
    data["notas_resumen"] = compact_spaces(text[:1200])
    return data


def build_record_key(fields: dict, pdf_path: Path) -> str:
    nif = compact_spaces(fields.get("cliente_nif"))
    if nif:
        return nif.upper()
    folder = pdf_path.parent.name if "RENTAS CLIENTES" in str(pdf_path.parent.parent) else ""
    if folder:
        return slug(folder)
    stem = pdf_path.stem
    stem = re.sub(r"\b[0-9A-Z]{5,}\b", " ", stem)
    stem = re.sub(r"\b\d{2}[_/-]?\d{2}[_/-]?\d{4}\b", " ", stem)
    stem = re.sub(r"\b\d{6,8}\b", " ", stem)
    return slug(stem)


def merge_record(target: dict, source: dict, pdf_path: Path) -> None:
    target.setdefault("source_files", []).append(str(pdf_path))
    target.setdefault("source_types", [])
    source_type = compact_spaces(source.get("source_type"))
    if source_type and source_type not in target["source_types"]:
        target["source_types"].append(source_type)
    for key, value in source.items():
        if key == "source_type":
            continue
        if value in (None, "", [], {}):
            continue
        if key == "hijos":
            existing = target.setdefault("hijos", [])
            seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in existing}
            for item in value:
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if marker not in seen:
                    existing.append(item)
                    seen.add(marker)
            target["hijos_count"] = len(existing)
            continue
        if key in ("cuentas_detectadas", "pagadores_detectados", "nombres_mencionados"):
            existing = target.setdefault(key, [])
            for item in value:
                if item not in existing:
                    existing.append(item)
            continue
        if not target.get(key):
            target[key] = value
    target["cliente_nombre"] = target.get("cliente_nombre") or infer_name_from_sources(target.get("source_files", []))
    if target.get("cliente_nombre") and not target.get("cliente_nombre_source"):
        target["cliente_nombre_source"] = "filename"


def infer_name_from_sources(paths: list[str]) -> str:
    if not paths:
        return ""
    first = Path(paths[0])
    if first.parent.name and not re.fullmatch(r"RENTAS\s+20[0-9]{2}", compact_spaces(first.parent.name), re.IGNORECASE):
        return compact_spaces(first.parent.name)
    stem = first.stem
    stem = re.sub(
        r"\b(firma|fraccionamiento|aplazamiento|solicitud|pago|plazo|renta|modelo|presentacion)\b.*$",
        " ",
        stem,
        flags=re.IGNORECASE,
    )
    stem = re.sub(r"\b[0-9]{2,}[_/-]?[0-9A-Z]{2,}\b", " ", stem)
    stem = re.sub(r"\b[0-9A-Z]{5,}\b", " ", stem)
    stem = re.sub(r"\b\d{2}[_/-]?\d{2}[_/-]?\d{4}\b", " ", stem)
    stem = re.sub(r"\b\d{6,8}\b", " ", stem)
    stem = re.sub(r"_+", " ", stem)
    return compact_spaces(stem)


def extract_dni_expiry_from_sources(paths: list[str]) -> str:
    return extract_dni_metadata_from_sources(paths).get("dni_caducidad") or ""


def detect_renta_doc_status(value: object) -> str:
    text = norm_text(value)
    if not text:
        return "Presentada"
    if any(token in text for token in ("borrador", "draft")):
        return "Borrador"
    return "Presentada"


def extract_dni_metadata_from_sources(paths: list[str]) -> dict:
    for raw_path in paths or []:
        stem = Path(raw_path).stem
        upper = stem.upper()
        dates = [parse_date_ddmmyyyy(value) for value in re.findall(r"(\d{8})", stem)]
        dates = [value for value in dates if value]
        if "PERMAN" in upper:
            return {
                "dni_expedicion": dates[0] if dates else "",
                "dni_caducidad": "Permanente",
                "dni_permanente": 1,
            }
        if len(dates) >= 2:
            return {
                "dni_expedicion": dates[0],
                "dni_caducidad": dates[-1],
                "dni_permanente": 0,
            }
        if len(dates) == 1:
            return {
                "dni_expedicion": "",
                "dni_caducidad": dates[0],
                "dni_permanente": 0,
            }
    return {"dni_expedicion": "", "dni_caducidad": "", "dni_permanente": 0}


def should_skip_auxiliary_record(record: dict) -> bool:
    source_types = set(record.get("source_types") or [])
    if not source_types:
        return False
    if source_types.issubset({"soporte_cliente", "notas"}):
        return True
    if "modelo_100" not in source_types:
        has_core_renta_data = any(
            record.get(field) not in (None, "", [], {})
            for field in ("ingresos_principales_total", "resultado_declaracion", "casilla_505")
        )
        if not has_core_renta_data:
            return True
    return False


def finalize_record(record: dict) -> dict:
    raw_record = dict(record)
    result = normalize_renta_amounts(record)
    result["source_files"] = sorted(result.get("source_files") or [])
    result["source_file_count"] = len(result["source_files"])
    result["source_types"] = sorted(result.get("source_types") or [])
    result["estado_presentacion"] = detect_renta_doc_status(
        result.get("estado_presentacion") or result.get("doc_status") or "Presentada"
    )
    result["doc_status"] = result["estado_presentacion"]
    dni_meta = extract_dni_metadata_from_sources(result["source_files"])
    if not result.get("dni_expedicion"):
        result["dni_expedicion"] = dni_meta.get("dni_expedicion") or ""
    if not result.get("dni_caducidad"):
        result["dni_caducidad"] = dni_meta.get("dni_caducidad") or ""
    if result.get("dni_permanente") in (None, "", 0, "0", False):
        result["dni_permanente"] = 1 if dni_meta.get("dni_permanente") else 0
    critical_missing = [field for field in CRITICAL_FIELDS if result.get(field) in (None, "", [], {})]
    flags = []
    if "pdf_desconocido" in result["source_types"]:
        flags.append("pdf_desconocido")
    if "modelo_100" not in result["source_types"]:
        flags.append("sin_modelo_100")
    if result.get("cliente_nombre_source") == "filename":
        flags.append("nombre_desde_filename")
    if critical_missing:
        flags.append("faltan_campos_criticos")
    if renta_normalization_changed(raw_record, result):
        flags.append("renta_corregida")
    for flag in renta_validation_flags(result):
        if flag not in flags:
            flags.append(flag)
    score = 0
    if "modelo_100" in result["source_types"]:
        score += 30
    if "datos_fiscales" in result["source_types"]:
        score += 20
    if "notas" in result["source_types"]:
        score += 5
    for field in CRITICAL_FIELDS:
        if result.get(field) not in (None, "", [], {}):
            score += 10
    if result.get("hijos_count"):
        score += 5
    if result.get("conyuge_nombre") or result.get("conyuge_nif"):
        score += 5
    if result.get("cliente_nombre_source") == "filename":
        score -= 20
    if result["source_types"] == ["pdf_desconocido"]:
        score -= 30
    if any(flag in flags for flag in ("importe_fuera_rango", "casilla_505_fuera_rango", "resultado_fuera_rango", "renta_incoherente", "renta_corregida")):
        score -= 35
    score = max(0, min(100, score))
    safe_to_apply = (
        not critical_missing
        and not any(flag in flags for flag in ("importe_fuera_rango", "casilla_505_fuera_rango", "resultado_fuera_rango", "renta_incoherente", "renta_corregida"))
        and result.get("cliente_nombre_source") != "filename"
        and any(kind in result["source_types"] for kind in ("modelo_100", "datos_fiscales"))
    )
    result["confidence_score"] = score
    result["critical_missing"] = critical_missing
    result["review_flags"] = flags
    result["safe_to_apply"] = safe_to_apply
    result["review_status"] = "ok" if safe_to_apply else "review"
    return result


def build_review_queue(records: list[dict]) -> list[dict]:
    queue = []
    for record in records:
        if record.get("safe_to_apply"):
            continue
        queue.append(
            {
                "cliente_nombre": record.get("cliente_nombre"),
                "cliente_nif": record.get("cliente_nif"),
                "confidence_score": record.get("confidence_score"),
                "critical_missing": record.get("critical_missing"),
                "review_flags": record.get("review_flags"),
                "source_types": record.get("source_types"),
                "source_files": record.get("source_files"),
            }
        )
    return queue


def write_csv_summary(csv_path: Path, records: list[dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "cliente_nombre",
        "cliente_nif",
        "cliente_fecha_nacimiento",
        "cliente_estado_civil",
        "ingresos_principales_total",
        "base_imponible_general",
        "resultado_declaracion",
        "confidence_score",
        "safe_to_apply",
        "critical_missing",
        "review_flags",
        "source_types",
        "source_file_count",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "cliente_nombre": record.get("cliente_nombre"),
                    "cliente_nif": record.get("cliente_nif"),
                    "cliente_fecha_nacimiento": record.get("cliente_fecha_nacimiento"),
                    "cliente_estado_civil": record.get("cliente_estado_civil"),
                    "ingresos_principales_total": record.get("ingresos_principales_total"),
                    "base_imponible_general": record.get("base_imponible_general"),
                    "resultado_declaracion": record.get("resultado_declaracion"),
                    "confidence_score": record.get("confidence_score"),
                    "safe_to_apply": 1 if record.get("safe_to_apply") else 0,
                    "critical_missing": "|".join(record.get("critical_missing") or []),
                    "review_flags": "|".join(record.get("review_flags") or []),
                    "source_types": "|".join(record.get("source_types") or []),
                    "source_file_count": record.get("source_file_count"),
                }
            )


def build_validation_summary(records: list[dict]) -> dict:
    total = len(records)
    if total <= 0:
        return {
            "total_registros": 0,
            "con_nombre_y_nif": 0,
            "con_fecha_nacimiento": 0,
            "con_ingresos_y_resultado": 0,
            "pdf_desconocido": 0,
            "posibles_duplicados_nombre": 0,
            "seguros_para_apply": 0,
            "pendientes_revision": 0,
            "pct_nombre_y_nif": 0.0,
            "pct_fecha_nacimiento": 0.0,
            "pct_ingresos_y_resultado": 0.0,
        }
    with_name_and_nif = sum(
        1
        for record in records
        if compact_spaces(record.get("cliente_nombre")) and compact_spaces(record.get("cliente_nif"))
    )
    with_birthdate = sum(1 for record in records if compact_spaces(record.get("cliente_fecha_nacimiento")))
    with_income_and_result = sum(
        1
        for record in records
        if record.get("ingresos_principales_total") not in (None, "", [], {})
        and record.get("resultado_declaracion") not in (None, "", [], {})
    )
    unknown_docs = sum(1 for record in records if "pdf_desconocido" in (record.get("source_types") or []))
    safe_count = sum(1 for record in records if record.get("safe_to_apply"))
    review_count = total - safe_count
    name_buckets: dict[str, int] = defaultdict(int)
    for record in records:
        name = slug(record.get("cliente_nombre"))
        if name:
            name_buckets[name] += 1
    duplicate_names = sum(1 for count in name_buckets.values() if count > 1)
    return {
        "total_registros": total,
        "con_nombre_y_nif": with_name_and_nif,
        "con_fecha_nacimiento": with_birthdate,
        "con_ingresos_y_resultado": with_income_and_result,
        "pdf_desconocido": unknown_docs,
        "posibles_duplicados_nombre": duplicate_names,
        "seguros_para_apply": safe_count,
        "pendientes_revision": review_count,
        "pct_nombre_y_nif": round((with_name_and_nif / total) * 100, 2),
        "pct_fecha_nacimiento": round((with_birthdate / total) * 100, 2),
        "pct_ingresos_y_resultado": round((with_income_and_result / total) * 100, 2),
    }


def parse_pdf(pdf_path: Path) -> dict:
    text, text_source = get_pdf_text(pdf_path)
    doc_type = classify_pdf(text, pdf_path)
    if doc_type == "modelo_100":
        fields = parse_modelo_100_text(text)
    elif doc_type == "datos_fiscales":
        fields = parse_datos_fiscales_text(text)
    elif doc_type == "notas":
        fields = parse_notas_text(text)
    else:
        fields = {"source_type": doc_type}
    fields["doc_type"] = doc_type
    fields["text_source"] = text_source
    fields["text_preview"] = compact_spaces(text[:500])
    return fields


def ensure_company_id(conn: sqlite3.Connection, company_name: str) -> str:
    row = conn.execute("SELECT id FROM empresas WHERE nombre = ?", (company_name,)).fetchone()
    if not row:
        raise RuntimeError(f"No existe la empresa {company_name!r} en la base.")
    return row[0]


def ensure_cliente(conn: sqlite3.Connection, empresa_id: str, service: str, record: dict, now: str) -> str | None:
    nombre = compact_spaces(record.get("cliente_nombre"))
    nif = compact_spaces(record.get("cliente_nif")).upper()
    if not nombre or not nif:
        return None
    if record.get("cliente_nombre_source") == "filename":
        return None
    row = None
    row = conn.execute("SELECT id FROM clientes WHERE nif = ?", (nif,)).fetchone()
    if not row:
        row = conn.execute("SELECT id FROM clientes WHERE nombre = ?", (nombre,)).fetchone()
    fields = {
        "telefono": None,
        "email": None,
        "fecha_nacimiento": record.get("cliente_fecha_nacimiento") or None,
        "direccion": record.get("direccion") or record.get("direccion_inmueble_principal") or None,
        "codigo_postal": record.get("codigo_postal") or None,
        "poblacion": record.get("poblacion") or None,
        "provincia": record.get("provincia") or None,
    }
    if not row:
        cliente_id = uuid.uuid4().hex
        tipo_persona = "Física" if re.match(r"^[0-9]{8}[A-Z]$", nif) else None
        conn.execute(
            """
            INSERT INTO clientes (
              id, nombre, tipo_persona, nif, telefono, email, fecha_nacimiento,
              direccion, codigo_postal, poblacion, provincia, estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Activo', datetime(?), datetime(?)
            )
            """,
            (
                cliente_id,
                nombre,
                tipo_persona,
                nif or None,
                fields["telefono"],
                fields["email"],
                fields["fecha_nacimiento"],
                fields["direccion"],
                fields["codigo_postal"],
                fields["poblacion"],
                fields["provincia"],
                now,
                now,
            ),
        )
    else:
        cliente_id = row[0]
        updates = {}
        if nif:
            updates["nif"] = nif
        for key, value in fields.items():
            if value:
                updates[key] = value
        if updates:
            # Rellenamos campos vacíos sin pisar datos existentes:
            # - En la BD hay muchos campos guardados como "" en vez de NULL.
            # - COALESCE(campo, ?) NO rellena cuando campo == "".
            # Usamos NULLIF(TRIM(campo),'') para tratar "" como NULL.
            set_clause = ", ".join([f"{key} = COALESCE(NULLIF(TRIM({key}), ''), ?)" for key in updates])
            conn.execute(
                f"UPDATE clientes SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                (*updates.values(), now, cliente_id),
            )
    link = conn.execute(
        """
        SELECT id FROM clientes_empresas WHERE cliente_id = ? AND empresa_id = ? AND servicio = ?
        """,
        (cliente_id, empresa_id, service),
    ).fetchone()
    if not link:
        conn.execute(
            """
            INSERT INTO clientes_empresas (
              id, cliente_id, empresa_id, servicio, estado, fecha_inicio, fecha_fin, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, 'Activo', NULL, NULL, datetime(?), datetime(?)
            )
            """,
            (uuid.uuid4().hex, cliente_id, empresa_id, service, now, now),
        )
    return cliente_id


def ensure_spouse(conn: sqlite3.Connection, empresa_id: str, service: str, record: dict, now: str) -> str | None:
    if not (record.get("conyuge_nombre") or record.get("conyuge_nif")):
        return None
    spouse_record = {
        "cliente_nombre": record.get("conyuge_nombre"),
        "cliente_nif": record.get("conyuge_nif"),
        "cliente_fecha_nacimiento": record.get("conyuge_fecha_nacimiento"),
    }
    return ensure_cliente(conn, empresa_id, service, spouse_record, now)


def build_renta_entry(record: dict, ejercicio: str | None = None, estado_presentacion: str | None = None) -> dict:
    ejercicio = str(ejercicio or record.get("ejercicio") or DEFAULT_EJERCICIO).strip() or DEFAULT_EJERCICIO
    estado_presentacion = detect_renta_doc_status(
        estado_presentacion or record.get("estado_presentacion") or record.get("doc_status")
    )
    patrimonio = {
        "base_imponible_general": record.get("base_imponible_general"),
        "base_imponible_ahorro": record.get("base_imponible_ahorro"),
        "base_liquidable_general": record.get("base_liquidable_general"),
        "casilla_505": record.get("casilla_505"),
        "base_liquidable_ahorro": record.get("base_liquidable_ahorro"),
        "direccion_inmueble_principal": record.get("direccion_inmueble_principal"),
        "referencia_catastral_principal": record.get("referencia_catastral_principal"),
        "prestamo_hipotecario_id": record.get("prestamo_hipotecario_id"),
    }
    return {
        "id": f"renta-{ejercicio}-{slug(record.get('cliente_nif') or record.get('cliente_nombre'))}",
        "ejercicio": ejercicio,
        "cliente_nombre": record.get("cliente_nombre"),
        "cliente_nif": record.get("cliente_nif"),
        "dni_expedicion": record.get("dni_expedicion") or "",
        "dni_caducidad": record.get("dni_caducidad") or "",
        "dni_permanente": 1 if str(record.get("dni_permanente") or "").strip().lower() in {"1", "true", "yes", "si", "sí"} else 0,
        "cliente_fecha_nacimiento": record.get("cliente_fecha_nacimiento") or "",
        "estado_civil": record.get("cliente_estado_civil") or "",
        "hijos_count": int(record.get("hijos_count") or 0),
        "hijos": record.get("hijos") or [],
        "casilla_505": record.get("casilla_505"),
        "resultado_declaracion": record.get("resultado_declaracion"),
        "presentacion_fecha": record.get("presentacion_fecha") or "",
        "direccion": record.get("direccion") or record.get("direccion_inmueble_principal") or "",
        "codigo_postal": record.get("codigo_postal") or "",
        "poblacion": record.get("poblacion") or "",
        "provincia": record.get("provincia") or "",
        "cuentas_detectadas": record.get("cuentas_detectadas") or [],
        "pagadores_detectados": record.get("pagadores_detectados") or [],
        "ingresos_principales_total": record.get("ingresos_principales_total"),
        "rendimientos_trabajo_total": record.get("rendimientos_trabajo_total"),
        "rendimientos_actividades_economicas_total": record.get("rendimientos_actividades_economicas_total"),
        "rendimientos_capital_inmobiliario_total": record.get("rendimientos_capital_inmobiliario_total"),
        "rendimientos_capital_mobiliario_total": record.get("rendimientos_capital_mobiliario_total"),
        "patrimonio": patrimonio,
        "source_files": record.get("source_files") or [],
        "source_file_count": record.get("source_file_count") or 0,
        "precio_servicio": record.get("precio_servicio"),
        "responsable": record.get("responsable") or "",
        "cobrada": 1 if str(record.get("cobrada") or "").strip().lower() in {"1", "true", "yes", "si", "sí"} else 0,
        "forma_cobro": record.get("forma_cobro") or "",
        "estado_presentacion": estado_presentacion,
        "doc_status": estado_presentacion,
        "gestion_notas": record.get("gestion_notas") or "",
        "confidence_score": record.get("confidence_score"),
        "notas_ocr": record,
    }


def load_renta_detalles(raw: object) -> dict:
    if isinstance(raw, dict):
        payload = raw
    else:
        text = compact_spaces(raw)
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
    notes = compact_spaces(payload.get("notes"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        entries = []
    return {"notes": notes, "entries": entries}


def ensure_cliente_gestoria_renta(
    conn: sqlite3.Connection,
    cliente_id: str,
    record: dict,
    now: str,
    ejercicio: str | None = None,
    estado_presentacion: str | None = None,
) -> None:
    entry = build_renta_entry(record, ejercicio=ejercicio, estado_presentacion=estado_presentacion)
    existing = conn.execute(
        "SELECT id, tipo_cliente, renta_detalles FROM cliente_gestoria WHERE cliente_id = ?",
        (cliente_id,),
    ).fetchone()
    payload = {"notes": "", "entries": [entry]}
    if existing:
        current = load_renta_detalles(existing["renta_detalles"])
        merged = []
        replaced = False
        for item in current.get("entries") or []:
            same_year = str(item.get("ejercicio") or "") == str(entry.get("ejercicio") or "")
            same_nif = compact_spaces(item.get("cliente_nif")).upper() == compact_spaces(entry.get("cliente_nif")).upper()
            if same_year and same_nif:
                merged.append(entry)
                replaced = True
            else:
                merged.append(item)
        if not replaced:
            merged.append(entry)
        payload = {"notes": current.get("notes") or "", "entries": merged}
        conn.execute(
            """
            UPDATE cliente_gestoria
            SET mod_renta = 1, renta_detalles = ?, updated_at = datetime(?)
            WHERE cliente_id = ?
            """,
            (json.dumps(payload, ensure_ascii=False), now, cliente_id),
        )
        return
    conn.execute(
        """
        INSERT INTO cliente_gestoria (
          id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
          mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
        ) VALUES (
          ?, ?, ?, 0, 0, 0, 1, 0, 0, 0, ?, datetime(?), datetime(?)
        )
        """,
        (
            uuid.uuid4().hex,
            cliente_id,
            "Particular",
            json.dumps(payload, ensure_ascii=False),
            now,
            now,
        ),
    )


def ensure_gestoria_renta_trabajo(
    conn: sqlite3.Connection,
    empresa_id: str,
    cliente_id: str,
    record: dict,
    now: str,
    ejercicio: str | None = None,
    estado_presentacion: str | None = None,
) -> None:
    ejercicio = str(ejercicio or record.get("ejercicio") or DEFAULT_EJERCICIO).strip() or DEFAULT_EJERCICIO
    estado_presentacion = detect_renta_doc_status(
        estado_presentacion or record.get("estado_presentacion") or record.get("doc_status")
    )
    row = conn.execute(
        """
        SELECT id
        FROM gestoria_trabajos
        WHERE empresa_id = ? AND cliente_id = ? AND tipo_trabajo = ? AND COALESCE(notas, '') LIKE ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (empresa_id, cliente_id, RENTA_ACTIVITY_TYPE, f"%Renta {ejercicio}%"),
    ).fetchone()
    trabajo_estado = "Finalizado" if estado_presentacion == "Presentada" else "En espera"
    responsable = record.get("responsable") or "Importación renta"
    notas = (
        f"Renta {ejercicio} {estado_presentacion.lower()} · DNI {record.get('cliente_nif') or ''} · "
        f"Resultado {record.get('resultado_declaracion') if record.get('resultado_declaracion') is not None else '-'}"
    ).strip()
    if row:
        conn.execute(
            """
            UPDATE gestoria_trabajos
            SET estado = ?, fecha_inicio = ?, fecha_fin = ?, responsable = ?, notas = ?, updated_at = datetime(?)
            WHERE id = ?
            """,
            (
                trabajo_estado,
                record.get("presentacion_fecha") or "",
                record.get("presentacion_fecha") or "",
                responsable,
                notas,
                now,
                row["id"],
            ),
        )
        return
    conn.execute(
        """
        INSERT INTO gestoria_trabajos (
          id, empresa_id, cliente_id, tipo_trabajo, estado, fecha_inicio, fecha_fin, responsable, importe, notas, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            uuid.uuid4().hex,
            empresa_id,
            cliente_id,
            RENTA_ACTIVITY_TYPE,
            trabajo_estado,
            record.get("presentacion_fecha") or "",
            record.get("presentacion_fecha") or "",
            responsable,
            record.get("resultado_declaracion"),
            notas,
            now,
            now,
        ),
    )


def ensure_gestoria_renta_docs(
    conn: sqlite3.Connection,
    empresa_id: str,
    cliente_id: str,
    record: dict,
    now: str,
    ejercicio: str | None = None,
    estado_presentacion: str | None = None,
) -> None:
    docs_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'gestoria_docs'"
    ).fetchone()
    if not docs_table:
        return
    ejercicio = str(ejercicio or record.get("ejercicio") or DEFAULT_EJERCICIO).strip() or DEFAULT_EJERCICIO
    estado_presentacion = detect_renta_doc_status(
        estado_presentacion or record.get("estado_presentacion") or record.get("doc_status")
    )
    presentacion_fecha = record.get("presentacion_fecha") or ""
    for source in record.get("source_files") or []:
        source_text = compact_spaces(source)
        if not source_text:
            continue
        doc_name = f"Renta {ejercicio} · {estado_presentacion} · {Path(source_text).name}"
        source_url = source_text if source_text.startswith("/uploads/") or source_text.startswith("http") else ""
        if source_url:
            existing = conn.execute(
                """
                SELECT id
                FROM gestoria_docs
                WHERE cliente_id = ?
                  AND LOWER(COALESCE(referencia_tipo, '')) = 'renta'
                  AND (
                    LOWER(COALESCE(doc_url, '')) = LOWER(?)
                    OR LOWER(COALESCE(nombre, '')) = LOWER(?)
                  )
                LIMIT 1
                """,
                (cliente_id, source_url, doc_name),
            ).fetchone()
        else:
            existing = conn.execute(
                """
                SELECT id
                FROM gestoria_docs
                WHERE cliente_id = ?
                  AND LOWER(COALESCE(referencia_tipo, '')) = 'renta'
                  AND LOWER(COALESCE(nombre, '')) = LOWER(?)
                LIMIT 1
                """,
                (cliente_id, doc_name),
            ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE gestoria_docs
                SET empresa_id = ?,
                    tipo = ?,
                    fecha = COALESCE(NULLIF(?, ''), fecha),
                    estado = ?,
                    notas = COALESCE(NULLIF(?, ''), notas),
                    doc_url = COALESCE(NULLIF(?, ''), doc_url),
                    updated_at = datetime(?)
                WHERE id = ?
                """,
                (
                    empresa_id,
                    f"Renta {estado_presentacion}",
                    presentacion_fecha,
                    estado_presentacion,
                    source_text,
                    source_url,
                    now,
                    existing["id"],
                ),
            )
            continue
        conn.execute(
            """
            INSERT INTO gestoria_docs (
              id, empresa_id, cliente_id, referencia_tipo, referencia_id,
              nombre, tipo, fecha, estado, notas, doc_key, doc_url,
              calidad_ocr, campos_ocr, created_at, updated_at
            ) VALUES (
              ?, ?, ?, 'renta', ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                uuid.uuid4().hex,
                empresa_id,
                cliente_id,
                f"renta-{ejercicio}-{slug(record.get('cliente_nif') or record.get('cliente_nombre'))}",
                doc_name,
                f"Renta {estado_presentacion}",
                presentacion_fecha,
                estado_presentacion,
                source_text or estado_presentacion,
                source_url or None,
                record.get("text_source") or "",
                ",".join(sorted(k for k, v in record.items() if v not in (None, "", [], {}))),
                now,
                now,
            ),
        )


def upsert_asesoramiento_renta(
    conn: sqlite3.Connection,
    empresa_id: str,
    cliente1_id: str,
    cliente2_id: str | None,
    record: dict,
    now: str,
    ejercicio: str | None = None,
) -> str:
    ejercicio = str(ejercicio or record.get("ejercicio") or DEFAULT_EJERCICIO).strip() or DEFAULT_EJERCICIO
    existing = conn.execute(
        """
        SELECT id FROM asesoramientos_financiacion
        WHERE empresa_id = ? AND origen = ? AND cliente1_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (empresa_id, f"Renta {ejercicio}", cliente1_id),
    ).fetchone()
    payload = {
        "fecha": record.get("presentacion_fecha") or datetime.now(timezone.utc).date().isoformat(),
        "estado": "Renta importada",
        "cliente1_id": cliente1_id,
        "cliente1_nombre": record.get("cliente_nombre"),
        "cliente1_dni": record.get("cliente_nif"),
        "cliente1_fecha_nacimiento": record.get("cliente_fecha_nacimiento"),
        "cliente1_estado_civil": record.get("cliente_estado_civil"),
        "cliente1_hijos": str(record.get("hijos_count") or ""),
        "cliente1_ingresos": record.get("ingresos_principales_total") or record.get("rendimientos_trabajo_total"),
        "cliente1_patrimonio": json.dumps(
            {
                "ingresos_principales_total": record.get("ingresos_principales_total"),
                "rendimientos_trabajo_total": record.get("rendimientos_trabajo_total"),
                "rendimientos_capital_inmobiliario_total": record.get("rendimientos_capital_inmobiliario_total"),
                "base_imponible_general": record.get("base_imponible_general"),
                "base_imponible_ahorro": record.get("base_imponible_ahorro"),
                "base_liquidable_general": record.get("base_liquidable_general"),
                "base_liquidable_ahorro": record.get("base_liquidable_ahorro"),
                "direccion_inmueble_principal": record.get("direccion_inmueble_principal"),
                "referencia_catastral_principal": record.get("referencia_catastral_principal"),
            },
            ensure_ascii=False,
        ),
        "cliente1_prestamos": record.get("prestamo_hipotecario_id") or "",
        "cliente2_id": cliente2_id,
        "cliente2_nombre": record.get("conyuge_nombre") or "",
        "cliente2_dni": record.get("conyuge_nif") or "",
        "cliente2_fecha_nacimiento": record.get("conyuge_fecha_nacimiento") or "",
        "ingresos_conjuntos": record.get("ingresos_principales_total") or record.get("rendimientos_trabajo_total"),
        "notas": "\n".join(record.get("source_files") or []),
        "notas_ocr": json.dumps(record, ensure_ascii=False),
        "calidad_ocr": "pdf_text",
        "campos_ocr": ",".join(sorted(k for k, v in record.items() if v not in (None, "", [], {}))),
    }
    if existing:
        record_id = existing[0]
        set_clause = ", ".join([f"{key} = ?" for key in payload.keys()])
        conn.execute(
            f"UPDATE asesoramientos_financiacion SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
            (*payload.values(), now, record_id),
        )
        return record_id
    record_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO asesoramientos_financiacion (
          id, empresa_id, origen, fecha, estado, cliente1_id, cliente1_nombre, cliente1_dni,
          cliente1_fecha_nacimiento, cliente1_estado_civil, cliente1_hijos, cliente1_ingresos,
          cliente1_patrimonio, cliente1_prestamos, cliente2_id, cliente2_nombre, cliente2_dni,
          cliente2_fecha_nacimiento, ingresos_conjuntos, notas, notas_ocr, calidad_ocr, campos_ocr,
          created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            record_id,
            empresa_id,
            f"Renta {ejercicio}",
            payload["fecha"],
            payload["estado"],
            payload["cliente1_id"],
            payload["cliente1_nombre"],
            payload["cliente1_dni"],
            payload["cliente1_fecha_nacimiento"],
            payload["cliente1_estado_civil"],
            payload["cliente1_hijos"],
            payload["cliente1_ingresos"],
            payload["cliente1_patrimonio"],
            payload["cliente1_prestamos"],
            payload["cliente2_id"],
            payload["cliente2_nombre"],
            payload["cliente2_dni"],
            payload["cliente2_fecha_nacimiento"],
            payload["ingresos_conjuntos"],
            payload["notas"],
            payload["notas_ocr"],
            payload["calidad_ocr"],
            payload["campos_ocr"],
            now,
            now,
        ),
    )
    return record_id


def scan_folder(source_dir: Path, limit: int = 0) -> list[dict]:
    records_by_key: dict[str, dict] = defaultdict(dict)
    pdfs = sorted(source_dir.rglob("*.pdf"))
    if limit > 0:
        pdfs = pdfs[:limit]
    total = len(pdfs)
    for idx, pdf_path in enumerate(pdfs, start=1):
        if idx == 1 or idx % 25 == 0 or idx == total:
            print(f"[rentas] Procesando PDF {idx}/{total}: {pdf_path.name}", file=sys.stderr)
        fields = parse_pdf(pdf_path)
        key = build_record_key(fields, pdf_path)
        if not key:
            continue
        record = records_by_key.setdefault(key, {})
        merge_record(record, fields, pdf_path)
    finalized = [finalize_record(record) for record in records_by_key.values()]
    finalized = [record for record in finalized if not should_skip_auxiliary_record(record)]
    return sorted(finalized, key=lambda item: compact_spaces(item.get("cliente_nombre")))


def write_json(out_path: Path, records: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_to_db(
    db_path: Path,
    records: list[dict],
    company_name: str,
    ejercicio: str | None = None,
    estado_presentacion: str = "Presentada",
) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        company_id = ensure_company_id(conn, company_name)
        now = datetime.now(timezone.utc).isoformat()
        created_or_updated = 0
        linked_spouses = 0
        skipped_for_review = 0
        for record in records:
            if not record.get("safe_to_apply"):
                skipped_for_review += 1
                continue
            record = dict(record)
            record["ejercicio"] = str(ejercicio or record.get("ejercicio") or DEFAULT_EJERCICIO)
            record["estado_presentacion"] = detect_renta_doc_status(
                record.get("estado_presentacion") or estado_presentacion
            )
            cliente_id = ensure_cliente(conn, company_id, RENTA_SERVICE, record, now)
            if not cliente_id:
                skipped_for_review += 1
                continue
            spouse_id = ensure_spouse(conn, company_id, RENTA_SERVICE, record, now)
            if spouse_id:
                linked_spouses += 1
            ensure_cliente_gestoria_renta(
                conn,
                cliente_id,
                record,
                now,
                ejercicio=record["ejercicio"],
                estado_presentacion=record["estado_presentacion"],
            )
            ensure_gestoria_renta_docs(
                conn,
                company_id,
                cliente_id,
                record,
                now,
                ejercicio=record["ejercicio"],
                estado_presentacion=record["estado_presentacion"],
            )
            ensure_gestoria_renta_trabajo(
                conn,
                company_id,
                cliente_id,
                record,
                now,
                ejercicio=record["ejercicio"],
                estado_presentacion=record["estado_presentacion"],
            )
            created_or_updated += 1
        conn.commit()
        return {
            "records_upserted": created_or_updated,
            "spouses_linked": linked_spouses,
            "skipped_for_review": skipped_for_review,
            "company": company_name,
        }
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa campañas de renta al CRM.")
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR, help="Carpeta raíz con PDFs de renta.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite del CRM.")
    parser.add_argument("--company", default=GESTORIA_COMPANY, help="Empresa destino para vincular clientes.")
    parser.add_argument("--out-json", default=f"data/rentas_{DEFAULT_EJERCICIO}_preview.json", help="Salida JSON consolidada.")
    parser.add_argument("--out-csv", default=f"data/rentas_{DEFAULT_EJERCICIO}_preview.csv", help="Salida CSV resumida.")
    parser.add_argument("--review-json", default=f"data/rentas_{DEFAULT_EJERCICIO}_review_queue.json", help="Cola de revisión para casos dudosos.")
    parser.add_argument("--ejercicio", default=DEFAULT_EJERCICIO, help="Ejercicio fiscal a cargar. En 2026, normalmente será 2025.")
    parser.add_argument("--estado-presentacion", default="Presentada", choices=("Borrador", "Presentada"), help="Estado documental de la renta importada.")
    parser.add_argument("--limit", type=int, default=0, help="Limita el número de PDFs procesados.")
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios en SQLite.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser()
    if not source_dir.exists():
        raise SystemExit(f"No existe la carpeta origen: {source_dir}")
    records = scan_folder(source_dir, limit=max(0, int(args.limit or 0)))
    out_path = Path(args.out_json).expanduser()
    write_json(out_path, records)
    csv_path = Path(args.out_csv).expanduser()
    write_csv_summary(csv_path, records)
    review_path = Path(args.review_json).expanduser()
    review_queue = build_review_queue(records)
    write_json(review_path, review_queue)
    validation = build_validation_summary(records)
    print(f"Registros consolidados: {len(records)}")
    print(f"Preview JSON: {out_path}")
    print(f"Preview CSV: {csv_path}")
    print(f"Review queue: {review_path}")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if args.apply:
        result = apply_to_db(
            Path(args.db).expanduser(),
            records,
            args.company,
            ejercicio=str(args.ejercicio or DEFAULT_EJERCICIO),
            estado_presentacion=str(args.estado_presentacion or "Presentada"),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
