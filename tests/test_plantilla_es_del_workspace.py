"""La plantilla de RRHH se acotaba por la empresa activa, y eso escondía gente.

Con Estudio Velázquez seleccionada, dos personas desaparecían del equipo:

  - Daniel García Campos, sin `empresa_id` asignado.
  - Teresa Ramos, cuya ficha es de Fincas Velázquez.

Los dos trabajan en Modernia. El servicio en el que trabajan —inmobiliaria y
gestoría— vive en su cuenta de usuario, no en el `empresa_id` de la ficha, así
que la sociedad no debería sacarles del equipo.

Y no desaparecían del todo, que es lo peor: su tarjeta de usuario seguía saliendo
con la etiqueta "Sin ficha" teniendo ficha, con NIF y bien enlazada. Eso invita a
crear una ficha nueva y duplicar a la persona.

El filtro no estaba solo en el cliente: la plantilla llega del arranque del
workspace, y esa petición ya lleva `empresa_id`. Por eso el módulo de RRHH pide
la suya aparte, sin acotar.
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class LaPlantillaSePideSinEmpresaTests(unittest.TestCase):
    def _peticion(self):
        i = APP.index("state.workspaceRrhhRosterRows = ")
        j = APP.rindex("/api/workspace_registro_personal?workspace_id=", 0, i)
        return APP[j: APP.index("\n", j)]

    def test_la_peticion_de_plantilla_no_lleva_empresa(self):
        self.assertNotIn("companyQuery", self._peticion())
        self.assertNotIn("empresa_id", self._peticion())

    def test_incluye_las_bajas(self):
        # Hacen falta para "Ver bajas"; el registro se conserva cuatro años.
        self.assertIn("activos=0", self._peticion())

    def test_la_cuadricula_usa_esa_lista(self):
        self.assertIn(
            "const employeesAll = Array.isArray(state.workspaceRrhhRosterRows) && state.workspaceRrhhRosterRows.length",
            APP,
        )

    def test_hay_respaldo_si_aun_no_ha_llegado(self):
        i = APP.index("const employeesAll = Array.isArray(state.workspaceRrhhRosterRows)")
        self.assertIn("state.workspaceTimeEmployees", APP[i: i + 400])

    def test_sigue_quitando_las_fichas_automaticas(self):
        # Eso no era el problema y no se toca.
        self.assertIn('.filter((row) => String(row?.source || "").trim() !== "auto")', APP)


class ElServidorDevuelveLaPlantillaEnteraTests(unittest.TestCase):
    """Sin `empresa_id`, `fetch_workspace_personal` no puede dejar fuera a nadie."""

    def _funcion(self):
        i = SERVER.index("def fetch_workspace_personal")
        return SERVER[i: SERVER.index("\ndef ", i + 10)]

    def test_sin_empresa_incluye_las_fichas_sin_empresa(self):
        f = self._funcion()
        self.assertIn("p.empresa_id IS NULL OR TRIM(COALESCE(p.empresa_id, '')) = ''", f)

    def test_sin_empresa_no_se_exige_asignacion_manual(self):
        # `empresa_manual = 1` solo aplica a la vista por empresa; si se colara en la
        # vista de equipo volvería a esconder gente.
        f = self._funcion()
        corte = f.index("if requested_company:")
        rama_con_empresa = f[corte: f.index("else:", corte)]
        rama_sin_empresa = f[f.index("else:", corte): f.index("if only_active:")]
        self.assertIn("COALESCE(p.empresa_manual, 0) = 1", rama_con_empresa)
        self.assertNotIn("empresa_manual", rama_sin_empresa)


if __name__ == "__main__":
    unittest.main()
