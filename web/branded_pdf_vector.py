#!/usr/bin/env python3
from __future__ import annotations

"""Documentos con marca, dibujados como texto en vez de como fotografía.

El motor de siempre (`build_modernia_branded_document_pdf`) compone cada página
con PIL y la incrusta como JPEG a 150 ppp. Funciona y se ve bien, pero:

  - el declarativo anual de hipotecas ocupa 10 MB y el listado 15 MB, a razón de
    156 kB por página;
  - no hay una sola fuente incrustada, así que no se puede buscar ni copiar una
    cifra, y un lector de pantalla no lee nada;
  - la tipografía del producto no llega: no hay texto que tipografiar.

Aquí se dibuja lo mismo con reportlab, en vectorial y con IBM Plex. Se respeta el
mismo contrato de `sections` —líneas sueltas, `kpi_cards`, `feature_card`,
`split_bar`, `waterfall` y `page_break`— para poder sustituir el motor sin tocar
a quien lo llama.

Las medidas van en puntos PDF (A4 = 595 x 842) en lugar de los píxeles del motor
de imagen, y las proporciones se mantienen dividiendo por 1240/595 ≈ 2,084.
"""

from io import BytesIO

try:  # como paquete o como script suelto, igual que el resto del proyecto
    from .pdf_fonts import PDF_FONT_BOLD, PDF_FONT_REGULAR
except ImportError:
    from pdf_fonts import PDF_FONT_BOLD, PDF_FONT_REGULAR

A4_ANCHO, A4_ALTO = 595.28, 841.89
MARGEN_X = 43.0
MARGEN_SUP = 29.0
MARGEN_INF = 43.0

VERDE = (22 / 255, 163 / 255, 74 / 255)
OLIVA = (116 / 255, 125 / 255, 106 / 255)
TINTA = (25 / 255, 28 / 255, 31 / 255)
APAGADO = (110 / 255, 116 / 255, 120 / 255)
LINEA = (222 / 255, 226 / 255, 230 / 255)
FONDO_SUAVE = (246 / 255, 248 / 255, 247 / 255)
#: Relleno de las tarjetas destacadas: el mismo crema del motor de imagen.
CREMA = (252 / 255, 248 / 255, 235 / 255)


def _texto(valor):
    return "" if valor is None else str(valor)


def _partir(c, texto, fuente, tamano, ancho_max):
    """Parte un texto en líneas que quepan en `ancho_max`."""
    palabras = _texto(texto).split()
    if not palabras:
        return [""]
    lineas, actual = [], palabras[0]
    for palabra in palabras[1:]:
        prueba = f"{actual} {palabra}"
        if c.stringWidth(prueba, fuente, tamano) <= ancho_max:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    lineas.append(actual)
    return lineas


def _logo_png(url, ancho_max, cache=None):
    """Devuelve (ImageReader, ancho, alto) del logo, o None si no se puede cargar.

    Se cachea por documento y se devuelve **el mismo** `ImageReader`: reportlab
    incrusta una sola copia cuando reconoce la misma instancia. Creando uno nuevo
    en cada página, el declarativo de 67 páginas se llevaba 266 imágenes dentro y
    pesaba 3,2 MB.
    """
    if not url:
        return None
    clave = (str(url), int(ancho_max))
    if cache is not None and clave in cache:
        return cache[clave]
    resultado = None
    try:
        try:
            from .server import _load_brand_logo
        except ImportError:
            from server import _load_brand_logo
        from reportlab.lib.utils import ImageReader

        imagen = _load_brand_logo(url, max_width=int(ancho_max))
        if imagen is not None:
            if imagen.mode not in ("RGB", "RGBA"):
                imagen = imagen.convert("RGBA")
            buf = BytesIO()
            imagen.save(buf, format="PNG")
            buf.seek(0)
            resultado = (ImageReader(buf), imagen.width, imagen.height)
    except Exception:
        resultado = None
    if cache is not None:
        cache[clave] = resultado
    return resultado


