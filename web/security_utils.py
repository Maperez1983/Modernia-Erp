import hmac
import html
import ipaddress
import json
import re
import socket
import urllib.parse
from pathlib import Path


def _ct_eq(a: str, b: str) -> bool:
    try:
        return hmac.compare_digest(str(a or ""), str(b or ""))
    except Exception:
        return False


def _normalize_s3_key(key):
    raw = str(key or "").strip().replace("\\", "/")
    return raw.lstrip("/")


def _iter_s3_legacy_key_candidates(key: str):
    safe = _normalize_s3_key(key)
    if not safe:
        return []
    candidates = [safe]
    # Legacy compatibility: some historical flows stored only a 32-char hex id
    # without prefix or extension, but the object could live under `docs/` or `renta/`.
    if re.fullmatch(r"[0-9a-fA-F]{32}", safe) and "/" not in safe:
        prefixes = ["gestoria", "gestoria_docs", "docs", "renta", "rentas"]
        suffixes = ["", ".pdf"]
        for pref in prefixes:
            for suf in suffixes:
                candidates.append(f"{pref}/{safe}{suf}")
        for suf in [".pdf"]:
            candidates.append(f"{safe}{suf}")
    seen = set()
    out = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _is_public_doc_url(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("/uploads/"):
        return True
    if text.startswith("s3://"):
        return True
    if text.startswith("http://") or text.startswith("https://"):
        return True
    return False


def _looks_like_placeholder_doc_key(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "/" in text or "." in text:
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{32}", text))


def _normalize_doc_key_for_ui(value: object) -> str:
    text = str(value or "").strip()
    if not text or _looks_like_placeholder_doc_key(text):
        return ""
    return _normalize_s3_key(text) if text.startswith("s3://") else text


def _safe_json_object(raw):
    try:
        if raw is None:
            return {}
        text = str(raw or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def html_to_text(value):
    text = str(value or "")
    text = re.sub(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _html_to_text(html_text):
    value = str(html_text or "")
    value = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\\1>", " ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = re.sub(r"[\\t\\r\\f\\v]+", " ", value)
    value = re.sub(r"\\n\\s*\\n+", "\\n\\n", value)
    value = re.sub(r"\\s{2,}", " ", value)
    return value.strip()


def _extract_title(html_text):
    text = str(html_text or "")
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if not m:
        return ""
    title = re.sub(r"(?s)<[^>]+>", " ", m.group(1))
    title = html.unescape(re.sub(r"\\s+", " ", title)).strip()
    return title


def _is_ip_literal(hostname):
    value = str(hostname or "").strip()
    if not value:
        return False
    if ":" in value:
        return True
    return bool(re.match(r"^\d{1,3}(\.\d{1,3}){3}$", value))


def _is_disallowed_hostname(hostname):
    host = str(hostname or "").strip().lower()
    if not host:
        return True
    if host in {"localhost", "localhost.localdomain"}:
        return True
    if host.endswith(".local"):
        return True
    if _is_ip_literal(host):
        return True
    return False


def _domain_is_allowed(hostname, allowed_domains):
    host = str(hostname or "").strip().lower().rstrip(".")
    if not host or _is_disallowed_hostname(host):
        return False
    for allowed in allowed_domains or ():
        allowed = str(allowed or "").strip().lower().rstrip(".")
        if not allowed:
            continue
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _hostname_resolves_to_disallowed_ip(hostname):
    host = str(hostname or "").strip()
    if not host:
        return True, "hostname vacío"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return True, "no se pudo resolver DNS"
    ips = []
    for info in infos or []:
        try:
            sockaddr = info[4]
            ip = sockaddr[0]
        except Exception:
            continue
        if not ip:
            continue
        ips.append(ip)
    if not ips:
        return True, "sin IPs resueltas"
    for ip in ips:
        try:
            obj = ipaddress.ip_address(ip)
        except Exception:
            return True, "IP no válida"
        if not getattr(obj, "is_global", False):
            return True, f"resuelve a IP no global ({ip})"
    return False, ""


def _pdf_escape(value):
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def safe_resolve_under(base_dir, rel_path):
    """
    Devuelve una ruta segura dentro de `base_dir` o None si intenta salir del directorio.
    """
    base_dir = Path(base_dir).resolve()
    rel = str(rel_path or "")
    rel = urllib.parse.unquote(rel)
    rel = rel.lstrip("/").replace("\\", "/")
    if not rel:
        return None
    if rel.startswith("../") or "/../" in rel or rel.startswith("..\\") or "\\..\\" in rel:
        return None
    candidate = (base_dir / rel).resolve()
    if candidate == base_dir:
        return None
    if base_dir not in candidate.parents:
        return None
    return candidate
