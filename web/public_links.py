import hashlib
import os
import secrets
import urllib.parse


def _normalize_url(value):
    return str(value or "").strip().rstrip("/")


def configured_app_base_url():
    return _normalize_url(os.environ.get("APP_BASE_URL"))


def resolve_public_link_base_url(base_url=""):
    base = _normalize_url(base_url)
    if base:
        return base
    return _normalize_url(os.environ.get("APP_BASE_URL") or os.environ.get("PUBLIC_URL") or "")


def external_base_url():
    configured = configured_app_base_url()
    if configured:
        return configured
    for env_key in ("RENDER_EXTERNAL_URL", "PUBLIC_BASE_URL", "PUBLIC_URL", "APP_PUBLIC_URL"):
        value = _normalize_url(os.environ.get(env_key))
        if value:
            return value
    # No inferimos el host desde cabeceras de petición para no construir enlaces
    # con tokens apuntando a un dominio controlado por el cliente.
    return "http://localhost:8000"


def build_public_fragment_url(fragment_key, token, base_url="", path=""):
    base = _normalize_url(base_url)
    safe_path = str(path or "").strip()
    if safe_path and not safe_path.startswith("/"):
        safe_path = "/" + safe_path
    prefix = f"{base}{safe_path}" if base else (safe_path or "/")
    fragment = str(fragment_key or "").strip() or "token"
    return f"{prefix}#{fragment}={urllib.parse.quote(str(token or ''))}"


def hash_signature_token(raw):
    return hashlib.sha256(str(raw or "").encode("utf-8")).hexdigest()


def make_signature_token():
    return secrets.token_urlsafe(32)


def signature_request_public_payload(row, token=""):
    if not row:
        return None
    data = dict(row)
    public = {
        "id": data.get("id") or "",
        "inmueble_id": data.get("inmueble_id") or "",
        "doc_nombre": data.get("doc_nombre") or "Documento",
        "doc_url": data.get("doc_url") or "",
        "signer_nombre": data.get("signer_nombre") or "",
        "signer_nif": data.get("signer_nif") or "",
        "signer_email": data.get("signer_email") or "",
        "purpose": data.get("purpose") or "Firma electrónica interna",
        "status": data.get("status") or "pending",
        "otp_required": bool(int(data.get("otp_required") or 0)),
        "expires_at": data.get("expires_at") or "",
        "opened_at": data.get("opened_at") or "",
        "signed_at": data.get("signed_at") or "",
        "signed_doc_url": data.get("signed_doc_url") or "",
        "doc_public_url": "/api/inmueble_signature_document",
    }
    return public