def _pinta_logo(c, datos, x, y, alto_max):
    """Dibuja el logo respetando su proporción. Devuelve el ancho ocupado."""
    if not datos:
        return 0.0
    lector, ancho, alto = datos
    if not alto:
        return 0.0
    escala = min(1.0, alto_max / float(alto))
    w, h = ancho * escala, alto * escala
    try:
        c.drawImage(lector, x, y, width=w, height=h, mask="auto")
    except Exception:
        return 0.0
    return w


def _pildora(c, texto, x, y, *, alto=11.0, fuente=PDF_FONT_REGULAR, tamano=6.6,
             color_texto=OLIVA, borde=LINEA, relleno=None):
    """Etiqueta redondeada. Devuelve el ancho que ha ocupado."""
    etiqueta = _texto(texto).strip()
    if not etiqueta:
        return 0.0
    ancho = c.stringWidth(etiqueta, fuente, tamano) + 12
    if relleno:
        c.setFillColorRGB(*relleno)
    else:
        c.setFillColorRGB(1, 1, 1)
    c.setStrokeColorRGB(*borde)
    c.setLineWidth(0.5)
    c.roundRect(x, y, ancho, alto, alto / 2, stroke=1, fill=1)
    c.setFillColorRGB(*color_texto)
    c.setFont(fuente, tamano)
    c.drawString(x + 6, y + (alto - tamano) / 2 + 0.6, etiqueta)
    return ancho


def _es_destacado(item):
    """`accent` marca los datos que el documento quiere que mires primero."""
    valor = item.get("accent") if isinstance(item, dict) else None
    if isinstance(valor, str):
        return valor.strip().lower() not in ("", "0", "false", "no")
    return bool(valor)


class _Lienzo:
    """Envoltorio del canvas que lleva la cuenta del hueco que queda."""

    def __init__(self, c, cabecera):
        self.c = c
        self.cabecera = cabecera
        self.y = 0.0
        self.pagina = 0
        self.nueva_pagina()

    def nueva_pagina(self):
        if self.pagina:
            self.c.showPage()
        self.pagina += 1
        self.y = self.cabecera(self.c, self.pagina)

    def sitio(self, alto):
        if self.y - alto < MARGEN_INF:
            self.nueva_pagina()

    def linea_texto(self, texto, fuente=PDF_FONT_REGULAR, tamano=9.5, color=TINTA, sangria=0.0, interlineado=None):
        interlineado = interlineado or tamano + 4
        ancho = A4_ANCHO - (MARGEN_X * 2) - sangria
        for trozo in _partir(self.c, texto, fuente, tamano, ancho):
            self.sitio(interlineado)
            self.c.setFillColorRGB(*color)
            self.c.setFont(fuente, tamano)
            self.c.drawString(MARGEN_X + sangria, self.y - tamano, trozo)
            self.y -= interlineado


def _dibuja_cabecera(titulo, subtitulo, meta_empresa, logo_marca=None):
    def cabecera(c, pagina):
        y = A4_ALTO - MARGEN_SUP
        if pagina == 1:
            if logo_marca:
                # El logo va sobre blanco, encima de la banda: sobre el verde de
                # marca perdería contraste y se vería sucio.
                _pinta_logo(c, logo_marca, MARGEN_X, y - 52, 50)
                y -= 64
            c.setFillColorRGB(*VERDE)
            c.rect(0, y - 40, A4_ANCHO, 40, stroke=0, fill=1)
            c.setFillColorRGB(1, 1, 1)
            c.setFont(PDF_FONT_BOLD, 15)
            c.drawString(MARGEN_X, y - 26, _texto(titulo)[:80])
            if subtitulo:
                c.setFont(PDF_FONT_REGULAR, 9)
                c.drawRightString(A4_ANCHO - MARGEN_X, y - 26, _texto(subtitulo)[:70])
            y -= 56
            if meta_empresa:
                c.setFillColorRGB(*APAGADO)
                c.setFont(PDF_FONT_REGULAR, 7.5)
                c.drawString(MARGEN_X, y, _texto(meta_empresa)[:150])
                y -= 15
        else:
            if logo_marca:
                _pinta_logo(c, logo_marca, MARGEN_X, y - 20, 16)
            c.setFillColorRGB(*APAGADO)
            c.setFont(PDF_FONT_REGULAR, 7.5)
            c.drawRightString(A4_ANCHO - MARGEN_X, y - 10, _texto(titulo)[:80])
            c.setStrokeColorRGB(*LINEA)
            c.setLineWidth(0.5)
            c.line(MARGEN_X, y - 26, A4_ANCHO - MARGEN_X, y - 26)
            y -= 42
        return y

    return cabecera


