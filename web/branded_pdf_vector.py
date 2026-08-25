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

#: Aire entre bloques. El documento salía apelotonado: los encabezados de sección
#: se pegaban al párrafo anterior y los párrafos entre sí, así que un presupuesto
#: parecía un muro de texto. Estas cuatro medidas son las que lo separan.
ESPACIO_ANTES_SECCION = 13.0
ESPACIO_TRAS_ENCABEZADO = 8.0
#: Un encabezado no puede quedarse solo al pie: se le reserva sitio para dos o tres
#: líneas de lo que venga detrás.
ALTO_ENCABEZADO_CON_ARRANQUE = 78.0
#: Separación por defecto entre los elementos de una lista (datos, servicios).
ESPACIO_ENTRE_ITEMS = 2.0
#: Cuánto baja la raya del encabezado por debajo de la base del texto. En IBM Plex
#: el trazo descendente de una «p» a cuerpo 11,5 llega a unos 2,6 puntos, así que
#: con menos de eso la raya cruza la letra y el título parece cortado.
REGLA_BAJO_ENCABEZADO = 4.5


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

    def __init__(self, c, cabecera, color=None, pie_pagina=None):
        self.c = c
        self.cabecera = cabecera
        self.color = color or VERDE
        self.pie_pagina = pie_pagina
        self.y = 0.0
        self.pagina = 0
        self.nueva_pagina()

    def nueva_pagina(self):
        if self.pagina:
            # El pie de la página que se cierra se dibuja antes del showPage: una
            # vez pasada de página el canvas ya no vuelve atrás.
            if self.pie_pagina:
                self.pie_pagina(self.c, self.pagina)
            self.c.showPage()
        self.pagina += 1
        self.y = self.cabecera(self.c, self.pagina)
        # Para saber si estamos recién abierta la página: al principio no se separa
        # nada, porque el hueco lo da ya la cabecera.
        self.y_inicial = self.y

    def cerrar(self):
        """Pie de la última página — no hay `nueva_pagina()` después que lo dibuje."""
        if self.pie_pagina:
            self.pie_pagina(self.c, self.pagina)

    def recien_abierta(self):
        return self.y >= getattr(self, "y_inicial", self.y) - 0.5

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


def _alto_util_pagina():
    """Lo que cabe en una página interior, ya descontada cabecera y márgenes."""
    return A4_ALTO - MARGEN_SUP - 42 - MARGEN_INF


def _alto_estimado(cuerpo):
    """Cuánto ocupa un bloque, para no dejarlo partido entre dos páginas.

    Antes solo se reservaban 22 puntos —el encabezado— así que una tabla de tres
    filas podía empezar al pie de una página y terminar en la siguiente, con una
    página casi en blanco para la última fila. Devuelve `None` cuando no se puede
    estimar (listas de texto, que se ajustan al ancho y se parten sin problema).
    """
    if not isinstance(cuerpo, dict):
        return None
    clase = str(cuerpo.get("kind") or "").lower()
    if clase == "table":
        filas = len([f for f in (cuerpo.get("rows") or []) if isinstance(f, (list, tuple))])
        if not filas:
            return None
        return 17.0 * (filas + 1) + (17.0 if cuerpo.get("total") else 0.0) + 10.0
    if clase == "waterfall":
        pasos = [p for p in (cuerpo.get("steps") or []) if isinstance(p, dict)]
        return sum(22.0 if _es_destacado(p) else 15.0 for p in pasos) + 8.0 if pasos else None
    if clase == "image":
        try:
            return float(cuerpo.get("height") or 0) + (16.0 if cuerpo.get("caption") else 4.0)
        except (TypeError, ValueError):
            return None
    if clase == "kpi_cards":
        return 62.0 if cuerpo.get("items") else None
    return None


