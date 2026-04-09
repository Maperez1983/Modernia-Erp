#!/usr/bin/env python3
"""
Genera un PDF (manual) del CRM Inmobiliaria, incluyendo capturas reales del UI.

Cómo funciona:
- Levanta el servidor del CRM y abre /manual/inmobiliaria?page=N (página sin auth).
- Usa Google Chrome headless para sacar capturas PNG.
- Compone un PDF multipágina con texto + capturas.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import time


CHROME_BIN = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _fit_image(img, max_w, max_h):
    from PIL import Image

    w, h = img.size
    if w <= 0 or h <= 0:
        return img
    ratio = min(float(max_w) / float(w), float(max_h) / float(h))
    ratio = min(1.0, ratio)
    nw, nh = int(w * ratio), int(h * ratio)
    if nw <= 0 or nh <= 0:
        return img
    if (nw, nh) == (w, h):
        return img
    return img.resize((nw, nh), Image.LANCZOS)


def _chrome_screenshot(url, out_png, window=(1600, 1000), scale=2, budget_ms=2400):
    out_png = str(Path(out_png).expanduser().resolve())
    w, h = int(window[0]), int(window[1])
    args = [
        CHROME_BIN,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--force-device-scale-factor={float(scale)}",
        f"--window-size={w},{h}",
        f"--virtual-time-budget={int(budget_ms)}",
        f"--screenshot={out_png}",
        url,
    ]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_png


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base-url",
        default=os.environ.get("CRM_BASE_URL", "") or "http://127.0.0.1:8010",
        help="Base URL del servidor del CRM (por defecto http://127.0.0.1:8010)",
    )
    ap.add_argument(
        "--out",
        default="/tmp/manual_crm_inmobiliaria_verifika2.pdf",
        help="Ruta de salida del PDF",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from web import server

    base_url = str(args.base_url).rstrip("/")
    pages = [
        ("Paso 1 · Resumen", f"{base_url}/manual/inmobiliaria?page=1"),
        ("Paso 2 · Pipeline", f"{base_url}/manual/inmobiliaria?page=2"),
        ("Paso 3 · Inmuebles", f"{base_url}/manual/inmobiliaria?page=3"),
        ("Paso 4 · Ficha inmueble", f"{base_url}/manual/inmobiliaria?page=4"),
        ("Paso 5 · Demandas", f"{base_url}/manual/inmobiliaria?page=5"),
        ("Paso 6 · PDFs", f"{base_url}/manual/inmobiliaria?page=6"),
    ]

    tmp_dir = Path("/tmp") / f"manual_inmo_{int(time.time())}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Capturas PNG.
    screenshots = []
    for idx, (label, url) in enumerate(pages, start=1):
        out_png = tmp_dir / f"screen_{idx:02d}.png"
        try:
            _chrome_screenshot(url, out_png, window=(1600, 980), scale=2, budget_ms=2600)
            screenshots.append((label, str(out_png)))
        except Exception:
            # Si falla Chrome/servidor, seguimos sin capturas.
            screenshots.append((label, ""))

    # Composición a PDF con Pillow.
    from PIL import Image, ImageDraw

    page_w, page_h = 1240, 1754
    margin_x, top_margin, bottom_margin = 90, 70, 90
    content_w = page_w - (margin_x * 2)

    logo = server._load_asset_logo("verifika2/verifika2_wordmark_check_green_transparent.png", max_width=520)
    font_title = server._document_font(34, bold=True)
    font_subtitle = server._document_font(18, bold=False)
    font_h2 = server._document_font(22, bold=True)
    font_body = server._document_font(17, bold=False)
    font_footer = server._document_font(14, bold=False)

    def new_page(title, subtitle):
        img = Image.new("RGB", (page_w, page_h), "white")
        draw = ImageDraw.Draw(img)
        y = top_margin
        if logo:
            img.paste(logo, (margin_x, y), logo)
            y += logo.height + 22
        draw.text((margin_x, y), title, fill=(48, 54, 58), font=font_title)
        box = draw.textbbox((margin_x, y), title, font=font_title)
        y = box[3] + 10
        if subtitle:
            lines, line_h, total_h = server._pil_multiline(draw, subtitle, font_subtitle, width=96, line_gap=6)
            draw.multiline_text((margin_x, y), "\n".join(lines), fill=(110, 116, 120), font=font_subtitle, spacing=6)
            y += total_h + 10
        return img, draw, y

    pages_out = []

    cover_title = "MANUAL · CRM INMOBILIARIA"
    cover_sub = (
        "Guia operativa del modulo Inmobiliaria dentro de Verifika².\n"
        "Incluye capturas (modo documentación) y reglas de funcionamiento recomendadas.\n"
        "Abril 2026."
    )
    img, draw, y = new_page(cover_title, cover_sub)
    intro = [
        "Este manual se estructura como un flujo de trabajo:",
        "  1) Revisar Resumen y convertir KPIs en acciones.",
        "  2) Gestionar Pipeline por etapa (Noticia, Encargo, Propuesta, ...).",
        "  3) Trabajar expediente (propietarios, documentos, checklist).",
        "  4) Gestionar Demandas y Matching.",
        "  5) Registrar Visitas y seguimiento (Agenda).",
        "  6) Generar PDFs cuando aplica (solo Encargo).",
        "",
        "Si algo no coincide con lo descrito, registra pasos de reproducción (usuario, empresa, inmueble/demanda).",
    ]
    for line in intro:
        lines, line_h, total_h = server._pil_multiline(draw, line, font_body, width=100, line_gap=6)
        draw.multiline_text((margin_x, y), "\n".join(lines), fill=(25, 28, 31), font=font_body, spacing=6)
        y += total_h + 4
    pages_out.append(img)

    for idx, (label, png_path) in enumerate(screenshots, start=1):
        img, draw, y = new_page(label, "Captura del UI (ejemplo) usando el estilo real del CRM.")
        if png_path:
            try:
                shot = Image.open(png_path).convert("RGB")
                shot = _fit_image(shot, content_w, page_h - y - bottom_margin - 120)
                x = margin_x + int((content_w - shot.width) / 2)
                img.paste(shot, (x, y))
                y += shot.height + 16
            except Exception:
                pass

        bullets = {
            1: [
                "Revisar avisos, visitas del dia y propuestas sin respuesta.",
                "Crear acciones (agenda) desde pendientes para que el pipeline sea accionable.",
                "KPI esperado: todo lo importante debe tener proxima accion y responsable.",
            ],
            2: [
                "Pipeline refleja etapa comercial. Mueve por etapa desde la ficha (Estado).",
                "Recomendado: no pasar a Encargo sin documentacion minima y propietarios validados.",
                "Error tipico: estados inconsistentes entre captacion e inmueble (botones desaparecen).",
            ],
            3: [
                "Listado: busca por direccion, ref catastral o zona.",
                "Esperado: abrir ficha siempre funciona; no debe volver a Home por routing.",
                "Calidad de datos: m2/hab/banos/precio deben estar para matching fiable.",
            ],
            4: [
                "Expediente: datos + propietarios + compradores + docs + checklist + auditoria.",
                "Autosave: cambios deben guardar con feedback (sin perderse).",
                "Mapa: completa lat/lon para ubicacion; ref catastral para catastro/documentos.",
            ],
            5: [
                "Demandas: zona, presupuesto, requisitos (m2/hab/banos), fase y estado.",
                "Matching: debe filtrar por empresa y aplicar reglas basicas; revisar campos vacios.",
                "Trabajo diario: convertir matching en visitas y acciones con fecha.",
            ],
            6: [
                "PDFs solo aparecen en Encargo: hoja visita, ficha venta, nota precio, nota encargo, DIA alquiler.",
                "Esperado: al generar, se guarda en Docs y si ya existe se reemplaza cuando procede (sin duplicar).",
                "Error tipico: estado mal escrito (no exactamente 'Encargo') oculta botones.",
            ],
        }.get(idx, [])

        if bullets:
            draw.text((margin_x, y), "Qué hacer / qué esperar", fill=(60, 67, 72), font=font_h2)
            box = draw.textbbox((margin_x, y), "Qué hacer / qué esperar", font=font_h2)
            y = box[3] + 10
            for b in bullets:
                text = f"• {b}"
                lines, line_h, total_h = server._pil_multiline(draw, text, font_body, width=100, line_gap=6)
                draw.multiline_text((margin_x, y), "\n".join(lines), fill=(25, 28, 31), font=font_body, spacing=6)
                y += total_h + 4

        footer = "Verifika² · Manual CRM Inmobiliaria · Capturas en /manual/inmobiliaria"
        draw.text((margin_x, page_h - bottom_margin + 26), footer, fill=(106, 111, 116), font=font_footer)
        pages_out.append(img)

    out_path = Path(args.out).expanduser().resolve()
    if len(pages_out) == 1:
        pages_out[0].save(out_path, format="PDF", resolution=150.0)
    else:
        pages_out[0].save(out_path, format="PDF", resolution=150.0, save_all=True, append_images=pages_out[1:])
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