def _tarjetas_kpi(lienzo, bloque):
    items = [i for i in (bloque.get("items") or []) if isinstance(i, dict)]
    if not items:
        return
    columnas = max(1, min(int(bloque.get("columns") or 3), 4))
    ancho_util = A4_ANCHO - (MARGEN_X * 2)
    hueco = 8.0
    ancho = (ancho_util - hueco * (columnas - 1)) / columnas
    alto = 44.0
    for arranque in range(0, len(items), columnas):
        fila = items[arranque: arranque + columnas]
        lienzo.sitio(alto + 8)
        base = lienzo.y - alto
        for idx, item in enumerate(fila):
            x = MARGEN_X + idx * (ancho + hueco)
            # `accent` no es decoración: marca los datos que hay que mirar primero.
            # El motor de imagen los pinta en crema con borde verde y aquí se hacía
            # lo mismo para todos, que era perder la jerarquía del documento.
            destacado = _es_destacado(item)
            lienzo.c.setFillColorRGB(*(CREMA if destacado else FONDO_SUAVE))
            lienzo.c.setStrokeColorRGB(*(VERDE if destacado else LINEA))
            lienzo.c.setLineWidth(1.1 if destacado else 0.6)
            lienzo.c.roundRect(x, base, ancho, alto, 4, stroke=1, fill=1)
            lienzo.c.setFillColorRGB(*APAGADO)
            lienzo.c.setFont(PDF_FONT_REGULAR, 7)
            lienzo.c.drawString(x + 8, base + alto - 13, _texto(item.get("label"))[:38].upper())
            lienzo.c.setFillColorRGB(*TINTA)
            lienzo.c.setFont(PDF_FONT_BOLD, 13)
            lienzo.c.drawString(x + 8, base + 12, _texto(item.get("value"))[:24])
        lienzo.y = base - 10


