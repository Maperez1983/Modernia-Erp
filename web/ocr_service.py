import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


def _resolve_external_ocr_config() -> tuple[str, str]:
    credentials_path = ""
    for env_name in ("OCR_GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_APPLICATION_CREDENTIALS"):
        raw_path = os.environ.get(env_name)
        if raw_path in (None, ""):
            continue
        try:
            raw_path = str(raw_path)
        except Exception:
            continue
        raw_path = raw_path.strip()
        if not raw_path:
            continue
        try:
            candidate = Path(raw_path).expanduser()
        except Exception:
            continue
        if not candidate.is_absolute():
            continue
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
        except Exception:
            continue
        suffix = candidate.suffix.lower()
        if suffix and suffix != ".json":
            continue
        credentials_path = str(candidate)
        break
    api_key = os.environ.get("GOOGLE_VISION_API_KEY") or os.environ.get("VISION_API_KEY")
    if api_key in (None, ""):
        api_key = ""
    else:
        try:
            api_key = str(api_key)
        except Exception:
            api_key = ""
        if api_key:
            api_key = api_key.split()[0].strip()
    return credentials_path, api_key


def external_ocr_available(*, resolver=None):
    resolver = resolver or _resolve_external_ocr_config
    flag = (os.environ.get("OCR_EXTERNAL_ENABLED", "1") or "").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    credentials_path, api_key = resolver()
    return bool(api_key) or (credentials_path and os.path.exists(credentials_path))


def ocr_image_external(image_bytes, *, resolver=None):
    resolver = resolver or _resolve_external_ocr_config
    credentials_path, api_key = resolver()
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
        # Endpoint HTTPS fijo; la URL no depende de entrada del usuario.
        with urllib.request.urlopen(req, timeout=20) as resp:  # nosec B310
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as err:
        msg = str(err)
        if api_key and api_key in msg:
            msg = msg.replace(api_key, "***")
        return "", f"OCR externo: {msg}"
    try:
        text = res["responses"][0].get("fullTextAnnotation", {}).get("text", "") or ""
        if not str(text).strip():
            return "", "OCR externo: sin texto"
        return text, ""
    except Exception:
        return "", "OCR externo: sin texto"


def ocr_image_docai(image_bytes, mime_type, *, resolver=None):
    resolver = resolver or _resolve_external_ocr_config
    credentials_path, _ = resolver()
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
        # Endpoint HTTPS fijo; la URL no depende de entrada del usuario.
        with urllib.request.urlopen(req, timeout=25) as resp:  # nosec B310
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
    occurrences: dict[str, int] = {}
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


def normalize_field_label(value):
    value = value or ""
    value = value.lower()
    value = value.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def docai_available():
    processor_id = os.environ.get("DOCUMENTAI_PROCESSOR_ID") or os.environ.get("DOC_AI_PROCESSOR_ID")
    return bool(processor_id)


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
