"""El guion de migración tiene que arrancar con el Python que hay en el Mac.

Al lanzarlo en producción reventó antes de conectarse a nada:

    _CONN_TRACKER: Any | None = None
    TypeError: unsupported operand type(s) for |: '_SpecialForm' and 'NoneType'

`X | Y` en anotaciones es sintaxis de Python 3.10, y el `python3` por defecto de
macOS es el de Xcode, que es 3.9.6. Aquí se ejecuta con 3.12, así que ningún test
lo habría notado: la anotación se evalúa al cargar el módulo.

Se arregla con `from __future__ import annotations`, que deja las anotaciones sin
evaluar y funciona desde 3.7.
"""

import ast
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

# Todo `web/*.py` y el guion de migración. Empezó cubriendo solo la cadena del
# backfill y por eso se coló `hipotecas_pdf.py`, que tampoco cargaba con 3.9 y
# se llevaba por delante a `server.py` entero al importarlo.
CADENA_DEL_BACKFILL = [
    RAIZ / "scripts" / "backfill_clientes_workspace.py",
    *sorted(p for p in (RAIZ / "web").glob("*.py")),
]


def _usa_uniones_nuevas(arbol):
    """Anotaciones tipo `X | Y`, que en 3.9 revientan al evaluarse."""
    encontradas = []
    for nodo in ast.walk(arbol):
        anotaciones = []
        if isinstance(nodo, (ast.AnnAssign,)):
            anotaciones.append(nodo.annotation)
        elif isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            anotaciones.extend(a.annotation for a in nodo.args.args if a.annotation)
            if nodo.returns:
                anotaciones.append(nodo.returns)
        for anotacion in anotaciones:
            for sub in ast.walk(anotacion):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    encontradas.append(getattr(nodo, "lineno", 0))
    return encontradas


class ElBackfillArrancaConElPythonDelMacTests(unittest.TestCase):
    def test_las_anotaciones_no_se_evaluan_al_cargar(self):
        for ruta in CADENA_DEL_BACKFILL:
            texto = ruta.read_text(encoding="utf-8")
            arbol = ast.parse(texto, filename=str(ruta))
            uniones = _usa_uniones_nuevas(arbol)
            if not uniones:
                continue
            with self.subTest(fichero=ruta.name):
                self.assertIn(
                    "from __future__ import annotations", texto,
                    f"{ruta.name} usa `X | Y` en anotaciones (líneas {uniones}) y no aplaza su evaluación: "
                    "revienta con el python3 de macOS, que es 3.9",
                )

    def test_el_future_import_va_el_primero(self):
        # Python exige que sea la primera sentencia del módulo.
        for ruta in CADENA_DEL_BACKFILL:
            texto = ruta.read_text(encoding="utf-8")
            if "from __future__ import annotations" not in texto:
                continue
            arbol = ast.parse(texto, filename=str(ruta))
            cuerpo = [n for n in arbol.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            with self.subTest(fichero=ruta.name):
                self.assertTrue(
                    isinstance(cuerpo[0], ast.ImportFrom) and cuerpo[0].module == "__future__",
                    f"en {ruta.name} el import de __future__ no es lo primero",
                )


if __name__ == "__main__":
    unittest.main()