def _item_a_texto(item):
    """Un elemento de lista puede venir como texto o como par (etiqueta, valor).

    El par es la forma que usan las fichas —«Referencia catastral», «Superficie»— y
    el motor de imagen lo unía con dos puntos. Aquí se hacía `str()` a secas, así que
    la ficha catastral salía con la tupla de Python en crudo:
    `('Dirección CRM', '100 - SOR TERESA PRAT 59 2º G')`.
    """
    if isinstance(item, (list, tuple)) and len(item) == 2:
        etiqueta, valor = item
        etiqueta, valor = _texto(etiqueta).strip(), _texto(valor).strip()
        if etiqueta and valor:
            return f"{etiqueta}: {valor}"
        return etiqueta or valor
    return _texto(item)


def _lista(lienzo, items, espaciado=None):
    """Pinta una lista de párrafos dejando aire entre ellos.

    Antes cada elemento se dibujaba pegado al siguiente, así que una carta de ocho
    párrafos salía como un bloque macizo: no se distinguía dónde acababa uno.
    """
    hueco = ESPACIO_ENTRE_ITEMS if espaciado is None else float(espaciado or 0)
    for item in items:
        lienzo.linea_texto(_item_a_texto(item), sangria=8)
        if hueco:
            lienzo.y -= hueco


def _columnas(lienzo, bloque):
    """Filas repartidas en columnas de igual ancho, sin rayas.

    Es lo que necesita el pie de firmas de un contrato: «Por el Intermediario» a la
    izquierda y «Por el cliente» a la derecha, cada uno sobre su hueco. Venía escrito
    alineando con tiradas de espacios, que el motor de imagen respetaba pero este
    colapsa al partir por palabras, así que las dos firmas acababan pegadas en una
    misma línea y no se distinguía dónde firmaba cada parte.
    """
    filas = [f for f in (bloque.get("items") or []) if f]
    if not filas:
        return
    columnas = max(len(f) for f in filas)
    if columnas < 2:
        _lista(lienzo, [" ".join(f) for f in filas])
        return
    util = A4_ANCHO - MARGEN_X * 2
    ancho = util / columnas
    tamano = float(bloque.get("tamano") or 9.5)
    for fila in filas:
        lienzo.sitio(tamano + 6)
        lienzo.c.setFillColorRGB(*TINTA)
        lienzo.c.setFont(PDF_FONT_REGULAR, tamano)
        for i, celda in enumerate(fila):
            texto = _texto(celda).strip()
            if not texto:
                continue
            cabido, cuerpo = _encoge_para_caber(
                lienzo.c, texto, PDF_FONT_REGULAR, tamano, ancho - 10, minimo=7.0)
            lienzo.c.setFont(PDF_FONT_REGULAR, cuerpo)
            lienzo.c.drawString(MARGEN_X + ancho * i, lienzo.y - tamano, cabido)
        lienzo.c.setFont(PDF_FONT_REGULAR, tamano)
        lienzo.y -= tamano + 6


def _cabe_en(c, texto, fuente, tamano, ancho):
    return c.stringWidth(texto, fuente, tamano) <= ancho


def _encoge_para_caber(c, texto, fuente, tamano, ancho, minimo=6.8):
    """Baja el cuerpo hasta que quepa; si aun así no cabe, recorta con puntos.

    El subtítulo de la banda se cortaba a 70 caracteres a ciegas, sin mirar lo que
    ocupaba de verdad, y con un nombre largo se comía el título de la izquierda.
    """
    # El paso es de 0,25, así que hay que comprobar el siguiente valor y no el
    # actual: con `while tamano > minimo` se acababa por debajo del mínimo.
    while tamano - 0.25 >= minimo and not _cabe_en(c, texto, fuente, tamano, ancho):
        tamano -= 0.25
    if _cabe_en(c, texto, fuente, tamano, ancho):
        return texto, tamano
    recorte = texto
    while recorte and not _cabe_en(c, recorte + "…", fuente, tamano, ancho):
        recorte = recorte[:-1]
    return (recorte.rstrip(" ·,-") + "…") if recorte else "", tamano


