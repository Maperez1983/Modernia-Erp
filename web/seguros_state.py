import re
import unicodedata


CANONICAL_STATES = {"Presupuesto", "Contratada", "En vigor", "Anulada", "Rechazada"}
BLOCKED_CANONICAL_TRANSITIONS = {
    ("Presupuesto", "En vigor"),
}


def _normalize_lookup_text(value):
    text = str(value or "").strip().upper()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_seguro_estado_value(value):
    key = _normalize_lookup_text(value)
    if not key:
        return ""
    if key in ("PRESUPUESTO", "PROYECTO", "PENDIENTE"):
        return "Presupuesto"
    if key in ("RECHAZADA", "RECHAZADO", "NO ACEPTADA", "NO ACEPTADO", "DENEGADA", "DENEGADO"):
        return "Rechazada"
    if key.startswith("RECHAZADA ") or key.startswith("RECHAZADO "):
        return "Rechazada"
    if key in ("CONTRATADA", "CONTRATADO"):
        return "Contratada"
    if key in ("EN VIGOR", "ENVIGOR", "VIGENTE", "ACTIVA", "ACTIVO"):
        return "En vigor"
    if key in ("ANULADA", "ANULADO", "BAJA", "CANCELADA", "CANCELADO"):
        return "Anulada"
    return str(value or "").strip()


def can_transition_seguro_estado(current_value, target_value):
    current = normalize_seguro_estado_value(current_value)
    target = normalize_seguro_estado_value(target_value)
    if not target:
        return True
    if not current or current == target:
        return True
    if current in CANONICAL_STATES and target in CANONICAL_STATES:
        return (current, target) not in BLOCKED_CANONICAL_TRANSITIONS
    return True
