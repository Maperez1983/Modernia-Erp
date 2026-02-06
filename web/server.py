#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sqlite3
import urllib.parse
import hashlib
import base64
import re
import subprocess
import tempfile
import shutil
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent / "assets"
UPLOADS = ROOT / "uploads"
DB_DEFAULT = ROOT.parent / "data" / "erp_import2.sqlite"
TESSDATA_DIR = "/opt/homebrew/share/tessdata"
POSTAL_CATALOG_PATH = ROOT.parent / "data" / "catalogos" / "postal_catalogo.csv"
ENV_PATH = ROOT.parent / ".env"

def load_env_file():
    if not ENV_PATH.exists():
        return
    try:
        with ENV_PATH.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        return

load_env_file()
S3_BUCKET = os.environ.get("AWS_S3_BUCKET") or os.environ.get("S3_BUCKET")
S3_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

POSTAL_PROVINCES = {
    "01": "Álava",
    "02": "Albacete",
    "03": "Alicante",
    "04": "Almería",
    "05": "Ávila",
    "06": "Badajoz",
    "07": "Islas Baleares",
    "08": "Barcelona",
    "09": "Burgos",
    "10": "Cáceres",
    "11": "Cádiz",
    "12": "Castellón",
    "13": "Ciudad Real",
    "14": "Córdoba",
    "15": "A Coruña",
    "16": "Cuenca",
    "17": "Girona",
    "18": "Granada",
    "19": "Guadalajara",
    "20": "Guipúzcoa",
    "21": "Huelva",
    "22": "Huesca",
    "23": "Jaén",
    "24": "León",
    "25": "Lleida",
    "26": "La Rioja",
    "27": "Lugo",
    "28": "Madrid",
    "29": "Málaga",
    "30": "Murcia",
    "31": "Navarra",
    "32": "Ourense",
    "33": "Asturias",
    "34": "Palencia",
    "35": "Las Palmas",
    "36": "Pontevedra",
    "37": "Salamanca",
    "38": "Santa Cruz de Tenerife",
    "39": "Cantabria",
    "40": "Segovia",
    "41": "Sevilla",
    "42": "Soria",
    "43": "Tarragona",
    "44": "Teruel",
    "45": "Toledo",
    "46": "Valencia",
    "47": "Valladolid",
    "48": "Vizcaya",
    "49": "Zamora",
    "50": "Zaragoza",
    "51": "Ceuta",
    "52": "Melilla",
}

def normalize_postal_code(value):
    code = re.sub(r"\D", "", str(value or ""))[:5]
    if len(code) == 4:
        code = f"0{code}"
    return code if len(code) == 5 else ""

def normalize_phone(value):
    if not value:
        return ""
    digits = re.sub(r"\D+", "", str(value))
    if not digits:
        return ""
    if digits.startswith("34") and len(digits) > 9:
        digits = digits[-9:]
    if len(digits) == 9:
        return digits
    return digits

def normalize_email(value):
    if not value:
        return ""
    return str(value).strip().lower()

def normalize_person_name(value):
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text

def normalize_company_name(value):
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text

def normalize_poliza_key(value):
    if not value:
        return ""
    text = re.sub(r"\s+", "", str(value).upper())
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text

def normalize_company_key(value):
    if not value:
        return ""
    text = normalize_company_name(value).upper()
    text = re.sub(r"[^A-Z0-9]", "", text)
    return text

def normalize_header(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())

def load_postal_catalog(conn):
    if not POSTAL_CATALOG_PATH.exists():
        return
    count_row = conn.execute("SELECT COUNT(*) AS total FROM postal_catalogo").fetchone()
    total = 0
    if count_row:
        try:
            total = count_row["total"]
        except (TypeError, KeyError, IndexError):
            total = count_row[0]
    if total:
        return
    encodings = ("utf-8-sig", "latin-1")
    for encoding in encodings:
        try:
            with POSTAL_CATALOG_PATH.open("r", encoding=encoding, newline="") as handle:
                reader = csv.DictReader(handle)
                if not reader.fieldnames:
                    return
                headers = {normalize_header(name): name for name in reader.fieldnames}
                cp_key = next(
                    (headers[k] for k in headers if k in ("codigopostal", "codigo_postal", "postalcode", "cp", "codigo")),
                    None,
                )
                pob_key = next(
                    (headers[k] for k in headers if k in ("poblacion", "municipio", "municipionombre", "localidad", "ciudad", "nombre")),
                    None,
                )
                prov_key = next(
                    (headers[k] for k in headers if k in ("provincia", "provincianombre", "province")),
                    None,
                )
                if not cp_key:
                    return
                batch = []
                seen = set()
                for row in reader:
                    cp_raw = row.get(cp_key, "")
                    cp = normalize_postal_code(cp_raw)
                    if not cp:
                        continue
                    poblacion = (row.get(pob_key, "") if pob_key else "") or ""
                    poblacion = str(poblacion).strip()
                    provincia = (row.get(prov_key, "") if prov_key else "") or ""
                    provincia = str(provincia).strip()
                    if not provincia:
                        provincia = POSTAL_PROVINCES.get(cp[:2], "")
                    key = (cp, poblacion, provincia)
                    if key in seen:
                        continue
                    seen.add(key)
                    batch.append(key)
                    if len(batch) >= 5000:
                        conn.executemany(
                            "INSERT INTO postal_catalogo (codigo_postal, poblacion, provincia) VALUES (?, ?, ?)",
                            batch,
                        )
                        batch = []
                if batch:
                    conn.executemany(
                        "INSERT INTO postal_catalogo (codigo_postal, poblacion, provincia) VALUES (?, ?, ?)",
                        batch,
                    )
            return
        except UnicodeDecodeError:
            continue

def hash_password(password):
    if not password:
        return None
    salt = os.urandom(16).hex()
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"{salt}${digest}"

def detect_ocr_lang():
    if os.path.isdir(TESSDATA_DIR):
        has_spa = os.path.exists(os.path.join(TESSDATA_DIR, "spa.traineddata"))
        has_eng = os.path.exists(os.path.join(TESSDATA_DIR, "eng.traineddata"))
        if has_spa and has_eng:
            return "spa+eng"
        if has_spa:
            return "spa"
        if has_eng:
            return "eng"
    return "spa+eng"


def s3_client():
    try:
        import boto3
    except ImportError:
        return None
    if not S3_BUCKET or not S3_REGION:
        return None
    return boto3.client("s3", region_name=S3_REGION)


def s3_safe_key(prefix, filename):
    base = os.path.basename(filename or "archivo.pdf")
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rand = os.urandom(4).hex()
    prefix = prefix.strip("/").strip() if prefix else "seguros"
    return f"{prefix}/{stamp}_{rand}_{safe}"