def _dibuja_cabecera(titulo, subtitulo, meta_empresa, logo_marca=None, color=None, sello=None):
    color = color or VERDE

    def cabecera(c, pagina):
        y = A4_ALTO - MARGEN_SUP
        if pagina == 1:
            if logo_marca or sello:
                # El logo va sobre blanco, encima de la banda: sobre el color de
                # marca perdería contraste y se vería sucio.
                if logo_marca:
                    _pinta_logo(c, logo_marca, MARGEN_X, y - 52, 50)
                # El sello (colegio, certificación) va a la derecha, enfrentado al
                # logo: es lo que da autoridad al documento y tiene que verse.
                if sello:
                    lector, ancho, alto = sello
                    escala = min(1.0, 40.0 / float(alto or 1), 150.0 / float(ancho or 1))
                    try:
                        c.drawImage(lector, A4_ANCHO - MARGEN_X - ancho * escala, y - 52,
                                    width=ancho * escala, height=alto * escala, mask="auto")
                    except Exception:
                        pass
                y -= 64
            c.setFillColorRGB(*color)
            c.rect(0, y - 40, A4_ANCHO, 40, stroke=0, fill=1)
            c.setFillColorRGB(1, 1, 1)
            texto_titulo = _texto(titulo)[:80]
            c.setFont(PDF_FONT_BOLD, 15)
            c.drawString(MARGEN_X, y - 26, texto_titulo)
            bajado = ""
            if subtitulo:
                # Lo que queda libre a la derecha del título, con un respiro en medio:
                # así el subtítulo se encoge o se recorta, pero nunca se solapa.
                libre = (A4_ANCHO - MARGEN_X * 2) - c.stringWidth(texto_titulo, PDF_FONT_BOLD, 15) - 18
                entero = _texto(subtitulo)
                cabido, cuerpo_sub = _encoge_para_caber(c, entero, PDF_FONT_REGULAR, 9, libre)
                if cabido and cabido == entero:
                    c.setFont(PDF_FONT_REGULAR, cuerpo_sub)
                    c.drawRightString(A4_ANCHO - MARGEN_X, y - 26, cabido)
                else:
                    # Con un título largo no queda hueco y el recorte dejaba cosas como
                    # «Modelo adaptad…», que no dice nada. Mejor entero, debajo.
                    bajado = entero
            y -= 56
            if bajado:
                c.setFillColorRGB(*TINTA)
                cabido, cuerpo_sub = _encoge_para_caber(
                    c, bajado, PDF_FONT_REGULAR, 9, A4_ANCHO - MARGEN_X * 2, minimo=7.0)
                c.setFont(PDF_FONT_REGULAR, cuerpo_sub)
                c.drawString(MARGEN_X, y, cabido)
                y -= 14
            if meta_empresa:
                c.setFillColorRGB(*APAGADO)
                cabido, cuerpo_meta = _encoge_para_caber(
                    c, _texto(meta_empresa), PDF_FONT_REGULAR, 7.5, A4_ANCHO - MARGEN_X * 2, minimo=6.0)
                c.setFont(PDF_FONT_REGULAR, cuerpo_meta)
                c.drawString(MARGEN_X, y, cabido)
                y -= 18
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


