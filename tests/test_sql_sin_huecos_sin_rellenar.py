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


class NingunHavingUsaUnAliasDelSelectTests(unittest.TestCase):
    """El otro SQL que se lee bien, importa bien, y solo falla en producción.

    El 2026-08-11, en el arranque del servidor contra Postgres:

        escritura accesoria fallida en ensure_workspace_product_tables/
        workspace_registro_personal: column "n" does not exist
        LINE 6:             HAVING n > 1

    La consulta hacía `SELECT ..., COUNT(*) AS n ... HAVING n > 1`. SQLite deja usar
    el alias del SELECT dentro del HAVING; el estándar y Postgres no —el HAVING se
    evalúa antes de que existan los alias de salida—. La limpieza de fichas de
    personal duplicadas llevaba, por tanto, sin ejecutarse nunca en producción, y el
    `except` que la envuelve se comía el aviso.

    La suite no lo veía porque corre sobre SQLite, donde la consulta es válida. Así
    que esto no vigila aquella línea: vigila la forma, que es lo que se repite.
    """

    #: `COUNT(...) AS n`, `SUM(x) AS total`… Solo los alias de un agregado: son los que
    #: no existen todavía cuando se evalúa el HAVING. Un `AS x` de tabla no cuenta.
    ALIAS_DE_AGREGADO = re.compile(
        r"\b(?:COUNT|SUM|MIN|MAX|AVG|TOTAL|GROUP_CONCAT|STRING_AGG)\s*\([^()]*(?:\([^()]*\)[^()]*)*\)"
        r"\s+AS\s+([A-Za-z_][A-Za-z_0-9]*)",
        re.IGNORECASE,
    )
    #: El alias usado como operando suelto: `n > 1`. Si aparece dentro del agregado
    #: —`COUNT(DISTINCT workspace_id)` con un alias que se llama igual que la columna—
    #: es la columna, no el alias, y ahí Postgres no protesta.
    OPERANDO = r"(?<![.\w]){0}\s*(?:=|<>|!=|<=|>=|<|>)"

    @staticmethod
    def _clausula_having(texto):
        """El HAVING hasta donde acaba: el paréntesis que cierra su subconsulta, un
        ORDER BY / LIMIT / UNION, o el final. Sin esto se tragaba el resto de la
        consulta y cualquier palabra de después parecía del HAVING."""
        encontrado = re.search(r"\bHAVING\b", texto, re.IGNORECASE)
        if not encontrado:
            return None
        resto = texto[encontrado.end():]
        corte = re.search(r"\b(ORDER\s+BY|LIMIT|UNION|EXCEPT|INTERSECT)\b", resto, re.IGNORECASE)
        if corte:
            resto = resto[: corte.start()]
        profundidad = 0
        for i, ch in enumerate(resto):
            if ch == "(":
                profundidad += 1
            elif ch == ")":
                if profundidad == 0:
                    return resto[:i]
                profundidad -= 1
        return resto

    def test_ningun_having_referencia_un_alias(self):
        sospechosos = []
        for ruta in sorted((RAIZ / "web").glob("*.py")):
            arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
            for nodo in ast.walk(arbol):
                if not isinstance(nodo, ast.Constant) or not isinstance(nodo.value, str):
                    continue
                texto = nodo.value
                if not ES_SQL.search(texto):
                    continue
                clausula = self._clausula_having(texto)
                if not clausula:
                    continue
                usados = sorted(
                    {
                        alias
                        for alias in self.ALIAS_DE_AGREGADO.findall(texto)
                        if re.search(self.OPERANDO.format(re.escape(alias)), clausula, re.IGNORECASE)
                    }
                )
                if usados:
                    sospechosos.append(f"{ruta.name}:{nodo.lineno} -> HAVING usa {usados}")
        self.assertEqual(
            sospechosos,
            [],
            "HAVING que usa un alias del SELECT: válido en SQLite, error en Postgres.\n"
            "Repite la expresión (`HAVING COUNT(*) > 1`) o envuélvelo en una subconsulta.\n"
            + "\n".join(sospechosos),
        )


if __name__ == "__main__":
    unittest.main()
