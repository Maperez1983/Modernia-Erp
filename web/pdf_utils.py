#!/usr/bin/env python3
import re
import textwrap
import unicodedata
import urllib.parse
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont


def _normalize_lookup_text(value):
    if not value:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.upper()
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


HIPOTECA_BANK_BRANDS = (
    {
        "name": "Banco Santander",
        "short": "Santander",
        "logo": "/assets/logos/santander.svg",
        "color": "#e30613",
        "logo_on_dark": True,
        "aliases": (
            "santander",
            "banco santander",
            "banco santander sa",
            "banco santander s a",
            "banco santander s.a.",
            "grupo santander",
            "santander consumer",
            "santander consumer finance",
            "santander consumer finance sa",
        ),
    },
    {
        "name": "BBVA",
        "short": "BBVA",
        "logo": "/assets/logos/bbva.png",
        "color": "#072146",
        "logo_on_dark": False,
        "aliases": ("bbva", "banco bilbao vizcaya argentaria", "banco bilbao vizcaya argentaria sa", "bbva sa"),
    },
    {
        "name": "CaixaBank",
        "short": "CaixaBank",
        "logo": "/assets/logos/caixabank.svg",
        "color": "#0079c1",
        "logo_on_dark": False,
        "aliases": (
            "caixabank",
            "caixa bank",
            "caixabank sa",
            "caixabank s a",
            "la caixa",
            "caixa",
            "criteria caixa",
        ),
    },
    {
        "name": "Banco Sabadell",
        "short": "Sabadell",
        "logo": "/assets/logos/sabadell.svg",
        "color": "#003b7a",
        "logo_on_dark": False,
        "aliases": (
            "sabadell",
            "banco sabadell",
            "banco sabadell sa",
            "banco sabadell s a",
            "banco de sabadell",
            "banco de sabadell sa",
            "banco de sabadell s a",
        ),
    },
    {
        "name": "Bankinter",
        "short": "Bankinter",
        "logo": "/assets/logos/bankinter.svg",
        "color": "#f58220",
        "logo_on_dark": False,
        "aliases": ("bankinter", "bankinter sa", "bankinter s a", "bankinter consumer finance", "bankinter consumer"),
    },
    {
        "name": "Unicaja Banco",
        "short": "Unicaja",
        "logo": "/assets/logos/unicaja.png",
        "color": "#007a53",
        "logo_on_dark": False,
        "aliases": ("unicaja", "unicaja banco", "unicaja banco sa", "unicaja banco s a"),
    },
    {
        "name": "ABANCA",
        "short": "ABANCA",
        "logo": "/assets/logos/abanca.svg",
        "color": "#001f5b",
        "logo_on_dark": False,
        "aliases": ("abanca", "abanca corporacion bancaria", "abanca corporacion bancaria sa"),
    },
    {
        "name": "Cajamar",
        "short": "Cajamar",
        "logo": "/assets/logos/cajamar.svg",
        "color": "#00843d",
        "logo_on_dark": False,
        "aliases": ("cajamar", "cajamar caja rural", "cajamar caja rural sociedad cooperativa de credito", "cajamar caja rural scc"),
    },
    {
        "name": "UCI",
        "short": "UCI",
        "logo": "/assets/logos/uci.svg",
        "color": "#5a2d82",
        "logo_on_dark": False,
        "aliases": ("uci", "u c i", "union de creditos inmobiliarios", "union de creditos inmobiliarios sa"),
    },
    {
        "name": "Caja Rural de Granada",
        "short": "CR Granada",
        "logo": "/assets/logos/caja-rural-granada.png",
        "color": "#2e7d32",
        "logo_on_dark": True,
        "aliases": ("caja rural de granada", "caja rural granada", "cajarural de granada", "cajarural granada", "rural granada"),
    },
    {
        "name": "Caja Rural del Sur",
        "short": "CR del Sur",
        "logo": "/assets/logos/caja-rural-del-sur.png",
        "color": "#0b8f3d",
        "logo_on_dark": False,
        "aliases": ("caja rural del sur", "caja rural sur", "cajarural del sur", "cajarural sur", "rural del sur", "rural sur"),
    },
    {
        "name": "ING",
        "short": "ING",
        "logo": "/assets/logos/ing.svg",
        "color": "#ff6200",
        "logo_on_dark": False,
        "aliases": ("ing", "ing direct", "ing bank", "ing direct nv", "ing direct n v", "ing direct nv sucursal en espana"),
    },
)

HIPOTECA_BANK_BRAND_LOOKUP = {}
HIPOTECA_EXPORT_BRANDS = {}
for _bank_brand in HIPOTECA_BANK_BRANDS:
    for _alias in (_bank_brand.get("name"), *(_bank_brand.get("aliases") or ())):
        _alias_key = _normalize_lookup_text(_alias)
        if not _alias_key:
            continue
        HIPOTECA_BANK_BRAND_LOOKUP[_alias_key] = _bank_brand
        HIPOTECA_EXPORT_BRANDS[_alias_key] = _bank_brand["name"]