def _dibuja_pie_paginado(total_paginas=None):
    """«Página N» o «Página N de M» si ya se conoce el total, esquina inferior
    derecha. Documentos legales (informes periciales, actas...) se esperan
    foliados; este motor no pintaba número de página en absoluto hasta ahora."""

    def pie(c, pagina):
        c.setFillColorRGB(*APAGADO)
        c.setFont(PDF_FONT_REGULAR, 7.5)
        texto = f"Página {pagina} de {total_paginas}" if total_paginas else f"Página {pagina}"
        c.drawRightString(A4_ANCHO - MARGEN_X, 20, texto)

    return pie


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
            lienzo.c.setStrokeColorRGB(*(lienzo.color if destacado else LINEA))
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
        lienzo.c.setFillColorRGB(*lienzo.color)
        lienzo.c.setFont(PDF_FONT_BOLD, 6.6)
        lienzo.c.drawString(MARGEN_X + 10, y, _texto(bloque.get("eyebrow"))[:50].upper())
    if badge:
        ancho_badge = lienzo.c.stringWidth(badge.upper(), PDF_FONT_BOLD, 6.6) + 12
        _pildora(lienzo.c, badge.upper(), A4_ANCHO - MARGEN_X - 10 - ancho_badge, y - 3,
                 fuente=PDF_FONT_BOLD, tamano=6.6, color_texto=lienzo.color, borde=lienzo.color)
    y -= 12

    if alto_marca:
        if logo:
            _pinta_logo(lienzo.c, logo, MARGEN_X + 10, y - alto_marca + 6, alto_marca - 8)
        else:
            lienzo.c.setFillColorRGB(*lienzo.color)
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
            _pildora(lienzo.c, chip.upper(), x, y - 11, borde=lienzo.color, color_texto=OLIVA)
            x += ancho_chip + 4
        # 11 de alto de píldora + 11 de aire: sin esto la primera cifra se dibujaba
        # encima de los chips.
        y -= 22
    for item in items:
        destacado = _es_destacado(item)
        lienzo.c.setFillColorRGB(*APAGADO)
        lienzo.c.setFont(PDF_FONT_REGULAR, 8.5)
        lienzo.c.drawString(MARGEN_X + 10, y, _texto(item.get("label"))[:52])
        lienzo.c.setFillColorRGB(*(lienzo.color if destacado else TINTA))
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
        lienzo.c.setFillColorRGB(lienzo.color[0] * tono, lienzo.color[1] * tono, lienzo.color[2] * tono)
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
        # La cifra final se separa con una línea y se escribe más grande: es el
        # número que se lee en la junta, y antes iba igual que el IVA.
        destacado = _es_destacado(paso)
        alto = 22.0 if destacado else 15.0
        lienzo.sitio(alto)
        if destacado:
            lienzo.y -= 4
            lienzo.c.setStrokeColorRGB(*LINEA)
            lienzo.c.setLineWidth(0.5)
            lienzo.c.line(MARGEN_X + 8, lienzo.y, A4_ANCHO - MARGEN_X, lienzo.y)
            lienzo.y -= 5
        cuerpo = 11.0 if destacado else 8.5
        lienzo.c.setFillColorRGB(*TINTA)
        lienzo.c.setFont(PDF_FONT_BOLD if destacado else PDF_FONT_REGULAR, cuerpo)
        lienzo.c.drawString(MARGEN_X + 8, lienzo.y - cuerpo, _texto(paso.get("label"))[:60])
        lienzo.c.setFont(PDF_FONT_BOLD, cuerpo)
        lienzo.c.drawRightString(A4_ANCHO - MARGEN_X, lienzo.y - cuerpo, _texto(paso.get("value"))[:24])
        lienzo.y -= cuerpo + 6
    lienzo.y -= 4


