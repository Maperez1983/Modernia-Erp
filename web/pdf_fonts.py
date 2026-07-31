"""IBM Plex en los documentos generados.

Los PDF salían en Helvetica, la fuente incrustada en reportlab, mientras la
aplicación usaba otras tres. Y los documentos que se dibujan como imagen elegían
la fuente del sistema: Arial en un Mac, DejaVu Sans en el servidor de Render, así
que el mismo documento no se veía igual según dónde se generara.

Los ficheros viven en `web/assets/fonts` (IBM Plex, licencia OFL). Si faltan —una
copia incompleta del repositorio, un despliegue a medias— se sigue con Helvetica
en vez de reventar: un documento con la fuente equivocada es un mal menor frente a
un documento que no se genera.

IBM Plex Sans es aproximadamente un 3 % más ancha que Helvetica. Donde se estampa
texto sobre formularios oficiales con posiciones fijas eso importa, pero el
estampado ya reduce el cuerpo y recorta para que quepa dentro de cada casilla.
"""

from pathlib import Path

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"

_FALLBACK_REGULAR = "Helvetica"
_FALLBACK_BOLD = "Helvetica-Bold"

_ARCHIVOS = (
    ("IBMPlexSans", "IBMPlexSans-Regular.ttf"),
    ("IBMPlexSans-Bold", "IBMPlexSans-Bold.ttf"),
    ("IBMPlexSans-Italic", "IBMPlexSans-Italic.ttf"),
    ("IBMPlexSans-BoldItalic", "IBMPlexSans-BoldItalic.ttf"),
)


def font_path(nombre_fichero):
    """Ruta a un .ttf de IBM Plex, o None si no está."""
    ruta = FONT_DIR / nombre_fichero
    return ruta if ruta.is_file() else None


def _register():
    """Registra IBM Plex en reportlab. Devuelve (regular, negrita) ya utilizables."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception:
        return _FALLBACK_REGULAR, _FALLBACK_BOLD

    registradas = set()
    for nombre, fichero in _ARCHIVOS:
        ruta = font_path(fichero)
        if ruta is None:
            continue
        try:
            pdfmetrics.registerFont(TTFont(nombre, str(ruta)))
            registradas.add(nombre)
        except Exception:
            continue

    if "IBMPlexSans" not in registradas or "IBMPlexSans-Bold" not in registradas:
        return _FALLBACK_REGULAR, _FALLBACK_BOLD

    # Para que <b> e <i> funcionen dentro de los Paragraph.
    try:
        pdfmetrics.registerFontFamily(
            "IBMPlexSans",
            normal="IBMPlexSans",
            bold="IBMPlexSans-Bold",
            italic="IBMPlexSans-Italic" if "IBMPlexSans-Italic" in registradas else "IBMPlexSans",
            boldItalic="IBMPlexSans-BoldItalic" if "IBMPlexSans-BoldItalic" in registradas else "IBMPlexSans-Bold",
        )
    except Exception:
        pass
    return "IBMPlexSans", "IBMPlexSans-Bold"


PDF_FONT_REGULAR, PDF_FONT_BOLD = _register()

# La fuente por defecto del lienzo. Sin esto, reportlab abre cada página en
# Helvetica: lo que se dibuja sin fijar fuente antes sale en Helvetica sin que
# nadie lo haya pedido, y la declara en los recursos de cada PDF aunque no se use.
if PDF_FONT_REGULAR != _FALLBACK_REGULAR:
    try:
        from reportlab import rl_config

        rl_config.canvas_basefontname = PDF_FONT_REGULAR
    except Exception:
        pass

#: Cierto cuando se está usando IBM Plex y no el respaldo.
PDF_FONTS_OK = PDF_FONT_REGULAR != _FALLBACK_REGULAR