def resolve_hipoteca_bank_brand(value):
    raw = str(value or "").strip()
    if not raw:
        return {
            "name": "",
            "short": "",
            "logo": "",
            "color": "#824c45",
            "logo_on_dark": False,
            "original": "",
            "display_name": "",
        }
    normalized = _normalize_lookup_text(raw)
    brand = HIPOTECA_BANK_BRAND_LOOKUP.get(normalized)
    if not brand and normalized:
        for alias_key, candidate in HIPOTECA_BANK_BRAND_LOOKUP.items():
            if alias_key and (normalized in alias_key or alias_key in normalized):
                brand = candidate
                break
    if brand:
        return {
            **brand,
            "logo_on_dark": bool(brand.get("logo_on_dark") or brand.get("logoOnDark")),
            "original": raw,
            "display_name": brand["name"],
        }
    initials = "".join(token[:1] for token in raw.split()[:2]).upper().strip() or "??"
    return {
        "name": raw,
        "short": initials,
        "logo": "",
        "color": "#824c45",
        "logo_on_dark": False,
        "original": raw,
        "display_name": raw,
    }


def build_hipoteca_bank_logo_meta(value):
    brand = resolve_hipoteca_bank_brand(value)
    return {
        "logo_url": str(brand.get("logo") or "").strip(),
        "logo_initials": str(brand.get("short") or "").strip(),
        "logo_color": str(brand.get("color") or "").strip() or "#824c45",
        "logo_on_dark": bool(brand.get("logo_on_dark") or brand.get("logoOnDark")),
        "logo_label": str(brand.get("display_name") or brand.get("name") or "").strip(),
    }


def normalize_hipoteca_pdf_sort_order(value):
    raw = _normalize_lookup_text(value)
    if raw in {"ASC", "ASCENDENTE", "ASCENDING", "CRECIENTE", "UP"}:
        return "asc"
    return "desc"


