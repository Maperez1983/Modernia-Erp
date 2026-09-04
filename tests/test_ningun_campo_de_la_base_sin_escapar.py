"""Un nombre de cliente con etiquetas se ejecutaba al abrir sus relaciones.

La tabla de relaciones del cliente pintaba `counterpart_nombre` y `counterpart_nif`
directamente en `innerHTML`. Los dos salen de una ficha donde escribe gente —y donde
también escribe el OCR de un DNI y lo que entra por el hub de leads—, así que un nombre
con `<img src=x onerror=...>` se ejecutaba en el origen de la aplicación al abrir esa
pestaña.

Era el único sitio: de las 235 interpolaciones sin escapar que hay en los seis ficheros
de JS, 234 son números, importes ya formateados o fragmentos de HTML construidos por el
propio front. La casa escapa con disciplina; se coló una.

Por eso esta prueba no comprueba esa línea, sino la regla: ninguna plantilla de
`innerHTML` puede interpolar un campo de la base sin pasar por `escapeHtml`. Encontrar
el fallo a mano costó un barrido; que no vuelva a colarse cuesta este fichero.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FICHEROS = ["app.js", "index.html", "app-routing.js", "app-auth.js", "ui-foundation.js",
            "app_shared.js", "inmo_operacion.js"]

# Envolturas que ya dejan el valor a salvo: escapan, o lo convierten en número.
SEGURO = re.compile(
    r"escapeHtml|escapeAttr|encodeURIComponent|Number\(|toFixed|formatEuros"
    r"|numberFormatter|euroFormatter|JSON\.stringify|\.length\b"
)

# Campos de texto que rellena una persona (o un OCR, o un lead) y acaban en la base.
CAMPO_DE_LA_BASE = re.compile(
    r"\b\w+\.(nombre|direccion|email|telefono|movil|observaciones|notas|descripcion"
    r"|titulo|concepto|comentario|mensaje|asunto|nif|piso|referencia|propietario"
    r"|inquilino|cliente_nombre|counterpart_nombre|counterpart_nif)\b"
)


def interpolaciones_crudas():
    hallazgos = []
    for nombre in FICHEROS:
        fuente = (RAIZ / "web" / nombre).read_text(encoding="utf-8")
        for m in re.finditer(r"innerHTML\s*(?:\+)?=\s*`", fuente):
            i = m.end()
            profundidad, j = 1, i
            while j < len(fuente) and profundidad:
                if fuente[j] == "`" and fuente[j - 1] != "\\":
                    profundidad -= 1
                j += 1
            plantilla = fuente[i:j]
            linea = fuente[:i].count("\n") + 1
            for expresion in re.findall(r"\$\{([^}]{1,160})\}", plantilla):
                if SEGURO.search(expresion):
                    continue
                if CAMPO_DE_LA_BASE.search(expresion):
                    hallazgos.append(f"{nombre}:{linea}  {expresion.strip()[:90]}")
    return hallazgos


class NingunCampoDeLaBaseSePintaCrudoTests(unittest.TestCase):
    def test_no_hay_interpolaciones_sin_escapar(self):
        crudas = interpolaciones_crudas()
        self.assertEqual(
            crudas, [],
            "se pinta un campo de la base en innerHTML sin escapar:\n  " + "\n  ".join(crudas),
        )

    def test_el_barrido_reconoce_las_plantillas(self):
        """Sin esto, un cambio de estilo que rompiera el patrón dejaría la prueba en verde
        sin haber mirado nada."""
        fuente = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        self.assertGreater(len(re.findall(r"innerHTML\s*(?:\+)?=\s*`", fuente)), 100)

    def test_escapehtml_escapa_lo_que_debe(self):
        fuente = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")
        i = fuente.index("const escapeHtml = (value) =>")
        bloque = fuente[i: i + 400]
        for caracter in ("&amp;", "&lt;", "&gt;", "&quot;", "&#39;"):
            with self.subTest(caracter=caracter):
                self.assertIn(caracter, bloque)


if __name__ == "__main__":
    unittest.main()