def preprocess_image_for_ocr(src_path, out_path=None):
    tmp_base = tempfile.gettempdir()
    created = False
    if not out_path:
        tmp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=tmp_base)
        out_path = tmp_file.name
        tmp_file.close()
        created = True
    magick = shutil.which("magick") or shutil.which("convert")
    if magick and os.path.exists(magick):
        try:
            subprocess.run(
                [
                    magick,
                    src_path,
                    "-colorspace",
                    "Gray",
                    "-density",
                    "300",
                    "-resize",
                    "2500x2500",
                    "-deskew",
                    "40%",
                    "-sharpen",
                    "0x1",
                    "-contrast-stretch",
                    "1%x1%",
                    out_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return out_path, created
        except Exception:
            pass
    try:
        subprocess.run(
            ["sips", "-s", "format", "png", src_path, "--out", out_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            subprocess.run(
                ["sips", "-Z", "2400", out_path, "--out", out_path],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass
        return out_path, created
    except Exception:
        return src_path, created

def ocr_image_file(image_path):
    lang = detect_ocr_lang()
    tesseract_cmd = (
        shutil.which("tesseract")
        or "/opt/homebrew/bin/tesseract"
        or "/usr/local/bin/tesseract"
    )
    if not tesseract_cmd or not os.path.exists(tesseract_cmd):
        return "", "tesseract no encontrado en PATH"
    env = os.environ.copy()
    if os.path.isdir(TESSDATA_DIR):
        env["TESSDATA_PREFIX"] = TESSDATA_DIR
    tmp_base = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(dir=tmp_base) as tmpdir:
        processed, created = preprocess_image_for_ocr(image_path)
        def run_tesseract(psm):
            result = subprocess.run(
                [
                    tesseract_cmd,
                    processed,
                    "stdout",
                    "-l",
                    lang,
                    "--oem",
                    "1",
                    "--psm",
                    str(psm),
                    "-c",
                    "user_defined_dpi=300",
                    "-c",
                    "preserve_interword_spaces=1",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
            )
            return result.stdout or ""
        try:
            candidates = []
            for psm in (6, 4, 11):
                try:
                    candidates.append(run_tesseract(psm))
                except subprocess.CalledProcessError:
                    continue
            if not candidates:
                return "", "tesseract: sin salida"
            best = max(candidates, key=lambda t: (len(t.strip()), sum(ch.isdigit() for ch in t)))
            return best, ""
        except subprocess.CalledProcessError as err:
            return "", f"tesseract: {err.stderr.strip()}"
        except Exception as err:
            return "", f"tesseract: {err}"
        finally:
            if created and processed and os.path.exists(processed):
                try:
                    os.unlink(processed)
                except Exception:
                    pass

def ocr_image_external(image_bytes):
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    api_key = os.environ.get("GOOGLE_VISION_API_KEY") or os.environ.get("VISION_API_KEY")
    auth_header = None
    if credentials_path and os.path.exists(credentials_path):
        try:
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
        except Exception:
            return "", "OCR externo: instala google-auth y requests (pip install google-auth requests)"
        try:
            creds = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            creds.refresh(Request())
            auth_header = f"Bearer {creds.token}"
        except Exception as err:
            return "", f"OCR externo: credenciales inválidas ({err})"
    elif not api_key:
        return "", "OCR externo no configurado"
    payload = {
        "requests": [
            {
                "image": {"content": base64.b64encode(image_bytes).decode("utf-8")},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            }
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    if auth_header:
        url = "https://vision.googleapis.com/v1/images:annotate"
        headers = {"Content-Type": "application/json", "Authorization": auth_header}
    else:
        url = f"https://vision.googleapis.com/v1/images:annotate?key={api_key}"
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        return "", f"OCR externo: {err}"
    try:
        text = res["responses"][0].get("fullTextAnnotation", {}).get("text", "")
        return text, ""
    except Exception:
        return "", "OCR externo: sin texto"

def external_ocr_available():
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    api_key = os.environ.get("GOOGLE_VISION_API_KEY") or os.environ.get("VISION_API_KEY")
    return bool(api_key) or (credentials_path and os.path.exists(credentials_path))

def docai_available():
    processor_id = os.environ.get("DOCUMENTAI_PROCESSOR_ID") or os.environ.get("DOC_AI_PROCESSOR_ID")
    return bool(processor_id)

def normalize_field_label(value):
    value = value or ""
    value = value.lower()
    value = value.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value

def ocr_image_docai(image_bytes, mime_type):
    credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not credentials_path or not os.path.exists(credentials_path):
        return "", {}, "Document AI: credenciales no configuradas"
    processor_id = os.environ.get("DOCUMENTAI_PROCESSOR_ID") or os.environ.get("DOC_AI_PROCESSOR_ID")
    if not processor_id:
        return "", {}, "Document AI: falta DOCUMENTAI_PROCESSOR_ID"
    location = os.environ.get("DOCUMENTAI_LOCATION") or "eu"
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except Exception:
        return "", {}, "Document AI: instala google-auth y requests"
    try:
        creds = service_account.Credentials.from_service_account_file(
            credentials_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        creds.refresh(Request())
        project_id = creds.project_id
    except Exception as err:
        return "", {}, f"Document AI: credenciales inválidas ({err})"
    if not project_id:
        return "", {}, "Document AI: project_id no encontrado"
    url = (
        f"https://{location}-documentai.googleapis.com/v1/projects/{project_id}"
        f"/locations/{location}/processors/{processor_id}:process"
    )
    payload = {
        "rawDocument": {
            "content": base64.b64encode(image_bytes).decode("utf-8"),
            "mimeType": mime_type or "image/jpeg",
        }
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {creds.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        try:
            detail = err.read().decode("utf-8")
        except Exception:
            detail = ""
        return "", {}, f"Document AI: {err} {detail}".strip()
    except Exception as err:
        return "", {}, f"Document AI: {err}"
    doc = res.get("document") or {}
    text = doc.get("text", "")
    fields = {}
    occurrences = {}
    for field in doc.get("pages", []) or []:
        for form_field in field.get("formFields", []) or []:
            name_text = ""
            value_text = ""
            name = form_field.get("fieldName", {}).get("textAnchor", {}).get("textSegments", [])
            for seg in name:
                try:
                    start = int(seg.get("startIndex", 0))
                    end = int(seg.get("endIndex", 0))
                    name_text += text[start:end]
                except Exception:
                    continue
            value = form_field.get("fieldValue", {}).get("textAnchor", {}).get("textSegments", [])
            for seg in value:
                try:
                    start = int(seg.get("startIndex", 0))
                    end = int(seg.get("endIndex", 0))
                    value_text += text[start:end]
                except Exception:
                    continue
            label = normalize_field_label(name_text)
            val = value_text.strip()
            if not label or not val:
                continue
            occurrences[label] = occurrences.get(label, 0) + 1
            key = label
            if label in (
                "nombre y apellidos",
                "nombre apellidos",
                "nombre",
                "dni",
                "nif",
                "telefono",
                "movil",
                "correo electronico",
                "email",
                "fecha nacimiento",
                "estado civil",
                "hijos",
                "profesion",
                "tipo contrato",
                "ingresos nomina",
                "ingresos",
                "nomina",
                "patrimonio alquiler",
                "prestamos",
            ):
                suffix = "1" if occurrences[label] == 1 else "2"
                key = f"{label} {suffix}"
            fields[key] = val
    return text, fields, ""

def map_docai_fields(doc_fields):
    doc_fields = doc_fields or {}
    def doc_pick(label, idx=1):
        key = f"{label} {idx}"
        return doc_fields.get(key, "") or doc_fields.get(label, "")
    fields = {}
    fields["cliente1_nombre"] = doc_pick("nombre y apellidos", 1) or doc_pick("nombre", 1)
    fields["cliente2_nombre"] = doc_pick("nombre y apellidos", 2) or doc_pick("nombre", 2)
    fields["cliente1_dni"] = doc_pick("dni", 1) or doc_pick("nif", 1)
    fields["cliente2_dni"] = doc_pick("dni", 2) or doc_pick("nif", 2)
    fields["cliente1_telefono"] = doc_pick("telefono", 1) or doc_pick("movil", 1)
    fields["cliente2_telefono"] = doc_pick("telefono", 2) or doc_pick("movil", 2)
    fields["cliente1_email"] = doc_pick("correo electronico", 1) or doc_pick("email", 1)
    fields["cliente2_email"] = doc_pick("correo electronico", 2) or doc_pick("email", 2)
    fields["cliente1_fecha_nacimiento"] = doc_pick("fecha nacimiento", 1)
    fields["cliente2_fecha_nacimiento"] = doc_pick("fecha nacimiento", 2)
    fields["cliente1_estado_civil"] = doc_pick("estado civil", 1)
    fields["cliente2_estado_civil"] = doc_pick("estado civil", 2)
    fields["cliente1_hijos"] = doc_pick("hijos", 1)
    fields["cliente2_hijos"] = doc_pick("hijos", 2)
    fields["cliente1_profesion"] = doc_pick("profesion", 1)
    fields["cliente2_profesion"] = doc_pick("profesion", 2)
    fields["cliente1_tipo_contrato"] = doc_pick("tipo contrato", 1)
    fields["cliente2_tipo_contrato"] = doc_pick("tipo contrato", 2)
    fields["cliente1_ingresos"] = doc_pick("ingresos nomina", 1) or doc_pick("ingresos", 1) or doc_pick("nomina", 1)
    fields["cliente2_ingresos"] = doc_pick("ingresos nomina", 2) or doc_pick("ingresos", 2) or doc_pick("nomina", 2)
    fields["cliente1_patrimonio"] = doc_pick("patrimonio alquiler", 1)
    fields["cliente2_patrimonio"] = doc_pick("patrimonio alquiler", 2)
    fields["cliente1_prestamos"] = doc_pick("prestamos", 1)
    fields["cliente2_prestamos"] = doc_pick("prestamos", 2)
    return fields

def map_docai_poliza_fields(doc_fields):
    doc_fields = doc_fields or {}
    def doc_pick(labels):
        for label in labels:
            key = normalize_field_label(label)
            if doc_fields.get(key):
                return doc_fields.get(key)
        return ""
    fields = {}
    fields["tomador"] = doc_pick([
        "tomador",
        "asegurado",
        "asegurado principal",
        "titular",
        "contratante",
        "nombre",
        "nombre y apellidos",
    ])
    fields["dni"] = doc_pick(["dni", "nif", "cif", "documento", "doc identificacion"])
    fields["telefono"] = doc_pick(["telefono", "móvil", "movil"])
    fields["email"] = doc_pick(["correo electronico", "email"])
    fields["direccion"] = doc_pick(["direccion", "domicilio"])
    fields["compania"] = doc_pick(["compania", "compañia", "aseguradora", "entidad aseguradora"])
    fields["ramo"] = doc_pick(["ramo", "modalidad", "producto"])
    fields["poliza_numero"] = doc_pick([
        "poliza",
        "numero poliza",
        "nº poliza",
        "número poliza",
        "certificado",
        "contrato",
    ])
    fields["fecha_efecto"] = doc_pick([
        "fecha efecto",
        "efecto",
        "inicio vigencia",
        "fecha inicio",
        "vigencia desde",
    ])
    fields["fecha_vencimiento"] = doc_pick([
        "fecha vencimiento",
        "vencimiento",
        "fin vigencia",
        "vigencia hasta",
    ])
    fields["prima_neta"] = doc_pick(["prima neta", "neta"])
    fields["prima_total"] = doc_pick(["prima total", "prima anual", "total recibo", "total"])
    return fields

def compute_ocr_quality(fields, required_keys=None):
    fields = fields or {}
    required_keys = required_keys or ()
    provided = [key for key, value in fields.items() if str(value or "").strip()]
    required_filled = [key for key in required_keys if str(fields.get(key) or "").strip()]
    total_required = len(required_keys)
    ratio = (len(required_filled) / total_required) if total_required else 0
    if total_required and ratio >= 0.75:
        calidad = "alta"
    elif total_required and ratio >= 0.45:
        calidad = "media"
    elif total_required:
        calidad = "baja"
    else:
        calidad = "desconocida"
    return {
        "calidad": calidad,
        "campos": provided,
        "required_filled": required_filled,
    }

def compute_fin_quality(fields):
    required = (
        "inmobiliaria_asesor",
        "fecha",
        "asesor",
        "cliente1_nombre",
        "cliente1_dni",
        "cliente1_telefono",
        "cliente1_email",
        "cliente1_ingresos",
    )
    return compute_ocr_quality(fields, required)

def openai_available():
    return bool(os.environ.get("OPENAI_API_KEY"))

def extract_openai_output(resp):
    if not resp:
        return ""
    if isinstance(resp, dict):
        if resp.get("output_text"):
            return resp.get("output_text")
        output = resp.get("output") or []
        parts = []
        for item in output:
            content = item.get("content") or []
            for block in content:
                if block.get("type") == "output_text":
                    parts.append(block.get("text", ""))
        if parts:
            return "\n".join(parts).strip()
    return ""

def call_openai(prompt, model=None, temperature=0.2, max_tokens=600):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "", "OPENAI_API_KEY no configurada"
    model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": "Eres un copiloto interno para un CRM de seguros. Responde en español.",
                    }
                ],
            },
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        "temperature": temperature,
        "max_output_tokens": max_tokens,
        "store": False,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        return "", f"OpenAI error: {err}"
    return extract_openai_output(res), ""

def call_openai_extract_fin(text, extra=""):
    prompt = (
        "Extrae datos de un asesoramiento financiero manuscrito. Responde solo JSON con claves conocidas, "
        "sin inventar. Usa los campos existentes del formulario (cliente1_nombre, cliente1_dni, cliente1_telefono, "
        "cliente1_email, cliente1_fecha_nacimiento, cliente1_estado_civil, cliente1_regimen, cliente1_hijos, "
        "cliente1_profesion, cliente1_tipo_contrato, cliente1_tiempo_contrato, cliente1_ingresos, cliente1_patrimonio, "
        "cliente1_prestamos, cliente1_prestamo_activo, cliente1_prestamo_entidad, cliente1_prestamo_resto, "
        "cliente2_nombre, cliente2_dni, cliente2_telefono, cliente2_email, cliente2_fecha_nacimiento, "
        "cliente2_estado_civil, cliente2_regimen, cliente2_hijos, cliente2_profesion, cliente2_tipo_contrato, "
        "cliente2_tiempo_contrato, cliente2_ingresos, cliente2_patrimonio, cliente2_prestamos, cliente2_prestamo_activo, "
        "cliente2_prestamo_entidad, cliente2_prestamo_resto, ingresos_conjuntos, entidades_financieras, avalistas, "
        "aportacion_cv, inmobiliaria_asesor, asesor, fecha). "
        "Si no ves un dato, deja el valor vacío.\n\n"
        f"Texto OCR:\n{text}\n\n"
        f"Instrucciones extra: {extra}"
    )
    output, err = call_openai(prompt, temperature=0.1, max_tokens=800)
    if err:
        return {}, err
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            return data, ""
    except Exception:
        return {}, "OpenAI no devolvió JSON válido"
    return {}, "OpenAI no devolvió JSON"

def classify_seguros_document(text):
    cleaned = (text or "").lower()
    if not cleaned:
        return "otro"
    presupuesto_hits = [
        "presupuesto",
        "propuesta",
        "cotizacion",
        "cotización",
        "oferta",
        "simulacion",
        "simulación",
    ]
    poliza_hits = [
        "poliza",
        "póliza",
        "certificado",
        "contrato",
        "vigencia",
        "fecha de efecto",
        "fecha de vencimiento",
    ]
    score_presupuesto = sum(1 for key in presupuesto_hits if key in cleaned)
    score_poliza = sum(1 for key in poliza_hits if key in cleaned)
    if score_presupuesto > score_poliza:
        return "presupuesto"
    if score_poliza > 0:
        return "poliza"
    return "otro"

def merge_fields(base_fields, extra_fields):
    base_fields = base_fields or {}
    extra_fields = extra_fields or {}
    merged = dict(base_fields)
    for key, value in extra_fields.items():
        if not str(merged.get(key, "") or "").strip() and str(value or "").strip():
            merged[key] = value
    return merged

def merge_many_fields(*field_sets):
    merged = {}
    for fields in field_sets:
        for key, value in (fields or {}).items():
            if value is None:
                continue
            val = str(value).strip()
            if not val:
                continue
            if key not in merged or not str(merged.get(key) or "").strip():
                merged[key] = value
    return merged

def get_image_size(image_path):
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", image_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return None
    width = None
    height = None
    for line in result.stdout.splitlines():
        if "pixelWidth" in line:
            parts = re.findall(r"([0-9]+)", line)
            if parts:
                width = int(parts[-1])
        if "pixelHeight" in line:
            parts = re.findall(r"([0-9]+)", line)
            if parts:
                height = int(parts[-1])
    if width and height:
        return width, height
    return None

def crop_image_region(image_path, x, y, w, h, out_path):
    magick = shutil.which("magick") or shutil.which("convert")
    if magick and os.path.exists(magick):
        try:
            subprocess.run(
                [
                    magick,
                    image_path,
                    "-crop",
                    f"{int(w)}x{int(h)}+{int(x)}+{int(y)}",
                    "+repage",
                    out_path,
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            return True
        except Exception:
            pass
    try:
        subprocess.run(
            [
                "sips",
                "-c",
                str(int(h)),
                str(int(w)),
                "--cropOffset",
                str(int(x)),
                str(int(y)),
                image_path,
                "--out",
                out_path,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return True
    except Exception:
        return False

def prepare_image_bytes_for_vision(image_path):
    magick = shutil.which("magick") or shutil.which("convert")
    if magick and os.path.exists(magick):
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp = tmp_file.name
            subprocess.run(
                [
                    magick,
                    image_path,
                    "-colorspace",
                    "Gray",
                    "-auto-level",
                    "-contrast-stretch",
                    "2%x2%",
                    "-sharpen",
                    "0x1",
                    "-deskew",
                    "40%",
                    tmp,
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            with open(tmp, "rb") as handle:
                return handle.read()
        except Exception:
            pass
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except Exception:
                    pass
    try:
        with open(image_path, "rb") as handle:
            return handle.read()
    except Exception:
        return b""

def asesoramiento_image_boxes(width, height):
    return {
        "header": (0.03 * width, 0.17 * height, 0.94 * width, 0.16 * height),
        "cliente1": (0.03 * width, 0.31 * height, 0.94 * width, 0.21 * height),
        "cliente2": (0.03 * width, 0.54 * height, 0.94 * width, 0.20 * height),
        "resumen": (0.03 * width, 0.74 * height, 0.94 * width, 0.18 * height),
    }

def ocr_best_block(image_path, box, use_external):
    x, y, w, h = box
    shifts = (0.0, 0.02, 0.04, -0.02)
    best = ""
    best_err = ""
    for shift in shifts:
        tmp_crop = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
                tmp_crop = tmp_file.name
            y_shifted = max(0, y + shift * h * 2)
            if not crop_image_region(image_path, x, y_shifted, w, h, tmp_crop):
                continue
            text = ""
            err = ""
            if use_external:
                vision_bytes = prepare_image_bytes_for_vision(tmp_crop)
                if vision_bytes:
                    text, err = ocr_image_external(vision_bytes)
            if not text:
                text, err = ocr_image_file(tmp_crop)
            if len(text.strip()) > len(best.strip()):
                best = text
                best_err = err
        finally:
            if tmp_crop and os.path.exists(tmp_crop):
                try:
                    os.unlink(tmp_crop)
                except Exception:
                    pass
    return best, best_err

def ocr_pdf_first_page(pdf_path):
    is_pdf = str(pdf_path).lower().endswith(".pdf")
    tmpdir = None
    tmp_generated = ""
    img_path = pdf_path
    if is_pdf:
        try:
            images, img_err, tmp_generated = pdftoppm_first_page(pdf_path, pages=1)
            if not images:
                return "", img_err or "pdftoppm: sin imagen"
            img_path = images[0]
        except Exception as err:
            return "", f"pdftoppm: {err}"
    if not os.path.exists(img_path):
        if tmp_generated:
            shutil.rmtree(tmp_generated, ignore_errors=True)
        return "", "imagen no encontrada para OCR"
    lang = detect_ocr_lang()
    tesseract_cmd = (
        shutil.which("tesseract")
        or "/opt/homebrew/bin/tesseract"
        or "/usr/local/bin/tesseract"
    )
    if not tesseract_cmd or not os.path.exists(tesseract_cmd):
        if tmp_generated:
            shutil.rmtree(tmp_generated, ignore_errors=True)
        return "", "tesseract no encontrado en PATH"
    env = os.environ.copy()
    if os.path.isdir(TESSDATA_DIR):
        env["TESSDATA_PREFIX"] = TESSDATA_DIR
    def run_tesseract(psm):
        result = subprocess.run(
            [
                tesseract_cmd,
                img_path,
                "stdout",
                "-l",
                lang,
                "--oem",
                "1",
                "--psm",
                str(psm),
                "-c",
                "user_defined_dpi=300",
                "-c",
                "preserve_interword_spaces=1",
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        )
        return result.stdout or ""
    try:
        candidates = []
        for psm in (6, 4, 11):
            try:
                candidates.append(run_tesseract(psm))
            except subprocess.CalledProcessError:
                continue
        if not candidates:
            return "", "tesseract: sin salida"
        best = max(candidates, key=lambda t: (len(t.strip()), sum(ch.isdigit() for ch in t)))
        return best, ""
    except subprocess.CalledProcessError as err:
        return "", f"tesseract: {err.stderr.strip()}"
    except Exception as err:
        return "", f"tesseract: {err}"
    finally:
        if tmp_generated:
            shutil.rmtree(tmp_generated, ignore_errors=True)

def pdftotext_extract(pdf_path, pages=None):
    cmd = (
        shutil.which("pdftotext")
        or "/opt/homebrew/bin/pdftotext"
        or "/usr/local/bin/pdftotext"
    )
    if not cmd or not os.path.exists(cmd):
        return "", "pdftotext no encontrado"
    tmp_base = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(dir=tmp_base) as tmpdir:
        out_txt = os.path.join(tmpdir, "out.txt")
        args = [cmd, "-layout", "-nopgbrk"]
        if pages and isinstance(pages, int):
            args.extend(["-f", "1", "-l", str(pages)])
        try:
            subprocess.run(
                [*args, pdf_path, out_txt],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except subprocess.CalledProcessError as err:
            return "", f"pdftotext: {err.stderr.strip()}"
        except Exception as err:
            return "", f"pdftotext: {err}"
        if not os.path.exists(out_txt):
            return "", "pdftotext: sin salida"
        try:
            with open(out_txt, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read(), ""
        except Exception as err:
            return "", f"pdftotext: {err}"

def pdfinfo_page_size(pdf_path):
    cmd = (
        shutil.which("pdfinfo")
        or "/opt/homebrew/bin/pdfinfo"
        or "/usr/local/bin/pdfinfo"
    )
    if not cmd or not os.path.exists(cmd):
        return None
    try:
        result = subprocess.run(
            [cmd, pdf_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        return None
    for line in result.stdout.splitlines():
        if line.lower().startswith("page size"):
            parts = re.findall(r"([0-9]+(?:\.[0-9]+)?)", line)
            if len(parts) >= 2:
                try:
                    return float(parts[0]), float(parts[1])
                except Exception:
                    return None
    return None

def pdftotext_crop(pdf_path, x, y, w, h):
    cmd = (
        shutil.which("pdftotext")
        or "/opt/homebrew/bin/pdftotext"
        or "/usr/local/bin/pdftotext"
    )
    if not cmd or not os.path.exists(cmd):
        return ""
    tmp_base = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(dir=tmp_base) as tmpdir:
        out_txt = os.path.join(tmpdir, "crop.txt")
        args = [
            cmd,
            "-f",
            "1",
            "-l",
            "1",
            "-layout",
            "-nopgbrk",
            "-x",
            str(int(x)),
            "-y",
            str(int(y)),
            "-W",
            str(int(w)),
            "-H",
            str(int(h)),
        ]
        try:
            subprocess.run(
                [*args, pdf_path, out_txt],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            if not os.path.exists(out_txt):
                return ""
            with open(out_txt, "r", encoding="utf-8", errors="ignore") as handle:
                return handle.read()
        except Exception:
            return ""

def pdftoppm_first_page(pdf_path, pages=None):
    cmd = (
        shutil.which("pdftoppm")
        or "/opt/homebrew/bin/pdftoppm"
        or "/usr/local/bin/pdftoppm"
    )
    if not cmd or not os.path.exists(cmd):
        return [], "pdftoppm no encontrado", ""
    tmp_base = tempfile.gettempdir()
    tmpdir = tempfile.mkdtemp(dir=tmp_base)
    base = os.path.join(tmpdir, "page")
    args = [cmd, "-f", "1"]
    if pages and isinstance(pages, int):
        args.extend(["-l", str(pages)])
    try:
        subprocess.run(
            [*args, "-r", "400", "-gray", "-png", pdf_path, base],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as err:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [], f"pdftoppm: {err.stderr.strip()}", ""
    except Exception as err:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [], f"pdftoppm: {err}", ""
    images = sorted(
        [
            os.path.join(tmpdir, name)
            for name in os.listdir(tmpdir)
            if name.startswith("page-") and name.endswith(".png")
        ]
    )
    if not images:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return [], "pdftoppm: sin imagen", ""
    return images, "", tmpdir

def extract_pdf_text(pdf_path):
    text, err = pdftotext_extract(pdf_path, pages=None)
    if text and len(text.strip()) >= 30:
        return text, "", "pdftotext"
    images, img_err, tmpdir = pdftoppm_first_page(pdf_path, pages=None)
    if images:
        combined = []
        try:
            for img_path in images:
                page_text, ocr_err = ocr_pdf_first_page(img_path)
                if page_text:
                    combined.append(page_text)
            if combined:
                return "\n".join(combined), "", "tesseract"
            return "", ocr_err, "tesseract"
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
    text, ocr_err = ocr_pdf_first_page(pdf_path)
    if text:
        return text, "", "tesseract"
    return "", err or img_err or ocr_err, "tesseract"

def ocr_pdf_all_pages(pdf_path, use_external=False):
    images, img_err, tmpdir = pdftoppm_first_page(pdf_path, pages=None)
    if images:
        combined = []
        last_err = ""
        try:
            for img_path in images:
                page_text = ""
                ocr_err = ""
                if use_external:
                    vision_bytes = prepare_image_bytes_for_vision(img_path)
                    if vision_bytes:
                        page_text, ocr_err = ocr_image_external(vision_bytes)
                if not page_text:
                    page_text, ocr_err = ocr_pdf_first_page(img_path)
                if page_text:
                    combined.append(page_text)
                elif ocr_err:
                    last_err = ocr_err
            if combined:
                return "\n".join(combined), ""
            return "", last_err or img_err
        finally:
            if tmpdir:
                shutil.rmtree(tmpdir, ignore_errors=True)
    text, ocr_err = ocr_pdf_first_page(pdf_path)
    if text:
        return text, ""
    return "", ocr_err or img_err

def parse_poliza_text(text):
    cleaned = text.replace("\u00a0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("N°", "Nº").replace("Nº", "Nº")
    cleaned = cleaned.replace("Poliza", "Póliza").replace("Poliza", "Póliza")
    def pick(patterns):
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            m = re.search(pat, cleaned, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""
    def normalize_ocr_digits(value):
        if not value:
            return ""
        raw = str(value).strip()
        if not raw:
            return ""
        confusable = set("OoIlSB")
        ratio = sum(1 for ch in raw if ch.isdigit() or ch in confusable) / max(len(raw), 1)
        if ratio < 0.6:
            return raw
        table = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
        return raw.translate(table)
    def normalize_nif_ocr(value):
        if not value:
            return ""
        raw = str(value).strip().upper()
        if not raw:
            return ""
        raw = raw.replace(" ", "").replace("-", "").replace(".", "")
        raw = raw.replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5").replace("B", "8")
        raw = re.sub(r"[^A-Z0-9]", "", raw)
        if len(raw) > 9:
            raw = raw[:9]
        return raw
    def is_valid_nif(value):
        if not value:
            return False
        return bool(
            re.match(r"^[0-9]{8}[A-Z]$", value)
            or re.match(r"^[XYZ][0-9]{7}[A-Z]$", value)
            or re.match(r"^[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-Z]$", value)
        )
    def normalize_nif_candidate(value):
        if not value:
            return ""
        candidate = normalize_nif_ocr(value)
        if is_valid_nif(candidate):
            return candidate
        if len(candidate) >= 9:
            candidate = candidate[:9]
            if is_valid_nif(candidate):
                return candidate
        return ""
    def normalize_ocr_date(value):
        if not value:
            return ""
        raw = str(value).strip()
        if not raw:
            return ""
        raw = normalize_ocr_digits(raw)
        raw = re.sub(r"[.\-]", "/", raw)
        raw = re.sub(r"(\d)\s+(\d)", r"\1/\2", raw)
        return raw
    def extract_date_range(text_value):
        if not text_value:
            return "", ""
        value = normalize_ocr_date(text_value)
        value = value.replace(" a ", " hasta ").replace(" al ", " hasta ")
        match = re.search(
            r"(?:desde|vigencia\s+desde|periodo\s+del\s+seguro)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}).*?"
            r"(?:hasta|a)\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            value,
            re.IGNORECASE,
        )
        if match:
            return match.group(1), match.group(2)
        dates = re.findall(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", value)
        if len(dates) >= 2:
            return dates[0], dates[1]
        return "", ""
    def normalize_poliza_number(value, compania=""):
        if not value:
            return ""
        raw = normalize_ocr_digits(value)
        raw = re.sub(r"\s+", "", raw).strip()
        if not raw:
            return ""
        raw = re.sub(r"^(N[ºo]\s*)", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^POLIZA", "", raw, flags=re.IGNORECASE)
        raw = raw.strip(":-#")
        candidates = re.split(r"[ \t,/]+", raw)
        candidates = [c for c in candidates if c]
        if not candidates:
            candidates = [raw]
        normalized_company = (compania or "").upper().strip()
        numeric_only = {
            "LINEA DIRECTA",
            "DIRECT SEGUROS",
            "FENIX DIRECTO",
            "MAPFRE",
            "OCASO",
            "SANTA LUCIA",
            "SANTALUCIA",
        }
        alnum_structured = {
            "AXA",
            "ALLIANZ",
            "GENERALI",
            "REALE",
            "ZURICH",
            "HELVETIA",
            "CASER",
            "LIBERTY",
            "MUTUA MADRILEÑA",
            "MUTUA MADRILENA",
        }
        if normalized_company in numeric_only:
            digit_runs = re.findall(r"\d{5,}", raw)
            if digit_runs:
                return max(digit_runs, key=len)
        if normalized_company in alnum_structured:
            alnum = re.findall(r"[A-Z0-9]{6,}", raw)
            if alnum:
                return max(alnum, key=len)
        # Prefer token with most digits and length between 5 and 20
        def score_token(token):
            digits = len(re.findall(r"\d", token))
            length = len(token)
            if length < 5 or length > 24:
                return -1
            return digits * 2 + length
        best = max(candidates, key=score_token)
        return best
    def line_pick(keys):
        if not keys:
            return ""
        key_pattern = "|".join([re.escape(k) for k in keys])
        for line in text.splitlines():
            if re.search(rf"\\b({key_pattern})\\b", line, re.IGNORECASE):
                parts = re.split(r"[:\\-]", line, maxsplit=1)
                if len(parts) > 1:
                    value = parts[1].strip()
                    if value:
                        return value
                cleaned_line = re.sub(rf".*?\\b({key_pattern})\\b", "", line, flags=re.IGNORECASE).strip()
                if cleaned_line:
                    return cleaned_line
        return ""
    def pick_date_range(value):
        if not value:
            return "", ""
        dates = re.findall(r"\\d{1,2}[/-]\\d{1,2}[/-]\\d{2,4}", value)
        if len(dates) >= 2:
            return dates[0], dates[1]
        return "", ""
    fields = {}
    fields["tomador"] = pick([
        r"Nombre y apellidos\s*:\s*([^\n]+)",
        r"Titular\s*de\s*la\s*p[oó]liza\s*:\s*([^\n]+)",
        r"Datos\s+del\s+asegurado\s*[:\-]?\s*([^\n]+)",
        r"Asegurado/Tomador\s*[:\-]?\s*([^\n]+)",
        r"Tomador\s*y\s+Asegurado\s*[:\-]?\s*([^\n]+)",
        r"Datos\s+Tomador\s*/\s*Conductor\s*Nombre\s*([A-ZÁÉÍÓÚÑ\s]+?)\s+Doc",
        r"Nombre\s+([A-ZÁÉÍÓÚÑ\s]+?)\s+Doc\.?\s+Identificaci[oó]n",
        r"Tomador\s*de\s*seguro\s*:\s*([^\n]+)",
        r"Tomador\s*:\s*([^\n]+)",
        r"Asegurado\s*:\s*([^\n]+)",
        r"Asegurado\s*principal\s*:\s*([^\n]+)",
        r"Titular\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ\s]+)",
        r"Nombre\s*[:\-]?\s*([A-ZÁÉÍÓÚÑ\s]+)",
        r"Asegurado\s+y\s+Tomador\s*[:\-]?\s*([^\n]+)",
        r"Contratante\s*[:\-]?\s*([^\n]+)",
    ])
    if fields["tomador"]:
        fields["tomador"] = normalize_person_name(fields["tomador"])
    fields["dni"] = pick([
        r"Doc\.?\s*Identificaci[oó]n\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"NIF/CIF\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"DNI\s*[:\-]?\s*([0-9]{8}[A-Z])",
        r"NIF\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"CIF\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"DNI/NIF\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"Documento\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"\b([0-9]{8}[A-Z])\b",
        r"\b([ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-Z])\b",
        r"\b([XYZ][0-9]{7}[A-Z])\b",
    ])
    fields["telefono"] = pick([
        r"Tel[eé]fono\s*[:\-]?\s*([0-9\s]{9,})",
        r"M[oó]vil\s*[:\-]?\s*([0-9\s]{9,})",
    ])
    fields["email"] = pick([
        r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    ])
    fields["direccion"] = pick([
        r"Direcci[oó]n\s*[:\-]?\s*([^\n]+)",
        r"Direcci[oó]n\s+([A-Z0-9ÁÉÍÓÚÑ\s,./-]+?\s+\d{5}\s+[A-ZÁÉÍÓÚÑ\s]+)",
        r"Direcci[oó]n\s+([A-Z0-9ÁÉÍÓÚÑ\s,./-]+?)(?:\\s+Uso\\s+|\\s+Beneficiario|\\s+Cl[aá]usulas|\\s+Datos|\\n)",
        r"Domicilio\s*[:\-]?\s*([^\n]+)",
    ])
    fields["fecha_nacimiento"] = pick([
        r"Fecha de nacimiento\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"F\.?\s*nacimiento\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
    ])
    if fields["fecha_nacimiento"]:
        fields["fecha_nacimiento"] = normalize_ocr_date(fields["fecha_nacimiento"])
    fields["poliza_numero"] = pick([
        r"N[ºo]\s*de\s*p[oó]liza\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[ºo]\s*p[oó]liza\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[ºo]\s*de\s*P[oó]liza\s*([A-Z0-9/.\-]+)",
        r"N[ºo]\s+de\s+P[oó]liza\s+([A-Z0-9/.\-]+)",
        r"N[ºo]\s+P[oó]liza\s*[:#]?\s*([0-9]{5,})",
        r"(?:P[oó]liza|P[oó]liza\s*n[ºo]|N[ºo] P[oó]liza)\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"P[oó]liza\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"P[oó]liza\s*N[úu]m\.?\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"Poliza\s*No\.?\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[úu]m\.?\s*P[oó]liza\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[úu]mero\s*de\s*p[oó]liza\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"Certificado\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[ºo]\s*de\s*certificado\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"N[ºo]\s*de\s*contrato\s*[:#]?\s*([A-Z0-9/.\-]+)",
        r"Contrato\s*[:#]?\s*([A-Z0-9/.\-]+)",
    ])
    fields["compania"] = ""
    company_aliases = [
        (r"\bZURICH\b", "Zurich"),
        (r"\bMAPFRE\b", "Mapfre"),
        (r"\bAXA\b", "AXA"),
        (r"\bALLIANZ\b", "Allianz"),
        (r"\bGENERALI\b", "Generali"),
        (r"\bREALE\b", "Reale"),
        (r"\bOCASO\b", "Ocaso"),
        (r"\bPELAYO\b", "Pelayo"),
        (r"\bSANTA\s*LUCIA\b|\bSANTALUCIA\b", "Santa Lucia"),
        (r"\bFIATC\b", "Fiatc"),
        (r"\bLINEA\s*DIRECTA\b", "Línea Directa"),
        (r"\bLIBERTY\b", "Liberty"),
        (r"\bMUTUA\s*MADRILE[NÑ]A\b", "Mutua Madrileña"),
        (r"\bCAJA\s*RURAL\b", "Caja Rural"),
        (r"\bCASER\b", "Caser"),
        (r"\bPLUS\s*ULTRA\b", "Plus Ultra"),
        (r"\bFENIX\s*DIRECTO\b", "Fénix Directo"),
        (r"\bDIRECT\s*SEGUROS\b", "Direct Seguros"),
        (r"\bHEL\s*VETIA\b|\bHELVETIA\b", "Helvetia"),
        (r"\bGROUPAMA\b", "Groupama"),
        (r"\bNATIONALE\s*NEDERLANDEN\b", "Nationale Nederlanden"),
        (r"\bREALE\s*SEGUROS\b", "Reale"),
        (r"\bREALE\s*MUTUA\b", "Reale"),
        (r"\bSANTA\s*LUC[IÍ]A\b", "Santa Lucia"),
        (r"\bDAS\b", "DAS"),
        (r"\bARAG\b", "ARAG"),
        (r"\bPREVISORA\b", "Previsora General"),
        (r"\bPREVISORA\s*GENERAL\b", "Previsora General"),
        (r"\bSANITAS\b", "Sanitas"),
        (r"\bDKV\b", "DKV"),
        (r"\bADESLAS\b", "Adeslas"),
        (r"\bASISA\b", "Asisa"),
        (r"\bCATALANA\s*OCCIDENTE\b", "Catalana Occidente"),
        (r"\bNORTEHISPANA\b", "NorteHispana"),
        (r"\bSEGUROS\s*BILBAO\b", "Seguros Bilbao"),
        (r"\bBILBAO\s*SEGUROS\b", "Seguros Bilbao"),
        (r"\bSEGUROS\s*PELayo\b", "Pelayo"),
    ]
    for pattern, name in company_aliases:
        if re.search(pattern, cleaned, re.IGNORECASE):
            fields["compania"] = name
            break
    if not fields["compania"]:
        fields["compania"] = pick([
            r"Compa[ñn]ia\s*[:\-]?\s*([A-Z0-9\s\-]+)",
            r"Aseguradora\s*[:\-]?\s*([A-Z0-9\s\-]+)",
            r"Entidad\s+aseguradora\s*[:\-]?\s*([A-Z0-9\s\-]+)",
            r"Compa[ñn]ia\s+aseguradora\s*[:\-]?\s*([A-Z0-9\s\-]+)",
        ])
    if fields["compania"]:
        normalized = re.sub(r"[^A-Z0-9 ]+", " ", fields["compania"].upper())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        aliases = {
            "SANTALUCIA": "Santa Lucia",
            "SANTA LUCIA": "Santa Lucia",
            "MUTUA MADRILENA": "Mutua Madrileña",
            "MUTUA MADRILEÑA": "Mutua Madrileña",
            "LINEA DIRECTA": "Línea Directa",
            "DIRECT SEGUROS": "Direct Seguros",
            "FENIX DIRECTO": "Fénix Directo",
            "NATIONALE NEDERLANDEN": "Nationale Nederlanden",
            "CAJA RURAL": "Caja Rural",
            "PLUS ULTRA": "Plus Ultra",
            "HEL VETIA": "Helvetia",
            "SEGUROS BILBAO": "Seguros Bilbao",
            "CATALANA OCCIDENTE": "Catalana Occidente",
        }
        fields["compania"] = aliases.get(normalized, fields["compania"].strip())
    if fields["compania"]:
        fields["compania"] = normalize_company_name(fields["compania"])
    fields["fecha_efecto"] = pick([
        r"Fecha de efecto\s*:\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Efecto\s*:\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Vigencia\s*desde\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Fecha\s*inicio\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Inicio\s*vigencia\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Per[ií]odo\s*del\s*seguro\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Per[ií]odo\s*del\s*seguro\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})\s*[0-9:]*",
        r"Desde\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
    ])
    fields["fecha_vencimiento"] = pick([
        r"Fecha de vencimiento\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Vencimiento\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Fin\s*vigencia\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Vigencia\s*hasta\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
        r"Hasta\s*[:\-]?\s*([0-9]{1,2}[ /.-][0-9]{1,2}[ /.-][0-9]{2,4})",
    ])
    if fields["fecha_efecto"]:
        fields["fecha_efecto"] = normalize_ocr_date(fields["fecha_efecto"])
    if fields["fecha_vencimiento"]:
        fields["fecha_vencimiento"] = normalize_ocr_date(fields["fecha_vencimiento"])
    if not fields["fecha_efecto"] or not fields["fecha_vencimiento"]:
        vigencia_line = line_pick(["Vigencia", "Periodo", "Período", "Duración"])
        start_date, end_date = pick_date_range(vigencia_line)
        if start_date and not fields["fecha_efecto"]:
            fields["fecha_efecto"] = start_date
        if end_date and not fields["fecha_vencimiento"]:
            fields["fecha_vencimiento"] = end_date
    fields["ramo"] = pick([
        r"Ramo\s*[:\-]?\s*([^\n]+)",
        r"Modalidad\s*[:\-]?\s*([^\n]+)",
        r"Modalidad\s+([A-ZÁÉÍÓÚÑa-z\s]+?)\s+Datos\s+Tomador",
        r"Producto\s*[:\-]?\s*([^\n]+)",
        r"Seguro\s*de\s*([A-ZÁÉÍÓÚÑa-z\s]+?)(?:\\.|\\n|Datos)",
    ])
    if not fields["ramo"]:
        ramo_keywords = [
            "Hogar",
            "Auto",
            "Automóvil",
            "Vida",
            "Salud",
            "Comercio",
            "RC",
            "Responsabilidad Civil",
            "Decesos",
            "Accidentes",
            "Comunidad",
            "Pymes",
            "Multirriesgo",
            "Ciber",
            "Mascotas",
            "Moto",
            "Coche",
            "Agro",
            "Construcción",
            "Transportes",
        ]
        for keyword in ramo_keywords:
            if re.search(rf"\\b{re.escape(keyword)}\\b", cleaned, re.IGNORECASE):
                fields["ramo"] = keyword
                break
    fields["prima_neta"] = pick([
        r"Prima neta\s*[:€]?\s*([0-9\.,]+)",
        r"Importe\s*prima\s*neta\s*[:€]?\s*([0-9\.,]+)",
        r"Neta\s*[:€]?\s*([0-9\.,]+)",
        r"Prima\s+neta\s+anual\s*[:€]?\s*([0-9\.,]+)",
    ])
    fields["prima_total"] = pick([
        r"Prima total\s*[:€]?\s*([0-9\.,]+)",
        r"Prima anual\s*[:€]?\s*([0-9\.,]+)",
        r"Importe\s*total\s*[:€]?\s*([0-9\.,]+)",
        r"Total\s*[:€]?\s*([0-9\.,]+)",
        r"Prima\s*total\s*anual\s*[:€]?\s*([0-9\.,]+)",
        r"Total\s+recibo\s*[:€]?\s*([0-9\.,]+)",
    ])
    if fields["tomador"]:
        tomador = fields["tomador"].splitlines()[0].strip()
        for cut in ["Marca", "Matrícula", "Doc."]:
            if cut in tomador:
                tomador = tomador.split(cut)[0].strip()
        fields["tomador"] = tomador
    if fields["direccion"]:
        fields["direccion"] = re.sub(r"\s{2,}.*$", "", fields["direccion"]).strip()
        postal_match = re.search(r"\b\d{5}\s+[A-ZÁÉÍÓÚÑ\s]+\b", cleaned)
        if postal_match and postal_match.group(0) not in fields["direccion"]:
            fields["direccion"] = f"{fields['direccion']} {postal_match.group(0)}".strip()
    if fields["telefono"]:
        fields["telefono"] = normalize_phone(fields["telefono"])
    if fields["email"]:
        fields["email"] = normalize_email(fields["email"])
    if fields["poliza_numero"]:
        if not re.search(r"\\d", fields["poliza_numero"]):
            fields["poliza_numero"] = ""
    if not fields["poliza_numero"]:
        pol_match = re.search(r"N[ºo]\\s*P[oó]liza\\s*[:#]?\\s*([0-9]{5,})", cleaned, re.IGNORECASE)
        if not pol_match:
            pol_match = re.search(r"N[ºo]\\s*P[oó]liza\\s*[:#]?\\s*([0-9]{5,})", text, re.IGNORECASE)
        if pol_match:
            fields["poliza_numero"] = pol_match.group(1).strip()
    if fields["dni"]:
        dni = normalize_nif_candidate(fields["dni"])
        fields["dni"] = dni
    if not fields["dni"]:
        dni_match = re.search(r"\b([0-9]{8}[A-Z])\b", text)
        if dni_match:
            fields["dni"] = normalize_nif_candidate(dni_match.group(1))
        else:
            cif_match = re.search(r"\b([ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-Z])\b", text)
            if cif_match:
                fields["dni"] = normalize_nif_candidate(cif_match.group(1))
    if fields["ramo"] and "@" in fields["ramo"]:
        fields["ramo"] = ""
    if fields["ramo"]:
        fields["ramo"] = fields["ramo"].splitlines()[0].strip()
    if not fields["ramo"]:
        modal_match = re.search(
            r"Modalidad\s+([A-ZÁÉÍÓÚÑa-z\s]+?)\s+Datos\s+Tomador",
            cleaned,
            re.IGNORECASE,
        )
        if modal_match:
            fields["ramo"] = modal_match.group(1).strip()
    if not fields["poliza_numero"] or not fields["ramo"] or not fields["fecha_efecto"]:
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if "Modalidad" in line and idx + 1 < len(lines):
                cols = [c for c in re.split(r"\s{2,}", lines[idx + 1].strip()) if c]
                if len(cols) >= 4:
                    if not fields["poliza_numero"] and re.search(r"\d{5,}", cols[1]):
                        fields["poliza_numero"] = re.search(r"\d{5,}", cols[1]).group(0)
                    if not fields["fecha_efecto"]:
                        fecha_match = re.search(r"\d{1,2}/\d{1,2}/\d{2,4}", cols[2])
                        if fecha_match:
                            fields["fecha_efecto"] = fecha_match.group(0)
                    if not fields["ramo"]:
                        fields["ramo"] = cols[-1]
                break
    if not fields["fecha_efecto"] or not fields["fecha_vencimiento"]:
        start_date, end_date = extract_date_range(cleaned)
        if start_date and not fields["fecha_efecto"]:
            fields["fecha_efecto"] = start_date
        if end_date and not fields["fecha_vencimiento"]:
            fields["fecha_vencimiento"] = end_date
    if not fields["tomador"]:
        fields["tomador"] = line_pick(["Tomador", "Asegurado", "Titular", "Contratante"])
    if fields["tomador"]:
        fields["tomador"] = normalize_person_name(fields["tomador"])
    if not fields["dni"]:
        fields["dni"] = line_pick(["DNI", "NIF", "CIF", "Documento"])
    if not fields["compania"]:
        fields["compania"] = line_pick(["Compañia", "Compania", "Aseguradora", "Entidad aseguradora"])
    if fields["compania"]:
        fields["compania"] = normalize_company_name(fields["compania"])
    if not fields["poliza_numero"]:
        fields["poliza_numero"] = line_pick(
            ["Póliza", "Poliza", "Nº póliza", "Numero de poliza", "Certificado", "Contrato"]
        )
    if not fields["ramo"]:
        fields["ramo"] = line_pick(["Ramo", "Modalidad", "Producto"])
    if not fields["fecha_efecto"]:
        fields["fecha_efecto"] = line_pick(["Fecha efecto", "Efecto", "Inicio vigencia", "Fecha inicio"])
    if not fields["fecha_vencimiento"]:
        fields["fecha_vencimiento"] = line_pick(["Vencimiento", "Fin vigencia", "Vigencia hasta"])
    if not fields["prima_total"]:
        fields["prima_total"] = line_pick(["Prima total", "Total recibo", "Total"])
    if not fields["prima_neta"]:
        fields["prima_neta"] = line_pick(["Prima neta", "Neta"])
    if not fields["direccion"]:
        fields["direccion"] = line_pick(["Direccion", "Domicilio"])
    if fields["direccion"]:
        fields["direccion"] = re.sub(r"\s{2,}.*$", "", fields["direccion"]).strip()
    if not fields["telefono"]:
        fields["telefono"] = line_pick(["Telefono", "Teléfono", "Movil", "Móvil", "Tfno", "Tlf"])
    if fields["telefono"]:
        fields["telefono"] = normalize_phone(fields["telefono"])
    if not fields["email"]:
        fields["email"] = line_pick(["Email", "Correo", "Correo electronico", "Correo electrónico"])
    if fields["email"]:
        fields["email"] = normalize_email(fields["email"])
    for key in ("fecha_efecto", "fecha_vencimiento", "fecha_nacimiento"):
        if fields.get(key):
            fields[key] = normalize_ocr_date(fields[key])
    if fields.get("poliza_numero"):
        fields["poliza_numero"] = normalize_poliza_number(fields["poliza_numero"], fields.get("compania"))
    if fields["dni"] and not fields.get("nif"):
        fields["nif"] = fields["dni"]
    if fields.get("nif"):
        fields["nif"] = normalize_nif_candidate(fields["nif"]) or fields["nif"]
    return fields

def parse_asesoramiento_block(block):
    block_clean = re.sub(r"\s+", " ", block.replace("\u00a0", " "))
    def pick(patterns):
        for pat in patterns:
            m = re.search(pat, block, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            m = re.search(pat, block_clean, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""
    data = {}
    data["nombre"] = pick([
        r"Nombre\s+y\s+apellidos\s*[:\-]?\s*([^\n]+)",
        r"Nombre\s+apellidos\s*[:\-]?\s*([^\n]+)",
        r"Nombre\s*[:\-]?\s*([^\n]+)",
    ])
    data["dni"] = pick([
        r"DNI\s*[:\-]?\s*([A-Z0-9\-]+)",
        r"NIF\s*[:\-]?\s*([A-Z0-9\-]+)",
    ])
    data["telefono"] = pick([
        r"Tel[eé]fono\s*[:\-]?\s*([0-9\s]{9,})",
        r"M[oó]vil\s*[:\-]?\s*([0-9\s]{9,})",
        r"Tfno\.?\s*[:\-]?\s*([0-9\s]{9,})",
        r"Tlf\.?\s*[:\-]?\s*([0-9\s]{9,})",
    ])
    data["email"] = pick([
        r"Correo\s*Electr[oó]nico\s*[:\-]?\s*([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})",
    ])
    data["fecha_nacimiento"] = pick([
        r"Fecha\s*Nacimiento\s*[:\-]?\s*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
    ])
    data["estado_civil"] = pick([
        r"Estado\s*Civil\s*[:\-]?\s*([^\n]+)",
        r"Est\.?\s*Civil\s*[:\-]?\s*([^\n]+)",
    ])
    data["hijos"] = pick([
        r"Hijos\s*[:\-]?\s*([0-9]+)",
    ])
    data["profesion"] = pick([
        r"Profesi[oó]n\s*[:\-]?\s*([^\n]+)",
        r"Prof\.?\s*[:\-]?\s*([^\n]+)",
    ])
    data["tipo_contrato"] = pick([
        r"Tipo\s*Contrato\s*[:\-]?\s*([^\n]+)",
        r"Contrato\s*[:\-]?\s*([^\n]+)",
    ])
    data["ingresos"] = pick([
        r"Ingresos/N[oó]mina\s*[:\-]?\s*([0-9\.,]+)",
        r"Ingresos\s*[:\-]?\s*([0-9\.,]+)",
        r"N[oó]mina\s*[:\-]?\s*([0-9\.,]+)",
        r"Sueldo\s*[:\-]?\s*([0-9\.,]+)",
    ])
    data["patrimonio"] = pick([
        r"Patrimonio-?Alquiler\s*[:\-]?\s*([^\n]+)",
    ])
    data["prestamos"] = pick([
        r"PR[EÉ]STAMOS.*?\s*[:\-]?\s*([^\n]+)",
        r"PR[EÉ]STAMOS\s*[:\-]?\s*([^\n]+)",
    ])
    return data

def parse_asesoramiento_template(pdf_path):
    size = pdfinfo_page_size(pdf_path)
    if not size:
        return {}
    width, height = size
    boxes = {
        "cliente1": (0.05 * width, 0.28 * height, 0.9 * width, 0.22 * height),
        "cliente2": (0.05 * width, 0.53 * height, 0.9 * width, 0.22 * height),
        "resumen": (0.05 * width, 0.76 * height, 0.9 * width, 0.20 * height),
        "header": (0.05 * width, 0.16 * height, 0.9 * width, 0.10 * height),
    }
    fields = {}
    header = pdftotext_crop(pdf_path, *boxes["header"])
    if header:
        fields["inmobiliaria_asesor"] = parse_asesoramiento_text(header).get("inmobiliaria_asesor", "")
        fields["fecha"] = parse_asesoramiento_text(header).get("fecha", "")
    cliente1_text = pdftotext_crop(pdf_path, *boxes["cliente1"])
    if cliente1_text:
        data1 = parse_asesoramiento_block(cliente1_text)
        fields["cliente1_nombre"] = data1.get("nombre", "")
        fields["cliente1_dni"] = data1.get("dni", "")
        fields["cliente1_telefono"] = data1.get("telefono", "")
        fields["cliente1_email"] = data1.get("email", "")
        fields["cliente1_fecha_nacimiento"] = data1.get("fecha_nacimiento", "")
        fields["cliente1_estado_civil"] = data1.get("estado_civil", "")
        fields["cliente1_hijos"] = data1.get("hijos", "")
        fields["cliente1_profesion"] = data1.get("profesion", "")
        fields["cliente1_tipo_contrato"] = data1.get("tipo_contrato", "")
        fields["cliente1_ingresos"] = data1.get("ingresos", "")
        fields["cliente1_patrimonio"] = data1.get("patrimonio", "")
        fields["cliente1_prestamos"] = data1.get("prestamos", "")
    cliente2_text = pdftotext_crop(pdf_path, *boxes["cliente2"])
    if cliente2_text:
        data2 = parse_asesoramiento_block(cliente2_text)
        fields["cliente2_nombre"] = data2.get("nombre", "")
        fields["cliente2_dni"] = data2.get("dni", "")
        fields["cliente2_telefono"] = data2.get("telefono", "")
        fields["cliente2_email"] = data2.get("email", "")
        fields["cliente2_fecha_nacimiento"] = data2.get("fecha_nacimiento", "")
        fields["cliente2_estado_civil"] = data2.get("estado_civil", "")
        fields["cliente2_hijos"] = data2.get("hijos", "")
        fields["cliente2_profesion"] = data2.get("profesion", "")
        fields["cliente2_tipo_contrato"] = data2.get("tipo_contrato", "")
        fields["cliente2_ingresos"] = data2.get("ingresos", "")
        fields["cliente2_patrimonio"] = data2.get("patrimonio", "")
        fields["cliente2_prestamos"] = data2.get("prestamos", "")
    resumen = pdftotext_crop(pdf_path, *boxes["resumen"])
    if resumen:
        resumen_fields = parse_asesoramiento_text(resumen)
        for key in ("ingresos_conjuntos", "entidades_financieras", "avalistas", "aportacion_cv"):
            if resumen_fields.get(key):
                fields[key] = resumen_fields.get(key)
    return fields

def parse_asesoramiento_template_image(image_path):
    size = get_image_size(image_path)
    if not size:
        return {}
    width, height = size
    base_boxes = asesoramiento_image_boxes(width, height)
    shifts = (-0.015, 0.0, 0.015)
    fields = {}
    tmp_base = tempfile.gettempdir()
    with tempfile.TemporaryDirectory(dir=tmp_base) as tmpdir:
        processed, created = preprocess_image_for_ocr(image_path)
        for dy in shifts:
            for key, (x, y, w, h) in base_boxes.items():
                out_path = os.path.join(tmpdir, f"{key}_{dy:+.3f}.png")
                ok = crop_image_region(processed, x, y + dy * height, w, h, out_path)
                if not ok:
                    continue
                block_text, _ = ocr_image_file(out_path)
                if not block_text:
                    continue
                if key == "header":
                    header_fields = parse_asesoramiento_text(block_text)
                    for field in ("inmobiliaria_asesor", "fecha"):
                        if header_fields.get(field) and not fields.get(field):
                            fields[field] = header_fields.get(field)
                elif key == "cliente1":
                    data1 = parse_asesoramiento_block(block_text)
                    for field, target in (
                        ("nombre", "cliente1_nombre"),
                        ("dni", "cliente1_dni"),
                        ("telefono", "cliente1_telefono"),
                        ("email", "cliente1_email"),
                        ("fecha_nacimiento", "cliente1_fecha_nacimiento"),
                        ("estado_civil", "cliente1_estado_civil"),
                        ("hijos", "cliente1_hijos"),
                        ("profesion", "cliente1_profesion"),
                        ("tipo_contrato", "cliente1_tipo_contrato"),
                        ("ingresos", "cliente1_ingresos"),
                        ("patrimonio", "cliente1_patrimonio"),
                        ("prestamos", "cliente1_prestamos"),
                    ):
                        if data1.get(field) and not fields.get(target):
                            fields[target] = data1.get(field)
                elif key == "cliente2":
                    data2 = parse_asesoramiento_block(block_text)
                    for field, target in (
                        ("nombre", "cliente2_nombre"),
                        ("dni", "cliente2_dni"),
                        ("telefono", "cliente2_telefono"),
                        ("email", "cliente2_email"),
                        ("fecha_nacimiento", "cliente2_fecha_nacimiento"),
                        ("estado_civil", "cliente2_estado_civil"),
                        ("hijos", "cliente2_hijos"),
                        ("profesion", "cliente2_profesion"),
                        ("tipo_contrato", "cliente2_tipo_contrato"),
                        ("ingresos", "cliente2_ingresos"),
                        ("patrimonio", "cliente2_patrimonio"),
                        ("prestamos", "cliente2_prestamos"),
                    ):
                        if data2.get(field) and not fields.get(target):
                            fields[target] = data2.get(field)
                elif key == "resumen":
                    resumen_fields = parse_asesoramiento_text(block_text)
                    for field in ("ingresos_conjuntos", "entidades_financieras", "avalistas", "aportacion_cv"):
                        if resumen_fields.get(field) and not fields.get(field):
                            fields[field] = resumen_fields.get(field)
        if created and processed and os.path.exists(processed):
            try:
                os.unlink(processed)
            except Exception:
                pass
    return fields

def parse_asesoramiento_text(text):
    cleaned = text.replace("\u00a0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.replace("D.N.I.", "DNI").replace("DNI.", "DNI")
    cleaned = cleaned.replace("Nómina", "Nomina").replace("NÓMINA", "NOMINA")
    def pick(patterns, source_text=None, source_clean=None):
        source_text = source_text or text
        source_clean = source_clean or cleaned
        for pat in patterns:
            m = re.search(pat, source_text, re.IGNORECASE)
            if m:
                return m.group(1).strip()
            m = re.search(pat, source_clean, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return ""

    fields = {}
    fields["inmobiliaria_asesor"] = pick([
        r"Inmobiliaria/?Asesor\s*[:\-]?\s*([^\n]+)",
        r"INMOBILIARIA/ASESOR\s*[:\-]?\s*([^\n]+)",
    ])
    fields["fecha"] = pick([
        r"Fecha\s*[:\-]?\s*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})",
    ])

    parts = re.split(r"(CLIENTE\s*1|CLIENTE\s*2)", text, flags=re.IGNORECASE)
    blocks = {"1": "", "2": ""}
    current = ""
    for part in parts:
        if re.match(r"CLIENTE\s*1", part, re.IGNORECASE):
            current = "1"
            continue
        if re.match(r"CLIENTE\s*2", part, re.IGNORECASE):
            current = "2"
            continue
        if current in blocks:
            blocks[current] += part

    if blocks["1"]:
        data1 = parse_asesoramiento_block(blocks["1"])
        fields["cliente1_nombre"] = data1.get("nombre", "")
        fields["cliente1_dni"] = data1.get("dni", "")
        fields["cliente1_telefono"] = data1.get("telefono", "")
        fields["cliente1_email"] = data1.get("email", "")
        fields["cliente1_fecha_nacimiento"] = data1.get("fecha_nacimiento", "")
        fields["cliente1_estado_civil"] = data1.get("estado_civil", "")
        fields["cliente1_hijos"] = data1.get("hijos", "")
        fields["cliente1_profesion"] = data1.get("profesion", "")
        fields["cliente1_tipo_contrato"] = data1.get("tipo_contrato", "")
        fields["cliente1_ingresos"] = data1.get("ingresos", "")
        fields["cliente1_patrimonio"] = data1.get("patrimonio", "")
        fields["cliente1_prestamos"] = data1.get("prestamos", "")

    if blocks["2"]:
        data2 = parse_asesoramiento_block(blocks["2"])
        fields["cliente2_nombre"] = data2.get("nombre", "")
        fields["cliente2_dni"] = data2.get("dni", "")
        fields["cliente2_telefono"] = data2.get("telefono", "")
        fields["cliente2_email"] = data2.get("email", "")
        fields["cliente2_fecha_nacimiento"] = data2.get("fecha_nacimiento", "")
        fields["cliente2_estado_civil"] = data2.get("estado_civil", "")
        fields["cliente2_hijos"] = data2.get("hijos", "")
        fields["cliente2_profesion"] = data2.get("profesion", "")
        fields["cliente2_tipo_contrato"] = data2.get("tipo_contrato", "")
        fields["cliente2_ingresos"] = data2.get("ingresos", "")
        fields["cliente2_patrimonio"] = data2.get("patrimonio", "")
        fields["cliente2_prestamos"] = data2.get("prestamos", "")

    if not fields.get("cliente1_nombre"):
        fields["cliente1_nombre"] = pick([
            r"Cliente\s*1.*?Nombre\s+y\s+apellidos\s*[:\-]?\s*([^\n]+)",
        ])
    if not fields.get("cliente2_nombre"):
        fields["cliente2_nombre"] = pick([
            r"Cliente\s*2.*?Nombre\s+y\s+apellidos\s*[:\-]?\s*([^\n]+)",
        ])

    fields["ingresos_conjuntos"] = pick([
        r"Ingresos\s+conjuntos\s*[:\-]?\s*([0-9\.,]+)",
        r"Ingresos\s+conjunto\s*[:\-]?\s*([0-9\.,]+)",
        r"Ingresos\s*[:\-]?\s*([0-9\.,]+)",
    ])
    fields["entidades_financieras"] = pick([
        r"Entidades\s+Financieras\s*[:\-]?\s*([^\n]+)",
        r"Entidad(?:es)?\s+Financiera(?:s)?\s*[:\-]?\s*([^\n]+)",
    ])
    fields["avalistas"] = pick([
        r"Posibles\s+Avalistas/Cotitulares\s*[:\-]?\s*([^\n]+)",
    ])
    fields["aportacion_cv"] = pick([
        r"Aportaci[oó]n\s+para\s+CV\s*[:\-]?\s*([0-9\.,]+)",
        r"Aportaci[oó]n\s*para\s*CV\s*[:\-]?\s*([0-9\.,]+)",
        r"Aportaci[oó]n\s*[:\-]?\s*([0-9\.,]+)",
        r"Aportaci[oó]n\s*CV\s*[:\-]?\s*([0-9\.,]+)",
    ])

    phones = re.findall(r"\b[6-9][0-9]{8}\b", cleaned)
    emails = re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", cleaned, re.IGNORECASE)
    dnis = re.findall(r"\b[0-9]{8}[A-Z]\b", cleaned)
    cifs = re.findall(r"\b[ABCDEFGHJNPQRSUVW][0-9]{7}[0-9A-Z]\b", cleaned)
    docs = dnis + cifs

    if phones:
        if not fields.get("cliente1_telefono"):
            fields["cliente1_telefono"] = phones[0]
        if len(phones) > 1 and not fields.get("cliente2_telefono"):
            fields["cliente2_telefono"] = phones[1]
    if emails:
        if not fields.get("cliente1_email"):
            fields["cliente1_email"] = emails[0]
        if len(emails) > 1 and not fields.get("cliente2_email"):
            fields["cliente2_email"] = emails[1]
    if docs:
        if not fields.get("cliente1_dni"):
            fields["cliente1_dni"] = docs[0]
        if len(docs) > 1 and not fields.get("cliente2_dni"):
            fields["cliente2_dni"] = docs[1]

    if not fields.get("entidades_financieras"):
        bancos = [
            "BBVA",
            "ING",
            "Santander",
            "CaixaBank",
            "Sabadell",
            "Unicaja",
            "Abanca",
            "Ibercaja",
            "Kutxabank",
            "Cajamar",
            "Bankinter",
        ]
        encontrados = []
        for bank in bancos:
            if re.search(rf"\\b{re.escape(bank)}\\b", cleaned, re.IGNORECASE):
                encontrados.append(bank)
        if encontrados:
            fields["entidades_financieras"] = ", ".join(sorted(set(encontrados)))

    return fields

def ensure_cliente_for_seguro(conn, empresa_id, tomador, nif, now, extra=None):
    if not tomador:
        return None
    tomador = tomador.strip()
    nif = (nif or "").strip()
    extra = extra or {}
    cliente = None
    if nif:
        cliente = conn.execute(
            "SELECT id FROM clientes WHERE nif = ?",
            (nif,),
        ).fetchone()
    if not cliente:
        cliente = conn.execute(
            "SELECT id FROM clientes WHERE nombre = ?",
            (tomador,),
        ).fetchone()
    if not cliente:
        tipo_persona = None
        if nif:
            if re.match(r"^[0-9]{8}[A-Z]$", nif):
                tipo_persona = "Física"
            elif re.match(r"^[A-Z][0-9]{7}[0-9A-Z]$", nif):
                tipo_persona = "Jurídica"
        cliente_id = os.urandom(16).hex()
        conn.execute(
            """
            INSERT INTO clientes (
              id, nombre, tipo_persona, nif, telefono, email, fecha_nacimiento, direccion, estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                cliente_id,
                tomador,
                tipo_persona,
                nif or None,
                extra.get("telefono"),
                extra.get("email"),
                extra.get("fecha_nacimiento"),
                extra.get("direccion"),
                "Activo",
                now,
                now,
            ),
        )
    else:
        cliente_id = cliente["id"]
        updates = {}
        if nif:
            updates["nif"] = nif
        for key in ("telefono", "email", "fecha_nacimiento", "direccion"):
            value = extra.get(key)
            if value:
                updates[key] = value
        if updates:
            set_clause = ", ".join([f"{key} = COALESCE({key}, ?)" for key in updates])
            values = list(updates.values()) + [now, cliente_id]
            conn.execute(
                f"UPDATE clientes SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
    link = conn.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND servicio = ?
        """,
        (cliente_id, empresa_id, "seguros"),
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
                "seguros",
                "Activo",
                None,
                None,
                now,
                now,
            ),
        )
    return cliente_id

def ensure_cliente_for_financiacion(conn, empresa_id, nombre, nif, now, extra=None):
    if not nombre:
        return None
    nombre = str(nombre).strip()
    nif = (nif or "").strip()
    extra = extra or {}
    cliente = None
    if nif:
        cliente = conn.execute(
            "SELECT id FROM clientes WHERE nif = ?",
            (nif,),
        ).fetchone()
    if not cliente:
        cliente = conn.execute(
            "SELECT id FROM clientes WHERE nombre = ?",
            (nombre,),
        ).fetchone()
    if not cliente:
        tipo_persona = None
        if nif:
            if re.match(r"^[0-9]{8}[A-Z]$", nif):
                tipo_persona = "Física"
            elif re.match(r"^[A-Z][0-9]{7}[0-9A-Z]$", nif):
                tipo_persona = "Jurídica"
        cliente_id = os.urandom(16).hex()
        conn.execute(
            """
            INSERT INTO clientes (
              id, nombre, tipo_persona, nif, telefono, email, fecha_nacimiento, direccion, estado, created_at, updated_at
            ) VALUES (
              ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
            )
            """,
            (
                cliente_id,
                nombre,
                tipo_persona,
                nif or None,
                extra.get("telefono"),
                extra.get("email"),
                extra.get("fecha_nacimiento"),
                extra.get("direccion"),
                "Activo",
                now,
                now,
            ),
        )
    else:
        cliente_id = cliente["id"]
        updates = {}
        if nif:
            updates["nif"] = nif
        for key in ("telefono", "email", "fecha_nacimiento", "direccion"):
            value = extra.get(key)
            if value:
                updates[key] = value
        if updates:
            set_clause = ", ".join([f"{key} = COALESCE({key}, ?)" for key in updates])
            values = list(updates.values()) + [now, cliente_id]
            conn.execute(
                f"UPDATE clientes SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
    link = conn.execute(
        """
        SELECT id FROM clientes_empresas
        WHERE cliente_id = ? AND empresa_id = ? AND servicio = ?
        """,
        (cliente_id, empresa_id, "financiaciones"),
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
    return cliente_id

TABLES = [
    "movimientos",
    "seguros",
    "gestoria",
    "captaciones",
    "inmuebles",
    "demandas",
    "visitas",
    "hipotecas",
    "alquileres",
    "inversores",
    "inversure_operaciones",
]


def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_tables(db_path):
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cliente_gestoria (
          id TEXT PRIMARY KEY,
          cliente_id TEXT UNIQUE,
          tipo_cliente TEXT,
          mod_fiscal INTEGER,
          mod_laboral INTEGER,
          mod_contable INTEGER,
          mod_renta INTEGER,
          mod_registro INTEGER,
          mod_trafico INTEGER,
          mod_puntuales INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    cliente_gestoria_cols = [row[1] for row in conn.execute("PRAGMA table_info(cliente_gestoria)").fetchall()]
    if "mod_renta" not in cliente_gestoria_cols:
        conn.execute("ALTER TABLE cliente_gestoria ADD COLUMN mod_renta INTEGER")
    if "renta_detalles" not in cliente_gestoria_cols:
        conn.execute("ALTER TABLE cliente_gestoria ADD COLUMN renta_detalles TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_modelos (
          id TEXT PRIMARY KEY,
          cliente_id TEXT,
          modelo TEXT,
          periodicidad TEXT,
          proxima_fecha TEXT,
          responsable TEXT,
          estado TEXT,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_trabajos (
          id TEXT PRIMARY KEY,
          empresa_id TEXT,
          cliente_id TEXT,
          tipo_trabajo TEXT,
          estado TEXT,
          fecha_inicio TEXT,
          fecha_fin TEXT,
          responsable TEXT,
          importe REAL,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    try:
        cap_cols = [row[1] for row in conn.execute("PRAGMA table_info(captaciones)").fetchall()]
        if "codigo_postal" not in cap_cols:
            conn.execute("ALTER TABLE captaciones ADD COLUMN codigo_postal TEXT")
        if "poblacion" not in cap_cols:
            conn.execute("ALTER TABLE captaciones ADD COLUMN poblacion TEXT")
        if "provincia" not in cap_cols:
            conn.execute("ALTER TABLE captaciones ADD COLUMN provincia TEXT")
    except sqlite3.Error:
        pass
    try:
        inm_cols = [row[1] for row in conn.execute("PRAGMA table_info(inmuebles)").fetchall()]
        if "codigo_postal" not in inm_cols:
            conn.execute("ALTER TABLE inmuebles ADD COLUMN codigo_postal TEXT")
        if "poblacion" not in inm_cols:
            conn.execute("ALTER TABLE inmuebles ADD COLUMN poblacion TEXT")
        if "provincia" not in inm_cols:
            conn.execute("ALTER TABLE inmuebles ADD COLUMN provincia TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_docs (
          id TEXT PRIMARY KEY,
          empresa_id TEXT,
          cliente_id TEXT,
          referencia_tipo TEXT,
          referencia_id TEXT,
          nombre TEXT,
          tipo TEXT,
          fecha TEXT,
          estado TEXT,
          notas TEXT,
          doc_key TEXT,
          doc_url TEXT,
          calidad_ocr TEXT,
          campos_ocr TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    try:
        docs_cols = [row[1] for row in conn.execute("PRAGMA table_info(gestoria_docs)").fetchall()]
        if "doc_key" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN doc_key TEXT")
        if "doc_url" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN doc_url TEXT")
        if "referencia_tipo" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN referencia_tipo TEXT")
        if "referencia_id" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN referencia_id TEXT")
        if "calidad_ocr" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN calidad_ocr TEXT")
        if "campos_ocr" not in docs_cols:
            conn.execute("ALTER TABLE gestoria_docs ADD COLUMN campos_ocr TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS asesoramientos_financiacion (
          id TEXT PRIMARY KEY,
          empresa_id TEXT,
          origen TEXT,
          inmobiliaria_asesor TEXT,
          asesor TEXT,
          fecha TEXT,
          estado TEXT,
          cliente1_id TEXT,
          cliente1_nombre TEXT,
          cliente1_dni TEXT,
          cliente1_telefono TEXT,
          cliente1_email TEXT,
          cliente1_fecha_nacimiento TEXT,
          cliente1_estado_civil TEXT,
          cliente1_regimen TEXT,
          cliente1_hijos TEXT,
          cliente1_profesion TEXT,
          cliente1_tipo_contrato TEXT,
          cliente1_tiempo_contrato TEXT,
          cliente1_ingresos REAL,
          cliente1_patrimonio TEXT,
          cliente1_prestamos TEXT,
          cliente1_prestamo_activo TEXT,
          cliente1_prestamo_entidad TEXT,
          cliente1_prestamo_resto REAL,
          cliente2_id TEXT,
          cliente2_nombre TEXT,
          cliente2_dni TEXT,
          cliente2_telefono TEXT,
          cliente2_email TEXT,
          cliente2_fecha_nacimiento TEXT,
          cliente2_estado_civil TEXT,
          cliente2_regimen TEXT,
          cliente2_hijos TEXT,
          cliente2_profesion TEXT,
          cliente2_tipo_contrato TEXT,
          cliente2_tiempo_contrato TEXT,
          cliente2_ingresos REAL,
          cliente2_patrimonio TEXT,
          cliente2_prestamos TEXT,
          cliente2_prestamo_activo TEXT,
          cliente2_prestamo_entidad TEXT,
          cliente2_prestamo_resto REAL,
          ingresos_conjuntos REAL,
          entidades_financieras TEXT,
          avalistas TEXT,
          aportacion_cv REAL,
          notas TEXT,
          notas_ocr TEXT,
          calidad_ocr TEXT,
          campos_ocr TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    ases_cols = [row[1] for row in conn.execute("PRAGMA table_info(asesoramientos_financiacion)").fetchall()]
    if "cliente1_tiempo_contrato" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente1_tiempo_contrato TEXT")
    if "cliente2_tiempo_contrato" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente2_tiempo_contrato TEXT")
    if "cliente1_regimen" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente1_regimen TEXT")
    if "cliente2_regimen" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente2_regimen TEXT")
    if "cliente1_prestamo_activo" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente1_prestamo_activo TEXT")
    if "cliente1_prestamo_entidad" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente1_prestamo_entidad TEXT")
    if "cliente1_prestamo_resto" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente1_prestamo_resto REAL")
    if "cliente2_prestamo_activo" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente2_prestamo_activo TEXT")
    if "cliente2_prestamo_entidad" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente2_prestamo_entidad TEXT")
    if "cliente2_prestamo_resto" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN cliente2_prestamo_resto REAL")
    if "calidad_ocr" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN calidad_ocr TEXT")
    if "campos_ocr" not in ases_cols:
        conn.execute("ALTER TABLE asesoramientos_financiacion ADD COLUMN campos_ocr TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_contabilidad (
          id TEXT PRIMARY KEY,
          empresa_id TEXT,
          cliente_id TEXT,
          fecha TEXT,
          concepto TEXT,
          gestion TEXT,
          tipo TEXT,
          importe REAL,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_conta_config (
          id TEXT PRIMARY KEY,
          cliente_id TEXT UNIQUE,
          periodo TEXT,
          fecha_inicio TEXT,
          responsable TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS gestoria_conta_tasks (
          id TEXT PRIMARY KEY,
          cliente_id TEXT,
          periodo TEXT,
          tarea TEXT,
          estado TEXT,
          fecha_limite TEXT,
          responsable TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS inmueble_checklist (
          id TEXT PRIMARY KEY,
          inmueble_id TEXT NOT NULL,
          etapa TEXT,
          tarea TEXT,
          estado TEXT,
          responsable TEXT,
          fecha_limite TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_ofertas (
          id TEXT PRIMARY KEY,
          cliente_id TEXT,
          ramo TEXT,
          compania TEXT,
          propuesta TEXT,
          estado TEXT,
          motivo TEXT,
          fecha TEXT,
          responsable TEXT,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_preferencias (
          id TEXT PRIMARY KEY,
          cliente_id TEXT UNIQUE,
          prioridad_precio INTEGER DEFAULT 0,
          prioridad_compania INTEGER DEFAULT 0,
          prioridad_coberturas INTEGER DEFAULT 0,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_referidos (
          id TEXT PRIMARY KEY,
          cliente_id TEXT,
          referido_por TEXT,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_campanas (
          id TEXT PRIMARY KEY,
          compania TEXT,
          nombre TEXT,
          ramo TEXT,
          origen TEXT,
          fecha_inicio TEXT,
          fecha_fin TEXT,
          descripcion TEXT,
          url TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    campanas_cols = [row[1] for row in conn.execute("PRAGMA table_info(seguros_campanas)").fetchall()]
    if "origen" not in campanas_cols:
        conn.execute("ALTER TABLE seguros_campanas ADD COLUMN origen TEXT")
    try:
        seguros_cols = [row[1] for row in conn.execute("PRAGMA table_info(seguros)").fetchall()]
        if "poliza_key" not in seguros_cols:
            conn.execute("ALTER TABLE seguros ADD COLUMN poliza_key TEXT")
        if "poliza_url" not in seguros_cols:
            conn.execute("ALTER TABLE seguros ADD COLUMN poliza_url TEXT")
        if "cliente_id" not in seguros_cols:
            conn.execute("ALTER TABLE seguros ADD COLUMN cliente_id TEXT")
    except sqlite3.Error:
        pass
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_comisiones (
          id TEXT PRIMARY KEY,
          compania TEXT,
          ramo TEXT,
          porcentaje REAL,
          vigencia_desde TEXT,
          vigencia_hasta TEXT,
          notas TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seguros_checklist (
          id TEXT PRIMARY KEY,
          poliza_id TEXT NOT NULL,
          tarea TEXT,
          estado TEXT,
          responsable TEXT,
          fecha_limite TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY (poliza_id) REFERENCES seguros(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auditoria (
          id TEXT PRIMARY KEY,
          empresa_id TEXT,
          entidad TEXT,
          entidad_id TEXT,
          accion TEXT,
          usuario TEXT,
          detalles TEXT,
          created_at TEXT NOT NULL,
          FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
          id TEXT PRIMARY KEY,
          nombre TEXT NOT NULL,
          apellido TEXT NOT NULL,
          servicio TEXT,
          rol TEXT,
          password_hash TEXT,
          activo INTEGER DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS postal_catalogo (
          codigo_postal TEXT,
          poblacion TEXT,
          provincia TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_postal_cp ON postal_catalogo(codigo_postal)"
    )
    user_cols = [row[1] for row in conn.execute("PRAGMA table_info(usuarios)").fetchall()]
    if "apellido" not in user_cols:
        conn.execute("ALTER TABLE usuarios ADD COLUMN apellido TEXT")
    if "usuario" not in user_cols:
        conn.execute("ALTER TABLE usuarios ADD COLUMN usuario TEXT")
    if "email" not in user_cols:
        conn.execute("ALTER TABLE usuarios ADD COLUMN email TEXT")
    if "servicio" not in user_cols:
        conn.execute("ALTER TABLE usuarios ADD COLUMN servicio TEXT")
    if "password_hash" not in user_cols:
        conn.execute("ALTER TABLE usuarios ADD COLUMN password_hash TEXT")
    users_count = conn.execute("SELECT COUNT(*) AS total FROM usuarios").fetchone()
    total_users = 0
    if users_count:
        try:
            total_users = users_count["total"]
        except (TypeError, KeyError, IndexError):
            total_users = users_count[0]
    if total_users == 0:
        conn.execute(
            "INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, activo, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (os.urandom(16).hex(), "Administrador", "General", "admin", "admin@liv.local", "Administración", "Administrador", 1),
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cnae_catalogo (
          codigo TEXT PRIMARY KEY,
          descripcion TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS iae_catalogo (
          codigo TEXT PRIMARY KEY,
          descripcion TEXT NOT NULL
        )
        """
    )
    cols = [row[1] for row in conn.execute("PRAGMA table_info(clientes)").fetchall()]
    if "tipo_persona" not in cols:
        conn.execute("ALTER TABLE clientes ADD COLUMN tipo_persona TEXT")
    if "codigo_postal" not in cols:
        conn.execute("ALTER TABLE clientes ADD COLUMN codigo_postal TEXT")
    if "poblacion" not in cols:
        conn.execute("ALTER TABLE clientes ADD COLUMN poblacion TEXT")
    if "provincia" not in cols:
        conn.execute("ALTER TABLE clientes ADD COLUMN provincia TEXT")
    modelo_cols = [row[1] for row in conn.execute("PRAGMA table_info(gestoria_modelos)").fetchall()]
    if "responsable" not in modelo_cols:
        conn.execute("ALTER TABLE gestoria_modelos ADD COLUMN responsable TEXT")
    trabajo_cols = [row[1] for row in conn.execute("PRAGMA table_info(gestoria_trabajos)").fetchall()]
    if "responsable" not in trabajo_cols:
        conn.execute("ALTER TABLE gestoria_trabajos ADD COLUMN responsable TEXT")
    if "sla_dias" not in trabajo_cols:
        conn.execute("ALTER TABLE gestoria_trabajos ADD COLUMN sla_dias INTEGER")
    acciones_cols = [row[1] for row in conn.execute("PRAGMA table_info(acciones)").fetchall()]
    if "responsable" not in acciones_cols:
        conn.execute("ALTER TABLE acciones ADD COLUMN responsable TEXT")
    if "recordatorio_min" not in acciones_cols:
        conn.execute("ALTER TABLE acciones ADD COLUMN recordatorio_min INTEGER")
    if "inmueble_id" not in acciones_cols:
        conn.execute("ALTER TABLE acciones ADD COLUMN inmueble_id TEXT")
    inm_cols = [row[1] for row in conn.execute("PRAGMA table_info(inmuebles)").fetchall()]
    if "valor_referencia" not in inm_cols:
        conn.execute("ALTER TABLE inmuebles ADD COLUMN valor_referencia REAL")
    conta_cols = [row[1] for row in conn.execute("PRAGMA table_info(gestoria_contabilidad)").fetchall()]
    if "gestion" not in conta_cols:
        conn.execute("ALTER TABLE gestoria_contabilidad ADD COLUMN gestion TEXT")
    load_postal_catalog(conn)
    conn.commit()
    conn.close()


def json_response(handler, data, status=200):
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


def send_file(handler, path):
    if not path.exists() or not path.is_file():
        handler.send_error(404, "Not found")
        return

    content_type = "text/plain"
    if path.suffix == ".html":
        content_type = "text/html; charset=utf-8"
    elif path.suffix == ".css":
        content_type = "text/css; charset=utf-8"
    elif path.suffix == ".js":
        content_type = "application/javascript; charset=utf-8"
    elif path.suffix in (".png", ".jpg", ".jpeg", ".gif"):
        content_type = f"image/{path.suffix.lstrip('.')}"
    elif path.suffix == ".svg":
        content_type = "image/svg+xml"

    data = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    db_path = DB_DEFAULT

    def log_message(self, format, *args):
        return

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api(parsed)
            return

        if parsed.path == "/" or parsed.path == "":
            send_file(self, ROOT / "index.html")
            return

        if parsed.path.startswith("/assets/"):
            rel = parsed.path.replace("/assets/", "")
            send_file(self, ASSETS / rel)
            return
        if parsed.path.startswith("/uploads/"):
            rel = parsed.path.replace("/uploads/", "")
            send_file(self, UPLOADS / rel)
            return

        rel_path = parsed.path.lstrip("/")
        file_path = ROOT / rel_path
        send_file(self, file_path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path not in (
            "/api/movimientos",
            "/api/hipotecas",
            "/api/hipotecas/firmar",
            "/api/gestoria",
            "/api/gestoria_trabajos",
            "/api/gestoria_trabajos_update",
            "/api/gestoria_trabajos_delete",
            "/api/gestoria_docs",
            "/api/gestoria_docs_update",
            "/api/gestoria_docs_delete",
            "/api/gestoria_contabilidad",
            "/api/gestoria_contabilidad_update",
            "/api/gestoria_contabilidad_delete",
            "/api/gestoria_update",
            "/api/seguros_ocr",
            "/api/fin_asesoramiento_ocr",
            "/api/fin_asesoramiento_ocr_guided",
            "/api/fin_asesoramiento_ocr_auto",
            "/api/seguros",
            "/api/seguros_update",
            "/api/seguros_enrich",
            "/api/fin_asesoramientos",
            "/api/fin_asesoramientos_update",
            "/api/fin_asesoramientos_convert",
            "/api/seguros_ofertas",
            "/api/seguros_ofertas_update",
            "/api/seguros_ofertas_delete",
            "/api/seguros_preferencias",
            "/api/seguros_referidos",
            "/api/seguros_campanas",
            "/api/seguros_campanas_update",
            "/api/seguros_campanas_delete",
            "/api/seguros_comisiones",
            "/api/seguros_comisiones_update",
            "/api/seguros_comisiones_delete",
            "/api/seguros_checklist_generate",
            "/api/seguros_checklist_update",
            "/api/ai_seguros_copilot",
            "/api/s3_presign",
            "/api/clientes",
            "/api/clientes_link",
            "/api/cliente_update",
            "/api/cliente_empresa_update",
            "/api/acciones",
            "/api/acciones_update",
            "/api/cliente_gestoria_update",
            "/api/gestoria_modelos",
            "/api/gestoria_modelos_update",
            "/api/gestoria_modelos_delete",
            "/api/cliente_profesional",
            "/api/cliente_profesional_update",
            "/api/cliente_profesional_delete",
            "/api/captaciones",
            "/api/captaciones_update",
            "/api/captacion_update",
            "/api/inmueble_update",
            "/api/inmueble_propietarios_update",
            "/api/inmueble_docs",
            "/api/inmueble_checklist_generate",
            "/api/inmueble_checklist_update",
            "/api/demandas",
            "/api/visitas",
            "/api/usuarios",
            "/api/usuarios_update",
            "/api/usuarios_delete",
        ):
            json_response(self, {"error": "Endpoint no valido"}, status=404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length or 0)
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            json_response(self, {"error": "JSON invalido"}, status=400)
            return

        empresa_nombre = payload.get("empresa_nombre")
        if parsed.path not in (
            "/api/hipotecas/firmar",
            "/api/clientes",
            "/api/clientes_link",
            "/api/inmueble_update",
            "/api/inmueble_propietarios_update",
            "/api/captacion_update",
            "/api/cliente_update",
            "/api/cliente_empresa_update",
            "/api/acciones",
            "/api/acciones_update",
            "/api/cliente_profesional",
            "/api/cliente_profesional_update",
            "/api/cliente_profesional_delete",
            "/api/usuarios",
            "/api/usuarios_update",
            "/api/usuarios_delete",
            "/api/cliente_gestoria_update",
            "/api/inmueble_docs",
            "/api/inmueble_checklist_generate",
            "/api/inmueble_checklist_update",
            "/api/gestoria_modelos",
            "/api/gestoria_trabajos",
            "/api/gestoria_docs",
            "/api/gestoria_contabilidad",
            "/api/gestoria_trabajos_update",
            "/api/gestoria_trabajos_delete",
            "/api/gestoria_docs_update",
            "/api/gestoria_docs_delete",
            "/api/gestoria_contabilidad_update",
            "/api/gestoria_contabilidad_delete",
            "/api/fin_asesoramientos",
            "/api/fin_asesoramientos_update",
            "/api/fin_asesoramientos_convert",
            "/api/gestoria_conta_config",
            "/api/gestoria_conta_tasks_bulk",
            "/api/gestoria_conta_task_update",
            "/api/seguros_ocr",
            "/api/fin_asesoramiento_ocr",
            "/api/fin_asesoramiento_ocr_guided",
            "/api/fin_asesoramiento_ocr_auto",
            "/api/seguros_ofertas",
            "/api/seguros_ofertas_update",
            "/api/seguros_ofertas_delete",
            "/api/seguros_preferencias",
            "/api/seguros_referidos",
            "/api/seguros_campanas",
            "/api/seguros_campanas_update",
            "/api/seguros_campanas_delete",
            "/api/seguros_comisiones",
            "/api/seguros_comisiones_update",
            "/api/seguros_comisiones_delete",
            "/api/s3_presign",
        ):
            if not empresa_nombre:
                json_response(self, {"error": "empresa_nombre requerido"}, status=400)
                return

        if empresa_nombre == "Inmovere Gestión AIE":
            try:
                anio = int(payload.get("anio"))
            except (TypeError, ValueError):
                json_response(self, {"error": "anio invalido"}, status=400)
                return
            mes = str(payload.get("mes", "")).strip().lower()
            meses = [
                "enero",
                "febrero",
                "marzo",
                "abril",
                "mayo",
                "junio",
                "julio",
                "agosto",
                "septiembre",
                "octubre",
                "noviembre",
                "diciembre",
            ]
            mes_idx = meses.index(mes) if mes in meses else -1
            if anio < 2026 or (anio == 2026 and mes_idx < 1):
                json_response(self, {"error": "Solo desde Febrero 2026"}, status=400)
                return

        conn = get_db(self.db_path)
        empresa = None
        if parsed.path not in (
            "/api/hipotecas/firmar",
            "/api/clientes",
            "/api/clientes_link",
            "/api/cliente_update",
            "/api/cliente_empresa_update",
            "/api/cliente_gestoria_update",
            "/api/cliente_profesional",
            "/api/cliente_profesional_update",
            "/api/cliente_profesional_delete",
            "/api/usuarios",
            "/api/usuarios_update",
            "/api/usuarios_delete",
            "/api/acciones_update",
            "/api/gestoria_modelos",
            "/api/gestoria_modelos_update",
            "/api/gestoria_modelos_delete",
            "/api/gestoria_trabajos_update",
            "/api/gestoria_trabajos_delete",
            "/api/gestoria_docs_update",
            "/api/gestoria_docs_delete",
            "/api/gestoria_contabilidad_update",
            "/api/gestoria_contabilidad_delete",
            "/api/auditoria",
            "/api/acciones",
            "/api/seguros_ocr",
            "/api/fin_asesoramiento_ocr",
            "/api/fin_asesoramiento_ocr_guided",
            "/api/fin_asesoramiento_ocr_auto",
            "/api/s3_presign",
            "/api/inmueble_checklist_generate",
            "/api/inmueble_checklist_update",
        ):
            empresa = conn.execute(
                "SELECT id FROM empresas WHERE nombre = ?",
                (empresa_nombre,),
            ).fetchone()
            if not empresa:
                json_response(self, {"error": "Empresa no encontrada"}, status=400)
                return

        now = "now"
        def audit(entidad, entidad_id, accion, detalles=None, usuario=None):
            conn.execute(
                """
                INSERT INTO auditoria (
                  id, empresa_id, entidad, entidad_id, accion, usuario, detalles, created_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"] if empresa else None,
                    entidad,
                    entidad_id,
                    accion,
                    usuario or "Sistema",
                    detalles,
                    now,
                ),
            )
        if parsed.path == "/api/s3_presign":
            filename = payload.get("filename") or "archivo.pdf"
            content_type = payload.get("content_type") or "application/pdf"
            prefix = payload.get("prefix") or "seguros"
            client = s3_client()
            if not client:
                json_response(self, {"error": "S3 no configurado"}, status=400)
                return
            key = s3_safe_key(prefix, filename)
            try:
                url = client.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": S3_BUCKET,
                        "Key": key,
                        "ContentType": content_type,
                    },
                    ExpiresIn=900,
                )
            except Exception:
                json_response(self, {"error": "No se pudo firmar la subida"}, status=500)
                return
            public_url = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{key}"
            json_response(self, {"url": url, "key": key, "public_url": public_url})
            return
        if parsed.path == "/api/movimientos":
            conn.execute(
                """
                INSERT INTO movimientos (
                  id, empresa_id, concepto, pisos_vendidos, comision, asesor,
                  anio, mes, sl, tipo, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("concepto"),
                    payload.get("pisos_vendidos"),
                    payload.get("comision"),
                    payload.get("asesor"),
                    payload.get("anio"),
                    payload.get("mes"),
                    payload.get("sl"),
                    payload.get("tipo"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/gestoria":
            conn.execute(
                """
                INSERT INTO gestoria (
                  id, empresa_id, cliente, fecha, cuota, precio, tipo, perfil,
                  estado, fecha_baja,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("cliente"),
                    payload.get("fecha"),
                    payload.get("cuota"),
                    payload.get("precio"),
                    payload.get("tipo"),
                    payload.get("perfil"),
                    payload.get("estado"),
                    payload.get("fecha_baja"),
                    now,
                    now,
                ),
            )
            audit("gestoria_cliente", payload.get("cliente"), "crear", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_trabajos":
            conn.execute(
                """
                INSERT INTO gestoria_trabajos (
                  id, empresa_id, cliente_id, tipo_trabajo, estado,
                  fecha_inicio, fecha_fin, sla_dias, responsable, importe, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("cliente_id"),
                    payload.get("tipo_trabajo"),
                    payload.get("estado"),
                    payload.get("fecha_inicio"),
                    payload.get("fecha_fin"),
                    payload.get("sla_dias"),
                    payload.get("responsable"),
                    payload.get("importe"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
            audit("gestoria_trabajo", payload.get("cliente_id"), "crear", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_trabajos_update":
            trabajo_id = payload.get("id")
            if not trabajo_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = (
                "tipo_trabajo",
                "estado",
                "fecha_inicio",
                "fecha_fin",
                "sla_dias",
                "responsable",
                "importe",
                "notas",
            )
            updates = []
            values = []
            for field in allowed:
                if field in payload:
                    updates.append(f"{field} = ?")
                    values.append(payload.get(field))
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            conn.execute(
                f"""
                UPDATE gestoria_trabajos
                SET {", ".join(updates)}, updated_at = datetime(?)
                WHERE id = ?
                """,
                (*values, now, trabajo_id),
            )
            audit("gestoria_trabajo", trabajo_id, "actualizar", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_trabajos_delete":
            trabajo_id = payload.get("id")
            if not trabajo_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM gestoria_trabajos WHERE id = ?", (trabajo_id,))
            audit("gestoria_trabajo", trabajo_id, "eliminar", None, payload.get("usuario"))
        elif parsed.path == "/api/gestoria_docs":
            conn.execute(
                """
                INSERT INTO gestoria_docs (
                  id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                  nombre, tipo, fecha, estado, notas, doc_key, doc_url,
                  calidad_ocr, campos_ocr, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("cliente_id"),
                    payload.get("referencia_tipo"),
                    payload.get("referencia_id"),
                    payload.get("nombre"),
                    payload.get("tipo"),
                    payload.get("fecha"),
                    payload.get("estado"),
                    payload.get("notas"),
                    payload.get("doc_key"),
                    payload.get("doc_url"),
                    payload.get("calidad_ocr"),
                    payload.get("campos_ocr"),
                    now,
                    now,
                ),
            )
            audit("gestoria_doc", payload.get("cliente_id"), "crear", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_docs_update":
            doc_id = payload.get("id")
            if not doc_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = (
                "nombre",
                "referencia_tipo",
                "referencia_id",
                "tipo",
                "fecha",
                "estado",
                "notas",
                "doc_key",
                "doc_url",
                "calidad_ocr",
                "campos_ocr",
            )
            updates = []
            values = []
            for field in allowed:
                if field in payload:
                    updates.append(f"{field} = ?")
                    values.append(payload.get(field))
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            conn.execute(
                f"""
                UPDATE gestoria_docs
                SET {", ".join(updates)}, updated_at = datetime(?)
                WHERE id = ?
                """,
                (*values, now, doc_id),
            )
            audit("gestoria_doc", doc_id, "actualizar", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_docs_delete":
            doc_id = payload.get("id")
            if not doc_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM gestoria_docs WHERE id = ?", (doc_id,))
            audit("gestoria_doc", doc_id, "eliminar", None, payload.get("usuario"))
        elif parsed.path == "/api/usuarios":
            nombre = payload.get("nombre")
            apellido = payload.get("apellido")
            usuario = payload.get("usuario")
            email = payload.get("email")
            servicio = payload.get("servicio")
            password = payload.get("password")
            if not nombre:
                json_response(self, {"error": "nombre requerido"}, status=400)
                return
            if not apellido:
                json_response(self, {"error": "apellido requerido"}, status=400)
                return
            if not usuario:
                json_response(self, {"error": "usuario requerido"}, status=400)
                return
            if not email:
                json_response(self, {"error": "email requerido"}, status=400)
                return
            if not servicio:
                json_response(self, {"error": "servicio requerido"}, status=400)
                return
            if not password:
                json_response(self, {"error": "password requerido"}, status=400)
                return
            password_hash = hash_password(password)
            conn.execute(
                """
                INSERT INTO usuarios (id, nombre, apellido, usuario, email, servicio, rol, password_hash, activo, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?))
                """,
                (
                    os.urandom(16).hex(),
                    nombre,
                    apellido,
                    usuario,
                    email,
                    servicio,
                    payload.get("rol"),
                    password_hash,
                    int(payload.get("activo") or 1),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/usuarios_update":
            user_id = payload.get("id")
            if not user_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("nombre", "apellido", "usuario", "email", "servicio", "rol", "activo", "password")
            updates = []
            values = []
            for field in allowed:
                if field in payload:
                    if field == "password":
                        updates.append("password_hash = ?")
                        values.append(hash_password(payload.get("password")))
                    else:
                        updates.append(f"{field} = ?")
                        values.append(payload.get(field))
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            conn.execute(
                f"""
                UPDATE usuarios
                SET {", ".join(updates)}, updated_at = datetime(?)
                WHERE id = ?
                """,
                (*values, now, user_id),
            )
        elif parsed.path == "/api/usuarios_delete":
            user_id = payload.get("id")
            if not user_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        elif parsed.path == "/api/gestoria_contabilidad":
            conn.execute(
                """
                INSERT INTO gestoria_contabilidad (
                  id, empresa_id, cliente_id, fecha, concepto, gestion, tipo, importe, notas,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("cliente_id"),
                    payload.get("fecha"),
                    payload.get("concepto"),
                    payload.get("gestion"),
                    payload.get("tipo"),
                    payload.get("importe"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/gestoria_contabilidad_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("fecha", "concepto", "gestion", "tipo", "importe", "notas", "cliente_id")
            updates = []
            values = []
            for field in allowed:
                if field in payload:
                    updates.append(f"{field} = ?")
                    values.append(payload.get(field))
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            conn.execute(
                f"""
                UPDATE gestoria_contabilidad
                SET {", ".join(updates)}, updated_at = datetime(?)
                WHERE id = ?
                """,
                (*values, now, record_id),
            )
        elif parsed.path == "/api/gestoria_contabilidad_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM gestoria_contabilidad WHERE id = ?", (record_id,))
        elif parsed.path == "/api/gestoria_conta_config":
            cliente_id = payload.get("cliente_id")
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            periodo = payload.get("periodo")
            fecha_inicio = payload.get("fecha_inicio")
            responsable = payload.get("responsable")
            existing = conn.execute(
                "SELECT id FROM gestoria_conta_config WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE gestoria_conta_config
                    SET periodo = ?, fecha_inicio = ?, responsable = ?, updated_at = datetime(?)
                    WHERE cliente_id = ?
                    """,
                    (periodo, fecha_inicio, responsable, now, cliente_id),
                )
                record_id = existing["id"]
            else:
                record_id = os.urandom(16).hex()
                conn.execute(
                    """
                    INSERT INTO gestoria_conta_config (
                      id, cliente_id, periodo, fecha_inicio, responsable, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (record_id, cliente_id, periodo, fecha_inicio, responsable, now, now),
                )
            audit("gestoria_conta_config", record_id, "Guardar configuración contable", usuario=payload.get("usuario"))
        elif parsed.path == "/api/gestoria_conta_tasks_bulk":
            cliente_id = payload.get("cliente_id")
            periodo = payload.get("periodo")
            tareas = payload.get("tareas", [])
            if not cliente_id or not periodo or not isinstance(tareas, list):
                json_response(self, {"error": "cliente_id, periodo y tareas requeridos"}, status=400)
                return
            conn.execute(
                "DELETE FROM gestoria_conta_tasks WHERE cliente_id = ? AND periodo = ?",
                (cliente_id, periodo),
            )
            for tarea in tareas:
                conn.execute(
                    """
                    INSERT INTO gestoria_conta_tasks (
                      id, cliente_id, periodo, tarea, estado, fecha_limite, responsable, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        os.urandom(16).hex(),
                        cliente_id,
                        periodo,
                        tarea.get("tarea"),
                        tarea.get("estado") or "Pendiente",
                        tarea.get("fecha_limite"),
                        tarea.get("responsable"),
                        now,
                        now,
                    ),
                )
            audit(
                "gestoria_conta_tasks",
                cliente_id,
                f"Crear checklist contable ({periodo})",
                usuario=payload.get("usuario"),
            )
        elif parsed.path == "/api/gestoria_conta_task_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            fields = ["tarea", "estado", "fecha_limite", "responsable"]
            updates = {f: payload.get(f) for f in fields if f in payload}
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{k} = ?" for k in updates])
            values = list(updates.values())
            values.append(now)
            values.append(record_id)
            conn.execute(
                f"UPDATE gestoria_conta_tasks SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            audit("gestoria_conta_tasks", record_id, "Actualizar tarea contable", usuario=payload.get("usuario"))
        elif parsed.path == "/api/seguros_ocr":
            data_uri = payload.get("file_base64") or payload.get("data")
            if not data_uri:
                json_response(self, {"error": "Archivo requerido"}, status=400)
                return
            if "," in data_uri:
                data_uri = data_uri.split(",", 1)[1]
            try:
                pdf_bytes = base64.b64decode(data_uri)
            except Exception:
                json_response(self, {"error": "Base64 invalido"}, status=400)
                return
            tmp_path = None
            text = ""
            err_detail = ""
            method = ""
            required_keys = ("tomador", "poliza_numero", "compania", "fecha_efecto")
            try:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_file:
                    tmp_file.write(pdf_bytes)
                    tmp_path = tmp_file.name
                text, err_detail, method = extract_pdf_text(tmp_path)
                if not text:
                    json_response(
                        self,
                        {
                            "error": "No se pudo extraer texto.",
                            "detail": err_detail or "Verifica tesseract y spa.traineddata.",
                            "language": detect_ocr_lang(),
                        },
                        status=400,
                    )
                    return
                fields = parse_poliza_text(text)
                if not any(str(value or "").strip() for value in fields.values()) or (
                    not fields.get("poliza_numero")
                    or not fields.get("tomador")
                    or not fields.get("compania")
                    or not fields.get("fecha_efecto")
                ):
                    ocr_text, ocr_err = ocr_pdf_all_pages(tmp_path, use_external=external_ocr_available())
                    if ocr_text:
                        fields = parse_poliza_text(ocr_text)
                        text = ocr_text
                        method = "vision" if external_ocr_available() else "tesseract"
                    elif ocr_err and not err_detail:
                        err_detail = ocr_err
                doc_text = ""
                missing_required = any(not fields.get(key) for key in required_keys)
                if missing_required and docai_available():
                    doc_text, doc_fields, doc_err = ocr_image_docai(pdf_bytes, "application/pdf")
                    if doc_err and not err_detail:
                        err_detail = doc_err
                    doc_mapped = map_docai_poliza_fields(doc_fields)
                    doc_parsed = parse_poliza_text(doc_text) if doc_text else {}
                    for key, value in doc_mapped.items():
                        if value and not fields.get(key):
                            fields[key] = value
                    for key, value in doc_parsed.items():
                        if value and not fields.get(key):
                            fields[key] = value
                    if doc_text and doc_text.strip():
                        method = "docai"
                doc_type = classify_seguros_document(text)
                if doc_type == "otro" and doc_text:
                    doc_type = classify_seguros_document(doc_text)
                ocr_quality = compute_ocr_quality(fields, required_keys)
                cliente_match = False
                cliente_id = None
                tomador = (fields.get("tomador") or "").strip()
                nif = (fields.get("nif") or fields.get("dni") or "").strip()
                if tomador or nif:
                    if nif:
                        nif_norm = re.sub(r"\s+", "", nif).upper()
                        row = conn.execute(
                            "SELECT id FROM clientes WHERE REPLACE(UPPER(nif), ' ', '') = ?",
                            (nif_norm,),
                        ).fetchone()
                        if row:
                            cliente_id = row["id"]
                            cliente_match = True
                    if not cliente_match and tomador:
                        nombre_norm = re.sub(r"\s+", " ", tomador).strip().upper()
                        row = conn.execute(
                            "SELECT id FROM clientes WHERE TRIM(UPPER(nombre)) = ?",
                            (nombre_norm,),
                        ).fetchone()
                        if row:
                            cliente_id = row["id"]
                            cliente_match = True
                json_response(
                    self,
                    {
                        "fields": fields,
                        "text": text,
                        "language": detect_ocr_lang(),
                        "method": method,
                        "doc_type": doc_type,
                        "ocr_quality": ocr_quality,
                        "cliente_id": cliente_id,
                        "cliente_match": cliente_match,
                    },
                )
                return
            except Exception as exc:
                json_response(self, {"error": "No se pudo procesar el PDF.", "detail": str(exc)}, status=400)
                return
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        elif parsed.path == "/api/fin_asesoramiento_ocr":
            data_uri = payload.get("file_base64") or payload.get("data")
            if not data_uri:
                json_response(self, {"error": "Archivo requerido"}, status=400)
                return
            use_external = bool(payload.get("use_external"))
            ocr_mode = (payload.get("ocr_mode") or "").strip().lower()
            if ocr_mode == "handwritten":
                use_external = True
                ocr_mode = "hybrid"
            if external_ocr_available() and not use_external:
                use_external = True
            if not ocr_mode:
                if external_ocr_available() and docai_available():
                    ocr_mode = "hybrid"
                elif docai_available():
                    ocr_mode = "docai"
            if external_ocr_available() and not use_external:
                use_external = True
            if not ocr_mode:
                if external_ocr_available() and docai_available():
                    ocr_mode = "hybrid"
                elif docai_available():
                    ocr_mode = "docai"
            mime = ""
            if "," in data_uri:
                header, data_uri = data_uri.split(",", 1)
                if header.startswith("data:") and ";base64" in header:
                    mime = header.split(":", 1)[1].split(";", 1)[0]
            try:
                pdf_bytes = base64.b64decode(data_uri)
            except Exception:
                json_response(self, {"error": "Base64 invalido"}, status=400)
                return
            tmp_path = None
            external_error = ""
            external_used = False
            try:
                suffix = ".pdf"
                if mime.startswith("image/"):
                    ext = mime.split("/", 1)[1]
                    suffix = f".{ext}"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                    tmp_file.write(pdf_bytes)
                    tmp_path = tmp_file.name
                if mime.startswith("image/"):
                    text = ""
                    err_detail = ""
                    method = "tesseract"
                    if ocr_mode == "docai":
                        text, doc_fields, err_detail = ocr_image_docai(pdf_bytes, mime)
                        method = "docai"
                        if doc_fields:
                            fields = map_docai_fields(doc_fields)
                        else:
                            fields = parse_asesoramiento_text(text) if text else {}
                    elif ocr_mode == "hybrid":
                        vision_text = ""
                        vision_err = ""
                        if use_external:
                            vision_text, vision_err = ocr_image_external(pdf_bytes)
                            external_error = vision_err or ""
                            external_used = bool(vision_text)
                        if not vision_text:
                            vision_text, vision_err = ocr_image_file(tmp_path)
                        vision_fields = parse_asesoramiento_text(vision_text) if vision_text else {}
                        template_fields = parse_asesoramiento_template_image(tmp_path)
                        vision_fields = merge_fields(vision_fields, template_fields)
                        doc_text, doc_fields, doc_err = ocr_image_docai(pdf_bytes, mime)
                        if doc_err:
                            err_detail = doc_err
                        doc_mapped = map_docai_fields(doc_fields)
                        fields = merge_fields(vision_fields, doc_mapped)
                        text = "\n".join([t for t in (vision_text, doc_text) if t])
                        method = "hybrid"
                    elif use_external:
                        text, err_detail = ocr_image_external(pdf_bytes)
                        external_error = err_detail or ""
                        method = "vision"
                        external_used = bool(text)
                    if not text:
                        text, err_detail = ocr_image_file(tmp_path)
                        method = "tesseract"
                    if "template_fields" not in locals():
                        template_fields = parse_asesoramiento_template_image(tmp_path)
                    if "fields" not in locals():
                        fields = parse_asesoramiento_text(text) if text else {}
                    if openai_available() and text:
                        ai_fields, ai_err = call_openai_extract_fin(text)
                        if ai_fields:
                            fields = merge_many_fields(fields, ai_fields)
                    for key, value in template_fields.items():
                        if not str(fields.get(key, "") or "").strip() and str(value or "").strip():
                            fields[key] = value
                    if openai_available() and text:
                        ai_fields, ai_err = call_openai_extract_fin(text)
                        if ai_fields:
                            fields = merge_many_fields(fields, ai_fields)
                else:
                    text, err_detail, method = extract_pdf_text(tmp_path)
                    if not text:
                        json_response(
                            self,
                            {
                                "error": "No se pudo extraer texto.",
                                "detail": err_detail or "Verifica tesseract y spa.traineddata.",
                                "language": detect_ocr_lang(),
                                "method": method,
                            },
                            status=400,
                        )
                        return
                    fields = parse_asesoramiento_text(text)
                    template_fields = parse_asesoramiento_template(tmp_path)
                    for key, value in template_fields.items():
                        if not str(fields.get(key, "") or "").strip() and str(value or "").strip():
                            fields[key] = value
                    filled = sum(1 for value in fields.values() if str(value or "").strip())
                    if filled < 8 or use_external:
                        ocr_text, ocr_err = ocr_pdf_all_pages(tmp_path, use_external=use_external)
                        if ocr_text:
                            ocr_fields = parse_asesoramiento_text(ocr_text)
                            for key, value in ocr_fields.items():
                                if not str(fields.get(key, "") or "").strip() and str(value or "").strip():
                                    fields[key] = value
                            text = ocr_text
                            method = "vision" if use_external else "tesseract"
                            external_used = external_used or bool(use_external)
                        elif ocr_err:
                            err_detail = ocr_err
                    doc_text = ""
                    if docai_available() and (use_external or filled < 10):
                        doc_text, doc_fields, doc_err = ocr_image_docai(pdf_bytes, "application/pdf")
                        if doc_err and not err_detail:
                            err_detail = doc_err
                        doc_mapped = map_docai_fields(doc_fields)
                        for key, value in doc_mapped.items():
                            if not str(fields.get(key, "") or "").strip() and str(value or "").strip():
                                fields[key] = value
                    if doc_text:
                        text = text or doc_text
                        method = "hybrid" if use_external else "docai"
                        external_used = external_used or bool(doc_text)
                    if openai_available() and text:
                        ai_fields, ai_err = call_openai_extract_fin(text)
                        if ai_fields:
                            fields = merge_many_fields(fields, ai_fields)
                if not text and not any(str(value or "").strip() for value in fields.values()):
                    json_response(
                        self,
                        {
                            "error": "No se pudo extraer texto.",
                            "detail": err_detail or "Verifica tesseract y spa.traineddata.",
                            "language": detect_ocr_lang(),
                            "method": method,
                        },
                        status=400,
                    )
                    return
                fin_quality = compute_fin_quality(fields)
                json_response(
                    self,
                    {
                        "fields": fields,
                        "text": text,
                        "language": detect_ocr_lang(),
                        "method": method,
                        "external_error": external_error,
                        "external_used": external_used,
                        "ocr_quality": fin_quality,
                    },
                )
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        elif parsed.path == "/api/fin_asesoramiento_ocr_guided":
            sections = payload.get("sections") or {}
            use_external = bool(payload.get("use_external"))
            ocr_mode = (payload.get("ocr_mode") or "").strip().lower()
            if ocr_mode == "handwritten":
                use_external = True
            allowed = {
                "header": "Cabecera",
                "cliente1": "Cliente 1",
                "cliente2": "Cliente 2",
                "resumen": "Resumen",
            }
            if not any(sections.get(key) for key in allowed):
                json_response(self, {"error": "Archivos requeridos"}, status=400)
                return
            fields = {}
            texts = []
            external_error = ""
            external_used = False
            for key in ("header", "cliente1", "cliente2", "resumen"):
                data_uri = sections.get(key)
                if not data_uri:
                    continue
                mime = ""
                if "," in data_uri:
                    header, data_uri = data_uri.split(",", 1)
                    if header.startswith("data:") and ";base64" in header:
                        mime = header.split(":", 1)[1].split(";", 1)[0]
                if not mime.startswith("image/"):
                    json_response(self, {"error": f"{allowed[key]} debe ser imagen"}, status=400)
                    return
                try:
                    image_bytes = base64.b64decode(data_uri)
                except Exception:
                    json_response(self, {"error": f"{allowed[key]} base64 invalido"}, status=400)
                    return
                text = ""
                err_detail = ""
                method = "tesseract"
                if use_external:
                    text, err_detail = ocr_image_external(image_bytes)
                    external_error = err_detail or external_error
                    method = "vision"
                    external_used = external_used or bool(text)
                if not text:
                    tmp_path = None
                    try:
                        ext = mime.split("/", 1)[1]
                        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_file:
                            tmp_file.write(image_bytes)
                            tmp_path = tmp_file.name
                        text, err_detail = ocr_image_file(tmp_path)
                        method = "tesseract"
                    finally:
                        if tmp_path and os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                if not text:
                    continue
                texts.append(f"[{allowed[key]}]\n{text}")
                if key == "header":
                    header_fields = parse_asesoramiento_text(text)
                    for field in ("inmobiliaria_asesor", "fecha", "asesor"):
                        if header_fields.get(field) and not fields.get(field):
                            fields[field] = header_fields.get(field)
                elif key == "cliente1":
                    data1 = parse_asesoramiento_block(text)
                    for field, target in (
                        ("nombre", "cliente1_nombre"),
                        ("dni", "cliente1_dni"),
                        ("telefono", "cliente1_telefono"),
                        ("email", "cliente1_email"),
                        ("fecha_nacimiento", "cliente1_fecha_nacimiento"),
                        ("estado_civil", "cliente1_estado_civil"),
                        ("hijos", "cliente1_hijos"),
                        ("profesion", "cliente1_profesion"),
                        ("tipo_contrato", "cliente1_tipo_contrato"),
                        ("ingresos", "cliente1_ingresos"),
                        ("patrimonio", "cliente1_patrimonio"),
                        ("prestamos", "cliente1_prestamos"),
                    ):
                        if data1.get(field) and not fields.get(target):
                            fields[target] = data1.get(field)
                elif key == "cliente2":
                    data2 = parse_asesoramiento_block(text)
                    for field, target in (
                        ("nombre", "cliente2_nombre"),
                        ("dni", "cliente2_dni"),
                        ("telefono", "cliente2_telefono"),
                        ("email", "cliente2_email"),
                        ("fecha_nacimiento", "cliente2_fecha_nacimiento"),
                        ("estado_civil", "cliente2_estado_civil"),
                        ("hijos", "cliente2_hijos"),
                        ("profesion", "cliente2_profesion"),
                        ("tipo_contrato", "cliente2_tipo_contrato"),
                        ("ingresos", "cliente2_ingresos"),
                        ("patrimonio", "cliente2_patrimonio"),
                        ("prestamos", "cliente2_prestamos"),
                    ):
                        if data2.get(field) and not fields.get(target):
                            fields[target] = data2.get(field)
                elif key == "resumen":
                    resumen_fields = parse_asesoramiento_text(text)
                    for field in ("ingresos_conjuntos", "entidades_financieras", "avalistas", "aportacion_cv"):
                        if resumen_fields.get(field) and not fields.get(field):
                            fields[field] = resumen_fields.get(field)
                if not any(str(value or "").strip() for value in fields.values()):
                    json_response(
                        self,
                        {
                            "error": "No se pudieron detectar campos.",
                            "detail": "Sube recortes más cercanos a cada bloque.",
                        },
                        status=400,
                    )
                    return
                if openai_available() and texts:
                    ai_fields, ai_err = call_openai_extract_fin("\n\n".join(texts))
                    if ai_fields:
                        fields = merge_many_fields(fields, ai_fields)
                fin_quality = compute_fin_quality(fields)
            json_response(
                self,
                {
                    "fields": fields,
                    "text": "\n\n".join(texts).strip(),
                    "language": detect_ocr_lang(),
                    "method": "guided",
                    "external_error": external_error,
                    "external_used": external_used,
                    "ocr_quality": fin_quality,
                },
            )
        elif parsed.path == "/api/fin_asesoramiento_ocr_auto":
            data_uri = payload.get("file_base64") or payload.get("data")
            if not data_uri:
                json_response(self, {"error": "Archivo requerido"}, status=400)
                return
            use_external = bool(payload.get("use_external"))
            ocr_mode = (payload.get("ocr_mode") or "").strip().lower()
            if ocr_mode == "handwritten":
                use_external = True
                ocr_mode = "hybrid"
            external_error = ""
            external_used = False
            mime = ""
            if "," in data_uri:
                header, data_uri = data_uri.split(",", 1)
                if header.startswith("data:") and ";base64" in header:
                    mime = header.split(":", 1)[1].split(";", 1)[0]
            if not mime.startswith("image/"):
                json_response(self, {"error": "La imagen debe ser JPG o PNG."}, status=400)
                return
            try:
                image_bytes = base64.b64decode(data_uri)
            except Exception:
                json_response(self, {"error": "Base64 invalido"}, status=400)
                return
            tmp_path = None
            try:
                ext = mime.split("/", 1)[1]
                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp_file:
                    tmp_file.write(image_bytes)
                    tmp_path = tmp_file.name
                if ocr_mode == "docai":
                    text, doc_fields, err_detail = ocr_image_docai(image_bytes, mime)
                    fields = map_docai_fields(doc_fields) if doc_fields else parse_asesoramiento_text(text)
                    fin_quality = compute_fin_quality(fields)
                    json_response(
                        self,
                        {
                            "fields": fields,
                            "text": text,
                            "language": detect_ocr_lang(),
                            "method": "docai",
                            "external_error": err_detail,
                            "external_used": True if text else False,
                            "ocr_quality": fin_quality,
                        },
                    )
                    return
                if ocr_mode == "hybrid":
                    vision_text = ""
                    vision_err = ""
                    if use_external:
                        vision_text, vision_err = ocr_image_external(image_bytes)
                        external_error = vision_err or ""
                        external_used = bool(vision_text)
                    if not vision_text:
                        vision_text, _ = ocr_image_file(tmp_path)
                    doc_text, doc_fields, doc_err = ocr_image_docai(image_bytes, mime)
                    if doc_err:
                        external_error = doc_err
                    fields = map_docai_fields(doc_fields)
                    vision_fields = parse_asesoramiento_text(vision_text) if vision_text else {}
                    fields = merge_fields(vision_fields, fields)
                    fin_quality = compute_fin_quality(fields)
                    json_response(
                        self,
                        {
                            "fields": fields,
                            "text": "\n".join([t for t in (vision_text, doc_text) if t]),
                            "language": detect_ocr_lang(),
                            "method": "hybrid",
                            "external_error": external_error,
                            "external_used": external_used,
                            "ocr_quality": fin_quality,
                        },
                    )
                    return
                size = get_image_size(tmp_path)
                if not size:
                    json_response(self, {"error": "No se pudo leer la imagen."}, status=400)
                    return
                width, height = size
                boxes = asesoramiento_image_boxes(width, height)
                fields = {}
                texts = []
                external_error = ""
                external_used = False
                for key in ("header", "cliente1", "cliente2", "resumen"):
                    block_text, err = ocr_best_block(tmp_path, boxes[key], use_external)
                    if err:
                        external_error = external_error or err
                    if not block_text:
                        continue
                    texts.append(f"[{key}]\n{block_text}")
                    if use_external and block_text:
                        external_used = True
                    if key == "header":
                        header_fields = parse_asesoramiento_text(block_text)
                        for field in ("inmobiliaria_asesor", "fecha", "asesor"):
                            if header_fields.get(field) and not fields.get(field):
                                fields[field] = header_fields.get(field)
                    elif key == "cliente1":
                        data1 = parse_asesoramiento_block(block_text)
                        for field, target in (
                            ("nombre", "cliente1_nombre"),
                            ("dni", "cliente1_dni"),
                            ("telefono", "cliente1_telefono"),
                            ("email", "cliente1_email"),
                            ("fecha_nacimiento", "cliente1_fecha_nacimiento"),
                            ("estado_civil", "cliente1_estado_civil"),
                            ("hijos", "cliente1_hijos"),
                            ("profesion", "cliente1_profesion"),
                            ("tipo_contrato", "cliente1_tipo_contrato"),
                            ("ingresos", "cliente1_ingresos"),
                            ("patrimonio", "cliente1_patrimonio"),
                            ("prestamos", "cliente1_prestamos"),
                        ):
                            if data1.get(field) and not fields.get(target):
                                fields[target] = data1.get(field)
                    elif key == "cliente2":
                        data2 = parse_asesoramiento_block(block_text)
                        for field, target in (
                            ("nombre", "cliente2_nombre"),
                            ("dni", "cliente2_dni"),
                            ("telefono", "cliente2_telefono"),
                            ("email", "cliente2_email"),
                            ("fecha_nacimiento", "cliente2_fecha_nacimiento"),
                            ("estado_civil", "cliente2_estado_civil"),
                            ("hijos", "cliente2_hijos"),
                            ("profesion", "cliente2_profesion"),
                            ("tipo_contrato", "cliente2_tipo_contrato"),
                            ("ingresos", "cliente2_ingresos"),
                            ("patrimonio", "cliente2_patrimonio"),
                            ("prestamos", "cliente2_prestamos"),
                        ):
                            if data2.get(field) and not fields.get(target):
                                fields[target] = data2.get(field)
                    elif key == "resumen":
                        resumen_fields = parse_asesoramiento_text(block_text)
                        for field in ("ingresos_conjuntos", "entidades_financieras", "avalistas", "aportacion_cv"):
                            if resumen_fields.get(field) and not fields.get(field):
                                fields[field] = resumen_fields.get(field)
                if not any(str(value or "").strip() for value in fields.values()):
                    json_response(
                        self,
                        {"error": "No se pudieron detectar campos.", "detail": "Prueba con recortes manuales."},
                        status=400,
                    )
                    return
                fin_quality = compute_fin_quality(fields)
                json_response(
                    self,
                    {
                        "fields": fields,
                        "text": "\n\n".join(texts).strip(),
                        "language": detect_ocr_lang(),
                        "method": "auto",
                        "external_error": external_error,
                        "external_used": external_used,
                        "ocr_quality": fin_quality,
                    },
                )
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        elif parsed.path == "/api/seguros":
            poliza_id = os.urandom(16).hex()
            cliente_id = payload.get("cliente_id")
            if cliente_id:
                exists = conn.execute(
                    "SELECT id FROM clientes WHERE id = ? AND empresa_id = ?",
                    (cliente_id, empresa["id"]),
                ).fetchone()
                if not exists:
                    cliente_id = None
            if not cliente_id:
                cliente_id = ensure_cliente_for_seguro(
                    conn,
                    empresa["id"],
                    payload.get("tomador"),
                    payload.get("nif") or payload.get("dni"),
                    now,
                    {
                        "telefono": payload.get("telefono"),
                        "email": payload.get("email"),
                        "fecha_nacimiento": payload.get("fecha_nacimiento"),
                        "direccion": payload.get("direccion"),
                    },
                )
            poliza_key = payload.get("poliza_key") or ""
            poliza_url = payload.get("poliza_url") or ""
            ocr_quality = payload.get("ocr_quality") or {}
            calidad_ocr = ocr_quality.get("calidad") if isinstance(ocr_quality, dict) else payload.get("calidad_ocr")
            campos_ocr = ""
            if isinstance(ocr_quality, dict):
                campos_list = ocr_quality.get("campos") or []
                if isinstance(campos_list, list):
                    campos_ocr = ",".join(campos_list)
                else:
                    campos_ocr = str(campos_list)
            else:
                campos_ocr = payload.get("campos_ocr") or ""
            # Deduplicación suave: si existe póliza con mismo nº y compañía, actualizar campos vacíos
            dup_id = None
            poliza_norm = normalize_poliza_key(payload.get("poliza_numero"))
            compania_norm = normalize_company_key(payload.get("compania"))
            if poliza_norm:
                candidates = conn.execute(
                    "SELECT id, poliza_numero, compania, cliente_id FROM seguros WHERE empresa_id = ?",
                    (empresa["id"],),
                ).fetchall()
                for row in candidates:
                    row_poliza = normalize_poliza_key(row["poliza_numero"])
                    if not row_poliza or row_poliza != poliza_norm:
                        continue
                    row_comp = normalize_company_key(row["compania"])
                    if compania_norm and row_comp and compania_norm != row_comp:
                        continue
                    if cliente_id and row["cliente_id"] and row["cliente_id"] != cliente_id:
                        continue
                    dup_id = row["id"]
                    break

            if dup_id:
                # Enriquecer la póliza existente con campos vacíos
                row = conn.execute("SELECT * FROM seguros WHERE id = ?", (dup_id,)).fetchone()
                updates = {}
                for key in (
                    "estado",
                    "fecha_efecto",
                    "fecha_vencimiento",
                    "estado_renovacion",
                    "renovacion_fecha",
                    "nueva_poliza_ref",
                    "poliza_numero",
                    "poliza_key",
                    "poliza_url",
                    "tomador",
                    "compania",
                    "ramo",
                    "prima_neta",
                    "prima_total",
                ):
                    incoming = payload.get(key)
                    if incoming in (None, ""):
                        continue
                    current = row[key] if key in row.keys() else None
                    if current is None or str(current).strip() == "":
                        updates[key] = incoming
                if updates:
                    set_clause = ", ".join([f\"{key} = ?\" for key in updates])
                    values = list(updates.values()) + [now, dup_id]
                    conn.execute(
                        f\"UPDATE seguros SET {set_clause}, updated_at = datetime(?) WHERE id = ?\",
                        values,
                    )
                poliza_id = dup_id
            else:
                conn.execute(
                    """
                    INSERT INTO seguros (
                      id, empresa_id, cliente_id, mes_creacion, fecha_efecto, fecha_vencimiento,
                      tomador, compania, ramo, poliza_numero, prima_neta,
                      prima_total, comision, produccion, colaborador, estado,
                      estado_renovacion, renovacion_fecha, nueva_poliza_ref,
                      poliza_key, poliza_url,
                      created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        poliza_id,
                        empresa["id"],
                        cliente_id,
                        payload.get("mes_creacion"),
                        payload.get("fecha_efecto"),
                        payload.get("fecha_vencimiento"),
                        payload.get("tomador"),
                        payload.get("compania"),
                        payload.get("ramo"),
                        payload.get("poliza_numero"),
                        payload.get("prima_neta"),
                        payload.get("prima_total"),
                        payload.get("comision"),
                        payload.get("produccion"),
                        payload.get("colaborador"),
                        payload.get("estado"),
                        payload.get("estado_renovacion"),
                        payload.get("renovacion_fecha"),
                        payload.get("nueva_poliza_ref"),
                        payload.get("poliza_key"),
                        payload.get("poliza_url"),
                        now,
                        now,
                    ),
                )
            if cliente_id and (poliza_key or poliza_url):
                where = ["cliente_id = ?", "empresa_id = ?"]
                values = [cliente_id, empresa["id"]]
                key_or_url = []
                if poliza_key:
                    key_or_url.append("doc_key = ?")
                    values.append(poliza_key)
                if poliza_url:
                    key_or_url.append("doc_url = ?")
                    values.append(poliza_url)
                if key_or_url:
                    where.append(f"({' OR '.join(key_or_url)})")
                where_clause = " AND ".join(where)
                exists = conn.execute(
                    f"SELECT id FROM gestoria_docs WHERE {where_clause}",
                    values,
                ).fetchone()
                doc_id = None
                if not exists:
                    nombre_doc = payload.get("poliza_numero") or payload.get("tomador") or "Póliza seguro"
                    estado_doc = payload.get("estado") or "En vigor"
                    notas_doc = " · ".join(
                        [value for value in (payload.get("compania"), payload.get("ramo")) if value]
                    )
                    doc_id = os.urandom(16).hex()
                    conn.execute(
                        """
                        INSERT INTO gestoria_docs (
                          id, empresa_id, cliente_id, referencia_tipo, referencia_id,
                          nombre, tipo, fecha, estado, notas, doc_key, doc_url,
                          calidad_ocr, campos_ocr, created_at, updated_at
                        ) VALUES (
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                        )
                        """,
                        (
                            doc_id,
                            empresa["id"],
                            cliente_id,
                            "seguros",
                            poliza_id,
                            nombre_doc,
                            "Seguros",
                            payload.get("fecha_efecto") or payload.get("mes_creacion"),
                            estado_doc,
                            notas_doc,
                            poliza_key or None,
                            poliza_url or None,
                            calidad_ocr,
                            campos_ocr,
                            now,
                            now,
                        ),
                    )
                json_response(
                    self,
                    {
                        "ok": True,
                        "id": poliza_id,
                        "doc_id": doc_id,
                        "ocr_quality": ocr_quality,
                        "duplicate_of": dup_id,
                    },
                )
                return
            # Crear acción si faltan campos obligatorios
            poliza_row = conn.execute("SELECT * FROM seguros WHERE id = ?", (poliza_id,)).fetchone()
            missing = []
            for key in ("tomador", "poliza_numero", "compania", "fecha_efecto"):
                if poliza_row and not str(poliza_row[key] or "").strip():
                    missing.append(key)
            if missing:
                notas = f"Completar datos póliza ({', '.join(missing)}). Poliza ID: {poliza_id}"
                if poliza_row and poliza_row["poliza_numero"]:
                    notas = f"Completar datos póliza {poliza_row['poliza_numero']} ({', '.join(missing)}). Poliza ID: {poliza_id}"
                exists = conn.execute(
                    """
                    SELECT id FROM acciones
                    WHERE servicio = 'Seguros'
                      AND cliente_id = ?
                      AND tipo = 'Completar datos póliza'
                      AND notas LIKE ?
                    LIMIT 1
                    """,
                    (cliente_id, f"%{poliza_id}%"),
                ).fetchone()
                if not exists:
                    today = datetime.now().strftime("%Y-%m-%d")
                    conn.execute(
                        """
                        INSERT INTO acciones (
                          id, empresa_id, servicio, cliente_id, inmueble_id, cliente_nombre,
                          fecha, hora, tipo, responsable, estado, notas, recordatorio_min, created_at, updated_at
                        ) VALUES (
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                        )
                        """,
                        (
                            os.urandom(16).hex(),
                            empresa["id"],
                            "Seguros",
                            cliente_id,
                            None,
                            poliza_row["tomador"] if poliza_row else "",
                            today,
                            None,
                            "Completar datos póliza",
                            None,
                            "Pendiente",
                            notas,
                            None,
                            now,
                            now,
                        ),
                    )
            json_response(self, {"ok": True, "id": poliza_id, "duplicate_of": dup_id})
            return
        elif parsed.path == "/api/fin_asesoramientos":
            cliente1_id = ensure_cliente_for_financiacion(
                conn,
                empresa["id"],
                payload.get("cliente1_nombre"),
                payload.get("cliente1_dni"),
                now,
                {
                    "telefono": payload.get("cliente1_telefono"),
                    "email": payload.get("cliente1_email"),
                    "fecha_nacimiento": payload.get("cliente1_fecha_nacimiento"),
                },
            )
            cliente2_id = ensure_cliente_for_financiacion(
                conn,
                empresa["id"],
                payload.get("cliente2_nombre"),
                payload.get("cliente2_dni"),
                now,
                {
                    "telefono": payload.get("cliente2_telefono"),
                    "email": payload.get("cliente2_email"),
                    "fecha_nacimiento": payload.get("cliente2_fecha_nacimiento"),
                },
            )
            conn.execute(
                """
                INSERT INTO asesoramientos_financiacion (
                  id, empresa_id, origen, inmobiliaria_asesor, asesor, fecha, estado,
                  cliente1_id, cliente1_nombre, cliente1_dni, cliente1_telefono, cliente1_email,
                  cliente1_fecha_nacimiento, cliente1_estado_civil, cliente1_regimen, cliente1_hijos, cliente1_profesion,
                  cliente1_tipo_contrato, cliente1_tiempo_contrato, cliente1_ingresos, cliente1_patrimonio, cliente1_prestamos,
                  cliente1_prestamo_activo, cliente1_prestamo_entidad, cliente1_prestamo_resto,
                  cliente2_id, cliente2_nombre, cliente2_dni, cliente2_telefono, cliente2_email,
                  cliente2_fecha_nacimiento, cliente2_estado_civil, cliente2_regimen, cliente2_hijos, cliente2_profesion,
                  cliente2_tipo_contrato, cliente2_tiempo_contrato, cliente2_ingresos, cliente2_patrimonio, cliente2_prestamos,
                  cliente2_prestamo_activo, cliente2_prestamo_entidad, cliente2_prestamo_resto,
                  ingresos_conjuntos, entidades_financieras, avalistas, aportacion_cv,
                  notas, notas_ocr, calidad_ocr, campos_ocr, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("origen"),
                    payload.get("inmobiliaria_asesor"),
                    payload.get("asesor"),
                    payload.get("fecha"),
                    payload.get("estado") or "En estudio",
                    cliente1_id,
                    payload.get("cliente1_nombre"),
                    payload.get("cliente1_dni"),
                    payload.get("cliente1_telefono"),
                    payload.get("cliente1_email"),
                    payload.get("cliente1_fecha_nacimiento"),
                    payload.get("cliente1_estado_civil"),
                    payload.get("cliente1_regimen"),
                    payload.get("cliente1_hijos"),
                    payload.get("cliente1_profesion"),
                    payload.get("cliente1_tipo_contrato"),
                    payload.get("cliente1_tiempo_contrato"),
                    payload.get("cliente1_ingresos"),
                    payload.get("cliente1_patrimonio"),
                    payload.get("cliente1_prestamos"),
                    payload.get("cliente1_prestamo_activo"),
                    payload.get("cliente1_prestamo_entidad"),
                    payload.get("cliente1_prestamo_resto"),
                    cliente2_id,
                    payload.get("cliente2_nombre"),
                    payload.get("cliente2_dni"),
                    payload.get("cliente2_telefono"),
                    payload.get("cliente2_email"),
                    payload.get("cliente2_fecha_nacimiento"),
                    payload.get("cliente2_estado_civil"),
                    payload.get("cliente2_regimen"),
                    payload.get("cliente2_hijos"),
                    payload.get("cliente2_profesion"),
                    payload.get("cliente2_tipo_contrato"),
                    payload.get("cliente2_tiempo_contrato"),
                    payload.get("cliente2_ingresos"),
                    payload.get("cliente2_patrimonio"),
                    payload.get("cliente2_prestamos"),
                    payload.get("cliente2_prestamo_activo"),
                    payload.get("cliente2_prestamo_entidad"),
                    payload.get("cliente2_prestamo_resto"),
                    payload.get("ingresos_conjuntos"),
                    payload.get("entidades_financieras"),
                    payload.get("avalistas"),
                    payload.get("aportacion_cv"),
                    payload.get("notas"),
                    payload.get("notas_ocr"),
                    payload.get("calidad_ocr"),
                    payload.get("campos_ocr"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/fin_asesoramientos_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            cliente1_id = ensure_cliente_for_financiacion(
                conn,
                empresa["id"],
                payload.get("cliente1_nombre"),
                payload.get("cliente1_dni"),
                now,
                {
                    "telefono": payload.get("cliente1_telefono"),
                    "email": payload.get("cliente1_email"),
                    "fecha_nacimiento": payload.get("cliente1_fecha_nacimiento"),
                },
            )
            cliente2_id = ensure_cliente_for_financiacion(
                conn,
                empresa["id"],
                payload.get("cliente2_nombre"),
                payload.get("cliente2_dni"),
                now,
                {
                    "telefono": payload.get("cliente2_telefono"),
                    "email": payload.get("cliente2_email"),
                    "fecha_nacimiento": payload.get("cliente2_fecha_nacimiento"),
                },
            )
            allowed = (
                "origen",
                "inmobiliaria_asesor",
                "asesor",
                "fecha",
                "estado",
                "cliente1_id",
                "cliente1_nombre",
                "cliente1_dni",
                "cliente1_telefono",
                "cliente1_email",
                "cliente1_fecha_nacimiento",
                "cliente1_estado_civil",
                "cliente1_regimen",
                "cliente1_hijos",
                "cliente1_profesion",
                "cliente1_tipo_contrato",
                "cliente1_tiempo_contrato",
                "cliente1_ingresos",
                "cliente1_patrimonio",
                "cliente1_prestamos",
                "cliente1_prestamo_activo",
                "cliente1_prestamo_entidad",
                "cliente1_prestamo_resto",
                "cliente2_id",
                "cliente2_nombre",
                "cliente2_dni",
                "cliente2_telefono",
                "cliente2_email",
                "cliente2_fecha_nacimiento",
                "cliente2_estado_civil",
                "cliente2_regimen",
                "cliente2_hijos",
                "cliente2_profesion",
                "cliente2_tipo_contrato",
                "cliente2_tiempo_contrato",
                "cliente2_ingresos",
                "cliente2_patrimonio",
                "cliente2_prestamos",
                "cliente2_prestamo_activo",
                "cliente2_prestamo_entidad",
                "cliente2_prestamo_resto",
                "ingresos_conjuntos",
                "entidades_financieras",
                "avalistas",
                "aportacion_cv",
                "notas",
                "notas_ocr",
                "calidad_ocr",
                "campos_ocr",
            )
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if cliente1_id:
                updates["cliente1_id"] = cliente1_id
            if cliente2_id:
                updates["cliente2_id"] = cliente2_id
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE asesoramientos_financiacion SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/fin_asesoramientos_convert":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            row = conn.execute(
                "SELECT * FROM asesoramientos_financiacion WHERE id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                json_response(self, {"error": "Registro no encontrado"}, status=404)
                return
            cliente_nombre = row["cliente1_nombre"] or ""
            if row["cliente2_nombre"]:
                cliente_nombre = f"{cliente_nombre} / {row['cliente2_nombre']}".strip(" /")
            fecha = row["fecha"] or ""
            try:
                anio = int(fecha.split("/")[-1]) if "/" in fecha else int(fecha.split("-")[0])
            except Exception:
                anio = None
            hipoteca_id = os.urandom(16).hex()
            conn.execute(
                """
                INSERT INTO hipotecas (
                  id, empresa_id, cliente, banco, precio, importe_hipoteca, porcentaje,
                  entrada, comision, oficina, fecha_encargo, encargo, tipo_hipoteca,
                  fecha_firma, cesion, comision_juan, comision_modernia, inmobiliaria_compra,
                  asesor, estado, anio, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    hipoteca_id,
                    empresa["id"],
                    cliente_nombre,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    fecha,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    row["inmobiliaria_asesor"],
                    row["asesor"],
                    "Pendiente",
                    anio,
                    now,
                    now,
                ),
            )
            conn.execute(
                "UPDATE asesoramientos_financiacion SET estado = ?, updated_at = datetime(?) WHERE id = ?",
                ("Convertido", now, record_id),
            )
            json_response(self, {"hipoteca_id": hipoteca_id})
        elif parsed.path == "/api/gestoria_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            updates = {}
            for key in ("estado", "fecha_baja"):
                if key in payload:
                    updates[key] = payload.get(key)
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE gestoria SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/seguros_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            updates = {}
            for key in (
                "cliente_id",
                "estado",
                "fecha_efecto",
                "fecha_vencimiento",
                "estado_renovacion",
                "renovacion_fecha",
                "nueva_poliza_ref",
                "poliza_numero",
                "poliza_key",
                "poliza_url",
            ):
                if key in payload:
                    updates[key] = payload.get(key)
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE seguros SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            row = conn.execute("SELECT * FROM seguros WHERE id = ?", (record_id,)).fetchone()
            if row:
                missing = []
                for key in ("tomador", "poliza_numero", "compania", "fecha_efecto"):
                    if not str(row[key] or "").strip():
                        missing.append(key)
                if not missing:
                    conn.execute(
                        """
                        UPDATE acciones
                        SET estado = 'Hecho', updated_at = datetime(?)
                        WHERE servicio = 'Seguros'
                          AND tipo = 'Completar datos póliza'
                          AND notas LIKE ?
                        """,
                        (now, f"%{record_id}%"),
                    )
        elif parsed.path == "/api/seguros_enrich":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            row = conn.execute(
                "SELECT * FROM seguros WHERE id = ?",
                (record_id,),
            ).fetchone()
            if not row:
                json_response(self, {"error": "Registro no encontrado"}, status=404)
                return
            allowed = (
                "cliente_id",
                "tomador",
                "compania",
                "ramo",
                "poliza_numero",
                "prima_neta",
                "prima_total",
                "fecha_efecto",
                "fecha_vencimiento",
            )
            updates = {}
            for key in allowed:
                incoming = payload.get(key)
                if incoming in (None, ""):
                    continue
                current = row[key] if key in row.keys() else None
                if current is None or str(current).strip() == "":
                    updates[key] = incoming
            if updates:
                set_clause = ", ".join([f"{key} = ?" for key in updates])
                values = list(updates.values()) + [now, record_id]
                conn.execute(
                    f"UPDATE seguros SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                    values,
                )
            row = conn.execute("SELECT * FROM seguros WHERE id = ?", (record_id,)).fetchone()
            if row:
                missing = []
                for key in ("tomador", "poliza_numero", "compania", "fecha_efecto"):
                    if not str(row[key] or "").strip():
                        missing.append(key)
                if not missing:
                    conn.execute(
                        """
                        UPDATE acciones
                        SET estado = 'Hecho', updated_at = datetime(?)
                        WHERE servicio = 'Seguros'
                          AND tipo = 'Completar datos póliza'
                          AND notas LIKE ?
                        """,
                        (now, f"%{record_id}%"),
                    )
        elif parsed.path == "/api/seguros_ofertas":
            conn.execute(
                """
                INSERT INTO seguros_ofertas (
                  id, cliente_id, ramo, compania, propuesta, estado, motivo,
                  fecha, responsable, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    payload.get("cliente_id"),
                    payload.get("ramo"),
                    payload.get("compania"),
                    payload.get("propuesta"),
                    payload.get("estado"),
                    payload.get("motivo"),
                    payload.get("fecha"),
                    payload.get("responsable"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/seguros_ofertas_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("ramo", "compania", "propuesta", "estado", "motivo", "fecha", "responsable", "notas", "cliente_id")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE seguros_ofertas SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/seguros_ofertas_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM seguros_ofertas WHERE id = ?", (record_id,))
        elif parsed.path == "/api/seguros_preferencias":
            cliente_id = payload.get("cliente_id")
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            prefs = (
                "prioridad_precio",
                "prioridad_compania",
                "prioridad_coberturas",
                "notas",
            )
            updates = {key: payload.get(key) for key in prefs if key in payload}
            existing = conn.execute(
                "SELECT id FROM seguros_preferencias WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchone()
            if existing:
                if updates:
                    set_clause = ", ".join([f"{key} = ?" for key in updates])
                    values = list(updates.values()) + [now, cliente_id]
                    conn.execute(
                        f"UPDATE seguros_preferencias SET {set_clause}, updated_at = datetime(?) WHERE cliente_id = ?",
                        values,
                    )
            else:
                conn.execute(
                    """
                    INSERT INTO seguros_preferencias (
                      id, cliente_id, prioridad_precio, prioridad_compania, prioridad_coberturas,
                      notas, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        os.urandom(16).hex(),
                        cliente_id,
                        payload.get("prioridad_precio"),
                        payload.get("prioridad_compania"),
                        payload.get("prioridad_coberturas"),
                        payload.get("notas"),
                        now,
                        now,
                    ),
                )
        elif parsed.path == "/api/seguros_referidos":
            conn.execute(
                """
                INSERT INTO seguros_referidos (
                  id, cliente_id, referido_por, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    payload.get("cliente_id"),
                    payload.get("referido_por"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/seguros_campanas":
            conn.execute(
                """
                INSERT INTO seguros_campanas (
                  id, compania, nombre, ramo, origen, fecha_inicio, fecha_fin, descripcion, url,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    payload.get("compania"),
                    payload.get("nombre"),
                    payload.get("ramo"),
                    payload.get("origen"),
                    payload.get("fecha_inicio"),
                    payload.get("fecha_fin"),
                    payload.get("descripcion"),
                    payload.get("url"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/seguros_campanas_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("compania", "nombre", "ramo", "origen", "fecha_inicio", "fecha_fin", "descripcion", "url")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE seguros_campanas SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/seguros_campanas_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM seguros_campanas WHERE id = ?", (record_id,))
        elif parsed.path == "/api/seguros_comisiones":
            conn.execute(
                """
                INSERT INTO seguros_comisiones (
                  id, compania, ramo, porcentaje, vigencia_desde, vigencia_hasta, notas,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    payload.get("compania"),
                    payload.get("ramo"),
                    payload.get("porcentaje"),
                    payload.get("vigencia_desde"),
                    payload.get("vigencia_hasta"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/seguros_comisiones_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("compania", "ramo", "porcentaje", "vigencia_desde", "vigencia_hasta", "notas")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE seguros_comisiones SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/seguros_comisiones_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM seguros_comisiones WHERE id = ?", (record_id,))
        elif parsed.path == "/api/seguros_checklist_generate":
            poliza_id = payload.get("poliza_id")
            if not poliza_id:
                json_response(self, {"error": "poliza_id requerido"}, status=400)
                return
            conn.execute("DELETE FROM seguros_checklist WHERE poliza_id = ?", (poliza_id,))
            tasks = [
                "Póliza firmada",
                "Documento identidad",
                "Recibo emitido",
                "Pago prima",
                "Suplementos/Anexos",
            ]
            for tarea in tasks:
                conn.execute(
                    """
                    INSERT INTO seguros_checklist (
                      id, poliza_id, tarea, estado, responsable, fecha_limite, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        os.urandom(16).hex(),
                        poliza_id,
                        tarea,
                        "Pendiente",
                        payload.get("responsable"),
                        payload.get("fecha_limite"),
                        now,
                        now,
                    ),
                )
            json_response(self, {"ok": True})
            return
        elif parsed.path == "/api/seguros_checklist_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            updates = {}
            for key in ("estado", "responsable", "fecha_limite"):
                if key in payload:
                    updates[key] = payload.get(key)
            if not updates:
                json_response(self, {"error": "sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE seguros_checklist SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            return
        elif parsed.path == "/api/ai_seguros_copilot":
            if not openai_available():
                json_response(self, {"error": "OPENAI_API_KEY no configurada"}, status=400)
                return
            poliza_id = payload.get("poliza_id")
            if not poliza_id:
                json_response(self, {"error": "poliza_id requerido"}, status=400)
                return
            task = (payload.get("task") or "resumen").strip().lower()
            extra = (payload.get("extra") or "").strip()
            poliza = conn.execute("SELECT * FROM seguros WHERE id = ?", (poliza_id,)).fetchone()
            if not poliza:
                json_response(self, {"error": "Póliza no encontrada"}, status=404)
                return
            cliente = None
            if poliza.get("cliente_id"):
                cliente = conn.execute(
                    "SELECT id, nombre, nif, telefono, email FROM clientes WHERE id = ?",
                    (poliza["cliente_id"],),
                ).fetchone()
            context = {
                "poliza": dict(poliza),
                "cliente": dict(cliente) if cliente else {},
            }
            if task == "email_renovacion":
                prompt = (
                    "Redacta un email breve de renovación de póliza. Incluye nombre del cliente, "
                    "número de póliza, compañía y fecha de vencimiento si está disponible. "
                    "Tono profesional y cercano. No inventes datos.\n\n"
                    f"Contexto: {json.dumps(context, ensure_ascii=False)}\n"
                    f"Instrucciones extra: {extra}"
                )
            elif task == "faltantes":
                prompt = (
                    "Lista los campos obligatorios faltantes de la póliza (tomador, poliza_numero, compania, fecha_efecto). "
                    "Si no falta ninguno, indícalo. No inventes datos.\n\n"
                    f"Contexto: {json.dumps(context, ensure_ascii=False)}\n"
                    f"Instrucciones extra: {extra}"
                )
            else:
                prompt = (
                    "Genera un resumen claro de la póliza: tomador, compañía, ramo, fechas, prima y estado. "
                    "Si falta algún dato, indícalo. No inventes datos.\n\n"
                    f"Contexto: {json.dumps(context, ensure_ascii=False)}\n"
                    f"Instrucciones extra: {extra}"
                )
            output, err = call_openai(prompt)
            if err:
                json_response(self, {"error": err}, status=400)
                return
            json_response(self, {"output": output})
            return
        elif parsed.path == "/api/captaciones":
            inmueble_id = os.urandom(16).hex()
            propietarios = payload.get("propietarios") or []
            if isinstance(propietarios, str):
                propietarios = [p for p in propietarios.split(",") if p]
            conn.execute(
                """
                INSERT INTO captaciones (
                  id, empresa_id, inmueble_id, propietario, tipo_inmueble, direccion, codigo_postal, poblacion, provincia, zona, m2,
                  habitaciones, banos, precio_objetivo, precio_valoracion, urgencia,
                  motivo, canal, etapa, probabilidad, proxima_accion, fecha_contacto,
                  asesor, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    inmueble_id,
                    payload.get("propietario"),
                    payload.get("tipo_inmueble"),
                    payload.get("direccion"),
                    payload.get("codigo_postal"),
                    payload.get("poblacion"),
                    payload.get("provincia"),
                    payload.get("zona"),
                    payload.get("m2"),
                    payload.get("habitaciones"),
                    payload.get("banos"),
                    payload.get("precio_objetivo"),
                    payload.get("precio_valoracion"),
                    payload.get("urgencia"),
                    payload.get("motivo"),
                    payload.get("canal"),
                    payload.get("etapa"),
                    payload.get("probabilidad"),
                    payload.get("proxima_accion"),
                    payload.get("fecha_contacto"),
                    payload.get("asesor"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO inmuebles (
                  id, empresa_id, referencia, direccion, codigo_postal, poblacion, provincia, zona, tipo_inmueble,
                  m2, habitaciones, banos, precio_objetivo, precio_valoracion,
                  valor_referencia, estado, lat, lon, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    inmueble_id,
                    empresa["id"],
                    payload.get("referencia"),
                    payload.get("direccion"),
                    payload.get("codigo_postal"),
                    payload.get("poblacion"),
                    payload.get("provincia"),
                    payload.get("zona"),
                    payload.get("tipo_inmueble"),
                    payload.get("m2"),
                    payload.get("habitaciones"),
                    payload.get("banos"),
                    payload.get("precio_objetivo"),
                    payload.get("precio_valoracion"),
                    payload.get("valor_referencia"),
                    payload.get("etapa"),
                    payload.get("lat"),
                    payload.get("lon"),
                    now,
                    now,
                ),
            )
            for cliente_id in propietarios:
                conn.execute(
                    """
                    INSERT INTO inmueble_propietarios (
                      id, inmueble_id, cliente_id, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (os.urandom(16).hex(), inmueble_id, cliente_id, now, now),
                )
        elif parsed.path == "/api/captaciones_update":
            record_id = payload.get("id")
            etapa = payload.get("etapa")
            if not record_id or not etapa:
                json_response(self, {"error": "id y etapa requeridos"}, status=400)
                return
            conn.execute(
                """
                UPDATE captaciones
                SET etapa = ?, updated_at = datetime(?)
                WHERE id = ?
                """,
                (etapa, now, record_id),
            )
        elif parsed.path == "/api/captacion_update":
            inmueble_id = payload.get("inmueble_id")
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            allowed = (
                "propietario",
                "tipo_inmueble",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "zona",
                "m2",
                "habitaciones",
                "banos",
                "precio_objetivo",
                "precio_valoracion",
                "urgencia",
                "motivo",
                "canal",
                "etapa",
                "probabilidad",
                "proxima_accion",
                "fecha_contacto",
                "asesor",
                "notas",
            )
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, inmueble_id]
            conn.execute(
                f"UPDATE captaciones SET {set_clause}, updated_at = datetime(?) WHERE inmueble_id = ?",
                values,
            )
            shared = (
                "tipo_inmueble",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "zona",
                "m2",
                "habitaciones",
                "banos",
                "precio_objetivo",
                "precio_valoracion",
            )
            inm_updates = {key: updates[key] for key in shared if key in updates}
            if "etapa" in updates:
                inm_updates["estado"] = updates["etapa"]
            if inm_updates:
                inm_set = ", ".join([f"{key} = ?" for key in inm_updates])
                inm_values = list(inm_updates.values()) + [now, inmueble_id]
                conn.execute(
                    f"UPDATE inmuebles SET {inm_set}, updated_at = datetime(?) WHERE id = ?",
                    inm_values,
                )
        elif parsed.path == "/api/inmueble_update":
            inmueble_id = payload.get("inmueble_id")
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            allowed = (
                "referencia",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "zona",
                "tipo_inmueble",
                "m2",
                "habitaciones",
                "banos",
                "precio_objetivo",
                "precio_valoracion",
                "valor_referencia",
                "estado",
                "lat",
                "lon",
            )
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, inmueble_id]
            conn.execute(
                f"UPDATE inmuebles SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            shared = (
                "tipo_inmueble",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "zona",
                "m2",
                "habitaciones",
                "banos",
                "precio_objetivo",
                "precio_valoracion",
            )
            cap_updates = {key: updates[key] for key in shared if key in updates}
            if "estado" in updates:
                cap_updates["etapa"] = updates["estado"]
            if cap_updates:
                cap_set = ", ".join([f"{key} = ?" for key in cap_updates])
                cap_values = list(cap_updates.values()) + [now, inmueble_id]
                conn.execute(
                    f"UPDATE captaciones SET {cap_set}, updated_at = datetime(?) WHERE inmueble_id = ?",
                    cap_values,
                )
        elif parsed.path == "/api/inmueble_checklist_generate":
            inmueble_id = payload.get("inmueble_id")
            etapa = payload.get("etapa")
            tareas = payload.get("tareas", [])
            if not inmueble_id or not etapa or not isinstance(tareas, list):
                json_response(self, {"error": "inmueble_id, etapa y tareas requeridos"}, status=400)
                return
            conn.execute(
                "DELETE FROM inmueble_checklist WHERE inmueble_id = ? AND etapa = ?",
                (inmueble_id, etapa),
            )
            for tarea in tareas:
                conn.execute(
                    """
                    INSERT INTO inmueble_checklist (
                      id, inmueble_id, etapa, tarea, estado, responsable, fecha_limite, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        os.urandom(16).hex(),
                        inmueble_id,
                        etapa,
                        tarea.get("tarea"),
                        tarea.get("estado") or "Pendiente",
                        tarea.get("responsable"),
                        tarea.get("fecha_limite"),
                        now,
                        now,
                    ),
                )
            audit("inmueble_checklist", inmueble_id, f"Generar checklist {etapa}", usuario=payload.get("usuario"))
        elif parsed.path == "/api/inmueble_checklist_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("tarea", "estado", "responsable", "fecha_limite")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE inmueble_checklist SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            audit("inmueble_checklist", record_id, "Actualizar tarea", usuario=payload.get("usuario"))
        elif parsed.path == "/api/inmueble_propietarios_update":
            inmueble_id = payload.get("inmueble_id")
            cliente_ids = payload.get("cliente_ids", [])
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            if not isinstance(cliente_ids, list):
                json_response(self, {"error": "cliente_ids invalido"}, status=400)
                return
            conn.execute(
                "DELETE FROM inmueble_propietarios WHERE inmueble_id = ?",
                (inmueble_id,),
            )
            for cliente_id in cliente_ids:
                exists = conn.execute(
                    "SELECT id FROM clientes WHERE id = ?",
                    (cliente_id,),
                ).fetchone()
                if not exists:
                    continue
                conn.execute(
                    """
                    INSERT INTO inmueble_propietarios (
                      id, inmueble_id, cliente_id, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (os.urandom(16).hex(), inmueble_id, cliente_id, now, now),
                )
        elif parsed.path == "/api/inmueble_docs":
            inmueble_id = payload.get("inmueble_id")
            nombre = payload.get("nombre") or ""
            tipo = payload.get("tipo") or ""
            data_uri = payload.get("file_base64") or payload.get("data") or ""
            if not inmueble_id or not data_uri:
                json_response(self, {"error": "inmueble_id y archivo requeridos"}, status=400)
                return
            if "," in data_uri:
                data_uri = data_uri.split(",", 1)[1]
            try:
                file_bytes = base64.b64decode(data_uri)
            except Exception:
                json_response(self, {"error": "Base64 invalido"}, status=400)
                return
            ext = ""
            if nombre and "." in nombre:
                ext = "." + nombre.split(".")[-1].lower()
            if not ext:
                ext = ".pdf"
            folder = UPLOADS / "inmuebles"
            folder.mkdir(parents=True, exist_ok=True)
            doc_id = os.urandom(16).hex()
            filename = f"{doc_id}{ext}"
            file_path = folder / filename
            file_path.write_bytes(file_bytes)
            url = f"/uploads/inmuebles/{filename}"
            conn.execute(
                """
                INSERT INTO inmueble_docs (
                  id, inmueble_id, nombre, url, tipo, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (doc_id, inmueble_id, nombre, url, tipo, now, now),
            )
            audit("inmueble_docs", doc_id, "Subir documento", usuario=payload.get("usuario"))
        elif parsed.path == "/api/demandas":
            conn.execute(
                """
                INSERT INTO demandas (
                  id, empresa_id, cliente_id, tipo, zona, precio_max, m2_min,
                  habitaciones_min, banos_min, estado, prioridad, notas,
                  created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("cliente_id"),
                    payload.get("tipo"),
                    payload.get("zona"),
                    payload.get("precio_max"),
                    payload.get("m2_min"),
                    payload.get("habitaciones_min"),
                    payload.get("banos_min"),
                    payload.get("estado"),
                    payload.get("prioridad"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/visitas":
            conn.execute(
                """
                INSERT INTO visitas (
                  id, empresa_id, inmueble_id, demanda_id, fecha, hora, estado,
                  asesor, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    payload.get("inmueble_id"),
                    payload.get("demanda_id"),
                    payload.get("fecha"),
                    payload.get("hora"),
                    payload.get("estado"),
                    payload.get("asesor"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/clientes":
            nombre = payload.get("nombre")
            if not nombre:
                json_response(self, {"error": "nombre requerido"}, status=400)
                return
            nombre_norm = re.sub(r"\s+", " ", str(nombre)).strip()
            nif = (payload.get("nif") or "").strip()
            dup = None
            if nif:
                nif_norm = re.sub(r"\s+", "", nif).upper()
                dup = conn.execute(
                    "SELECT id FROM clientes WHERE REPLACE(UPPER(nif), ' ', '') = ?",
                    (nif_norm,),
                ).fetchone()
            if not dup:
                dup = conn.execute(
                    "SELECT id FROM clientes WHERE TRIM(UPPER(nombre)) = ?",
                    (nombre_norm.upper(),),
                ).fetchone()
            if dup:
                json_response(self, {"error": "Cliente duplicado", "id": dup["id"]}, status=409)
                return
            cliente_id = payload.get("id") or os.urandom(16).hex()
            conn.execute(
                """
                INSERT INTO clientes (
                  id, nombre, tipo_persona, nif, telefono, email, fecha_nacimiento, direccion,
                  codigo_postal, poblacion, provincia, tipo, perfil, estado, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    cliente_id,
                    nombre,
                    payload.get("tipo_persona"),
                    payload.get("nif"),
                    payload.get("telefono"),
                    payload.get("email"),
                    payload.get("fecha_nacimiento"),
                    payload.get("direccion"),
                    payload.get("codigo_postal"),
                    payload.get("poblacion"),
                    payload.get("provincia"),
                    payload.get("tipo"),
                    payload.get("perfil"),
                    payload.get("estado"),
                    now,
                    now,
                ),
            )
            json_response(self, {"ok": True, "id": cliente_id})
            conn.commit()
            return
        elif parsed.path == "/api/clientes_link":
            cliente_id = payload.get("cliente_id")
            empresa_id = payload.get("empresa_id")
            if not cliente_id or not empresa_id:
                json_response(self, {"error": "cliente_id y empresa_id requeridos"}, status=400)
                return
            cliente_exists = conn.execute(
                "SELECT id FROM clientes WHERE id = ?",
                (cliente_id,),
            ).fetchone()
            empresa_exists = conn.execute(
                "SELECT id FROM empresas WHERE id = ?",
                (empresa_id,),
            ).fetchone()
            if not cliente_exists or not empresa_exists:
                json_response(self, {"error": "Cliente o empresa no encontrados"}, status=400)
                return
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
                    payload.get("servicio"),
                    payload.get("estado"),
                    payload.get("fecha_inicio"),
                    payload.get("fecha_fin"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/cliente_update":
            cliente_id = payload.get("id")
            if not cliente_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = (
                "nombre",
                "tipo_persona",
                "nif",
                "telefono",
                "email",
                "fecha_nacimiento",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "tipo",
                "perfil",
                "estado",
            )
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, cliente_id]
            conn.execute(
                f"UPDATE clientes SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/cliente_empresa_update":
            rel_id = payload.get("id")
            if not rel_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("servicio", "estado", "fecha_inicio", "fecha_fin")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, rel_id]
            conn.execute(
                f"UPDATE clientes_empresas SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/cliente_gestoria_update":
            cliente_id = payload.get("cliente_id")
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            allowed = (
                "tipo_cliente",
                "mod_fiscal",
                "mod_laboral",
                "mod_contable",
                "mod_renta",
                "mod_registro",
                "mod_trafico",
                "mod_puntuales",
                "renta_detalles",
            )
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            existing = conn.execute(
                "SELECT id FROM cliente_gestoria WHERE cliente_id = ?",
                (cliente_id,),
            ).fetchone()
            if existing:
                set_clause = ", ".join([f"{key} = ?" for key in updates])
                values = list(updates.values()) + [now, cliente_id]
                conn.execute(
                    f"UPDATE cliente_gestoria SET {set_clause}, updated_at = datetime(?) WHERE cliente_id = ?",
                    values,
                )
            else:
                new_id = os.urandom(16).hex()
                conn.execute(
                    """
                    INSERT INTO cliente_gestoria (
                      id, cliente_id, tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
                      mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles, created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        new_id,
                        cliente_id,
                        updates.get("tipo_cliente"),
                        updates.get("mod_fiscal"),
                        updates.get("mod_laboral"),
                        updates.get("mod_contable"),
                        updates.get("mod_renta"),
                        updates.get("mod_registro"),
                        updates.get("mod_trafico"),
                        updates.get("mod_puntuales"),
                        updates.get("renta_detalles"),
                        now,
                        now,
                    ),
                )
        elif parsed.path == "/api/acciones":
            servicio = payload.get("servicio")
            if not servicio:
                json_response(self, {"error": "servicio requerido"}, status=400)
                return
            conn.execute(
                """
                INSERT INTO acciones (
                  id, empresa_id, servicio, cliente_id, inmueble_id, cliente_nombre,
                  fecha, hora, tipo, responsable, estado, notas, recordatorio_min, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    os.urandom(16).hex(),
                    empresa["id"],
                    servicio,
                    payload.get("cliente_id"),
                    payload.get("inmueble_id"),
                    payload.get("cliente_nombre"),
                    payload.get("fecha"),
                    payload.get("hora"),
                    payload.get("tipo"),
                    payload.get("responsable"),
                    payload.get("estado"),
                    payload.get("notas"),
                    payload.get("recordatorio_min"),
                    now,
                    now,
                ),
            )
        elif parsed.path == "/api/acciones_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            updates = {}
            for key in (
                "fecha",
                "hora",
                "tipo",
                "responsable",
                "estado",
                "notas",
                "cliente_id",
                "cliente_nombre",
                "inmueble_id",
                "recordatorio_min",
            ):
                if key in payload:
                    updates[key] = payload.get(key)
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE acciones SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
        elif parsed.path == "/api/cliente_profesional":
            cliente_id = payload.get("cliente_id")
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            new_id = os.urandom(16).hex()
            principal = 1 if str(payload.get("principal", "0")) in ("1", "true", "True") else 0
            conn.execute(
                """
                INSERT INTO cliente_profesional (
                  id, cliente_id, cnae, iae, actividad, iban, principal, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    new_id,
                    cliente_id,
                    payload.get("cnae"),
                    payload.get("iae"),
                    payload.get("actividad"),
                    payload.get("iban"),
                    principal,
                    now,
                    now,
                ),
            )
            if principal:
                conn.execute(
                    """
                    UPDATE cliente_profesional
                    SET principal = 0, updated_at = datetime(?)
                    WHERE cliente_id = ? AND id != ?
                    """,
                    (now, cliente_id, new_id),
                )
        elif parsed.path == "/api/cliente_profesional_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("cnae", "iae", "actividad", "iban", "principal")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            if "principal" in updates:
                updates["principal"] = 1 if str(updates["principal"]) in ("1", "true", "True") else 0
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE cliente_profesional SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            if "principal" in updates and updates["principal"]:
                cliente_id = conn.execute(
                    "SELECT cliente_id FROM cliente_profesional WHERE id = ?",
                    (record_id,),
                ).fetchone()
                if cliente_id:
                    conn.execute(
                        """
                        UPDATE cliente_profesional
                        SET principal = 0, updated_at = datetime(?)
                        WHERE cliente_id = ? AND id != ?
                        """,
                        (now, cliente_id["cliente_id"], record_id),
                    )
        elif parsed.path == "/api/cliente_profesional_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM cliente_profesional WHERE id = ?", (record_id,))
        elif parsed.path == "/api/gestoria_modelos":
            cliente_id = payload.get("cliente_id")
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            new_id = os.urandom(16).hex()
            conn.execute(
                """
                INSERT INTO gestoria_modelos (
                  id, cliente_id, modelo, periodicidad, proxima_fecha, responsable, estado, notas, created_at, updated_at
                ) VALUES (
                  ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                )
                """,
                (
                    new_id,
                    cliente_id,
                    payload.get("modelo"),
                    payload.get("periodicidad"),
                    payload.get("proxima_fecha"),
                    payload.get("responsable"),
                    payload.get("estado"),
                    payload.get("notas"),
                    now,
                    now,
                ),
            )
            audit("gestoria_modelo", new_id, "crear", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_modelos_update":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            allowed = ("modelo", "periodicidad", "proxima_fecha", "responsable", "estado", "notas")
            updates = {key: payload.get(key) for key in allowed if key in payload}
            if not updates:
                json_response(self, {"error": "Sin cambios"}, status=400)
                return
            set_clause = ", ".join([f"{key} = ?" for key in updates])
            values = list(updates.values()) + [now, record_id]
            conn.execute(
                f"UPDATE gestoria_modelos SET {set_clause}, updated_at = datetime(?) WHERE id = ?",
                values,
            )
            audit("gestoria_modelo", record_id, "actualizar", json.dumps(payload), payload.get("usuario"))
        elif parsed.path == "/api/gestoria_modelos_delete":
            record_id = payload.get("id")
            if not record_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            conn.execute("DELETE FROM gestoria_modelos WHERE id = ?", (record_id,))
            audit("gestoria_modelo", record_id, "eliminar", None, payload.get("usuario"))
        elif parsed.path == "/api/hipotecas":
            # try to update existing encargo/estudio instead of creating duplicates
            cliente = payload.get("cliente")
            fecha_encargo = payload.get("fecha_encargo")
            precio = payload.get("precio")
            importe_hipoteca = payload.get("importe_hipoteca")
            estado_busqueda = ("estudio", "encargo", "pendiente")
            where = "empresa_id = ? AND LOWER(TRIM(estado)) IN (?, ?, ?) AND LOWER(TRIM(cliente)) = LOWER(TRIM(?))"
            values = [empresa["id"], *estado_busqueda, cliente]
            if fecha_encargo:
                where += " AND fecha_encargo = ?"
                values.append(fecha_encargo)
            if precio:
                where += " AND precio = ?"
                values.append(precio)
            if importe_hipoteca:
                where += " AND importe_hipoteca = ?"
                values.append(importe_hipoteca)
            existing = conn.execute(
                f"SELECT id FROM hipotecas WHERE {where} LIMIT 1",
                values,
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE hipotecas SET
                      banco = COALESCE(?, banco),
                      precio = COALESCE(?, precio),
                      importe_hipoteca = COALESCE(?, importe_hipoteca),
                      porcentaje = COALESCE(?, porcentaje),
                      entrada = COALESCE(?, entrada),
                      comision = COALESCE(?, comision),
                      oficina = COALESCE(?, oficina),
                      fecha_encargo = COALESCE(?, fecha_encargo),
                      encargo = COALESCE(?, encargo),
                      tipo_hipoteca = COALESCE(?, tipo_hipoteca),
                      fecha_firma = COALESCE(?, fecha_firma),
                      cesion = COALESCE(?, cesion),
                      comision_juan = COALESCE(?, comision_juan),
                      comision_modernia = COALESCE(?, comision_modernia),
                      inmobiliaria_compra = COALESCE(?, inmobiliaria_compra),
                      asesor = COALESCE(?, asesor),
                      estado = COALESCE(?, estado),
                      anio = COALESCE(?, anio),
                      updated_at = datetime(?)
                    WHERE id = ?
                    """,
                    (
                        payload.get("banco"),
                        precio,
                        importe_hipoteca,
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
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO hipotecas (
                      id, empresa_id, cliente, banco, precio, importe_hipoteca,
                      porcentaje, entrada, comision, oficina, fecha_encargo,
                      encargo, tipo_hipoteca, fecha_firma, cesion, comision_juan,
                      comision_modernia, inmobiliaria_compra, asesor, estado, anio,
                      created_at, updated_at
                    ) VALUES (
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime(?), datetime(?)
                    )
                    """,
                    (
                        os.urandom(16).hex(),
                        empresa["id"],
                        payload.get("cliente"),
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
                    ),
                )
        else:
            hipoteca_id = payload.get("id")
            fecha_firma = payload.get("fecha_firma")
            estado = payload.get("estado", "FIRMADA")
            if not hipoteca_id or not fecha_firma:
                json_response(self, {"error": "id y fecha_firma requeridos"}, status=400)
                return
            conn.execute(
                """
                UPDATE hipotecas SET
                  estado = ?,
                  fecha_firma = ?,
                  anio = COALESCE(?, anio),
                  updated_at = datetime(?)
                WHERE id = ?
                """,
                (estado, fecha_firma, payload.get("anio"), now, hipoteca_id),
            )
        conn.commit()
        json_response(self, {"ok": True})
    def handle_api(self, parsed):
        path = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        conn = get_db(self.db_path)

        if path == "/api/empresas":
            rows = conn.execute(
                "SELECT id, nombre FROM empresas ORDER BY nombre"
            ).fetchall()
            json_response(self, [dict(r) for r in rows])
            return

        if path == "/api/years":
            years = set()
            tables = [
                "movimientos",
                "hipotecas",
                "alquileres",
                "seguros",
                "captaciones",
                "gestoria_contabilidad",
                "gestoria_trabajos",
                "gestoria_modelos",
                "asesoramientos_financiacion",
                "inmuebles",
                "demandas",
                "visitas",
            ]
            for table in tables:
                try:
                    cols = {
                        row["name"]
                        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
                    }
                except sqlite3.Error:
                    continue
                if "anio" in cols:
                    try:
                        for row in conn.execute(
                            f"SELECT DISTINCT anio AS y FROM {table} WHERE anio IS NOT NULL"
                        ).fetchall():
                            if row["y"] is not None:
                                years.add(str(row["y"]))
                    except sqlite3.Error:
                        pass
                elif "fecha" in cols:
                    try:
                        for row in conn.execute(
                            f"SELECT DISTINCT strftime('%Y', fecha) AS y FROM {table} WHERE fecha IS NOT NULL"
                        ).fetchall():
                            if row["y"]:
                                years.add(str(row["y"]))
                    except sqlite3.Error:
                        pass
            json_response(self, {"years": sorted(years)})
            return

        if path == "/api/s3_url":
            key = params.get("key", [""])[0]
            if not key:
                json_response(self, {"error": "key requerido"}, status=400)
                return
            client = s3_client()
            if not client:
                json_response(self, {"error": "S3 no configurado"}, status=400)
                return
            try:
                url = client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": S3_BUCKET, "Key": key},
                    ExpiresIn=3600,
                )
            except Exception:
                json_response(self, {"error": "No se pudo firmar el archivo"}, status=500)
                return
            json_response(self, {"url": url})
            return

        if path == "/api/tablas":
            json_response(self, TABLES)
            return

        if path == "/api/resumen":
            rows = conn.execute(
                """
                SELECT e.nombre AS empresa,
                  (SELECT COUNT(*) FROM movimientos m WHERE m.empresa_id = e.id) AS bdt,
                  (SELECT COUNT(*) FROM seguros s WHERE s.empresa_id = e.id) AS seguros,
                  (SELECT COUNT(*) FROM gestoria g WHERE g.empresa_id = e.id) AS gestoria,
                  (SELECT COUNT(*) FROM hipotecas h WHERE h.empresa_id = e.id) AS hipotecas,
                  (SELECT COUNT(*) FROM alquileres a WHERE a.empresa_id = e.id) AS alquileres,
                  (SELECT COUNT(*) FROM inversores i WHERE i.empresa_id = e.id) AS inversores,
                  (SELECT COUNT(*) FROM inversure_operaciones io WHERE io.empresa_id = e.id) AS inversure_ops
                FROM empresas e
                ORDER BY e.nombre
                """
            ).fetchall()
            json_response(self, [dict(r) for r in rows])
            return

        if path == "/api/clientes_stats":
            total = conn.execute("SELECT COUNT(*) AS total FROM clientes").fetchone()
            json_response(self, {"total": total["total"] if total else 0})
            return

        if path == "/api/postal_lookup":
            cp_raw = params.get("cp", [""])[0]
            cp = normalize_postal_code(cp_raw)
            if not cp:
                json_response(self, {"error": "cp requerido"}, status=400)
                return
            rows = conn.execute(
                "SELECT poblacion, provincia FROM postal_catalogo WHERE codigo_postal = ?",
                (cp,),
            ).fetchall()
            opciones = []
            poblaciones = []
            provincia = ""
            for row in rows:
                poblacion = (row["poblacion"] or "").strip()
                prov = (row["provincia"] or "").strip()
                if not provincia and prov:
                    provincia = prov
                if poblacion:
                    poblaciones.append(poblacion)
                    opciones.append({"poblacion": poblacion, "provincia": prov or provincia})
            if not provincia:
                provincia = POSTAL_PROVINCES.get(cp[:2], "")
            unique_poblaciones = sorted(set(poblaciones))
            poblacion_value = unique_poblaciones[0] if len(unique_poblaciones) == 1 else ""
            json_response(
                self,
                {
                    "codigo_postal": cp,
                    "poblacion": poblacion_value,
                    "provincia": provincia,
                    "opciones": opciones,
                },
            )
            return

        if path == "/api/clientes_list":
            rows = conn.execute(
                "SELECT id, nombre FROM clientes ORDER BY nombre"
            ).fetchall()
            json_response(self, [dict(r) for r in rows])
            return

        if path == "/api/fin_inmobiliarias":
            rows = conn.execute(
                """
                SELECT DISTINCT TRIM(inmobiliaria_compra) AS nombre
                FROM hipotecas
                WHERE inmobiliaria_compra IS NOT NULL AND TRIM(inmobiliaria_compra) <> ''
                ORDER BY nombre
                """
            ).fetchall()
            json_response(self, {"items": [row["nombre"] for row in rows if row["nombre"]]})
            return

        if path == "/api/cliente":
            cliente_id = params.get("id", [""])[0]
            if not cliente_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            cliente = conn.execute(
                "SELECT * FROM clientes WHERE id = ?",
                (cliente_id,),
            ).fetchone()
            if not cliente:
                json_response(self, {"error": "Cliente no encontrado"}, status=404)
                return
            empresas = conn.execute(
                """
                SELECT ce.id AS rel_id, e.nombre AS empresa, ce.servicio, ce.estado,
                       ce.fecha_inicio, ce.fecha_fin
                FROM clientes_empresas ce
                LEFT JOIN empresas e ON e.id = ce.empresa_id
                WHERE ce.cliente_id = ?
                ORDER BY e.nombre
                """,
                (cliente_id,),
            ).fetchall()
            json_response(
                self,
                {
                    "cliente": dict(cliente),
                    "empresas": [dict(r) for r in empresas],
                },
            )
            return

        if path == "/api/cliente_gestoria":
            cliente_id = params.get("cliente_id", [""])[0]
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            row = conn.execute(
                """
                SELECT tipo_cliente, mod_fiscal, mod_laboral, mod_contable,
                       mod_renta, mod_registro, mod_trafico, mod_puntuales, renta_detalles
                FROM cliente_gestoria
                WHERE cliente_id = ?
                """,
                (cliente_id,),
            ).fetchone()
            json_response(self, {"row": dict(row) if row else {}})
            return

        if path == "/api/acciones":
            empresa_id = params.get("empresa_id", [""])[0]
            servicio = params.get("servicio", [""])[0]
            cliente_id = params.get("cliente_id", [""])[0]
            inmueble_id = params.get("inmueble_id", [""])[0]
            if not servicio:
                json_response(self, {"error": "servicio requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT
                  a.id, a.cliente_id, a.fecha, a.hora,
                  COALESCE(c.nombre, a.cliente_nombre) AS cliente,
                  a.tipo, a.responsable, a.estado, a.notas, a.servicio, a.recordatorio_min, a.inmueble_id
                FROM acciones a
                LEFT JOIN clientes c ON c.id = a.cliente_id
                WHERE a.servicio = ?
                  AND (? = '' OR a.empresa_id = ?)
                  AND (? = '' OR a.cliente_id = ?)
                  AND (? = '' OR a.inmueble_id = ?)
                ORDER BY a.fecha DESC, a.hora DESC
                LIMIT 300
                """,
                (servicio, empresa_id, empresa_id, cliente_id, cliente_id, inmueble_id, inmueble_id),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/fin_asesoramientos":
            empresa_id = params.get("empresa_id", [""])[0]
            q = params.get("q", [""])[0].strip().lower()
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT *
                FROM asesoramientos_financiacion
                WHERE empresa_id = ?
                ORDER BY created_at DESC
                """,
                (empresa_id,),
            ).fetchall()
            data = [dict(r) for r in rows]
            if q:
                filtered = []
                for row in data:
                    hay = " ".join([str(row.get(key, "") or "") for key in (
                        "cliente1_nombre",
                        "cliente2_nombre",
                        "cliente1_dni",
                        "cliente2_dni",
                        "inmobiliaria_asesor",
                        "asesor",
                        "estado",
                        "entidades_financieras",
                    )]).lower()
                    if q in hay:
                        filtered.append(row)
                data = filtered
            json_response(self, {"rows": data})
            return

        if path == "/api/seguros_ofertas":
            cliente_id = params.get("cliente_id", [""])[0]
            where = []
            values = []
            if cliente_id:
                where.append("o.cliente_id = ?")
                values.append(cliente_id)
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            rows = conn.execute(
                f"""
                SELECT o.id, o.cliente_id, o.ramo, o.compania, o.propuesta, o.estado,
                       o.motivo, o.fecha, o.responsable, o.notas,
                       COALESCE(c.nombre, '') AS cliente
                FROM seguros_ofertas o
                LEFT JOIN clientes c ON c.id = o.cliente_id
                {where_clause}
                ORDER BY o.fecha DESC, o.created_at DESC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/seguros_preferencias":
            cliente_id = params.get("cliente_id", [""])[0]
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            row = conn.execute(
                """
                SELECT cliente_id, prioridad_precio, prioridad_compania, prioridad_coberturas, notas
                FROM seguros_preferencias
                WHERE cliente_id = ?
                """,
                (cliente_id,),
            ).fetchone()
            json_response(self, {"row": dict(row) if row else {}})
            return

        if path == "/api/seguros_referidos":
            rows = conn.execute(
                """
                SELECT r.id, r.cliente_id, r.referido_por, r.notas,
                       COALESCE(c.nombre, '') AS cliente
                FROM seguros_referidos r
                LEFT JOIN clientes c ON c.id = r.cliente_id
                ORDER BY r.created_at DESC
                """
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/seguros_campanas":
            rows = conn.execute(
                """
                SELECT id, compania, nombre, ramo, origen, fecha_inicio, fecha_fin, descripcion, url
                FROM seguros_campanas
                ORDER BY fecha_inicio DESC, created_at DESC
                """
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/seguros_comisiones":
            rows = conn.execute(
                """
                SELECT id, compania, ramo, porcentaje, vigencia_desde, vigencia_hasta, notas
                FROM seguros_comisiones
                ORDER BY compania, ramo
                """
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/seguros_insights":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            por_ramo = conn.execute(
                """
                SELECT ramo, COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                GROUP BY ramo
                ORDER BY total DESC
                """,
                (empresa_id,),
            ).fetchall()
            por_compania = conn.execute(
                """
                SELECT compania, COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                GROUP BY compania
                ORDER BY total DESC
                """,
                (empresa_id,),
            ).fetchall()
            ofertas_estado = conn.execute(
                """
                SELECT estado, COUNT(*) AS total
                FROM seguros_ofertas
                GROUP BY estado
                ORDER BY total DESC
                """
            ).fetchall()
            preferencias = conn.execute(
                """
                SELECT
                  SUM(CASE WHEN prioridad_precio = 1 THEN 1 ELSE 0 END) AS prioriza_precio,
                  SUM(CASE WHEN prioridad_compania = 1 THEN 1 ELSE 0 END) AS prioriza_compania,
                  SUM(CASE WHEN prioridad_coberturas = 1 THEN 1 ELSE 0 END) AS prioriza_coberturas,
                  COUNT(*) AS total
                FROM seguros_preferencias
                """
            ).fetchone()
            json_response(
                self,
                {
                    "por_ramo": [dict(r) for r in por_ramo],
                    "por_compania": [dict(r) for r in por_compania],
                    "ofertas_estado": [dict(r) for r in ofertas_estado],
                    "preferencias": dict(preferencias) if preferencias else {},
                },
            )
            return

        if path == "/api/cliente_profesional":
            cliente_id = params.get("cliente_id", [""])[0]
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT id, cnae, iae, actividad, iban, principal
                FROM cliente_profesional
                WHERE cliente_id = ?
                ORDER BY created_at DESC
                """,
                (cliente_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/gestoria_modelos":
            cliente_id = params.get("cliente_id", [""])[0]
            empresa_id = params.get("empresa_id", [""])[0]
            scope = params.get("scope", [""])[0]
            if not cliente_id and not empresa_id:
                json_response(self, {"error": "cliente_id o empresa_id requerido"}, status=400)
                return
            if cliente_id:
                rows = conn.execute(
                    """
                    SELECT id, modelo, periodicidad, proxima_fecha, responsable, estado, notas
                    FROM gestoria_modelos
                    WHERE cliente_id = ?
                    ORDER BY proxima_fecha DESC
                    """,
                    (cliente_id,),
                ).fetchall()
                json_response(self, {"rows": [dict(r) for r in rows]})
                return
            today = datetime.now().date()
            next_30 = today + timedelta(days=30)
            where = ["ce.empresa_id = ?"]
            values = [empresa_id]
            if scope == "proximos":
                where.append("m.proxima_fecha IS NOT NULL")
                where.append("date(m.proxima_fecha) BETWEEN date(?) AND date(?)")
                values.extend([today.isoformat(), next_30.isoformat()])
            elif scope == "vencidos":
                where.append("m.proxima_fecha IS NOT NULL")
                where.append("date(m.proxima_fecha) < date(?)")
                where.append("(m.estado IS NULL OR LOWER(m.estado) != 'presentado')")
                values.append(today.isoformat())
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT m.id, m.modelo, m.periodicidad, m.proxima_fecha, m.responsable, m.estado, m.notas,
                       COALESCE(c.nombre, '') AS cliente
                FROM gestoria_modelos m
                JOIN clientes c ON c.id = m.cliente_id
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE {where_clause}
                ORDER BY m.proxima_fecha ASC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/gestoria_trabajos":
            cliente_id = params.get("cliente_id", [""])[0]
            empresa_id = params.get("empresa_id", [""])[0]
            if not cliente_id and not empresa_id:
                json_response(self, {"error": "cliente_id o empresa_id requerido"}, status=400)
                return
            where = []
            values = []
            if cliente_id:
                where.append("gt.cliente_id = ?")
                values.append(cliente_id)
            if empresa_id:
                where.append("gt.empresa_id = ?")
                values.append(empresa_id)
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT gt.id, gt.tipo_trabajo, gt.estado, gt.fecha_inicio, gt.fecha_fin,
                       gt.sla_dias, gt.responsable, gt.importe, gt.notas, gt.cliente_id,
                       COALESCE(c.nombre, '') AS cliente
                FROM gestoria_trabajos gt
                LEFT JOIN clientes c ON c.id = gt.cliente_id
                WHERE {where_clause}
                ORDER BY gt.created_at DESC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/gestoria_docs":
            cliente_id = params.get("cliente_id", [""])[0]
            empresa_id = params.get("empresa_id", [""])[0]
            limit = params.get("limit", [""])[0]
            if not cliente_id and not empresa_id:
                json_response(self, {"error": "cliente_id o empresa_id requerido"}, status=400)
                return
            if cliente_id:
                rows = conn.execute(
                    """
                    SELECT id, nombre, tipo, fecha, estado, notas
                    FROM gestoria_docs
                    WHERE cliente_id = ?
                    ORDER BY created_at DESC
                    """,
                    (cliente_id,),
                ).fetchall()
                json_response(self, {"rows": [dict(r) for r in rows]})
                return
            limit_clause = "LIMIT 50"
            if limit.isdigit():
                limit_clause = f"LIMIT {int(limit)}"
            rows = conn.execute(
                f"""
                SELECT d.id, d.nombre, d.tipo, d.fecha, d.estado, d.notas,
                       COALESCE(c.nombre, '') AS cliente
                FROM gestoria_docs d
                LEFT JOIN clientes c ON c.id = d.cliente_id
                WHERE d.empresa_id = ?
                ORDER BY d.fecha DESC
                {limit_clause}
                """,
                (empresa_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/gestoria_contabilidad":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            q = params.get("q", [""])[0].strip()
            where = ["gc.empresa_id = ?"]
            values = [empresa_id]
            if q:
                where.append("(gc.concepto LIKE ? OR c.nombre LIKE ?)")
                values.extend([f"%{q}%", f"%{q}%"])
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT gc.id, gc.fecha, gc.concepto, gc.gestion, gc.tipo, gc.importe, gc.notas,
                       gc.cliente_id, COALESCE(c.nombre, '') AS cliente
                FROM gestoria_contabilidad gc
                LEFT JOIN clientes c ON c.id = gc.cliente_id
                WHERE {where_clause}
                ORDER BY gc.fecha DESC
                LIMIT 300
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/gestoria_conta_config":
            cliente_id = params.get("cliente_id", [""])[0]
            if not cliente_id:
                json_response(self, {"error": "cliente_id requerido"}, status=400)
                return
            row = conn.execute(
                """
                SELECT id, cliente_id, periodo, fecha_inicio, responsable
                FROM gestoria_conta_config
                WHERE cliente_id = ?
                """,
                (cliente_id,),
            ).fetchone()
            json_response(self, {"row": dict(row) if row else {}})
            return

        if path == "/api/gestoria_conta_tasks":
            cliente_id = params.get("cliente_id", [""])[0]
            empresa_id = params.get("empresa_id", [""])[0]
            estado = params.get("estado", [""])[0]
            periodo = params.get("periodo", [""])[0]
            if not cliente_id and not empresa_id:
                json_response(self, {"error": "cliente_id o empresa_id requerido"}, status=400)
                return
            where = []
            values = []
            if cliente_id:
                where.append("t.cliente_id = ?")
                values.append(cliente_id)
            if periodo:
                where.append("t.periodo = ?")
                values.append(periodo)
            if estado:
                where.append("LOWER(t.estado) = ?")
                values.append(estado.lower())
            if empresa_id:
                where.append("c.empresa_id = ?")
                values.append(empresa_id)
            where_clause = " AND ".join(where) if where else "1=1"
            rows = conn.execute(
                f"""
                SELECT t.id, t.cliente_id, t.periodo, t.tarea, t.estado,
                       t.fecha_limite, t.responsable,
                       COALESCE(c.nombre, '') AS cliente
                FROM gestoria_conta_tasks t
                LEFT JOIN clientes c ON c.id = t.cliente_id
                WHERE {where_clause}
                ORDER BY t.fecha_limite ASC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/usuarios":
            rows = conn.execute(
                "SELECT id, nombre, apellido, usuario, email, servicio, rol, activo FROM usuarios ORDER BY nombre, apellido"
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/auditoria":
            empresa_id = params.get("empresa_id", [""])[0]
            limit = params.get("limit", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            limit_clause = "LIMIT 50"
            if limit.isdigit():
                limit_clause = f"LIMIT {int(limit)}"
            rows = conn.execute(
                f"""
                SELECT a.id, a.entidad, a.entidad_id, a.accion, a.usuario, a.detalles, a.created_at,
                       COALESCE(c.nombre, '') AS cliente
                FROM auditoria a
                LEFT JOIN clientes c ON c.id = a.entidad_id
                WHERE a.empresa_id = ?
                ORDER BY a.created_at DESC
                {limit_clause}
                """,
                (empresa_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/catalogo":
            tipo = params.get("tipo", [""])[0].lower()
            q = params.get("q", [""])[0].strip()
            if tipo not in ("cnae", "iae"):
                json_response(self, {"error": "tipo requerido"}, status=400)
                return
            table = "cnae_catalogo" if tipo == "cnae" else "iae_catalogo"
            if q:
                rows = conn.execute(
                    f"""
                    SELECT codigo, descripcion
                    FROM {table}
                    WHERE codigo LIKE ? OR descripcion LIKE ?
                    ORDER BY codigo
                    LIMIT 30
                    """,
                    (f"%{q}%", f"%{q}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT codigo, descripcion
                    FROM {table}
                    ORDER BY codigo
                    LIMIT 30
                    """
                ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/catalogo_match":
            texto = params.get("texto", [""])[0].strip()
            if not texto:
                json_response(self, {"error": "texto requerido"}, status=400)
                return
            def match(table):
                return conn.execute(
                    f"""
                    SELECT codigo, descripcion
                    FROM {table}
                    WHERE LOWER(descripcion) LIKE LOWER(?)
                    ORDER BY CASE
                      WHEN LOWER(descripcion) = LOWER(?) THEN 0
                      ELSE 1
                    END, codigo
                    LIMIT 5
                    """,
                    (f"%{texto}%", texto),
                ).fetchall()
            cnae = match("cnae_catalogo")
            iae = match("iae_catalogo")
            json_response(
                self,
                {
                    "cnae": [dict(r) for r in cnae],
                    "iae": [dict(r) for r in iae],
                },
            )
            return

        if path == "/api/gestoria_dashboard":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            today = datetime.now().date()
            next_30 = today + timedelta(days=30)
            next_14 = today + timedelta(days=14)
            service_filter = (
                "LOWER(ce.servicio) IN ('gestoria', 'gestoría', "
                "'administracion fincas', 'administración fincas')"
            )
            total = conn.execute(
                f"""
                SELECT COUNT(DISTINCT c.id) AS total
                FROM clientes c
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE ce.empresa_id = ? AND {service_filter}
                """,
                (empresa_id,),
            ).fetchone()
            activos = conn.execute(
                f"""
                SELECT COUNT(DISTINCT c.id) AS total
                FROM clientes c
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE ce.empresa_id = ?
                  AND {service_filter}
                  AND LOWER(COALESCE(ce.estado, '')) = 'alta'
                """,
                (empresa_id,),
            ).fetchone()
            tipos = conn.execute(
                f"""
                SELECT cg.tipo_cliente AS tipo, COUNT(*) AS total
                FROM cliente_gestoria cg
                JOIN clientes_empresas ce ON ce.cliente_id = cg.cliente_id
                WHERE ce.empresa_id = ? AND {service_filter}
                GROUP BY cg.tipo_cliente
                """,
                (empresa_id,),
            ).fetchall()
            tipos_map = {row["tipo"]: row["total"] for row in tipos if row["tipo"]}
            def tipo_count(*labels):
                return sum(tipos_map.get(label, 0) for label in labels)
            modelos_mes = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM gestoria_modelos m
                JOIN clientes_empresas ce ON ce.cliente_id = m.cliente_id
                WHERE ce.empresa_id = ? AND {service_filter}
                  AND m.proxima_fecha IS NOT NULL
                  AND strftime('%Y-%m', m.proxima_fecha) = ?
                """,
                (empresa_id, today.strftime("%Y-%m")),
            ).fetchone()
            modelos = conn.execute(
                f"""
                SELECT c.nombre AS cliente, m.modelo, m.proxima_fecha, m.estado
                FROM gestoria_modelos m
                JOIN clientes c ON c.id = m.cliente_id
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE ce.empresa_id = ? AND {service_filter}
                  AND m.proxima_fecha IS NOT NULL
                  AND date(m.proxima_fecha) BETWEEN date(?) AND date(?)
                ORDER BY m.proxima_fecha ASC
                LIMIT 12
                """,
                (empresa_id, today.isoformat(), next_30.isoformat()),
            ).fetchall()
            modelos_vencidos = conn.execute(
                f"""
                SELECT c.nombre AS cliente, m.modelo, m.proxima_fecha, m.estado
                FROM gestoria_modelos m
                JOIN clientes c ON c.id = m.cliente_id
                JOIN clientes_empresas ce ON ce.cliente_id = c.id
                WHERE ce.empresa_id = ? AND {service_filter}
                  AND m.proxima_fecha IS NOT NULL
                  AND date(m.proxima_fecha) < date(?)
                  AND (m.estado IS NULL OR LOWER(m.estado) != 'presentado')
                ORDER BY m.proxima_fecha ASC
                LIMIT 12
                """,
                (empresa_id, today.isoformat()),
            ).fetchall()
            acciones_pendientes = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM acciones a
                WHERE a.empresa_id = ?
                  AND LOWER(a.servicio) = 'gestoria'
                  AND (a.estado IS NULL OR LOWER(a.estado) != 'hecho')
                  AND a.fecha IS NOT NULL
                  AND date(a.fecha) >= date(?)
                """,
                (empresa_id, today.isoformat()),
            ).fetchone()
            acciones = conn.execute(
                """
                SELECT a.fecha, a.hora,
                       COALESCE(c.nombre, a.cliente_nombre) AS cliente,
                       a.tipo, a.estado
                FROM acciones a
                LEFT JOIN clientes c ON c.id = a.cliente_id
                WHERE a.empresa_id = ?
                  AND LOWER(a.servicio) = 'gestoria'
                  AND (a.estado IS NULL OR LOWER(a.estado) != 'hecho')
                  AND a.fecha IS NOT NULL
                  AND date(a.fecha) BETWEEN date(?) AND date(?)
                ORDER BY a.fecha ASC, a.hora ASC
                LIMIT 10
                """,
                (empresa_id, today.isoformat(), next_14.isoformat()),
            ).fetchall()
            acciones_vencidas = conn.execute(
                """
                SELECT a.fecha, a.hora,
                       COALESCE(c.nombre, a.cliente_nombre) AS cliente,
                       a.tipo, a.estado
                FROM acciones a
                LEFT JOIN clientes c ON c.id = a.cliente_id
                WHERE a.empresa_id = ?
                  AND LOWER(a.servicio) = 'gestoria'
                  AND a.fecha IS NOT NULL
                  AND date(a.fecha) < date(?)
                  AND (a.estado IS NULL OR LOWER(a.estado) != 'hecho')
                ORDER BY a.fecha ASC, a.hora ASC
                LIMIT 10
                """,
                (empresa_id, today.isoformat()),
            ).fetchall()
            json_response(
                self,
                {
                    "counts": {
                        "total": total["total"] if total else 0,
                        "activos": activos["total"] if activos else 0,
                        "autonomos": tipo_count("Autónomo", "Autonomo"),
                        "empresas": tipo_count("Empresa", "Empresas"),
                        "puntuales": tipo_count("Puntual", "Puntuales"),
                        "modelos_mes": modelos_mes["total"] if modelos_mes else 0,
                        "acciones_pendientes": acciones_pendientes["total"] if acciones_pendientes else 0,
                    },
                    "modelos": [dict(r) for r in modelos],
                    "modelos_vencidos": [dict(r) for r in modelos_vencidos],
                    "acciones": [dict(r) for r in acciones],
                    "acciones_vencidas": [dict(r) for r in acciones_vencidas],
                },
            )
            return

        if path == "/api/clientes":
            empresa_id = params.get("empresa_id", [""])[0]
            q = params.get("q", [""])[0].strip()
            estado = params.get("estado", [""])[0].strip()
            include_id = params.get("include_id", [""])[0] == "1"
            limit_param = params.get("limit", [""])[0].strip()
            where = []
            values = []
            if empresa_id:
                where.append("ce.empresa_id = ?")
                values.append(empresa_id)
            if q:
                where.append(
                    "(c.nombre LIKE ? OR c.nif LIKE ? OR c.telefono LIKE ? OR c.email LIKE ?)"
                )
                values.extend([f"%{q}%"] * 4)
            if estado:
                where.append("c.estado = ?")
                values.append(estado)
            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            select_id = "c.id, " if include_id else ""
            limit_clause = "LIMIT 500"
            if limit_param.isdigit():
                limit_clause = f"LIMIT {int(limit_param)}"
            rows = conn.execute(
                f"""
                SELECT
                  {select_id}
                  c.nombre,
                  c.tipo_persona,
                  c.nif,
                  c.telefono,
                  c.email,
                  c.fecha_nacimiento,
                  c.direccion,
                  c.codigo_postal,
                  c.poblacion,
                  c.provincia,
                  GROUP_CONCAT(e.nombre, ' | ') AS empresas,
                  GROUP_CONCAT(ce.servicio, ' | ') AS servicios
                FROM clientes c
                LEFT JOIN clientes_empresas ce ON ce.cliente_id = c.id
                LEFT JOIN empresas e ON e.id = ce.empresa_id
                {where_clause}
                GROUP BY c.id
                ORDER BY c.nombre
                {limit_clause}
                """,
                values,
            ).fetchall()
            columns = [
                "nombre",
                "tipo_persona",
                "nif",
                "telefono",
                "email",
                "fecha_nacimiento",
                "direccion",
                "codigo_postal",
                "poblacion",
                "provincia",
                "empresas",
                "servicios",
            ]
            if include_id:
                columns = ["id"] + columns
            json_response(self, {"columns": columns, "rows": [list(r) for r in rows]})
            return

        if path == "/api/inmuebles":
            empresa_id = params.get("empresa_id", [""])[0]
            q = params.get("q", [""])[0].strip()
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            where = ["i.empresa_id = ?"]
            values = [empresa_id]
            if q:
                where.append(
                    "(i.referencia LIKE ? OR i.direccion LIKE ? OR i.zona LIKE ? OR i.estado LIKE ? OR c.nombre LIKE ?)"
                )
                values.extend([f"%{q}%"] * 5)
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT
                  i.id,
                  i.referencia,
                  i.direccion,
                  i.zona,
                  i.estado,
                  GROUP_CONCAT(c.nombre, ' | ') AS propietarios
                FROM inmuebles i
                LEFT JOIN inmueble_propietarios ip ON ip.inmueble_id = i.id
                LEFT JOIN clientes c ON c.id = ip.cliente_id
                WHERE {where_clause}
                GROUP BY i.id
                ORDER BY i.created_at DESC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/inmueble":
            inmueble_id = params.get("id", [""])[0]
            if not inmueble_id:
                json_response(self, {"error": "id requerido"}, status=400)
                return
            inmueble = conn.execute(
                "SELECT * FROM inmuebles WHERE id = ?",
                (inmueble_id,),
            ).fetchone()
            if not inmueble:
                json_response(self, {"error": "Inmueble no encontrado"}, status=404)
                return
            propietarios = conn.execute(
                """
                SELECT c.id, c.nombre, c.nif, c.telefono, c.email
                FROM inmueble_propietarios ip
                JOIN clientes c ON c.id = ip.cliente_id
                WHERE ip.inmueble_id = ?
                """,
                (inmueble_id,),
            ).fetchall()
            docs = conn.execute(
                """
                SELECT nombre, url, tipo
                FROM inmueble_docs
                WHERE inmueble_id = ?
                ORDER BY created_at DESC
                """,
                (inmueble_id,),
            ).fetchall()
            captacion = conn.execute(
                """
                SELECT *
                FROM captaciones
                WHERE inmueble_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (inmueble_id,),
            ).fetchone()
            json_response(
                self,
                {
                    "inmueble": dict(inmueble),
                    "propietarios": [dict(r) for r in propietarios],
                    "docs": [dict(r) for r in docs],
                    "captacion": dict(captacion) if captacion else {},
                },
            )
            return

        if path == "/api/inmueble_docs":
            inmueble_id = params.get("inmueble_id", [""])[0]
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT id, nombre, url, tipo, created_at
                FROM inmueble_docs
                WHERE inmueble_id = ?
                ORDER BY created_at DESC
                """,
                (inmueble_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/demandas":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT d.id, d.tipo, d.zona, d.precio_max, d.m2_min,
                       d.habitaciones_min, d.banos_min, d.estado, d.prioridad,
                       c.nombre AS cliente
                FROM demandas d
                LEFT JOIN clientes c ON c.id = d.cliente_id
                WHERE d.empresa_id = ?
                ORDER BY d.created_at DESC
                """,
                (empresa_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/visitas":
            empresa_id = params.get("empresa_id", [""])[0]
            inmueble_id = params.get("inmueble_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            where = ["v.empresa_id = ?"]
            values = [empresa_id]
            if inmueble_id:
                where.append("v.inmueble_id = ?")
                values.append(inmueble_id)
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT v.id, v.fecha, v.hora, v.estado, v.asesor, v.notas,
                       i.direccion AS inmueble,
                       c.nombre AS cliente
                FROM visitas v
                LEFT JOIN inmuebles i ON i.id = v.inmueble_id
                LEFT JOIN demandas d ON d.id = v.demanda_id
                LEFT JOIN clientes c ON c.id = d.cliente_id
                WHERE {where_clause}
                ORDER BY v.fecha DESC, v.hora DESC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/matching":
            empresa_id = params.get("empresa_id", [""])[0]
            demanda_id = params.get("demanda_id", [""])[0]
            if not empresa_id or not demanda_id:
                json_response(self, {"error": "empresa_id y demanda_id requeridos"}, status=400)
                return
            demanda = conn.execute(
                "SELECT * FROM demandas WHERE id = ? AND empresa_id = ?",
                (demanda_id, empresa_id),
            ).fetchone()
            if not demanda:
                json_response(self, {"error": "Demanda no encontrada"}, status=404)
                return
            where = ["empresa_id = ?"]
            values = [empresa_id]
            if demanda["zona"]:
                where.append("LOWER(zona) LIKE ?")
                values.append(f"%{demanda['zona'].lower()}%")
            if demanda["precio_max"]:
                where.append("precio_objetivo <= ?")
                values.append(demanda["precio_max"])
            if demanda["m2_min"]:
                where.append("m2 >= ?")
                values.append(demanda["m2_min"])
            if demanda["habitaciones_min"]:
                where.append("habitaciones >= ?")
                values.append(demanda["habitaciones_min"])
            if demanda["banos_min"]:
                where.append("banos >= ?")
                values.append(demanda["banos_min"])
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT id, referencia, direccion, zona, precio_objetivo, m2, habitaciones, banos, estado
                FROM inmuebles
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT 50
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/inmueble_matching":
            inmueble_id = params.get("inmueble_id", [""])[0]
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            inmueble = conn.execute(
                "SELECT * FROM inmuebles WHERE id = ?",
                (inmueble_id,),
            ).fetchone()
            if not inmueble:
                json_response(self, {"error": "Inmueble no encontrado"}, status=404)
                return
            where = ["d.empresa_id = ?"]
            values = [inmueble["empresa_id"]]
            if inmueble["zona"]:
                where.append("LOWER(d.zona) LIKE ?")
                values.append(f"%{inmueble['zona'].lower()}%")
            if inmueble["precio_objetivo"]:
                where.append("(d.precio_max IS NULL OR d.precio_max >= ?)")
                values.append(inmueble["precio_objetivo"])
            if inmueble["m2"]:
                where.append("(d.m2_min IS NULL OR d.m2_min <= ?)")
                values.append(inmueble["m2"])
            if inmueble["habitaciones"]:
                where.append("(d.habitaciones_min IS NULL OR d.habitaciones_min <= ?)")
                values.append(inmueble["habitaciones"])
            if inmueble["banos"]:
                where.append("(d.banos_min IS NULL OR d.banos_min <= ?)")
                values.append(inmueble["banos"])
            where_clause = " AND ".join(where)
            rows = conn.execute(
                f"""
                SELECT d.id, d.tipo, d.zona, d.precio_max, d.m2_min,
                       d.habitaciones_min, d.banos_min, d.estado,
                       c.nombre AS cliente
                FROM demandas d
                LEFT JOIN clientes c ON c.id = d.cliente_id
                WHERE {where_clause}
                ORDER BY d.created_at DESC
                LIMIT 100
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/inmueble_checklist":
            inmueble_id = params.get("inmueble_id", [""])[0]
            etapa = params.get("etapa", [""])[0]
            if not inmueble_id:
                json_response(self, {"error": "inmueble_id requerido"}, status=400)
                return
            where = ["inmueble_id = ?"]
            values = [inmueble_id]
            if etapa:
                where.append("etapa = ?")
                values.append(etapa)
            rows = conn.execute(
                f"""
                SELECT id, etapa, tarea, estado, responsable, fecha_limite
                FROM inmueble_checklist
                WHERE {' AND '.join(where)}
                ORDER BY created_at ASC
                """,
                values,
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/hipoteca_stats":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return

            total = conn.execute(
                "SELECT COUNT(*) AS total FROM hipotecas WHERE empresa_id = ?",
                (empresa_id,),
            ).fetchone()

            firmadas_mes = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                  AND fecha_firma IS NOT NULL
                  AND strftime('%Y-%m', fecha_firma) = strftime('%Y-%m', 'now', 'localtime')
                """,
                (empresa_id,),
            ).fetchone()

            averages = conn.execute(
                """
                SELECT
                  AVG(
                    CASE
                      WHEN precio IS NOT NULL AND precio > 0 AND importe_hipoteca IS NOT NULL
                        THEN (importe_hipoteca * 100.0 / precio)
                      WHEN porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 1 THEN porcentaje * 100.0
                      WHEN porcentaje IS NOT NULL AND porcentaje > 1 THEN porcentaje
                      ELSE NULL
                    END
                  ) AS porcentaje_medio,
                  AVG(COALESCE(comision, 0)) AS comision_media
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                """,
                (empresa_id,),
            ).fetchone()

            json_response(
                self,
                {
                    "total": total["total"] if total else 0,
                    "firmadas_mes": firmadas_mes["total"] if firmadas_mes else 0,
                    "porcentaje_medio": averages["porcentaje_medio"] if averages else 0,
                    "comision_media": averages["comision_media"] if averages else 0,
                },
            )
            return

        if path == "/api/hipoteca_dashboard":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return

            current_year = conn.execute("SELECT strftime('%Y','now','localtime') AS y").fetchone()["y"]

            current = conn.execute(
                """
                SELECT
                  COUNT(*) AS total,
                  AVG(
                    CASE
                      WHEN precio IS NOT NULL AND precio > 0 AND importe_hipoteca IS NOT NULL
                        THEN (importe_hipoteca * 100.0 / precio)
                      WHEN porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 1 THEN porcentaje * 100.0
                      WHEN porcentaje IS NOT NULL AND porcentaje > 1 THEN porcentaje
                      ELSE NULL
                    END
                  ) AS porcentaje_medio,
                  AVG(COALESCE(comision, 0)) AS comision_media
                FROM hipotecas
                WHERE empresa_id = ?
                  AND anio = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                """,
                (empresa_id, current_year),
            ).fetchone()

            firmadas_mes = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                  AND fecha_firma IS NOT NULL
                  AND strftime('%Y-%m', fecha_firma) = strftime('%Y-%m', 'now', 'localtime')
                """,
                (empresa_id,),
            ).fetchone()

            series_totales = conn.execute(
                """
                SELECT anio AS year, COUNT(*) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            series_comision = conn.execute(
                """
                SELECT anio AS year, SUM(COALESCE(comision, 0)) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            series_porcentaje = conn.execute(
                """
                SELECT anio AS year,
                       AVG(
                         CASE
                           WHEN precio IS NOT NULL AND precio > 0 AND importe_hipoteca IS NOT NULL
                             THEN (importe_hipoteca * 100.0 / precio)
                           WHEN porcentaje IS NOT NULL AND porcentaje > 0 AND porcentaje <= 1 THEN porcentaje * 100.0
                           WHEN porcentaje IS NOT NULL AND porcentaje > 1 THEN porcentaje
                           ELSE NULL
                         END
                       ) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            series_entidades = conn.execute(
                """
                SELECT banco AS label, COUNT(*) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND banco IS NOT NULL
                  AND TRIM(banco) != ''
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                GROUP BY banco
                ORDER BY COUNT(*) DESC
                LIMIT 8
                """,
                (empresa_id,),
            ).fetchall()

            series_oficinas = conn.execute(
                """
                SELECT oficina AS label, COUNT(*) AS total
                FROM hipotecas
                WHERE empresa_id = ?
                  AND oficina IS NOT NULL
                  AND TRIM(oficina) != ''
                  AND LOWER(TRIM(estado)) IN ('firmado', 'firmada', 'indemnización', 'indemnizacion')
                GROUP BY oficina
                ORDER BY COUNT(*) DESC
                """,
                (empresa_id,),
            ).fetchall()

            json_response(
                self,
                {
                    "current": {
                        "total": current["total"] if current else 0,
                        "porcentaje_medio": current["porcentaje_medio"] if current else 0,
                        "comision_media": current["comision_media"] if current else 0,
                        "firmadas_mes": firmadas_mes["total"] if firmadas_mes else 0,
                    },
                    "series_totales": [dict(r) for r in series_totales],
                    "series_comision": [dict(r) for r in series_comision],
                    "series_porcentaje": [dict(r) for r in series_porcentaje],
                    "series_entidades": [dict(r) for r in series_entidades],
                    "series_oficinas": [dict(r) for r in series_oficinas],
                },
            )
            return

        if path == "/api/fincas_stats":
            empresa_id = params.get("empresa_id", [""])[0]
            year = params.get("year", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            if not year:
                year = conn.execute(
                    "SELECT strftime('%Y','now','localtime') AS y"
                ).fetchone()["y"]

            facturado = conn.execute(
                """
                SELECT SUM(COALESCE(comision, 0)) AS total
                FROM movimientos
                WHERE empresa_id = ?
                  AND anio = ?
                  AND LOWER(TRIM(tipo)) = 'ingreso'
                """,
                (empresa_id, year),
            ).fetchone()

            gastos = conn.execute(
                """
                SELECT SUM(COALESCE(comision, 0)) AS total
                FROM movimientos
                WHERE empresa_id = ?
                  AND anio = ?
                  AND LOWER(TRIM(tipo)) = 'gasto'
                """,
                (empresa_id, year),
            ).fetchone()

            empresas_total = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM gestoria
                WHERE empresa_id = ?
                  AND LOWER(TRIM(tipo)) IN ('empresa', 'empresas')
                """,
                (empresa_id,),
            ).fetchone()

            comunidades = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM gestoria
                WHERE empresa_id = ?
                  AND LOWER(TRIM(tipo)) IN ('comunidad', 'comunidad de propietarios', 'comunidades')
                """,
                (empresa_id,),
            ).fetchone()

            autonomos = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM gestoria
                WHERE empresa_id = ?
                  AND LOWER(TRIM(REPLACE(REPLACE(tipo, 'Ó', 'o'), 'ó', 'o'))) IN (
                    'autonomo',
                    'autónomo',
                    'autonomos',
                    'autónomos'
                  )
                """,
                (empresa_id,),
            ).fetchone()

            polizas = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                  AND LOWER(TRIM(estado)) IN ('en vigor', 'vigente', 'en_vigor')
                """,
                (empresa_id,),
            ).fetchone()

            json_response(
                self,
                {
                    "year": year,
                    "facturado": facturado["total"] if facturado else 0,
                    "gastos": gastos["total"] if gastos else 0,
                    "clientes_empresas": empresas_total["total"] if empresas_total else 0,
                    "comunidades": comunidades["total"] if comunidades else 0,
                    "autonomos": autonomos["total"] if autonomos else 0,
                    "polizas_vigor": polizas["total"] if polizas else 0,
                },
            )
            return

        if path == "/api/fincas_seguros_dashboard":
            empresa_id = params.get("empresa_id", [""])[0]
            year = params.get("year", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            if not year:
                year = conn.execute(
                    "SELECT strftime('%Y','now','localtime') AS y"
                ).fetchone()["y"]

            estado_expr = "LOWER(TRIM(estado))"
            year_expr = "COALESCE(STRFTIME('%Y', fecha_efecto), STRFTIME('%Y', created_at))"

            current = conn.execute(
                f"""
                SELECT
                  SUM(CASE WHEN {estado_expr} IN ('presupuesto', 'presupuestos') THEN 1 ELSE 0 END) AS presupuesto,
                  SUM(CASE WHEN {estado_expr} IN ('contratada', 'contratado', 'contrato', 'proyecto') THEN 1 ELSE 0 END) AS contratada,
                  SUM(CASE WHEN {estado_expr} IN ('en vigor', 'en_vigor', 'vigente', 'poliza', 'póliza', 'poliza en vigor') THEN 1 ELSE 0 END) AS en_vigor
                FROM seguros
                WHERE empresa_id = ?
                  AND {year_expr} = ?
                """,
                (empresa_id, year),
            ).fetchone()

            series = conn.execute(
                f"""
                SELECT
                  {year_expr} AS year,
                  SUM(CASE WHEN {estado_expr} IN ('presupuesto', 'presupuestos') THEN 1 ELSE 0 END) AS presupuesto,
                  SUM(CASE WHEN {estado_expr} IN ('contratada', 'contratado', 'contrato', 'proyecto') THEN 1 ELSE 0 END) AS contratada,
                  SUM(CASE WHEN {estado_expr} IN ('en vigor', 'en_vigor', 'vigente', 'poliza', 'póliza', 'poliza en vigor') THEN 1 ELSE 0 END) AS en_vigor
                FROM seguros
                WHERE empresa_id = ?
                  AND {year_expr} IS NOT NULL
                GROUP BY {year_expr}
                ORDER BY {year_expr}
                """,
                (empresa_id,),
            ).fetchall()

            presupuesto = current["presupuesto"] if current else 0
            contratada = current["contratada"] if current else 0
            en_vigor = current["en_vigor"] if current else 0
            total = (presupuesto or 0) + (contratada or 0) + (en_vigor or 0)
            conversion = (en_vigor / total * 100) if total else 0

            series_payload = []
            for row in series:
                row_dict = dict(row)
                total_row = (
                    (row_dict.get("presupuesto") or 0)
                    + (row_dict.get("contratada") or 0)
                    + (row_dict.get("en_vigor") or 0)
                )
                row_dict["conversion"] = (
                    (row_dict.get("en_vigor") or 0) / total_row * 100
                    if total_row
                    else 0
                )
                series_payload.append(row_dict)

            json_response(
                self,
                {
                    "current": {
                        "year": year,
                        "presupuesto": presupuesto or 0,
                        "contratada": contratada or 0,
                        "en_vigor": en_vigor or 0,
                        "total": total,
                        "conversion": conversion,
                    },
                    "series": series_payload,
                },
            )
            return

        if path == "/api/fincas_alerts":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT
                  tomador,
                  poliza_numero,
                  fecha_efecto,
                  DATE(fecha_efecto, '+1 year') AS fecha_vencimiento
                FROM seguros
                WHERE empresa_id = ?
                  AND fecha_efecto IS NOT NULL
                  AND DATE(fecha_efecto, '+1 year') BETWEEN DATE('now','localtime')
                      AND DATE('now','localtime','+30 days')
                ORDER BY DATE(fecha_efecto, '+1 year') ASC
                LIMIT 50
                """,
                (empresa_id,),
            ).fetchall()
            json_response(
                self,
                {
                    "count": len(rows),
                    "items": [dict(r) for r in rows],
                },
            )
            return

        if path == "/api/seguros_alertas":
            empresa_id = params.get("empresa_id", [""])[0]
            days = params.get("days", ["30"])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            try:
                days_int = int(days)
            except Exception:
                days_int = 30
            rows = conn.execute(
                f"""
                SELECT
                  id,
                  cliente_id,
                  tomador,
                  poliza_numero,
                  compania,
                  fecha_efecto,
                  COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year')) AS fecha_vencimiento
                FROM seguros
                WHERE empresa_id = ?
                  AND COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year')) IS NOT NULL
                  AND DATE(COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year'))) BETWEEN DATE('now','localtime')
                      AND DATE('now','localtime', '+{days_int} days')
                ORDER BY DATE(COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year'))) ASC
                LIMIT 50
                """,
                (empresa_id,),
            ).fetchall()
            json_response(self, {"count": len(rows), "items": [dict(r) for r in rows]})
            return

        if path == "/api/seguros_kpis":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return
            estado_expr = "LOWER(TRIM(estado))"
            total = conn.execute(
                "SELECT COUNT(*) AS total FROM seguros WHERE empresa_id = ?",
                (empresa_id,),
            ).fetchone()
            en_vigor = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                  AND {estado_expr} IN ('en vigor', 'en_vigor', 'vigente', 'poliza', 'póliza')
                """,
                (empresa_id,),
            ).fetchone()
            presupuesto = conn.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                  AND {estado_expr} IN ('presupuesto', 'presupuestos')
                """,
                (empresa_id,),
            ).fetchone()
            vencen_30 = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                  AND COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year')) IS NOT NULL
                  AND DATE(COALESCE(fecha_vencimiento, DATE(fecha_efecto, '+1 year'))) BETWEEN DATE('now','localtime')
                      AND DATE('now','localtime','+30 days')
                """,
                (empresa_id,),
            ).fetchone()
            faltantes = conn.execute(
                """
                SELECT COUNT(*) AS total
                FROM seguros
                WHERE empresa_id = ?
                  AND (
                    tomador IS NULL OR TRIM(tomador) = '' OR
                    poliza_numero IS NULL OR TRIM(poliza_numero) = '' OR
                    compania IS NULL OR TRIM(compania) = '' OR
                    fecha_efecto IS NULL OR TRIM(fecha_efecto) = ''
                  )
                """,
                (empresa_id,),
            ).fetchone()
            quality_rows = conn.execute(
                """
                SELECT calidad_ocr, COUNT(*) AS total
                FROM gestoria_docs
                WHERE empresa_id = ?
                  AND (referencia_tipo = 'seguros' OR tipo = 'Seguros')
                GROUP BY calidad_ocr
                """,
                (empresa_id,),
            ).fetchall()
            quality = {"alta": 0, "media": 0, "baja": 0, "desconocida": 0}
            for row in quality_rows:
                key = (row["calidad_ocr"] or "desconocida").lower()
                if key not in quality:
                    key = "desconocida"
                quality[key] += row["total"] or 0
            json_response(
                self,
                {
                    "total": total["total"] if total else 0,
                    "en_vigor": en_vigor["total"] if en_vigor else 0,
                    "presupuesto": presupuesto["total"] if presupuesto else 0,
                    "vencen_30": vencen_30["total"] if vencen_30 else 0,
                    "faltantes": faltantes["total"] if faltantes else 0,
                    "ocr_quality": quality,
                },
            )
            return

        if path == "/api/seguros_checklist":
            poliza_id = params.get("poliza_id", [""])[0]
            if not poliza_id:
                json_response(self, {"error": "poliza_id requerido"}, status=400)
                return
            rows = conn.execute(
                """
                SELECT id, poliza_id, tarea, estado, responsable, fecha_limite
                FROM seguros_checklist
                WHERE poliza_id = ?
                ORDER BY created_at
                """,
                (poliza_id,),
            ).fetchall()
            json_response(self, {"rows": [dict(r) for r in rows]})
            return

        if path == "/api/dashboard":
            empresa_id = params.get("empresa_id", [""])[0]
            if not empresa_id:
                json_response(self, {"error": "empresa_id requerido"}, status=400)
                return

            ventas = conn.execute(
                """
                SELECT anio AS year, COUNT(*) AS total
                FROM movimientos
                WHERE empresa_id = ?
                  AND UPPER(TRIM(concepto)) = 'COMPRAVENTA'
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            ingresos = conn.execute(
                """
                SELECT anio AS year, SUM(COALESCE(comision, 0)) AS total
                FROM movimientos
                WHERE empresa_id = ?
                  AND LOWER(TRIM(tipo)) = 'ingreso'
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            gastos = conn.execute(
                """
                SELECT anio AS year, SUM(COALESCE(comision, 0)) AS total
                FROM movimientos
                WHERE empresa_id = ?
                  AND LOWER(TRIM(tipo)) = 'gasto'
                GROUP BY anio
                ORDER BY anio
                """,
                (empresa_id,),
            ).fetchall()

            alquileres = conn.execute(
                """
                SELECT STRFTIME('%Y', fecha) AS year,
                       COUNT(*) AS total,
                       SUM(COALESCE(precio, 0)) AS facturado
                FROM alquileres
                WHERE empresa_id = ?
                  AND fecha IS NOT NULL
                GROUP BY STRFTIME('%Y', fecha)
                ORDER BY STRFTIME('%Y', fecha)
                """,
                (empresa_id,),
            ).fetchall()

            json_response(
                self,
                {
                    "ventas": [dict(r) for r in ventas],
                    "ingresos": [dict(r) for r in ingresos],
                    "gastos": [dict(r) for r in gastos],
                    "alquileres": [dict(r) for r in alquileres],
                },
            )
            return

        if path == "/api/tabla":
            tabla = params.get("tabla", ["movimientos"])[0]
            if tabla not in TABLES:
                json_response(self, {"error": "Tabla no valida"}, status=400)
                return

            empresa_id = params.get("empresa_id", [""])[0]
            q = params.get("q", [""])[0].strip()
            year_filter = params.get("year", [""])[0].strip()
            field_filter = params.get("field", [""])[0].strip()
            estado_filter = params.get("estado", [""])[0].strip()
            tipo_filter = params.get("tipo", [""])[0].strip()
            perfil_filter = params.get("perfil", [""])[0].strip()
            limit_param = params.get("limit", [""])[0].strip()
            include_id = params.get("include_id", ["0"])[0] == "1"

            columns = [
                r["name"]
                for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()
            ]
            hidden = {"empresa_id", "created_at", "updated_at"}
            visible_columns = [col for col in columns if col not in hidden]
            if not include_id:
                visible_columns = [col for col in visible_columns if col != "id"]
            text_columns = [col for col in visible_columns]

            where = []
            values = []
            if empresa_id:
                where.append("t.empresa_id = ?")
                values.append(empresa_id)

            if year_filter and tabla == "movimientos":
                where.append("t.anio = ?")
                values.append(year_filter)

            if q:
                if field_filter and field_filter in visible_columns:
                    where.append(f"t.{field_filter} LIKE ?")
                    values.append(f"%{q}%")
                else:
                    likes = " OR ".join([f"t.{col} LIKE ?" for col in text_columns])
                    where.append(f"({likes})")
                    values.extend([f"%{q}%"] * len(text_columns))

            if estado_filter and "estado" in visible_columns:
                where.append("t.estado = ?")
                values.append(estado_filter)
            if tipo_filter and "tipo" in visible_columns:
                where.append("t.tipo = ?")
                values.append(tipo_filter)
            if perfil_filter and "perfil" in visible_columns:
                where.append("t.perfil LIKE ?")
                values.append(f"%{perfil_filter}%")

            where_clause = f"WHERE {' AND '.join(where)}" if where else ""
            select_cols = ", ".join([f"t.{col}" for col in visible_columns])
            limit_clause = "LIMIT 200"
            if limit_param.isdigit():
                limit_clause = f"LIMIT {int(limit_param)}"
            query = (
                f"SELECT e.nombre AS empresa, {select_cols} "
                f"FROM {tabla} t "
                "LEFT JOIN empresas e ON e.id = t.empresa_id "
                f"{where_clause} "
                f"{limit_clause}"
            )
            rows = conn.execute(query, values).fetchall()
            json_response(
                self,
                {"columns": ["empresa"] + visible_columns, "rows": [list(r) for r in rows]},
            )
            return

        json_response(self, {"error": "Endpoint no valido"}, status=404)


def main():
    parser = argparse.ArgumentParser(description="ERP Modernia local server.")
    parser.add_argument("--db", default=str(DB_DEFAULT), help="SQLite path.")
    parser.add_argument("--host", default="127.0.0.1", help="Host.")
    parser.add_argument("--port", type=int, default=8000, help="Port.")
    args = parser.parse_args()

    ensure_tables(args.db)
    Handler.db_path = args.db
    server = HTTPServer((args.host, args.port), Handler)
    print(f"Servidor activo en http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
