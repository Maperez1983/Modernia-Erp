"""Una referencia a un formulario que ya no existe tumbaba todos los demás.

`hydrateWorkspaceCompanySelects` recorre una lista de formularios para rellenar su
desplegable de empresa. Al resolver la fusión 453042d (2026-09-04) se perdió el `const`
de `workspacePericialForm`, pero la referencia siguió en la lista. Montar la lista
lanzaba un ReferenceError antes de recorrerla: ningún formulario recibía sus empresas,
y facturas, presupuestos, series, remesas, bandeja, registro horario y la ficha de
empresa se cortaban a medias. Producción lo registró dos semanas como
"workspacePericialForm is not defined" hasta que se miró el 2026-09-18.
"""

import re
import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


class FormulariosDeEmpresaDeclaradosTests(unittest.TestCase):
    def _lista(self):
        i = APP.index("const hydrateWorkspaceCompanySelects = () => {")
        inicio = APP.index("[", APP.index("const html =", i))
        fin = APP.index("].forEach(", inicio)
        cuerpo = re.sub(r"(?m)//[^\n]*", "", APP[inicio + 1 : fin])
        return [n.strip() for n in cuerpo.split(",") if n.strip()]

    def test_la_lista_no_esta_vacia(self):
        self.assertGreaterEqual(len(self._lista()), 5)

    def test_cada_formulario_de_la_lista_esta_declarado(self):
        for nombre in self._lista():
            with self.subTest(formulario=nombre):
                self.assertRegex(
                    APP,
                    rf"\b(?:const|let|var)\s+{re.escape(nombre)}\b",
                    f"{nombre} se usa en hydrateWorkspaceCompanySelects pero no está declarado",
                )

    def test_el_formulario_pericial_ya_no_esta(self):
        self.assertNotIn("workspacePericialForm", self._lista())


if __name__ == "__main__":
    unittest.main()
