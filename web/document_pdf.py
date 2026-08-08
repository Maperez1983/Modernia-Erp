#!/usr/bin/env python3
import os
import re
import sys
import textwrap
from io import BytesIO
from pathlib import Path
import urllib.parse
from typing import Any

from PIL import Image, ImageDraw
try:  # arranca como paquete (python -m web.server) o como script suelto
    from .pdf_fonts import PDF_FONT_BOLD, PDF_FONT_REGULAR
except ImportError:
    from pdf_fonts import PDF_FONT_BOLD, PDF_FONT_REGULAR

try:
    import cairosvg
except Exception:  # pragma: no cover
    cairosvg = None

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib import colors as rl_colors
except Exception:  # pragma: no cover
    rl_canvas = None
    rl_colors = None

try:
    from . import pdf_utils as runtime_pdf_utils
except ImportError:  # pragma: no cover
    import pdf_utils as _runtime_pdf_utils
    runtime_pdf_utils = _runtime_pdf_utils


_document_font = runtime_pdf_utils._document_font
_pil_multiline = runtime_pdf_utils._pil_multiline
_logo_badge_info_from_path = runtime_pdf_utils._logo_badge_info_from_path
_build_logo_badge_image = runtime_pdf_utils._build_logo_badge_image

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT.parent / "assets"

_DEPENDENCIES: dict[str, Any] = {}

_RESAMPLE_LANCZOS = getattr(Image, "LANCZOS", getattr(Image, "BICUBIC", 0))


def configure_dependencies(**deps):
    for key, value in deps.items():
        if value is not None:
            _DEPENDENCIES[key] = value


def _dep(name):
    if name not in _DEPENDENCIES:
        raise RuntimeError(f"document_pdf dependency not configured: {name}")
    return _DEPENDENCIES[name]


def format_eur(value):
    amount = float(value or 0.0)
    raw = f"{amount:,.2f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _load_image_from_bytes(raw_bytes, max_width=520):
    if not raw_bytes:
        return None
    logo = None
    try:
        logo = Image.open(BytesIO(raw_bytes)).convert("RGBA")
    except Exception:
        logo = None
    if logo is None and cairosvg is not None:
        try:
            svg_kwargs = {}
            if max_width and max_width > 0:
                svg_kwargs["output_width"] = int(max_width)
            png_bytes = cairosvg.svg2png(bytestring=raw_bytes, **svg_kwargs)
            logo = Image.open(BytesIO(png_bytes)).convert("RGBA")
        except Exception:
            logo = None
    if logo is None:
        return None
    if logo.width > max_width:
        ratio = max_width / float(logo.width)
        logo = logo.resize((int(logo.width * ratio), int(logo.height * ratio)), _RESAMPLE_LANCZOS)
    return logo


def _load_image_from_path(logo_path, max_width=520):
    if not logo_path or not logo_path.exists():
        return None
    try:
        raw_bytes = logo_path.read_bytes()
    except Exception:
        return None
    return _load_image_from_bytes(raw_bytes, max_width=max_width)