def _ficha_destacada(lienzo, bloque, cache=None):
    """La tarjeta grande: logo del banco, badge de estado, chips y datos."""
    titulo = _texto(bloque.get("title"))
    subtitulo = _texto(bloque.get("subtitle"))
    nota = _texto(bloque.get("note"))
    badge = _texto(bloque.get("badge")).strip()
    chips = [_texto(x).strip() for x in (bloque.get("chips") or []) if _texto(x).strip()]
    items = [i for i in (bloque.get("items") or []) if isinstance(i, dict)]

    logo = _logo_png(bloque.get("logo_url"), 80, cache)
    iniciales = _texto(bloque.get("logo_initials")).strip()
    alto_marca = 30.0 if (logo or iniciales) else 0.0

    alto = 26 + alto_marca + (13 if subtitulo else 0) + (22 if chips else 0) + (13 * len(items)) + (14 if nota else 0)
    lienzo.sitio(alto + 10)
    base = lienzo.y - alto
    ancho_util = A4_ANCHO - MARGEN_X * 2
    lienzo.c.setFillColorRGB(*FONDO_SUAVE)
    lienzo.c.setStrokeColorRGB(*LINEA)
    lienzo.c.setLineWidth(0.6)
    lienzo.c.roundRect(MARGEN_X, base, ancho_util, alto, 5, stroke=1, fill=1)

    y = base + alto - 13
    if bloque.get("eyebrow"):
        lienzo.c.setFillColorRGB(*VERDE)
        lienzo.c.setFont(PDF_FONT_BOLD, 6.6)
        lienzo.c.drawString(MARGEN_X + 10, y, _texto(bloque.get("eyebrow"))[:50].upper())
    if badge:
        ancho_badge = lienzo.c.stringWidth(badge.upper(), PDF_FONT_BOLD, 6.6) + 12
        _pildora(lienzo.c, badge.upper(), A4_ANCHO - MARGEN_X - 10 - ancho_badge, y - 3,
                 fuente=PDF_FONT_BOLD, tamano=6.6, color_texto=VERDE, borde=VERDE)
    y -= 12

    if alto_marca:
        if logo:
            _pinta_logo(lienzo.c, logo, MARGEN_X + 10, y - alto_marca + 6, alto_marca - 8)
        else:
            lienzo.c.setFillColorRGB(*VERDE)
            lienzo.c.roundRect(MARGEN_X + 10, y - alto_marca + 6, 34, alto_marca - 8, 3, stroke=0, fill=1)
            lienzo.c.setFillColorRGB(1, 1, 1)
            lienzo.c.setFont(PDF_FONT_BOLD, 10)
            lienzo.c.drawCentredString(MARGEN_X + 27, y - alto_marca + 6 + (alto_marca - 8) / 2 - 3.5, iniciales[:3])
        y -= alto_marca

    lienzo.c.setFillColorRGB(*TINTA)
    lienzo.c.setFont(PDF_FONT_BOLD, 12)
    lienzo.c.drawString(MARGEN_X + 10, y, titulo[:70])
    y -= 13
    if subtitulo:
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 8.5)
        lienzo.c.drawString(MARGEN_X + 10, y, subtitulo[:95])
        y -= 13
    if chips:
        x = MARGEN_X + 10
        for chip in chips:
            ancho_chip = lienzo.c.stringWidth(chip.upper(), PDF_FONT_REGULAR, 6.6) + 12
            if x + ancho_chip > A4_ANCHO - MARGEN_X - 10:
                break
            _pildora(lienzo.c, chip.upper(), x, y - 11, borde=VERDE, color_texto=OLIVA)
            x += ancho_chip + 4
        # 11 de alto de píldora + 11 de aire: sin esto la primera cifra se dibujaba
        # encima de los chips.
        y -= 22
    for item in items:
        destacado = _es_destacado(item)
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 8.5)
        lienzo.c.drawString(MARGEN_X + 10, y, _texto(item.get("label"))[:52])
        lienzo.c.setFillColorRGB(*(VERDE if destacado else TINTA))
        lienzo.c.setFont(PDF_FONT_BOLD, 8.5)
        lienzo.c.drawRightString(A4_ANCHO - MARGEN_X - 10, y, _texto(item.get("value"))[:34])
        y -= 13
    if nota:
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 7.5)
        lienzo.c.drawString(MARGEN_X + 10, y, nota[:120])
    lienzo.y = base - 10


def _barra_partida(lienzo, bloque):
    items = [i for i in (bloque.get("items") or []) if isinstance(i, dict)]
    if not items:
        return
    valores = []
    for item in items:
        try:
            valores.append(abs(float(item.get("value") or 0)))
        except (TypeError, ValueError):
            valores.append(0.0)
    total = sum(valores) or 1.0
    etiqueta = _texto(bloque.get("label"))
    lienzo.sitio(46)
    if etiqueta:
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 8)
        lienzo.c.drawString(MARGEN_X, lienzo.y - 8, etiqueta[:90])
        lienzo.y -= 15
    ancho_util = A4_ANCHO - MARGEN_X * 2
    x, alto = MARGEN_X, 9.0
    base = lienzo.y - alto
    for idx, valor in enumerate(valores):
        ancho = ancho_util * (valor / total)
        tono = 0.55 + (idx % 3) * 0.14
        lienzo.c.setFillColorRGB(VERDE[0] * tono, VERDE[1] * tono, VERDE[2] * tono)
        # 2 pt de aire entre tramos para que se distingan sin depender del color.
        lienzo.c.rect(x, base, max(0.0, ancho - 2), alto, stroke=0, fill=1)
        x += ancho
    lienzo.y = base - 12
    for item, valor in zip(items, valores):
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 7.5)
        pct = f" ({valor / total * 100:.0f} %)" if total else ""
        lienzo.c.drawString(MARGEN_X, lienzo.y, f"{_texto(item.get('label'))[:40]}: {_texto(item.get('value'))}{pct}")
        lienzo.y -= 10
    lienzo.y -= 4


