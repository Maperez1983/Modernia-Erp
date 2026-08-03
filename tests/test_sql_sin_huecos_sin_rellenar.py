"""Un hueco `{...}` que llega literal a la base de datos.

En producción, el 2026-08-02, el dashboard de hipotecas respondía 500 con:

    SyntaxError: syntax error at or near "{" LINE 5: AND {signed_expr}

La causa es una trampa del propio lenguaje. Al reescribir la consulta para
acotar por workspace quedó así:

    f\"\"\"... WHERE \"\"\" + ambito + \"\"\" AND {signed_expr}\"\"\"

La `f` solo marca el PRIMER literal. El trozo que va detrás de `+ ambito +` es
una cadena corriente, así que `{signed_expr}` no se sustituye por nada: viaja
tal cual hasta Postgres. Se lee bien y no falla al importar; solo revienta
cuando alguien abre la pantalla.

Este test no vigila esa línea: vigila la forma. Cualquier literal de SQL que
conserve un hueco sin rellenar es un 500 esperando a que alguien entre.
"""

import ast
import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
HUECO = re.compile(r"\{[A-Za-z_][A-Za-z_0-9]*\}")
ES_SQL = re.compile(r"\b(SELECT|WHERE|FROM|INSERT INTO|UPDATE|DELETE FROM)\b")


class NingunSqlLlevaHuecosSinRellenarTests(unittest.TestCase):
    def test_ningun_literal_de_sql_conserva_un_hueco(self):
        sospechosos = []
        for ruta in sorted((RAIZ / "web").glob("*.py")):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
            for nodo in ast.walk(arbol):
                # Los f-string son ast.JoinedStr: sus huecos ya son FormattedValue
                # y nunca aparecen como texto. Aquí solo miramos cadenas normales.
                if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                    continue
                texto = nodo.value
                if HUECO.search(texto) and ES_SQL.search(texto):
                    sospechosos.append(
                        f"{ruta.name}:{nodo.lineno} -> {sorted(set(HUECO.findall(texto)))}"
                    )
        self.assertEqual(
            sospechosos,
            [],
            "SQL con huecos sin sustituir (¿un `+` que rompió el f-string?):\n"
            + "\n".join(sospechosos),
        )


if __name__ == "__main__":
    unittest.main()