def _pdf_escape(value):
    return str(value or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdf_wrap_lines(text, width=86):
    raw = str(text or "").strip()
    if not raw:
        return [""]
    lines = []
    for block in raw.splitlines():
        block = block.strip()
        if not block:
            lines.append("")
            continue
        wrapped = textwrap.wrap(block, width=width, break_long_words=False, break_on_hyphens=False)
        lines.extend(wrapped or [""])
    return lines or [""]


def _pdf_wrap_lines_px(draw, text, font, max_width_px):
    raw = str(text or "").strip()
    if not raw:
        return [""]

    def measure(txt):
        try:
            return float(draw.textlength(txt, font=font))
        except Exception:
            box = draw.textbbox((0, 0), txt, font=font)
            return float(box[2] - box[0])

    lines = []
    for block in raw.splitlines():
        block = block.strip()
        if not block:
            lines.append("")
            continue
        words = block.split()
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if current and measure(trial) > max_width_px:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
    return lines or [""]


def _pdf_draw_justified_paragraph(draw, x, y, max_width_px, text, font, fill, *, line_spacing=6):
    raw = str(text or "").strip()
    if not raw:
        return y

    def measure(txt):
        try:
            return float(draw.textlength(txt, font=font))
        except Exception:
            box = draw.textbbox((0, 0), txt, font=font)
            return float(box[2] - box[0])

    lines = _pdf_wrap_lines_px(draw, raw, font, max_width_px)
    sample_box = draw.textbbox((x, y), "Ag", font=font)
    line_h = (sample_box[3] - sample_box[1]) + (line_spacing + 2)

    for index, line in enumerate(lines):
        if not line.strip():
            y += line_h
            continue
        is_last = index == len(lines) - 1
        words = line.split()
        if is_last or len(words) <= 1:
            draw.text((x, y), line, fill=fill, font=font)
            y += line_h
            continue

        base = " ".join(words)
        base_w = measure(base)
        extra = max(0.0, max_width_px - base_w)
        gaps = max(1, len(words) - 1)
        per_gap = extra / gaps

        cursor_x = float(x)
        for wi, word in enumerate(words):
            draw.text((cursor_x, y), word, fill=fill, font=font)
            cursor_x += measure(word)
            if wi != len(words) - 1:
                cursor_x += measure(" ") + per_gap
        y += line_h
    return y


def _parse_money_value(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    text = re.sub(r"[^0-9,\.\-]+", "", text)
    if not text or text in ("-", ".", ","):
        return 0.0
    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        text = text.replace(".", "").replace(",", ".")
    elif has_comma:
        text = text.replace(",", ".")
    elif has_dot:
        parts = text.split(".")
        if len(parts) > 1:
            last = parts[-1]
            groups_ok = all(len(p) == 3 for p in parts[1:])
            if groups_ok and len(last) == 3:
                text = "".join(parts)
    if not text or text in ("-", "."):
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _pdf_format_number(value, decimals=2):
    amount = _parse_money_value(value)
    return f"{amount:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _document_font(size=18, bold=False):
    candidates = []
    if bold:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            continue
    return ImageFont.load_default()


def _parse_pdf_color(value, fallback=(255, 255, 255)):
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if raw.startswith("#"):
        hex_value = raw.lstrip("#")
        if len(hex_value) == 3:
            hex_value = "".join(ch * 2 for ch in hex_value)
        if len(hex_value) == 6:
            try:
                return tuple(int(hex_value[idx : idx + 2], 16) for idx in (0, 2, 4))
            except Exception:
                return fallback
    return fallback


def _pil_multiline(draw, text, font, width, line_gap=8):
    lines = _pdf_wrap_lines(text, width=width)
    bbox = draw.textbbox((0, 0), "Ag", font=font)
    line_height = (bbox[3] - bbox[1]) + line_gap
    total_height = max(line_height * len(lines), line_height)
    return lines, line_height, total_height


def _logo_badge_info_from_path(raw_logo_url):
    raw = str(raw_logo_url or "").strip()
    if not raw:
        return None
    raw_lower = raw.lower()
    for brand in HIPOTECA_BANK_BRANDS:
        logo_path = str(brand.get("logo") or "").strip()
        if logo_path and logo_path.lower() == raw_lower:
            return {
                "label": str(brand.get("name") or "").strip() or str(brand.get("short") or "").strip() or "Banco",
                "short": str(brand.get("short") or "").strip()
                or "".join(token[:1] for token in str(brand.get("name") or "").split()[:2]).upper(),
                "color": str(brand.get("color") or "").strip() or "#824c45",
                "logo_on_dark": bool(brand.get("logoOnDark") or brand.get("logo_on_dark")),
            }
    parsed = urllib.parse.urlparse(raw)
    stem = Path(parsed.path or raw).stem.strip()
    if not stem:
        return None
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem:
        return None
    lower = stem.lower()
    if lower == "grupo modernia logo":
        label = "Grupo Modernia"
        color = "#c8a24a"
    elif lower.startswith("verifika2"):
        label = "Verifika²"
        color = "#2f5c45"
    else:
        label = stem.title()
        color = "#824c45"
    short = "".join(token[:1] for token in label.split()[:2]).upper().strip() or label[:2].upper()
    return {
        "label": label,
        "short": short,
        "color": color,
        "logo_on_dark": False,
    }


def _build_logo_badge_image(label, color="#824c45", short=None, logo_on_dark=False, max_width=520):
    label = str(label or "").strip() or "Banco"
    short = str(short or "").strip() or "".join(token[:1] for token in label.split()[:2]).upper().strip() or label[:2].upper()
    try:
        accent = ImageColor.getrgb(str(color or "#824c45").strip())
    except Exception:
        accent = (132, 76, 69)
    fill = accent if logo_on_dark else (255, 255, 255)
    border = accent
    text_fill = (255, 255, 255) if logo_on_dark else accent
    secondary_fill = accent if logo_on_dark else (250, 250, 250)
    badge_height = 96 if len(label) <= 16 else 110 if len(label) <= 28 else 124
    badge_width = min(max_width, max(240, 150 + len(label) * 9))
    image = Image.new("RGBA", (badge_width, badge_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    try:
        draw.rounded_rectangle((1, 1, badge_width - 2, badge_height - 2), radius=22, fill=fill, outline=border, width=3)
    except Exception:
        draw.rectangle((1, 1, badge_width - 2, badge_height - 2), fill=fill, outline=border, width=3)
    box_size = min(72, badge_height - 24)
    box_y = int((badge_height - box_size) / 2)
    draw.rounded_rectangle((14, box_y, 14 + box_size, box_y + box_size), radius=18, fill=secondary_fill, outline=border, width=2)
    short_font = _document_font(28 if len(short) <= 3 else 22, bold=True)
    short_fill = (255, 255, 255) if logo_on_dark else accent
    draw.text((14 + box_size / 2, box_y + box_size / 2), short, fill=short_fill, font=short_font, anchor="mm")
    label_x = 14 + box_size + 16
    label_width = max(90, badge_width - label_x - 18)
    label_font = _document_font(18 if len(label) <= 18 else 16 if len(label) <= 28 else 14, bold=True)
    label_lines = _pdf_wrap_lines_px(draw, label, label_font, label_width)
    try:
        sample_box = draw.textbbox((0, 0), "Ag", font=label_font)
        line_height = (sample_box[3] - sample_box[1]) + 3
    except Exception:
        line_height = 22
    block_height = max(line_height * len(label_lines), line_height)
    label_y = max(12, int((badge_height - block_height) / 2))
    draw.multiline_text((label_x, label_y), "\n".join(label_lines), fill=text_fill, font=label_font, spacing=3)
    return image
