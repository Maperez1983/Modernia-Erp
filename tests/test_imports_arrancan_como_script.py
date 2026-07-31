"""En producción el servidor arranca como script suelto, no como paquete.

`from web.pdf_fonts import ...` funcionaba en local (`python -m web.server`) y en
los tests, y tumbó el despliegue: arrancado como script, `web` no es un módulo
importable, el import falla al cargar y el proceso no llega a escuchar. Render lo
marcó "Failed deploy" y siguió sirviendo la versión anterior durante una hora sin
que ningún test se enterara.

Por eso el resto de `server.py` importa a sus hermanos con dos intentos:

    try:
        from .db_backend import ...
    except ImportError:
        from db_backend import ...
"""

import ast
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
MODULOS = sorted(p for p in WEB.glob("*.py") if p.name != "__init__.py")
HERMANOS = {p.stem for p in MODULOS}


class NingunModuloSeImportaComoPaqueteTests(unittest.TestCase):
    def test_no_hay_imports_absolutos_del_paquete_web(self):
        malos = []
        for ruta in MODULOS:
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
            for nodo in ast.walk(arbol):
                if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("web."):
                    malos.append(f"{ruta.name}:{nodo.lineno} -> from {nodo.module} import ...")
                elif isinstance(nodo, ast.Import):
                    for alias in nodo.names:
                        if alias.name.startswith("web."):
                            malos.append(f"{ruta.name}:{nodo.lineno} -> import {alias.name}")
        self.assertEqual(
            malos, [],
            "arrancado como script, `web` no existe: usa `try: from .x import ... "
            "except ImportError: from x import ...`\n" + "\n".join(malos),
        )

    def test_cada_import_relativo_tiene_su_respaldo(self):
        """Un `from .x import` a secas también rompe fuera del paquete."""
        for ruta in MODULOS:
            texto = ruta.read_text(encoding="utf-8")
            arbol = ast.parse(texto, filename=str(ruta))
            relativos = {
                nodo.module
                for nodo in ast.walk(arbol)
                if isinstance(nodo, ast.ImportFrom) and nodo.level and nodo.module in HERMANOS
            }
            for modulo in relativos:
                with self.subTest(fichero=ruta.name, modulo=modulo):
                    self.assertIn(
                        f"from {modulo} import", texto,
                        f"{ruta.name} importa `.{modulo}` sin respaldo plano",
                    )


if __name__ == "__main__":
    unittest.main()
