#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


GESTORIA_COMPANY = "Fincas Velazquez"
DEFAULT_SOURCE_DIR = (
    "/Users/miguelperezrodriguez/Library/Mobile Documents/com~apple~CloudDocs/"
    "MIGUE TRABAJO/RENTAS 2024"
)
RENTA_SERVICE = "gestoria"
RENTA_ACTIVITY_TYPE = "Declaración en periodo"
CRITICAL_FIELDS = (
    "cliente_nombre",
    "cliente_nif",
    "cliente_fecha_nacimiento",
    "ingresos_principales_total",
    "resultado_declaracion",
)


def norm_text(value: object) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def slug(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", norm_text(value)).strip("_")


def compact_spaces(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_ocr_text_value(value: object) -> str:
    text = compact_spaces(value)
    if not text:
        return ""
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"[|]+$", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return compact_spaces(text)


def looks_like_nif(value: object) -> bool:
    text = compact_spaces(value).upper().replace(" ", "").replace("-", "").replace(".", "")
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


def parse_date_ddmmyyyy(raw: object) -> str:
    text = compact_spaces(raw)
    if not text:
        return ""
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
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


def run_pdftotext(pdf_path: Path) -> str:
    proc = subprocess.run(
        ["pdftotext", str(pdf_path), "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout or ""


def run_tesseract_ocr(pdf_path: Path) -> str:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "page"
            proc = subprocess.run(
                ["pdftoppm", "-r", "300", "-png", str(pdf_path), str(prefix)],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                return ""
            chunks = []
            for image_path in sorted(Path(tmpdir).glob("*.png")):
                ocr = subprocess.run(
                    ["tesseract", str(image_path), "stdout", "-l", "spa+eng"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if ocr.returncode == 0 and compact_spaces(ocr.stdout):
                    chunks.append(ocr.stdout)
            return "\n".join(chunks)
    except FileNotFoundError:
        return ""


def get_pdf_text(pdf_path: Path) -> tuple[str, str]:
    text = run_pdftotext(pdf_path)
    if len(compact_spaces(text)) >= 40:
        return text, "pdftotext"
    ocr_text = run_tesseract_ocr(pdf_path)
    if compact_spaces(ocr_text):
        return ocr_text, "ocr"
    return text, "empty"


def classify_pdf(text: str, pdf_path: Path) -> str:
    upper = norm_text(text)
    name = norm_text(pdf_path.name)
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
    if "renta 2024" in upper and "adjuntos" in upper:
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
    data["presentacion_fecha"] = parse_date_ddmmyyyy(
        re.search(r"Presentación realizada el:\s*([0-9]{2}-[0-9]{2}-[0-9]{4})", text)
        and re.search(r"Presentación realizada el:\s*([0-9]{2}-[0-9]{2}-[0-9]{4})", text).group(1)
    )
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
        data["cliente_nif"] = compact_spaces(titular.group(1)).upper()
        data["cliente_nombre"] = compact_spaces(titular.group(2))
        data["cliente_nif_source"] = "modelo_100"
        data["cliente_nombre_source"] = "modelo_100"
        data["cliente_estado_civil"] = re.sub(r"^\(\d+\)\s*", "", compact_spaces(titular.group(4))).strip()
        data["cliente_fecha_nacimiento"] = parse_date_ddmmyyyy(titular.group(5))
    else:
        match = re.search(r"Primer declarante.*?\b([0-9A-Z]{8,10})\s+0001\b", text, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nif"] = compact_spaces(match.group(1)).upper()
            data["cliente_nif_source"] = "modelo_100"
        match = re.search(r"\b0001\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+0002\b", text, re.IGNORECASE | re.DOTALL)
        if match:
            data["cliente_nombre"] = compact_spaces(match.group(1))
            data["cliente_nombre_source"] = "modelo_100"
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
            data["cliente_nif"] = presentador_nif.group(1).upper()
            data["cliente_nif_source"] = "presentador"
    if not data.get("cliente_nif"):
        nif_0001 = extract_single_code_value(text, "0001", r"([A-Z0-9]{8,10})")
        if nif_0001:
            data["cliente_nif"] = nif_0001.upper()
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
    if not looks_like_person_name(data.get("cliente_nombre")):
        presentador = compact_spaces(data.get("cliente_nombre")) if data.get("cliente_nombre_source") == "presentador" else ""
        if not presentador:
            match = re.search(r"Apellidos y Nombre / Razon social:\s*(.+?)\s+En calidad de:", normalized, re.IGNORECASE | re.DOTALL)
            if match:
                presentador = compact_spaces(match.group(1))
        if looks_like_person_name(presentador):
            data["cliente_nombre"] = presentador
            data["cliente_nombre_source"] = "presentador"
    conyuge_nif = re.search(r"(?:Cónyuge.*?NIF\s+)?([A-Z0-9]{8,10})\s+0013\b", text, re.IGNORECASE | re.DOTALL)
    if conyuge_nif:
        data["conyuge_nif"] = compact_spaces(conyuge_nif.group(1)).upper()
    conyuge_nombre = re.search(r"(?:Apellidos y nombre\s+)?([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+0014\b", text, re.IGNORECASE | re.DOTALL)
    if conyuge_nombre:
        nombre = compact_spaces(conyuge_nombre.group(1))
        if nombre and "primer declarante" not in norm_text(nombre):
            data["conyuge_nombre"] = nombre
    conyuge_fecha = re.search(r"Fecha de nacimiento del cónyuge\s+([0-9]{2}/[0-9]{2}/[0-9]{4})\s+0060\b", text)
    if conyuge_fecha:
        data["conyuge_fecha_nacimiento"] = parse_date_ddmmyyyy(conyuge_fecha.group(1))
    if not data.get("conyuge_nif"):
        match = re.search(r"C[oó]nyuge .*?NIF\s+([A-Z0-9]{8,10})", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["conyuge_nif"] = compact_spaces(match.group(1)).upper()
    if not data.get("conyuge_nombre"):
        match = re.search(r"C[oó]nyuge .*?Apellidos y nombre\s+([A-ZÁÉÍÓÚÜÑ ,'./-]+?)\s+Sexo del c[oó]nyuge", normalized, re.IGNORECASE | re.DOTALL)
        if match:
            data["conyuge_nombre"] = compact_spaces(match.group(1))
    if not data.get("conyuge_fecha_nacimiento"):
        match = re.search(r"Fecha de nacimiento del c[oó]nyuge\s+([0-9]{2}/[0-9]{2}/[0-9]{4})", normalized, re.IGNORECASE)
        if match:
            data["conyuge_fecha_nacimiento"] = parse_date_ddmmyyyy(match.group(1))
    comunidad = re.search(r"\n([A-ZÁÉÍÓÚÜÑ ]+)\s+0070\b", text)
    if comunidad:
        data["comunidad_autonoma"] = compact_spaces(comunidad.group(1))

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
    if data.get("rendimientos_trabajo_total") is None:
        data["rendimientos_trabajo_total"] = extract_label_money(
            normalized,
            r"Total ingresos integros computables.*?\]\s*",
        )
    if data.get("rendimientos_trabajo_total") is None:
        data["rendimientos_trabajo_total"] = extract_money_near_line(
            normalized,
            r"Total ingresos integros computables|Retribuciones dinerarias",
        )
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
            r"Resultado de la declaraci[oó]n|Resultado a ingresar o devolver",
            window=4,
        )
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
    return data


def parse_datos_fiscales_text(text: str) -> dict:
    data: dict[str, object] = {"source_type": "datos_fiscales"}
    if not text:
        return data
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
    if poblacion:
        data["codigo_postal"] = poblacion.group(1)
        data["poblacion"] = compact_spaces(poblacion.group(2))
    if provincia:
        data["provincia"] = compact_spaces(provincia.group(1))
    ref = re.search(r"Referencia Catastral\s+([A-Z0-9]+)", text)
    if ref:
        data["referencia_catastral"] = ref.group(1)
    cuentas = sorted(set(re.findall(r"\b[0-9]{10,20}\b", text)))
    if cuentas:
        data["cuentas_detectadas"] = cuentas
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
    if first.parent.name and first.parent.name != "RENTAS 2024":
        return compact_spaces(first.parent.name)
    stem = first.stem
    stem = re.sub(r"\b[0-9]{2,}[_/-]?[0-9A-Z]{2,}\b", " ", stem)
    stem = re.sub(r"\b[0-9A-Z]{5,}\b", " ", stem)
    stem = re.sub(r"\b\d{2}[_/-]?\d{2}[_/-]?\d{4}\b", " ", stem)
    stem = re.sub(r"\b\d{6,8}\b", " ", stem)
    stem = re.sub(r"_+", " ", stem)
    return compact_spaces(stem)


def extract_dni_expiry_from_sources(paths: list[str]) -> str:
    for raw_path in paths or []:
        stem = Path(raw_path).stem
        matches = re.findall(r"(\d{8})(?!.*\d{8})", stem)
        if not matches:
            continue
        value = parse_date_ddmmyyyy(matches[-1])
        if value:
            return value
    return ""


def should_skip_auxiliary_record(record: dict) -> bool:
    source_types = set(record.get("source_types") or [])
    if not source_types:
        return False
    if source_types.issubset({"soporte_cliente", "notas"}):
        return True
    return False


def finalize_record(record: dict) -> dict:
    result = dict(record)
    result["source_files"] = sorted(result.get("source_files") or [])
    result["source_file_count"] = len(result["source_files"])
    result["source_types"] = sorted(result.get("source_types") or [])
    if not result.get("dni_caducidad"):
        result["dni_caducidad"] = extract_dni_expiry_from_sources(result["source_files"])
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
    score = max(0, min(100, score))
    safe_to_apply = (
        not critical_missing
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
            set_clause = ", ".join([f"{key} = COALESCE({key}, ?)" for key in updates])
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


def build_renta_entry(record: dict) -> dict:
    ejercicio = "2024"
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
        "dni_caducidad": record.get("dni_caducidad") or "",
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
) -> None:
    entry = build_renta_entry(record)
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
) -> None:
    ejercicio = "2024"
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
    notas = (
        f"Renta {ejercicio} importada · DNI {record.get('cliente_nif') or ''} · "
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
                "Finalizado",
                record.get("presentacion_fecha") or "",
                record.get("presentacion_fecha") or "",
                "Importación renta",
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
          ?, ?, ?, ?, 'Finalizado', ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            uuid.uuid4().hex,
            empresa_id,
            cliente_id,
            RENTA_ACTIVITY_TYPE,
            record.get("presentacion_fecha") or "",
            record.get("presentacion_fecha") or "",
            "Importación renta",
            record.get("resultado_declaracion"),
            notas,
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
) -> str:
    existing = conn.execute(
        """
        SELECT id FROM asesoramientos_financiacion
        WHERE empresa_id = ? AND origen = 'Renta 2024' AND cliente1_id = ?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (empresa_id, cliente1_id),
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
          ?, ?, 'Renta 2024', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
        )
        """,
        (
            record_id,
            empresa_id,
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
    for pdf_path in pdfs:
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


def apply_to_db(db_path: Path, records: list[dict], company_name: str) -> dict:
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
            cliente_id = ensure_cliente(conn, company_id, RENTA_SERVICE, record, now)
            if not cliente_id:
                skipped_for_review += 1
                continue
            spouse_id = ensure_spouse(conn, company_id, RENTA_SERVICE, record, now)
            if spouse_id:
                linked_spouses += 1
            ensure_cliente_gestoria_renta(conn, cliente_id, record, now)
            ensure_gestoria_renta_trabajo(conn, company_id, cliente_id, record, now)
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
    parser = argparse.ArgumentParser(description="Importa rentas 2024 al CRM.")
    parser.add_argument("--source-dir", default=DEFAULT_SOURCE_DIR, help="Carpeta raíz con PDFs de renta.")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta a la SQLite del CRM.")
    parser.add_argument("--company", default=GESTORIA_COMPANY, help="Empresa destino para vincular clientes.")
    parser.add_argument("--out-json", default="data/rentas_2024_preview.json", help="Salida JSON consolidada.")
    parser.add_argument("--out-csv", default="data/rentas_2024_preview.csv", help="Salida CSV resumida.")
    parser.add_argument("--review-json", default="data/rentas_2024_review_queue.json", help="Cola de revisión para casos dudosos.")
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
        result = apply_to_db(Path(args.db).expanduser(), records, args.company)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