def _tabla(lienzo, bloque):
    """Tabla con cabecera, filas alternas y fila de totales opcional.

    Las columnas se declaran como `{"label", "width", "align"}`; `width` es una
    proporción, no puntos, para que la tabla se adapte al ancho útil. Cada fila es
    una lista de celdas ya formateadas: aquí no se decide cómo se escribe un euro.
    """
    columnas = [c for c in (bloque.get("columns") or []) if isinstance(c, dict)]
    filas = [f for f in (bloque.get("rows") or []) if isinstance(f, (list, tuple))]
    if not columnas or not filas:
        return
    ancho_util = A4_ANCHO - MARGEN_X * 2
    pesos = [float(c.get("width") or 1) for c in columnas]
    total_peso = sum(pesos) or 1.0
    anchos = [ancho_util * (p / total_peso) for p in pesos]
    alto_fila = 17.0

    def cabecera_tabla():
        lienzo.sitio(alto_fila + 4)
        base = lienzo.y - alto_fila
        lienzo.c.setFillColorRGB(*lienzo.color)
        lienzo.c.rect(MARGEN_X, base, ancho_util, alto_fila, stroke=0, fill=1)
        lienzo.c.setFillColorRGB(1, 1, 1)
        lienzo.c.setFont(PDF_FONT_BOLD, 7)
        x = MARGEN_X
        for col, ancho in zip(columnas, anchos):
            etiqueta = _texto(col.get("label")).upper()
            if str(col.get("align") or "left") == "right":
                lienzo.c.drawRightString(x + ancho - 7, base + 5.5, etiqueta)
            else:
                lienzo.c.drawString(x + 7, base + 5.5, etiqueta)
            x += ancho
        lienzo.y = base

    cabecera_tabla()
    pagina_tabla = lienzo.pagina
    for idx, fila in enumerate(filas):
        lienzo.sitio(alto_fila)
        # Si la tabla ha saltado de página, la cabecera se repite: una tabla
        # descabezada obliga a volver atrás para saber qué columna es cuál.
        if lienzo.pagina != pagina_tabla:
            pagina_tabla = lienzo.pagina
            cabecera_tabla()
            lienzo.sitio(alto_fila)
        base = lienzo.y - alto_fila
        if idx % 2:
            lienzo.c.setFillColorRGB(*FONDO_SUAVE)
            lienzo.c.rect(MARGEN_X, base, ancho_util, alto_fila, stroke=0, fill=1)
        x = MARGEN_X
        for col, ancho, celda in zip(columnas, anchos, list(fila) + [""] * len(columnas)):
            lienzo.c.setFillColorRGB(*TINTA)
            lienzo.c.setFont(PDF_FONT_REGULAR, 8)
            texto = _texto(celda)
            if str(col.get("align") or "left") == "right":
                lienzo.c.drawRightString(x + ancho - 7, base + 5.5, texto)
            else:
                # Se recorta a lo que cabe en vez de desbordar sobre la columna vecina.
                while texto and lienzo.c.stringWidth(texto, PDF_FONT_REGULAR, 8) > ancho - 14:
                    texto = texto[:-1]
                lienzo.c.drawString(x + 7, base + 5.5, texto)
            x += ancho
        lienzo.y = base
    total = bloque.get("total")
    if isinstance(total, (list, tuple)):
        lienzo.sitio(alto_fila + 2)
        base = lienzo.y - alto_fila
        lienzo.c.setStrokeColorRGB(*lienzo.color)
        lienzo.c.setLineWidth(1.0)
        lienzo.c.line(MARGEN_X, base + alto_fila, A4_ANCHO - MARGEN_X, base + alto_fila)
        x = MARGEN_X
        for col, ancho, celda in zip(columnas, anchos, list(total) + [""] * len(columnas)):
            lienzo.c.setFillColorRGB(*TINTA)
            lienzo.c.setFont(PDF_FONT_BOLD, 8.5)
            if str(col.get("align") or "left") == "right":
                lienzo.c.drawRightString(x + ancho - 7, base + 5.5, _texto(celda))
            else:
                lienzo.c.drawString(x + 7, base + 5.5, _texto(celda))
            x += ancho
        lienzo.y = base
    lienzo.y -= 12


def _imagen_pil(imagen):
    """Convierte una imagen de PIL en (ImageReader, ancho, alto).

    Los logos van en PNG porque suelen llevar transparencia; las fotografías, en
    JPEG. Guardar una foto del equipo en PNG engordaba el presupuesto de 33 kB a
    3,3 MB, que es peor que el problema que vinimos a arreglar.
    """
    try:
        from reportlab.lib.utils import ImageReader

        # Se mira el canal alfa, no el modo: los assets llegan todos en RGBA aunque
        # sean fotografías opacas, y por el modo la del equipo se guardaba en PNG.
        transparente = False
        if "A" in imagen.getbands():
            try:
                transparente = imagen.getchannel("A").getextrema() != (255, 255)
            except Exception:
                transparente = True
        elif "transparency" in getattr(imagen, "info", {}):
            transparente = True
        buf = BytesIO()
        if transparente:
            if imagen.mode != "RGBA":
                imagen = imagen.convert("RGBA")
            imagen.save(buf, format="PNG")
        else:
            if imagen.mode != "RGB":
                imagen = imagen.convert("RGB")
            imagen.save(buf, format="JPEG", quality=82, optimize=True)
        buf.seek(0)
        return (ImageReader(buf), imagen.width, imagen.height)
    except Exception:
        return None