def load_brand_logo(logo_url=None, max_width=520):
    raw = str(logo_url).strip() if logo_url else ""
    logo_path = None
    logo = None

    if raw:
        parsed = urllib.parse.urlparse(raw)
        path_raw = parsed.path or raw
        candidate = None
        if raw.startswith("/assets/"):
            candidate = ASSETS / raw.replace("/assets/", "", 1)
        elif raw.startswith("assets/"):
            candidate = ROOT / raw
        elif parsed.scheme == "file" and path_raw:
            candidate = Path(path_raw)
        elif not parsed.scheme and path_raw:
            candidate = Path(path_raw)
        elif path_raw.startswith("/assets/"):
            candidate = ASSETS / path_raw.replace("/assets/", "", 1)
        elif path_raw.startswith("assets/"):
            candidate = ROOT / path_raw
        if candidate is not None and candidate.exists():
            logo_path = candidate
            logo = _load_image_from_path(candidate, max_width=max_width)

    if logo is None:
        if logo_path is None:
            logo_path = ASSETS / "verifika2" / "verifika2_wordmark_check_green_transparent.png"
            if not logo_path.exists():
                logo_path = ASSETS / "verifika2" / "verifika2_wordmark_check_green.png"
        if not logo_path.exists():
            logo = None
        else:
            logo = _load_image_from_path(logo_path, max_width=max_width)
        if logo is None:
            badge_info = _logo_badge_info_from_path(raw)
            if badge_info:
                try:
                    logo = _build_logo_badge_image(
                        badge_info.get("label") or "Logo",
                        color=badge_info.get("color") or "#824c45",
                        short=badge_info.get("short") or "",
                        logo_on_dark=bool(badge_info.get("logo_on_dark")),
                        max_width=max_width,
                    )
                except Exception:
                    logo = None
        if logo is None:
            return None
    return logo


def _company_uses_modernia_pdf_brand(company):
    company = company or {}
    name = str(company.get("nombre") or "").strip().lower()
    logo_url = str(company.get("logo_url") or "").strip().lower()
    return ("modernia" in name) or ("modernia" in logo_url) or ("grupo_modernia" in logo_url)


