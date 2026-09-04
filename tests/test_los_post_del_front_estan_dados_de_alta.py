"""Rutas POST con manejador que nadie dio de alta.

El servidor mantiene una lista blanca de rutas POST: lo que no está en ella responde

    {"error": "Endpoint no valido"}  404

y esa comprobación va **antes** que la de autenticación. Escribir el manejador no
basta; si no se añade a la lista, la ruta no existe para nadie.

Encontradas 22 así el 2026-08-04, todas con su manejador escrito:

  - `/api/hipotecas_listado_excel` y `/api/hipotecas_export_pdf`: las dos
    exportaciones de listados del CRM financiero. Es lo que reportó el usuario.
  - `/api/auth_request_access_recovery`: la recuperación de acceso. Estaba incluso
    en AUTH_PUBLIC_POST_ENDPOINTS, pero se rechazaba antes de llegar a mirarlo.
  - Borrado de presupuestos, alta de vecinos y comunidades de fincas, importación
    de nóminas, conciliación bancaria de gestoría...

Ya existía un test que comparaba las rutas que llama el front con las que declara
el servidor, y pasaba: las rutas **sí** estaban escritas en server.py. Lo que no
comprobaba era si estaban dadas de alta. Este lo hace.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FRONT_FICHEROS = ["app.js", "index.html", "app-routing.js", "app-auth.js", "ui-foundation.js",
                  "app_shared.js", "inmo_operacion.js"]
FRONT = "\n".join((RAIZ / "web" / n).read_text(encoding="utf-8") for n in FRONT_FICHEROS)
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

# Ayudantes del front que siempre mandan POST. Faltaba `apiPost`, que es el más usado
# después de `fetch` —39 rutas—, y por ese hueco se colaron tres el 2026-08-21: cerrar
# una compraventa, la preparación guiada del inmueble y reprocesar el OCR de una nómina.
# La prueba pasaba en verde sin haber mirado ninguna de las tres.
AYUDANTES_POST = ("apiPost", "postJsonWithDbRetry", "postJsonWithRetryBasic", "postJson",
                  "postPayload", "loadPdfFromApi", "downloadPdfFromApi", "postForm")


def rutas_permitidas():
    i = SERVER.index("if parsed.path not in (")
    blanca = SERVER[i: SERVER.index('json_response(self, {"error": "Endpoint no valido"}', i)]
    permitidas = set(re.findall(r'"(/api/[a-z0-9_/]+)"', blanca))
    # Las rutas tempranas se despachan antes de la lista blanca.
    j = SERVER.index("_POST_EARLY_ROUTES = {")
    permitidas |= set(re.findall(r'"(/api/[a-z0-9_/]+)"', SERVER[j: SERVER.index("\n    }", j)]))
    return permitidas


def rutas_que_el_front_manda_por_post():
    rutas = {}
    # fetch("<ruta>", { ... method: "POST" ... }) — la ruta es el primer argumento.
    for m in re.finditer(r'fetch\(\s*[`"\']([^`"\'?]+)[^)]*?method:\s*["\']POST["\']', FRONT, re.S):
        if m.group(1).startswith("/api/"):
            rutas.setdefault(m.group(1), "fetch")
    for ayudante in AYUDANTES_POST:
        for m in re.finditer(re.escape(ayudante) + r'\(\s*[`"\']([^`"\'?]+)', FRONT):
            if m.group(1).startswith("/api/"):
                rutas.setdefault(m.group(1), ayudante)
    return rutas


class TodoLoQueElFrontMandaPorPostExisteTests(unittest.TestCase):
    def test_ninguna_ruta_se_queda_sin_dar_de_alta(self):
        permitidas = rutas_permitidas()
        rotas = sorted(r for r in rutas_que_el_front_manda_por_post() if r not in permitidas)
        self.assertEqual(
            rotas,
            [],
            'el front manda POST a rutas que responderían "Endpoint no valido":\n  '
            + "\n  ".join(rotas),
        )

    def test_el_barrido_encuentra_algo(self):
        """Si el regex dejara de reconocer las llamadas, el test de arriba pasaría vacío."""
        self.assertGreater(len(rutas_que_el_front_manda_por_post()), 240)


class LasRutasPublicasLleganAComprobarseTests(unittest.TestCase):
    """Estar en AUTH_PUBLIC_POST_ENDPOINTS no sirve si la lista blanca la rechaza antes.

    Es el caso de la recuperación de acceso: marcada como pública, y aun así
    inalcanzable. Alguien sin contraseña no podía recuperarla.
    """

    def test_toda_ruta_publica_esta_tambien_en_la_lista_blanca(self):
        i = SERVER.index("AUTH_PUBLIC_POST_ENDPOINTS = {")
        publicas = set(re.findall(r'"(/api/[a-z0-9_/]+)"', SERVER[i: SERVER.index("\n}", i)]))
        permitidas = rutas_permitidas()
        huerfanas = sorted(p for p in publicas if p not in permitidas)
        self.assertEqual(
            huerfanas,
            [],
            "rutas marcadas como públicas que la lista blanca rechaza antes:\n  " + "\n  ".join(huerfanas),
        )


class LasExportacionesDeListadosFuncionanTests(unittest.TestCase):
    """Lo que reportó el usuario, fijado por su nombre."""

    def test_el_excel_y_el_pdf_estan_dados_de_alta(self):
        permitidas = rutas_permitidas()
        for ruta in ("/api/hipotecas_listado_excel", "/api/hipotecas_export_pdf"):
            with self.subTest(ruta=ruta):
                self.assertIn(ruta, permitidas)


if __name__ == "__main__":
    unittest.main()
