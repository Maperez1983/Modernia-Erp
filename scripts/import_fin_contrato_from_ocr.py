#!/usr/bin/env python3
"""
Importa un "Contrato de intermediación" / "Información precontractual" (OCR en TXT)
como ficha en la tabla `hipotecas` de Financiaciones Modernia (SQLite).

Entrada esperada:
  - Carpeta con ficheros .txt generados por OCR (tesseract) de fotos/escaneos.
  - El script agrega la información de todos los TXT y construye:
      - hipotecas.cliente_inmueble_json
      - hipotecas.hipoteca_detalle_json
  - Crea (si no existe) un `clientes` para C1 y lo vincula a hipotecas.cliente_id.

Uso:
  python3 scripts/import_fin_contrato_from_ocr.py \
    --ocr-dir ~/tmp_fin/ocr \
    --db data/erp_import2.sqlite
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


FINANCIACIONES_EMPRESA_ID = "5a676274-4ba8-4ec5-8010-af2bd2bfada7"

_MONTHS = {
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_nif(raw: str) -> str:
    txt = (raw or "").strip().upper()
    # OCR habituales: '¥' por 'Y', etc.
    txt = txt.replace("¥", "Y").replace("￥", "Y")
    txt = re.sub(r"[^0-9A-Z]", "", txt)
    return txt


def first_email(text: str) -> str:
    m = re.search(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text, flags=re.I)
    return m.group(1).strip() if m else ""


def first_phone(text: str) -> str:
    # 9 dígitos (España) con o sin espacios
    m = re.search(r"(?<!\d)(\d[\d ]{7,}\d)(?!\d)", text)
    if not m:
        return ""
    digits = re.sub(r"\D", "", m.group(1))
    if len(digits) < 9:
        return ""
    return digits[:9]


def parse_eur_amount(text: str) -> Optional[float]:
    # Acepta "173.700€", "41.200€", "173700", etc.
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:[.,]\d{1,2})?\s*€?", text)
    if not m:
        return None
    raw = m.group(0)
    raw = raw.replace("€", "").strip()
    raw = raw.replace(" ", "")
    # 173.700 -> 173700 ; 173.700,50 -> 173700.50
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw and raw.count(",") == 1 and len(raw.split(",")[-1]) in (1, 2):
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_spanish_date(text: str) -> str:
    """
    Busca: "En Malaga a 21 de enero de 2026" y devuelve ISO "2026-01-21".
    """
    m = re.search(
        r"\bEn\s+[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+\s+a\s+(\d{1,2})\s+de\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+)\s+de\s+(\d{4})\b",
        text,
        flags=re.I,
    )
    if not m:
        return ""
    day = int(m.group(1))
    month_name = m.group(2).strip().lower()
    year = int(m.group(3))
    month = _MONTHS.get(month_name, 0)
    if not month:
        return ""
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return ""


def slice_between(text: str, start_pat: str, end_pat: str) -> str:
    start = re.search(start_pat, text, flags=re.I)
    if not start:
        return ""
    end = re.search(end_pat, text[start.end() :], flags=re.I)
    if not end:
        return text[start.end() :].strip()
    return text[start.end() : start.end() + end.start()].strip()


@dataclass
class Party:
    nombre: str = ""
    nif: str = ""
    email: str = ""
    telefono: str = ""
    domicilio: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "nombre": self.nombre,
            "nif": self.nif,
            "email": self.email,
            "telefono": self.telefono,
            "domicilio": self.domicilio,
        }


def parse_party(text: str, key: str) -> Party:
    # Extrae chunk aproximado entre "C1:"/"C2:" y el siguiente marcador.
    other = "C2" if key.upper() == "C1" else "C1"
    chunk = slice_between(text, rf"\b{re.escape(key)}\s*:\s*", rf"\b{re.escape(other)}\s*:\s*")
    if not chunk:
        # fallback: sólo hasta salto de línea grande
        m = re.search(rf"\b{re.escape(key)}\s*:\s*(.+)", text, flags=re.I)
        chunk = m.group(1) if m else ""
    chunk = re.sub(r"\s+", " ", chunk).strip()
    if not chunk:
        return Party()

    # Nombre: antes de ", con"
    nombre = ""
    m = re.search(r"^(?:D\.|DA\.|Dª\.|DON|DOÑA)?\s*([^,]+?)\s*,\s*con\b", chunk, flags=re.I)
    if m:
        nombre = m.group(1).strip()

    nif = ""
    # OCR frecuente: "N.1.F." (con '1' en lugar de 'I') o "NIF"
    m = re.search(r"\bN\.?\s*[I1L]\.?\s*F\.?\s*:\s*([0-9A-Z¥￥.\-]+)\b", chunk, flags=re.I)
    if not m:
        m = re.search(r"\bNIF\s*:\s*([0-9A-Z¥￥.\-]+)\b", chunk, flags=re.I)
    if m:
        nif = normalize_nif(m.group(1))

    email = first_email(chunk)
    telefono = first_phone(chunk)

    domicilio = ""
    m = re.search(r"\bdomicilio\s+en\s+(.+?)(?:\bemail\b|\btel[eé]fono\b|$)", chunk, flags=re.I)
    if m:
        domicilio = m.group(1).strip(" ,.;")
        domicilio = re.sub(r"[|=]+", " ", domicilio)
        domicilio = re.sub(r"\s+", " ", domicilio).strip()

    return Party(nombre=nombre, nif=nif, email=email, telefono=telefono, domicilio=domicilio)


def parse_inmueble(text: str) -> dict[str, str]:
    chunk = slice_between(text, r"\binmueble\s+sito\s+en\s+", r"\batendiendo\b")
    chunk = re.sub(r"\s+", " ", chunk).strip(" ,.;")
    if not chunk:
        return {}
    # intenta extraer CP al final
    cp = ""
    m = re.search(r"\b(\d{5})\b", chunk)
    if m:
        cp = m.group(1)
    # localidad/provincia son heurísticos; si aparece "Malaga" lo usamos.
    localidad = ""
    provincia = ""
    if re.search(r"\bmalaga\b", chunk, flags=re.I):
        localidad = "Málaga"
        provincia = "Málaga"
    return {
        "direccion": chunk,
        "localidad": localidad,
        "provincia": provincia,
        "codigo_postal": cp,
    }


def parse_preferencias(text: str) -> dict[str, Any]:
    prefs: dict[str, Any] = {}
    m = re.search(r"IMPORTE\s+DEL\s+PRESTAMO\s*:\s*([^\n]+)", text, flags=re.I)
    if m:
        prefs["importe_prestamo"] = parse_eur_amount(m.group(1))
    m = re.search(r"PLAZO\s+DE\s+AMORTIZACION\s*:\s*([0-9]{1,2})", text, flags=re.I)
    if m:
        prefs["plazo_anos"] = int(m.group(1))
    # OCR: a veces introduce caracteres ("2xFUO"); buscamos por tokens.
    m = re.search(r"TIPO\s+DE\s*INTERES\s*:\s*([^\n]+)", text, flags=re.I)
    if m:
        raw_line = m.group(1).strip().lower()
        if "fij" in raw_line:
            prefs["tipo_interes"] = "Fijo"
        elif "fuo" in raw_line or "fjo" in raw_line or "fio" in raw_line:
            prefs["tipo_interes"] = "Fijo"
        elif "vari" in raw_line:
            prefs["tipo_interes"] = "Variable"
        elif "mix" in raw_line:
            prefs["tipo_interes"] = "Mixto"
    # Garantía: si aparece "vivienda habitual) Si" marcamos Sí
    if re.search(r"vivienda\s+habitual\)\s*si", text, flags=re.I):
        prefs["garantia_vivienda_habitual"] = "Sí"
    m = re.search(r"COMISION\s+MAXIMA\s+DE\s+APERTURA\s*:\s*([0-9.,]+)\s*%", text, flags=re.I)
    if m:
        try:
            prefs["comision_apertura_max"] = float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    m = re.search(r"OTRAS\s*:\s*(.+)", text, flags=re.I)
    if m:
        prefs["otras"] = m.group(1).strip()
        # intenta extraer aportación si aparece
        ap = re.search(r"aportan.*?(\d[\d.\s]*€?)", prefs["otras"], flags=re.I)
        if ap:
            prefs["aportacion_compra"] = parse_eur_amount(ap.group(1))
    return prefs


def parse_precontractual(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    # Identificadores de registro
    reg_parts = []
    m = re.search(r"Cr[eé]dito\s+Inmobiliario\s*:\s*([A-Z]-\d+)", text, flags=re.I)
    if m:
        reg_parts.append(m.group(1).strip())
    m = re.search(r"REEIF\s*:\s*([0-9/ ]+)", text, flags=re.I)
    if m:
        raw = m.group(1).strip()
        raw = re.sub(r"\s+", "", raw)
        if re.fullmatch(r"\d{1,4}/\d{4}", raw):
            reg_parts.append(f"REEIF {raw}")
    if reg_parts:
        out["registro"] = " / ".join(reg_parts)
    # Seguro RC
    aseguradora = ""
    poliza = ""
    m = re.search(r"Compania\s+aseguradora\s*:\s*([^\n]+)", text, flags=re.I)
    if m:
        aseguradora = re.sub(r"\s+", " ", m.group(1)).strip(" .")
    m = re.search(r"N[ºo®]\s+de\s+poliza\s*:\s*([A-Z0-9]+)", text, flags=re.I)
    if m:
        poliza = m.group(1).strip()
    if aseguradora or poliza:
        out["seguro_rc"] = " · ".join([x for x in [aseguradora, f"Póliza {poliza}" if poliza else ""] if x])
    return out


def merge_dict(dst: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    for k, v in src.items():
        if v in (None, "", {}, []):
            continue
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            merge_dict(dst[k], v)  # type: ignore[index]
        else:
            current = dst.get(k)
            # Evita sobrescribir strings "más completas" por otras más cortas.
            if isinstance(current, str) and isinstance(v, str) and current.strip() and v.strip():
                dst[k] = v if len(v.strip()) > len(current.strip()) else current
            else:
                dst[k] = v
    return dst


def parse_contract_from_ocr_texts(texts: list[str]) -> dict[str, Any]:
    merged_text = "\n".join(texts)
    fecha = ""
    for t in texts:
        fecha = parse_spanish_date(t) or fecha
    c1 = Party()
    c2 = Party()
    inmueble: dict[str, str] = {}
    preferencias: dict[str, Any] = {}
    precontractual: dict[str, Any] = {}
    for t in texts:
        c1_candidate = parse_party(t, "C1")
        c2_candidate = parse_party(t, "C2")
        if c1_candidate.nombre or c1_candidate.nif:
            c1 = c1_candidate
        if c2_candidate.nombre or c2_candidate.nif:
            c2 = c2_candidate
        merge_dict(inmueble, parse_inmueble(t))
        merge_dict(preferencias, parse_preferencias(t))
        merge_dict(precontractual, parse_precontractual(t))

    # Refina registro (buscando el mejor REEIF y el mejor identificador E-xxx).
    merged_text = "\n".join(texts)
    if merged_text:
        id_candidates = re.findall(r"\b([A-Z]-\d{2,4})\b", merged_text, flags=re.I)
        # Preferimos E-xxx si aparece.
        inter_id = ""
        if id_candidates:
            upper = [c.upper() for c in id_candidates]
            inter_id = next((c for c in upper if c.startswith("E-")), upper[0])

        reei_candidates = []
        for m in re.finditer(r"REEIF\s*:\s*([0-9/ ]+)", merged_text, flags=re.I):
            raw = re.sub(r"\s+", "", m.group(1).strip())
            if re.fullmatch(r"\d{1,4}/\d{4}", raw):
                reei_candidates.append(raw)
        best_reeif = ""
        if reei_candidates:
            # Preferimos 4 dígitos antes de '/', y luego el más largo.
            reei_candidates.sort(key=lambda s: (len(s.split('/')[0]) == 4, len(s)), reverse=True)
            best_reeif = reei_candidates[0]

        reg_parts = []
        if inter_id:
            reg_parts.append(inter_id)
        if best_reeif:
            reg_parts.append(f"REEIF {best_reeif}")
        if reg_parts:
            precontractual["registro"] = " / ".join(reg_parts)

    return {
        "fecha_contrato": fecha,
        "c1": c1,
        "c2": c2,
        "inmueble": inmueble,
        "preferencias": preferencias,
        "precontractual": precontractual,
        "merged_text": merged_text,
    }


def upsert_cliente(conn: sqlite3.Connection, empresa_id: str, party: Party, now: str) -> str:
    nif = normalize_nif(party.nif)
    if nif:
        row = conn.execute(
            "SELECT id FROM clientes WHERE empresa_id = ? AND REPLACE(UPPER(nif), '.', '') = ? LIMIT 1",
            (empresa_id, nif),
        ).fetchone()
        if row:
            cliente_id = str(row["id"])  # type: ignore[index]
            conn.execute(
                """
                UPDATE clientes
                SET nombre = COALESCE(NULLIF(?, ''), nombre),
                    nif = COALESCE(NULLIF(?, ''), nif),
                    email = COALESCE(NULLIF(?, ''), email),
                    telefono = COALESCE(NULLIF(?, ''), telefono),
                    direccion = COALESCE(NULLIF(?, ''), direccion),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    party.nombre,
                    nif,
                    party.email,
                    party.telefono,
                    party.domicilio,
                    now,
                    cliente_id,
                ),
            )
            return cliente_id
    cliente_id = os.urandom(16).hex()
    conn.execute(
        """
        INSERT INTO clientes (
          id, empresa_id, nombre, nif, telefono, email, tipo, perfil, estado, created_at, updated_at, direccion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            cliente_id,
            empresa_id,
            party.nombre or "Cliente",
            nif or None,
            party.telefono or None,
            party.email or None,
            "Física",
            "Autónomo",
            "Activo",
            now,
            now,
            party.domicilio or None,
        ),
    )
    return cliente_id


def insert_hipoteca(conn: sqlite3.Connection, empresa_id: str, payload: dict[str, Any], now: str) -> str:
    hipoteca_id = os.urandom(16).hex()
    conn.execute(
        """
        INSERT INTO hipotecas (
          id, empresa_id, cliente, cliente_id, banco, precio, importe_hipoteca,
          porcentaje, entrada, comision, oficina, fecha_encargo, encargo, tipo_hipoteca,
          fecha_firma, cesion, comision_juan, comision_modernia, inmobiliaria_compra, asesor,
          estado, anio, created_at, updated_at, cliente_inmueble_json, hipoteca_detalle_json, liquidacion_json
        ) VALUES (
          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            hipoteca_id,
            empresa_id,
            payload.get("cliente"),
            payload.get("cliente_id"),
            payload.get("banco"),
            payload.get("precio"),
            payload.get("importe_hipoteca"),
            payload.get("porcentaje"),
            payload.get("entrada"),
            payload.get("comision"),
            payload.get("oficina"),
            payload.get("fecha_encargo"),
            payload.get("encargo"),
            payload.get("tipo_hipoteca"),
            payload.get("fecha_firma"),
            payload.get("cesion"),
            payload.get("comision_juan"),
            payload.get("comision_modernia"),
            payload.get("inmobiliaria_compra"),
            payload.get("asesor"),
            payload.get("estado"),
            payload.get("anio"),
            now,
            now,
            payload.get("cliente_inmueble_json"),
            payload.get("hipoteca_detalle_json"),
            payload.get("liquidacion_json"),
        ),
    )
    return hipoteca_id


