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
        with urllib.request.urlopen(req, timeout=20) as resp:
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


def normalize_field_label(value):
    value = value or ""
    value = value.lower()
    value = value.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value