def _cascada(lienzo, bloque):
    pasos = [p for p in (bloque.get("steps") or []) if isinstance(p, dict)]
    etiqueta = _texto(bloque.get("label"))
    if etiqueta:
        lienzo.linea_texto(etiqueta, PDF_FONT_BOLD, 9, APAGADO)
    for paso in pasos:
        lienzo.sitio(12)
        lienzo.c.setFillColorRGB(*TINTA)
        lienzo.c.setFont(PDF_FONT_REGULAR, 8.5)
        lienzo.c.drawString(MARGEN_X + 8, lienzo.y - 8, _texto(paso.get("label"))[:60])
        lienzo.c.setFont(PDF_FONT_BOLD, 8.5)
        lienzo.c.drawRightString(A4_ANCHO - MARGEN_X, lienzo.y - 8, _texto(paso.get("value"))[:24])
        lienzo.y -= 12
    lienzo.y -= 4


def build_modernia_branded_document_pdf_vector(
    title, subtitle, sections, footer_lines=None, company=None, brand_logo_url=None
):
    """Mismo documento que el motor de imagen, dibujado como texto."""
    from reportlab.pdfgen import canvas as rl_canvas

    company = company or {}
    meta = " · ".join(
        p
        for p in (
            _texto(company.get("razon_social") or company.get("nombre")),
            f"CIF: {company.get('nif') or company.get('cif')}" if (company.get("nif") or company.get("cif")) else "",
            _texto(company.get("direccion_fiscal") or company.get("direccion")),
        )
        if p
    )

    cache_logos = {}
    logo_marca = _logo_png(
        brand_logo_url or company.get("logo_url") or "/assets/grupo_modernia_logo.png", 150, cache_logos
    )

    buffer = BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=(A4_ANCHO, A4_ALTO))
    c.setTitle(_texto(title))
    lienzo = _Lienzo(c, _dibuja_cabecera(title, subtitle, meta, logo_marca))

    for seccion in sections or []:
        encabezado, cuerpo = (seccion if isinstance(seccion, (list, tuple)) and len(seccion) == 2 else ("", seccion))
        if isinstance(cuerpo, dict) and str(cuerpo.get("kind") or "").lower() == "page_break":
            lienzo.nueva_pagina()
            continue
        if encabezado:
            lienzo.sitio(22)
            lienzo.y -= 4
            lienzo.linea_texto(_texto(encabezado), PDF_FONT_BOLD, 11.5, TINTA)
            lienzo.c.setStrokeColorRGB(*LINEA)
            lienzo.c.setLineWidth(0.5)
            lienzo.c.line(MARGEN_X, lienzo.y + 4, A4_ANCHO - MARGEN_X, lienzo.y + 4)
            lienzo.y -= 6
        clase = str(cuerpo.get("kind") or "").lower() if isinstance(cuerpo, dict) else ""
        if clase == "kpi_cards":
            _tarjetas_kpi(lienzo, cuerpo)
        elif clase == "feature_card":
            _ficha_destacada(lienzo, cuerpo, cache_logos)
        elif clase == "split_bar":
            _barra_partida(lienzo, cuerpo)
        elif clase == "waterfall":
            _cascada(lienzo, cuerpo)
        elif isinstance(cuerpo, dict):
            for item in cuerpo.get("items") or []:
                lienzo.linea_texto(_texto(item), sangria=8)
        else:
            for linea in (cuerpo or []):
                lienzo.linea_texto(_texto(linea), sangria=8)

    for pie in footer_lines or []:
        lienzo.sitio(11)
        lienzo.linea_texto(_texto(pie), PDF_FONT_REGULAR, 7.5, APAGADO)

    c.save()
    return buffer.getvalue()
