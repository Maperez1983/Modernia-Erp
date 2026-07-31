"""La plantilla de RRHH se acotaba por la empresa activa, y eso escondía gente.

Con Estudio Velázquez seleccionada, dos personas desaparecían del equipo:

  - Daniel García Campos, sin `empresa_id` asignado.
  - Teresa Ramos, cuya ficha es de Fincas Velázquez.

Y no desaparecían del todo: su tarjeta de usuario seguía saliendo, pero con la
etiqueta "Sin ficha" — teniendo ficha, con NIF y bien enlazada. Peor que faltar,
porque invita a crear una ficha nueva y duplicar a la persona.

Es el mismo patrón que dejó 2014 clientes invisibles: acotar por empresa dentro
de un workspace donde el ámbito real es el workspace. Los dos trabajan en
Modernia; en qué sociedad estén no los saca del equipo.
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


class LaPlantillaNoSeAcotaPorEmpresaTests(unittest.TestCase):
    def _bloque(self):
        i = APP.index("const employeesAll =")
        return APP[i - 400: i + 500]

    def test_lee_la_lista_del_workspace(self):
        self.assertIn(
            "const employeesAll = Array.isArray(state.currentWorkspaceData?.timeEmployees)",
            APP,
        )

    def test_no_parte_de_la_lista_ya_filtrada_por_empresa(self):
        bloque = self._bloque()
        # `workspaceTimeEmployees` solo queda como respaldo si aún no hay datos crudos.
        primera = bloque.index("const employeesAll =")
        eleccion = bloque[primera: bloque.index("const employees =", primera)]
        self.assertLess(
            eleccion.index("currentWorkspaceData?.timeEmployees"),
            eleccion.index("state.workspaceTimeEmployees"),
            "la lista del workspace tiene que ir primero; la filtrada solo de respaldo",
        )

    def test_sigue_quitando_las_fichas_automaticas(self):
        # Eso no era el problema y no se toca.
        self.assertIn('.filter((row) => String(row?.source || "").trim() !== "auto")', APP)


if __name__ == "__main__":
    unittest.main()
