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
workspace, y esa petición ya lleva `empresa_id`. Meterla en la carga general de
RRHH tampoco bastó, porque esa carga se descarta cuando llega otra más nueva
(`isStale`) y la lista nunca llegaba a estado. Se pide aparte, como los KPIs, y
se repinta al llegar.
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class LaPlantillaSePideSinEmpresaTests(unittest.TestCase):
    def _peticion(self):
        i = APP.index("const loadWorkspaceRrhhRoster = async () => {")
        return APP[i: APP.index("};", i)]

    def test_la_peticion_de_plantilla_no_lleva_empresa(self):
        self.assertNotIn("companyQuery", self._peticion())
        self.assertNotIn("empresa_id", self._peticion())

    def test_incluye_las_bajas(self):
        # Hacen falta para "Ver bajas"; el registro se conserva cuatro años.
        self.assertIn("activos=0", self._peticion())

    def test_repinta_cuando_llega(self):
        """Llega después del primer pintado; sin repintar no se vería."""
        bloque = self._peticion()
        self.assertIn("renderWorkspaceRrhhHub();", bloque)

    def test_no_se_pide_en_bucle(self):
        # Repintar vuelve a llamar al cargador: sin centinela sería un bucle.
        bloque = self._peticion()
        self.assertIn("if (!wsId || peticionRosterRrhh) return;", bloque)
        self.assertIn("if (yaEsta) return;", bloque)

    def test_se_llama_al_pintar_el_modulo(self):
        self.assertIn("loadWorkspaceRrhhRoster();", APP)

    def test_la_cuadricula_une_las_tres_fuentes(self):
        """Elegir una sola lista dependía del orden de carga.

        Con Estudio Velázquez activa se veían 9 de 11: las bajas que mostraba eran
        exactamente las 6 de esa sociedad, y las 5 de Fincas Velázquez no salían.
        Unir por id es lo único que no depende de cuál llegue antes.
        """
        i = APP.index("const employeesAll = (() => {")
        bloque = APP[i: APP.index("})();", i)]
        for fuente in ("state.workspaceRrhhRosterRows",
                       "state.currentWorkspaceData?.timeEmployees",
                       "state.workspaceTimeEmployees"):
            with self.subTest(fuente=fuente):
                self.assertIn(fuente, bloque)

    def test_no_duplica_a_nadie_al_unirlas(self):
        i = APP.index("const employeesAll = (() => {")
        bloque = APP[i: APP.index("})();", i)]
        self.assertIn("if (id && !porId.has(id)) porId.set(id, fila);", bloque)

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