def main() -> None:
    parser = argparse.ArgumentParser(description="Importa contrato (OCR) a hipotecas (Financiaciones).")
    parser.add_argument("--ocr-dir", required=True, help="Carpeta con .txt OCR (tesseract).")
    parser.add_argument("--db", default="data/erp_import2.sqlite", help="Ruta SQLite local.")
    parser.add_argument("--empresa-id", default=FINANCIACIONES_EMPRESA_ID, help="empresa_id destino.")
    parser.add_argument("--dry-run", action="store_true", help="No escribe en DB; imprime el JSON.")
    parser.add_argument("--force", action="store_true", help="Inserta aunque detecte posible duplicado.")
    args = parser.parse_args()

    ocr_dir = Path(args.ocr_dir).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    if not ocr_dir.exists():
        raise SystemExit(f"No existe ocr-dir: {ocr_dir}")
    if not db_path.exists():
        raise SystemExit(f"No existe db: {db_path}")

    txts = sorted(p for p in ocr_dir.iterdir() if p.suffix.lower() == ".txt")
    if not txts:
        raise SystemExit(f"No hay .txt en: {ocr_dir}")
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in txts]

    parsed = parse_contract_from_ocr_texts(texts)
    c1: Party = parsed["c1"]
    c2: Party = parsed["c2"]

    cliente_name = " + ".join([x for x in [c1.nombre.strip(), c2.nombre.strip()] if x])
    inmueble = parsed["inmueble"] or {}
    preferencias = parsed["preferencias"] or {}
    precontractual = parsed["precontractual"] or {}

    cliente_inmueble = {
        "inmueble": inmueble,
        "comprador": {"c1": c1.as_json(), "c2": c2.as_json()},
        "prestataria": {"p1": {"source": "c1"}, "p2": {"source": "c2"}},
    }

    hipoteca_detalle = {
        "preferencias": {
            "plazo_anos": preferencias.get("plazo_anos"),
            "tipo_interes": preferencias.get("tipo_interes"),
            "garantia_vivienda_habitual": preferencias.get("garantia_vivienda_habitual"),
            "comision_apertura_max": preferencias.get("comision_apertura_max"),
            "otras": preferencias.get("otras"),
        },
        "precontractual": precontractual,
    }

    fecha_encargo = parsed.get("fecha_contrato") or ""
    importe_prestamo = preferencias.get("importe_prestamo")
    aportacion = preferencias.get("aportacion_compra")

    payload: dict[str, Any] = {
        "cliente": cliente_name or "Cliente",
        "cliente_id": "",
        "banco": "",
        "precio": None,
        "importe_hipoteca": float(importe_prestamo) if isinstance(importe_prestamo, (int, float)) else None,
        "porcentaje": None,
        "entrada": float(aportacion) if isinstance(aportacion, (int, float)) else None,
        "comision": None,
        "oficina": "",
        "fecha_encargo": fecha_encargo or None,
        "encargo": "Sí" if fecha_encargo else "",
        "tipo_hipoteca": "Compra",
        "fecha_firma": None,
        "cesion": None,
        "comision_juan": None,
        "comision_modernia": None,
        "inmobiliaria_compra": "",
        "asesor": "",
        "estado": "Encargo" if fecha_encargo else "Pendiente",
        "anio": int(fecha_encargo.split("-")[0]) if fecha_encargo else None,
        "cliente_inmueble_json": json.dumps(cliente_inmueble, ensure_ascii=False, separators=(",", ":")),
        "hipoteca_detalle_json": json.dumps(hipoteca_detalle, ensure_ascii=False, separators=(",", ":")),
        "liquidacion_json": json.dumps({}, ensure_ascii=False, separators=(",", ":")),
    }

    if args.dry_run:
        print(json.dumps({"hipoteca": payload, "parsed": _preview(parsed)}, ensure_ascii=False, indent=2))
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        now = now_iso()
        conn.execute("BEGIN IMMEDIATE;")
        cliente_id = upsert_cliente(conn, args.empresa_id, c1, now)
        payload["cliente_id"] = cliente_id

        # Dedupe simple: mismo cliente + fecha_encargo + importe_hipoteca
        if not args.force:
            existing = conn.execute(
                """
                SELECT id FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(cliente)) = LOWER(TRIM(?))
                  AND COALESCE(fecha_encargo, '') = COALESCE(?, '')
                  AND COALESCE(importe_hipoteca, 0) = COALESCE(?, 0)
                LIMIT 1
                """,
                (args.empresa_id, payload["cliente"], payload.get("fecha_encargo"), payload.get("importe_hipoteca")),
            ).fetchone()
            if existing:
                raise SystemExit(f"Ya existe una hipoteca similar: {existing['id']} (usa --force para insertar igual)")

        hipoteca_id = insert_hipoteca(conn, args.empresa_id, payload, now)
        conn.commit()
        print(json.dumps({"ok": True, "hipoteca_id": hipoteca_id, "cliente_id": cliente_id}, ensure_ascii=False))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _preview(parsed: dict[str, Any]) -> dict[str, Any]:
    c1: Party = parsed["c1"]
    c2: Party = parsed["c2"]
    out = dict(parsed)
    out["c1"] = c1.as_json()
    out["c2"] = c2.as_json()
    out.pop("merged_text", None)
    return out


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