def build_branded_document_pdf(title, subtitle, sections, footer_lines=None, brand_logo_url=None):
    footer_lines = footer_lines or []
    page_width, page_height = 1240, 1754
    margin_x, top_margin, bottom_margin = 90, 70, 90
    logo = _dep("load_brand_logo")(brand_logo_url, max_width=560)
    font_title = _document_font(34, bold=True)
    font_subtitle = _document_font(18, bold=False)
    font_section = _document_font(22, bold=True)
    font_body = _document_font(17, bold=False)
    font_footer = _document_font(15, bold=False)
    pages = []

    def new_page():
        image = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(image)
        y: float = float(top_margin)
        if logo:
            image.paste(logo, (margin_x, int(y)), logo)
            y += logo.height + 30
        draw.text((margin_x, y), title, fill=(48, 54, 58), font=font_title)
        title_box = draw.textbbox((margin_x, y), title, font=font_title)
        y = float(title_box[3]) + 12.0
        if subtitle:
            subtitle_lines, sub_line_height, sub_height = _pil_multiline(draw, subtitle, font_subtitle, width=94, line_gap=6)
            draw.multiline_text((margin_x, y), "\n".join(subtitle_lines), fill=(110, 116, 120), font=font_subtitle, spacing=6)
            y += sub_height + 18
        return image, draw, y

    image, draw, y = new_page()
    usable_bottom = page_height - bottom_margin

    def ensure_space(required_height):
        nonlocal image, draw, y
        if y + required_height <= usable_bottom:
            return
        pages.append(image)
        image, draw, y = new_page()

    for heading, lines in sections:
        if str(heading or "").strip().upper() in {"__PAGE_BREAK__", "__PAGEBREAK__"} or (
            isinstance(lines, dict) and str(lines.get("kind") or "").strip().lower() == "page_break"
        ):
            pages.append(image)
            image, draw, y = new_page()
            continue
        heading_box = draw.textbbox((margin_x, y), heading, font=font_section)
        ensure_space((heading_box[3] - heading_box[1]) + 20)
        draw.text((margin_x, y), heading, fill=(60, 67, 72), font=font_section)
        y = heading_box[3] + 12
        for line in lines:
            raw = f"{line[0]}: {line[1]}" if isinstance(line, (list, tuple)) and len(line) == 2 else str(line or "")
            wrapped, line_height, total_height = _pil_multiline(draw, raw, font_body, width=96, line_gap=6)
            ensure_space(total_height + 6)
            draw.multiline_text((margin_x, y), "\n".join(wrapped), fill=(25, 28, 31), font=font_body, spacing=6)
            y += total_height + 6
        y += 14

    for line in footer_lines:
        wrapped, line_height, total_height = _pil_multiline(draw, line, font_footer, width=100, line_gap=5)
        ensure_space(total_height + 4)
        draw.multiline_text((margin_x, y), "\n".join(wrapped), fill=(106, 111, 116), font=font_footer, spacing=5)
        y += total_height + 4

    pages.append(image)
    buffer = BytesIO()
    if len(pages) == 1:
        pages[0].save(buffer, format="PDF", resolution=150.0)
    else:
        pages[0].save(buffer, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def build_company_branded_document_pdf(company, title, subtitle, sections, footer_lines=None, brand_logo_url=None):
    """Documento con la marca de la empresa que lo emite.

    Antes esto miraba si la empresa era Modernia y, sólo en ese caso, usaba el motor
    que sabe dibujar texto; las demás caían al de imagen. Pero de las nueve empresas
    reales sólo dos llevan «modernia» en el nombre, y las inmobiliarias no: sus 86
    inmuebles emitían notas de encargo, hojas de precio y ofertas como un mapa de
    bits de 1240x1754, sin una sola fuente incrustada. El propietario firmaba un
    documento en el que no se puede buscar una cifra, ni copiar una cláusula, ni
    leerlo un lector de pantalla.

    La estética no era de Modernia, era la del producto: logo de la empresa, banda
    de color y título. Cada empresa entra con su propio logo, así que la puerta
    sobraba. `PDF_MOTOR=imagen` sigue devolviendo el aspecto anterior sin desplegar.
    """
    company = company or {}
    logo = brand_logo_url or company.get("logo_url")
    if not logo:
        # Empresas sin logo (Inmovere Fincas, Verifika2): se resuelve aquí el mismo
        # respaldo que aplicaba el motor de imagen, para que no cambie la marca.
        logo = _dep("load_brand_logo")(None, max_width=560)
    return _dep("build_modernia_branded_document_pdf")(
        title,
        subtitle,
        sections,
        footer_lines,
        company=company,
        brand_logo_url=logo,
    )


def _texto_corrido_a_secciones(body_lines):
    """Convierte la lista plana de párrafos en las secciones que espera el vectorial.

    El texto corrido no tiene encabezados: es un contrato, párrafo tras párrafo. Se
    parte por los saltos de página explícitos y cada trozo va como una sección sin
    título, para que el motor respete los cortes que pedía el documento.
    """
    secciones = []
    bloque = []
    columnas = []

    def cierra_columnas():
        nonlocal columnas
        if columnas:
            secciones.append(("", {"kind": "columns", "items": columnas}))
            columnas = []

    def cierra_bloque():
        nonlocal bloque
        if bloque:
            secciones.append(("", bloque))
            bloque = []

    for line in body_lines:
        raw = str(line or "")
        if raw.strip().upper() in {"__PAGE_BREAK__", "__PAGEBREAK__"}:
            cierra_bloque()
            cierra_columnas()
            secciones.append(("", {"kind": "page_break"}))
            continue
        # Las líneas que reparten dos rótulos con una tirada de espacios (el pie de
        # firmas, sobre todo) son una tabla escrita a mano: aquí se recupera como tal,
        # porque al partir por palabras esos espacios se pierden y los dos rótulos
        # acaban pegados.
        celdas = [c.strip() for c in re.split(r" {3,}", raw.strip())]
        if len(celdas) > 1 and all(celdas):
            cierra_bloque()
            columnas.append(celdas)
            continue
        cierra_columnas()
        bloque.append(raw)
    cierra_bloque()
    cierra_columnas()
    return secciones or [("", [])]


def build_branded_text_document_pdf(title, subtitle, body_lines, footer_lines=None, brand_logo_url=None, company=None):
    """Documento de texto corrido (contratos, notas de encargo, cartas).

    La nota de encargo llamaba aquí directamente, saltándose el enrutado por empresa,
    así que se dibujaba como imagen aunque hubiera un motor de texto disponible: tres
    páginas, 617 kB y ni una fuente dentro. Ahora pasa por el mismo motor que el
    resto y sigue habiendo respaldo si algo falla.
    """
    footer_lines = footer_lines or []
    body_lines = body_lines or []

    motor = (os.environ.get("PDF_MOTOR") or "").strip().lower()
    if motor not in ("imagen", "pil", "raster"):
        try:
            return _dep("build_modernia_branded_document_pdf")(
                title,
                subtitle,
                _texto_corrido_a_secciones(body_lines),
                footer_lines,
                company=company or {},
                brand_logo_url=brand_logo_url,
            )
        except Exception as exc:  # pragma: no cover - un documento feo es mejor que ninguno
            print(f"[pdf] texto corrido: motor vectorial falló, se usa el de imagen: {exc}", file=sys.stderr)

    page_width, page_height = 1240, 1754
    margin_x, top_margin, bottom_margin = 90, 70, 90
    logo = _dep("load_brand_logo")(brand_logo_url, max_width=560)
    font_title = _document_font(34, bold=True)
    font_subtitle = _document_font(18, bold=False)
    font_body = _document_font(17, bold=False)
    font_footer = _document_font(15, bold=False)
    pages = []

    def new_page():
        image = Image.new("RGB", (page_width, page_height), "white")
        draw = ImageDraw.Draw(image)
        y: float = float(top_margin)
        if logo:
            image.paste(logo, (margin_x, int(y)), logo)
            y += logo.height + 30
        if title:
            draw.text((margin_x, y), title, fill=(48, 54, 58), font=font_title)
            title_box = draw.textbbox((margin_x, y), title, font=font_title)
            y = float(title_box[3]) + 12.0
        if subtitle:
            subtitle_lines, sub_line_height, sub_height = _pil_multiline(draw, subtitle, font_subtitle, width=94, line_gap=6)
            draw.multiline_text((margin_x, y), "\n".join(subtitle_lines), fill=(110, 116, 120), font=font_subtitle, spacing=6)
            y += sub_height + 18
        return image, draw, y

    image, draw, y = new_page()
    usable_bottom = page_height - bottom_margin

    def ensure_space(required_height):
        nonlocal image, draw, y
        if y + required_height <= usable_bottom:
            return
        pages.append(image)
        image, draw, y = new_page()

    for line in body_lines:
        if str(line or "").strip().upper() in {"__PAGE_BREAK__", "__PAGEBREAK__"}:
            pages.append(image)
            image, draw, y = new_page()
            continue
        raw = str(line or "")
        if not raw.strip():
            ensure_space(24)
            y += 18
            continue
        wrapped, line_height, total_height = _pil_multiline(draw, raw, font_body, width=96, line_gap=6)
        ensure_space(total_height + 8)
        draw.multiline_text((margin_x, y), "\n".join(wrapped), fill=(25, 28, 31), font=font_body, spacing=6)
        y += total_height + 8

    for line in footer_lines:
        wrapped, line_height, total_height = _pil_multiline(draw, str(line or ""), font_footer, width=100, line_gap=5)
        ensure_space(total_height + 4)
        draw.multiline_text((margin_x, y), "\n".join(wrapped), fill=(106, 111, 116), font=font_footer, spacing=5)
        y += total_height + 4

    pages.append(image)
    buffer = BytesIO()
    if len(pages) == 1:
        pages[0].save(buffer, format="PDF", resolution=150.0)
    else:
        pages[0].save(buffer, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def build_company_branded_text_document_pdf(company, title, subtitle, body_lines, footer_lines=None, brand_logo_url=None):
    company = company or {}
    if _company_uses_modernia_pdf_brand(company):
        sections = [("Contenido", body_lines or [])]
        return _dep("build_modernia_branded_document_pdf")(
            title,
            subtitle,
            sections,
            footer_lines,
            company=company,
            brand_logo_url=brand_logo_url,
        )
    return _dep("build_branded_text_document_pdf")(
        title,
        subtitle,
        body_lines,
        footer_lines=footer_lines,
        brand_logo_url=brand_logo_url or company.get("logo_url"),
    )


def _legacy_build_modernia_branded_document_pdf(title, subtitle, sections, footer_lines=None, company=None, brand_logo_url=None):
    """
    Variante de `build_branded_document_pdf` con estética Modernia (logo + banda dorada con título).
    Se usa para documentos generados (no basados en plantilla) para mantener consistencia visual.
    """
    footer_lines = footer_lines or []
    company = company or {}

    page_width, page_height = 1240, 1754
    margin_x, top_margin, bottom_margin = 90, 60, 90
    content_width = page_width - (margin_x * 2)
    logo_url = brand_logo_url or company.get("logo_url") or "/assets/grupo_modernia_logo.png"
    # El logo del template Modernia es relativamente compacto; limitamos ancho para evitar solapes.
    logo = load_brand_logo(logo_url, max_width=340)

    # Paleta aproximada del template Modernia.
    gold = (200, 162, 74)
    ink = (25, 28, 31)
    muted = (110, 116, 120)
    bg = "white"

    font_title = _document_font(30, bold=True)
    font_subtitle = _document_font(16, bold=False)
    font_section = _document_font(22, bold=True)
    font_body = _document_font(17, bold=False)
    font_kpi_value = _document_font(26, bold=True)
    font_kpi_label = _document_font(14, bold=False)
    font_feature_eyebrow = _document_font(13, bold=True)
    font_feature_title = _document_font(28, bold=True)
    font_feature_subtitle = _document_font(16, bold=False)
    font_feature_note = _document_font(14, bold=False)
    font_footer = _document_font(15, bold=False)
    font_header_small = _document_font(14, bold=False)

    company_head = str(company.get("razon_social") or company.get("nombre") or "").strip()
    company_nif = str(company.get("nif") or company.get("cif") or "").strip()
    company_addr = str(company.get("direccion_fiscal") or company.get("direccion") or "").strip()
    company_tel = str(company.get("telefono") or "").strip()
    company_meta_parts = []
    if company_head:
        company_meta_parts.append(company_head)
    if company_nif:
        company_meta_parts.append(f"CIF: {company_nif}")
    if company_addr:
        company_meta_parts.append(company_addr)
    if company_tel:
        company_meta_parts.append(f"Tlf: {company_tel}")

    pages = []

    def _draw_card_box(
        draw_obj,
        box,
        *,
        outline=None,
        fill=None,
        width=2,
        radius=18,
        shadow=False,
        shadow_offset=4,
        shadow_fill=(234, 236, 239),
    ):
        if shadow:
            sx0, sy0, sx1, sy1 = box[0] + shadow_offset, box[1] + shadow_offset, box[2] + shadow_offset, box[3] + shadow_offset
            try:
                draw_obj.rounded_rectangle((sx0, sy0, sx1, sy1), radius=radius, outline=None, fill=shadow_fill, width=1)
            except Exception:
                draw_obj.rectangle((sx0, sy0, sx1, sy1), outline=None, fill=shadow_fill, width=1)
        try:
            draw_obj.rounded_rectangle(box, radius=radius, outline=outline, fill=fill, width=width)
        except Exception:
            draw_obj.rectangle(box, outline=outline, fill=fill, width=width)

    def new_page():
        image = Image.new("RGB", (page_width, page_height), bg)
        draw = ImageDraw.Draw(image)
        y = top_margin

        # Header: logo + meta derecha
        logo_bottom = y
        if logo:
            image.paste(logo, (margin_x, y), logo)
            logo_bottom = y + logo.height
        if company_meta_parts:
            right_x = page_width - margin_x
            meta_text = " · ".join([p for p in company_meta_parts if p])
            draw.text((right_x, y + 12), meta_text, fill=muted, font=font_header_small, anchor="ra")

        y = max(logo_bottom + 26, y + 110)

        # Banda título (dorado) en ancho completo (sin remate en otro color).
        band_h = 62
        draw.rectangle((0, y, page_width, y + band_h), fill=gold)
        draw.text((page_width / 2, y + 16), str(title or "").upper(), fill="white", font=font_title, anchor="mm")

        y += band_h + 34

        if subtitle:
            subtitle_lines, _sub_line_height, sub_height = _pil_multiline(draw, subtitle, font_subtitle, width=96, line_gap=6)
            draw.multiline_text((margin_x, y), "\n".join(subtitle_lines), fill=muted, font=font_subtitle, spacing=6)
            y += sub_height + 18

        return image, draw, y

    image, draw, y = new_page()
    usable_bottom = page_height - bottom_margin

    def ensure_space(required_height):
        nonlocal image, draw, y
        if y + required_height <= usable_bottom:
            return
        pages.append(image)
        image, draw, y = new_page()

    def draw_kpi_row(draw_obj, x0, y0, box_w, value, label):
        box = (x0, y0, x0 + box_w, y0 + 112)
        _draw_card_box(draw_obj, box, outline=(210, 214, 219), fill=(255, 255, 255), width=2, radius=18, shadow=True)
        draw_obj.text((x0 + 18, y0 + 18), str(value or "").strip(), fill=ink, font=font_kpi_value)
        draw_obj.text((x0 + 18, y0 + 72), str(label or "").strip(), fill=muted, font=font_kpi_label)

    def draw_feature_panel(draw_obj, x0, y0, box_w, title_text, subtitle_text, note_text):
        box_h = 204
        box = (x0, y0, x0 + box_w, y0 + box_h)
        _draw_card_box(draw_obj, box, outline=(220, 223, 227), fill=(255, 255, 255), width=2, radius=20, shadow=True, shadow_offset=5)
        draw_obj.text((x0 + 18, y0 + 20), str("VERIFIKA²" if not title_text else title_text).strip(), fill=gold, font=font_feature_eyebrow)
        draw_obj.text((x0 + 18, y0 + 54), str(subtitle_text or "").strip(), fill=ink, font=font_feature_title)
        if note_text:
            wrapped, _line_height, total_height = _pil_multiline(draw_obj, note_text, font_feature_note, width=max(24, int(box_w / 10)), line_gap=4)
            draw_obj.multiline_text((x0 + 18, y0 + 112), "\n".join(wrapped), fill=muted, font=font_feature_note, spacing=4)
        return box_h

    def draw_section_text(draw_obj, x0, y0, title_text, lines, body_font=font_body):
        y_cursor = y0
        if title_text:
            draw_obj.text((x0, y_cursor), str(title_text).strip(), fill=ink, font=font_section)
            title_box = draw_obj.textbbox((x0, y_cursor), str(title_text).strip(), font=font_section)
            y_cursor = title_box[3] + 10
        for line in lines or []:
            if isinstance(line, (list, tuple)) and len(line) == 2:
                raw = f"{line[0]}: {line[1]}"
            else:
                raw = str(line or "")
            wrapped, _line_height, total_height = _pil_multiline(draw_obj, raw, body_font, width=94, line_gap=6)
            draw_obj.multiline_text((x0, y_cursor), "\n".join(wrapped), fill=ink, font=body_font, spacing=6)
            y_cursor += total_height + 8
        return y_cursor

    # Portada resumida si el documento aporta títulos/metadata sencillos.
    title_box = (margin_x, y, page_width - margin_x, y + 250)
    _draw_card_box(draw, title_box, outline=(226, 229, 233), fill=(255, 255, 255), width=2, radius=24, shadow=True, shadow_offset=8)
    draw.text((margin_x + 24, y + 26), str(title or "").strip().upper(), fill=ink, font=font_feature_title)
    if subtitle:
        subtitle_lines, _line_height, total_height = _pil_multiline(draw, subtitle, font_feature_subtitle, width=92, line_gap=6)
        draw.multiline_text((margin_x + 24, y + 76), "\n".join(subtitle_lines), fill=muted, font=font_feature_subtitle, spacing=6)
    if company_head or company_nif or company_addr or company_tel:
        company_lines = [part for part in [company_head, company_nif and f"CIF {company_nif}", company_addr, company_tel and f"Tlf {company_tel}"] if part]
        draw_section_text(draw, margin_x + 24, y + 150, "", company_lines, body_font=font_feature_note)
    y += 276

    # Tarjetas KPI iniciales.
    if sections:
        first_section_title = str(sections[0][0] or "").strip()
    else:
        first_section_title = ""
    draw_feature_panel(
        draw,
        margin_x,
        y,
        content_width,
        first_section_title or "Documento",
        str(title or "").strip().title() if title else "Documento",
        str(subtitle or "").strip(),
    )
    y += 224

    for heading, lines in sections:
        if str(heading or "").strip().upper() in {"__PAGE_BREAK__", "__PAGEBREAK__"} or (
            isinstance(lines, dict) and str(lines.get("kind") or "").strip().lower() == "page_break"
        ):
            pages.append(image)
            image, draw, y = new_page()
            continue
        ensure_space(32)
        y = draw_section_text(draw, margin_x, y, heading, lines, body_font=font_body)
        y += 12

    for line in footer_lines:
        wrapped, _line_height, total_height = _pil_multiline(draw, line, font_footer, width=100, line_gap=5)
        ensure_space(total_height + 4)
        draw.multiline_text((margin_x, y), "\n".join(wrapped), fill=muted, font=font_footer, spacing=5)
        y += total_height + 4

    pages.append(image)
    buffer = BytesIO()
    if len(pages) == 1:
        pages[0].save(buffer, format="PDF", resolution=150.0)
    else:
        pages[0].save(buffer, format="PDF", resolution=150.0, save_all=True, append_images=pages[1:])
    return buffer.getvalue()


def build_modernia_branded_document_pdf(title, subtitle, sections, footer_lines=None, company=None, brand_logo_url=None):
    try:
        from . import server as runtime_server
    except ImportError:  # pragma: no cover
        import server as runtime_server
    return runtime_server.build_modernia_branded_document_pdf(
        title,
        subtitle,
        sections,
        footer_lines,
        company=company,
        brand_logo_url=brand_logo_url,
    )


def build_signature_evidence_pdf(request_row, evidence):
    row = dict(request_row)
    evidence = evidence or {}
    if rl_canvas is None or rl_colors is None:
        body = [
            f"Solicitud: {row.get('id') or '-'}",
            f"Documento: {row.get('doc_nombre') or '-'}",
            f"URL documento: {row.get('doc_url') or '-'}",
            f"Hash SHA-256 documento: {row.get('document_sha256') or evidence.get('document_sha256') or '-'}",
            f"Finalidad: {row.get('purpose') or '-'}",
            f"Firmante previsto: {row.get('signer_nombre') or '-'} · {row.get('signer_nif') or '-'}",
            f"Firmado como: {row.get('signed_name') or evidence.get('signed_name') or '-'} · {row.get('signed_nif') or evidence.get('signed_nif') or '-'}",
            f"Fecha envío: {row.get('sent_at') or '-'}",
            f"Fecha apertura: {row.get('opened_at') or '-'}",
            f"Fecha firma: {row.get('signed_at') or evidence.get('signed_at') or '-'}",
            f"OTP requerido: {'Sí' if int(row.get('otp_required') or 0) else 'No'}",
            f"IP firma: {evidence.get('ip') or '-'}",
            f"Navegador: {evidence.get('user_agent') or '-'}",
            f"Texto aceptado: {row.get('acceptance_text') or evidence.get('acceptance_text') or '-'}",
            "Resultado: Documento aceptado y firmado electrónicamente dentro del CRM.",
        ]
        return _dep("build_branded_text_document_pdf")(
            "JUSTIFICANTE DE FIRMA ELECTRÓNICA INTERNA",
            "Evidencias técnicas registradas por el CRM Verifika2.",
            body,
            ["Este justificante acredita trazabilidad interna; no sustituye por sí solo a un prestador cualificado eIDAS."],
        )
    buf = BytesIO()
    w, h = (595.27, 841.89)
    c = rl_canvas.Canvas(buf, pagesize=(w, h))
    primary = rl_colors.HexColor("#0B1D33")
    accent = rl_colors.HexColor("#C8A24A")
    muted = rl_colors.HexColor("#6B7280")
    ink = rl_colors.HexColor("#111827")
    c.setFillColor(primary)
    c.rect(0, h - 100, w, 100, stroke=0, fill=1)
    c.setFillColor(rl_colors.white)
    c.setFont(PDF_FONT_BOLD, 18)
    c.drawString(42, h - 45, "JUSTIFICANTE DE FIRMA ELECTRÓNICA INTERNA")
    c.setFont(PDF_FONT_REGULAR, 9)
    c.drawString(42, h - 68, "Evidencias técnicas registradas por el CRM Verifika2.")
    c.setFillColor(accent)
    c.rect(42, h - 88, 160, 5, stroke=0, fill=1)

    y = h - 132

    def line(label, value):
        nonlocal y
        if y < 70:
            c.showPage()
            y = h - 52
        c.setFillColor(muted)
        c.setFont(PDF_FONT_BOLD, 8)
        c.drawString(42, y, str(label or "").upper())
        c.setFillColor(ink)
        c.setFont(PDF_FONT_REGULAR, 10)
        text = str(value or "-")
        for part in textwrap.wrap(text, width=92) or ["-"]:
            c.drawString(178, y, part)
            y -= 14
        y -= 4

    line("Solicitud", row.get("id"))
    line("Documento", row.get("doc_nombre"))
    line("URL documento", row.get("doc_url"))
    line("Hash SHA-256 documento", row.get("document_sha256") or evidence.get("document_sha256"))
    line("Finalidad", row.get("purpose"))
    line("Firmante previsto", f"{row.get('signer_nombre') or '-'} · {row.get('signer_nif') or '-'}")
    line("Firmado como", f"{row.get('signed_name') or evidence.get('signed_name') or '-'} · {row.get('signed_nif') or evidence.get('signed_nif') or '-'}")
    line("Fecha envío", row.get("sent_at"))
    line("Fecha apertura", row.get("opened_at"))
    line("Fecha firma", row.get("signed_at") or evidence.get("signed_at"))
    line("OTP requerido", "Sí" if int(row.get("otp_required") or 0) else "No")
    line("IP firma", evidence.get("ip"))
    line("Navegador", evidence.get("user_agent"))
    line("Texto aceptado", row.get("acceptance_text") or evidence.get("acceptance_text"))
    line("Resultado", "Documento aceptado y firmado electrónicamente dentro del CRM.")
    c.setFillColor(muted)
    c.setFont(PDF_FONT_REGULAR, 8)
    c.drawString(42, 38, "Este justificante acredita trazabilidad interna; no sustituye por sí solo a un prestador cualificado eIDAS.")
    c.save()
    return buf.getvalue()


configure_dependencies(
    load_brand_logo=load_brand_logo,
    build_branded_document_pdf=lambda *args, **kwargs: build_branded_document_pdf(*args, **kwargs),
    build_branded_text_document_pdf=lambda *args, **kwargs: build_branded_text_document_pdf(*args, **kwargs),
    build_modernia_branded_document_pdf=lambda *args, **kwargs: build_modernia_branded_document_pdf(*args, **kwargs),
)
