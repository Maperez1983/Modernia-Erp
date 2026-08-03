"""El CRM de hipotecas pedía las hipotecas de la empresa activa, no de la suya.

En producción, con Estudio Velázquez como empresa activa, el dashboard de
financiaciones salía vacío y el desplegable de ejercicios no tenía ni un año. No
era un fallo de datos: las 110 hipotecas están en Financiaciones Modernia, y la
matriz de servicios ya dice `financiaciones -> Financiaciones Modernia` marcada
como predeterminada.

`resolveCrmFinEmpresa` preguntaba primero por la empresa activa del workspace, y
esa rama devolvía Estudio Velázquez antes de mirar la matriz. Todo lo que había
debajo —la empresa configurada, la guardada, la del mapa de servicios— quedaba
inalcanzable en modo tenant.
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


class LaEmpresaDelServicioMandaTests(unittest.TestCase):
    def _funcion(self):
        i = APP.index("const resolveCrmFinEmpresa = () => {")
        return APP[i: APP.index("\n};", i)]

    def test_se_consulta_la_matriz_antes_que_la_empresa_activa(self):
        f = self._funcion()
        self.assertLess(
            f.index('resolveWorkspaceDefaultEmpresa("financiaciones")'),
            f.index("currentWorkspaceCompanyId"),
            "la empresa del servicio tiene que resolverse antes que la activa",
        )

    def test_la_empresa_activa_sigue_valiendo_de_respaldo(self):
        # Si el servicio no tiene empresa configurada, se sigue usando la activa.
        f = self._funcion()
        self.assertIn("isTenantWorkspaceMode()", f)
        self.assertIn("currentWorkspaceCompanyId", f)

    def test_queda_escrito_el_sintoma(self):
        # Para que nadie lo revierta pensando que la activa debe mandar siempre.
        self.assertIn("El dashboard salía vacío", self._funcion())


class ElMismoPatronEnOtrosServiciosTests(unittest.TestCase):
    """Seguros hace lo mismo y de momento se deja como está.

    No se toca sin comprobarlo en pantalla: cambiarlo mueve de empresa a un CRM
    entero, y ya hemos visto hoy lo que pasa al dar por bueno un cambio de ámbito
    sin verlo funcionando.
    """

    def test_seguros_sigue_prefiriendo_la_activa(self):
        i = APP.index("const resolveCrmSegurosEmpresa = () => {")
        f = APP[i: APP.index("\n};", i)]
        self.assertIn("currentWorkspaceCompanyId", f)


if __name__ == "__main__":
    unittest.main()