def _imagen(lienzo, bloque, cache=None):
    """Una imagen a lo ancho, con alto máximo. Si no carga, no deja hueco."""
    if bloque.get("image") is not None:
        datos = _imagen_pil(bloque.get("image"))
    else:
        datos = _logo_png(bloque.get("url"), int(bloque.get("max_width") or 900), cache)
    if not datos:
        return
    lector, ancho, alto = datos
    ancho_util = A4_ANCHO - MARGEN_X * 2
    alto_max = float(bloque.get("height") or 190)
    escala = min(ancho_util / float(ancho or 1), alto_max / float(alto or 1))
    w, h = ancho * escala, alto * escala
    lienzo.sitio(h + 10)
    base = lienzo.y - h
    try:
        lienzo.c.drawImage(lector, MARGEN_X + (ancho_util - w) / 2, base, width=w, height=h, mask="auto")
    except Exception:
        return
    pie = _texto(bloque.get("caption")).strip()
    lienzo.y = base - 8
    if pie:
        lienzo.linea_texto(pie, PDF_FONT_REGULAR, 7.5, APAGADO)
    lienzo.y -= 4


def _color_de(valor, defecto=VERDE):
    """Convierte «#3C6E71» en la terna que quiere reportlab. Sin valor, el verde."""
    crudo = _texto(valor).strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(ch * 2 for ch in crudo)
    if len(crudo) != 6:
        return defecto
    try:
        return tuple(int(crudo[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return defecto


def build_modernia_branded_document_pdf_vector(
    title, subtitle, sections, footer_lines=None, company=None, brand_logo_url=None,
    brand_color=None, seal_logo_url=None, seal_image=None, paginar=False,
):
    """Mismo documento que el motor de imagen, dibujado como texto.

    `paginar=True` añade «Página N de M» al pie de cada página. Como M no se
    sabe hasta terminar de maquetar, se hace un pre-pase silencioso (mismo
    canvas, mismo cálculo de saltos de página) solo para contar cuántas
    páginas hará falta; ese primer PDF se tira entero y solo se devuelve el
    de la segunda pasada, que ya sabe el total desde la primera página.
    """
    total_paginas = None
    if paginar:
        _, total_paginas = _construir_documento_pdf_vector(
            title, subtitle, sections, footer_lines, company, brand_logo_url,
            brand_color, seal_logo_url, seal_image, pintar_folio=True, total_paginas=None,
        )
    pdf_bytes, _ = _construir_documento_pdf_vector(
        title, subtitle, sections, footer_lines, company, brand_logo_url,
        brand_color, seal_logo_url, seal_image, pintar_folio=paginar, total_paginas=total_paginas,
    )
    return pdf_bytes


def _construir_documento_pdf_vector(
    title, subtitle, sections, footer_lines, company, brand_logo_url,
    brand_color, seal_logo_url, seal_image, *, pintar_folio=False, total_paginas=None,
):
    from reportlab.pdfgen import canvas as rl_canvas

    company = company or {}
    # El nombre comercial va delante, porque es el del logo y el que conoce el
    # cliente; la sociedad y el CIF siguen apareciendo detrás, que son los que
    # identifican a quién contrata. Si coinciden, no se repite.
    comercial = _texto(company.get("nombre_comercial")).strip()
    legal = _texto(company.get("razon_social") or company.get("nombre")).strip()
    if comercial and _texto(legal).casefold() == comercial.casefold():
        legal = ""
    meta = " · ".join(
        p
        for p in (
            comercial,
            legal,
            f"CIF: {company.get('nif') or company.get('cif')}" if (company.get("nif") or company.get("cif")) else "",
            _texto(company.get("direccion_fiscal") or company.get("direccion")),
        )
        if p
    )

    cache_logos = {}
    if hasattr(brand_logo_url, "size"):
        logo_marca = _imagen_pil(brand_logo_url)
    else:
        logo_marca = _logo_png(
            brand_logo_url or company.get("logo_url") or "/assets/grupo_modernia_logo.png", 150, cache_logos
        )

    buffer = BytesIO()
    c = rl_canvas.Canvas(buffer, pagesize=(A4_ANCHO, A4_ALTO))
    c.setTitle(_texto(title))
    sello = None
    if seal_image is not None:
        sello = _imagen_pil(seal_image)
    elif seal_logo_url:
        sello = _logo_png(seal_logo_url, 300, cache_logos)
    color_marca = _color_de(brand_color)
    lienzo = _Lienzo(
        c,
        _dibuja_cabecera(title, subtitle, meta, logo_marca, color=color_marca, sello=sello),
        color=color_marca,
        pie_pagina=_dibuja_pie_paginado(total_paginas) if pintar_folio else None,
    )

    for seccion in sections or []:
        encabezado, cuerpo = (seccion if isinstance(seccion, (list, tuple)) and len(seccion) == 2 else ("", seccion))
        if isinstance(cuerpo, dict) and str(cuerpo.get("kind") or "").lower() == "page_break":
            lienzo.nueva_pagina()
            continue
        if encabezado:
            # Se reserva sitio para el encabezado **y para un arranque de contenido**:
            # con los 22 puntos de antes, un título podía quedarse solo al pie y su
            # contenido empezar en la página siguiente («Cierre económico» acabó así,
            # con una página entera para tres cifras).
            estimado = _alto_estimado(cuerpo)
            necesario = ALTO_ENCABEZADO_CON_ARRANQUE
            if estimado:
                # Con la altura real del bloque se decide bien: si cabe entero en una
                # página, se pasa a la siguiente antes que partirlo.
                necesario = min(30.0 + estimado, _alto_util_pagina())
            lienzo.sitio(necesario)
            if not lienzo.recien_abierta():
                lienzo.y -= ESPACIO_ANTES_SECCION
            lienzo.linea_texto(_texto(encabezado), PDF_FONT_BOLD, 11.5, TINTA)
            # `linea_texto` deja la base del texto en `y + 4`. Dibujar ahí la raya la
            # hacía pasar por encima de los trazos que bajan —la «p» de «Carta de
            # presentación», la «g» de «Gestión»— y el encabezado salía cortado por
            # la mitad. Va por debajo del descendente.
            base_texto = lienzo.y + 4
            lienzo.c.setStrokeColorRGB(*LINEA)
            lienzo.c.setLineWidth(0.5)
            regla = base_texto - REGLA_BAJO_ENCABEZADO
            lienzo.c.line(MARGEN_X, regla, A4_ANCHO - MARGEN_X, regla)
            lienzo.y = regla - ESPACIO_TRAS_ENCABEZADO
        clase = str(cuerpo.get("kind") or "").lower() if isinstance(cuerpo, dict) else ""
        if clase == "kpi_cards":
            _tarjetas_kpi(lienzo, cuerpo)
        elif clase == "feature_card":
            _ficha_destacada(lienzo, cuerpo, cache_logos)
        elif clase == "split_bar":
            _barra_partida(lienzo, cuerpo)
        elif clase == "waterfall":
            _cascada(lienzo, cuerpo)
        elif clase == "table":
            _tabla(lienzo, cuerpo)
        elif clase == "image":
            _imagen(lienzo, cuerpo, cache_logos)
        elif clase == "columns":
            _columnas(lienzo, cuerpo)
        elif isinstance(cuerpo, dict):
            _lista(lienzo, cuerpo.get("items") or [], cuerpo.get("espaciado"))
        else:
            _lista(lienzo, cuerpo or [], None)

    for pie in footer_lines or []:
        lienzo.sitio(11)
        lienzo.linea_texto(_texto(pie), PDF_FONT_REGULAR, 7.5, APAGADO)

    # El pie de la última página no lo dibuja ningún `nueva_pagina()` posterior.
    lienzo.cerrar()
    c.save()
    return buffer.getvalue(), lienzo.pagina
