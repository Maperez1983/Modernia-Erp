"""Seguros salía vacío según qué empresa tuvieras activa.

El mismo fallo que tenía el CRM de hipotecas. `resolveCrmSegurosEmpresa` daba
prioridad a la empresa activa del workspace, así que con "Estudio Velazquez 2012
SL" seleccionada el CRM pedía las pólizas de esa sociedad y encontraba cero.
Medido en producción el 2026-08-03: las **408 pólizas del workspace están en
Fincas Velázquez**, ninguna en Estudio Velázquez.

La matriz de servicios ya dice a qué sociedad pertenece cada CRM. Esa es la
respuesta correcta, y la empresa activa solo debe mandar cuando la matriz no
tiene nada que decir.

El dashboard se arregla igual que el listado: si uno usara la activa y el otro la
del servicio, la misma pantalla enseñaría cifras de dos sociedades distintas.
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


def bloque(nombre):
    i = APP.index(f"const {nombre} = ")
    return APP[i: APP.index("\nconst ", i + 10)]


class LaEmpresaDelServicioMandaTests(unittest.TestCase):
    def test_seguros_consulta_primero_la_matriz(self):
        cuerpo = bloque("resolveCrmSegurosEmpresa")
        primera = cuerpo.index('resolveWorkspaceDefaultEmpresa("seguros")')
        activa = cuerpo.index("state.currentWorkspaceCompanyId")
        self.assertLess(primera, activa, "la empresa activa sigue ganando a la del servicio")

    def test_el_dashboard_de_seguros_usa_la_misma_regla(self):
        cuerpo = bloque("resolveSegurosDashboardEmpresaId")
        self.assertIn('resolveWorkspaceDefaultEmpresa("seguros")', cuerpo)
        primera = cuerpo.index('resolveWorkspaceDefaultEmpresa("seguros")')
        activa = cuerpo.index("state.currentWorkspaceCompanyId")
        self.assertLess(primera, activa)

    def test_la_empresa_activa_sigue_valiendo_de_respaldo(self):
        """Quitarla del todo dejaría sin empresa a los workspaces sin matriz."""
        for nombre in ("resolveCrmSegurosEmpresa", "resolveSegurosDashboardEmpresaId"):
            with self.subTest(nombre=nombre):
                self.assertIn("state.currentWorkspaceCompanyId", bloque(nombre))

    def test_hipotecas_conserva_la_regla_que_ya_tenia(self):
        """La misma corrección se hizo antes en financiaciones; que no se deshaga."""
        cuerpo = bloque("resolveCrmFinEmpresa")
        primera = cuerpo.index('resolveWorkspaceDefaultEmpresa("financiaciones")')
        activa = cuerpo.index("state.currentWorkspaceCompanyId")
        self.assertLess(primera, activa)


class LosCincoCrmResuelvenIgualTests(unittest.TestCase):
    """Que no quede ninguno con la regla vieja.

    Medido en producción el 2026-08-03, con "Estudio Velazquez 2012 SL" activa:

      - gestoría: 1788 de 1840 clientes invisibles (viven en Fincas Velázquez)
      - seguros:  408 de 408 pólizas invisibles (Fincas Velázquez)
      - financiaciones: 110 de 110 hipotecas invisibles (Financiaciones Modernia)
      - inmobiliaria: 0 perdidos hoy, porque la matriz apunta a Estudio Velázquez;
        se cambia igual para que los cinco resuelvan con la misma regla.
    """

    CASOS = {
        "resolveCrmFinEmpresa": "financiaciones",
        "resolveCrmSegurosEmpresa": "seguros",
        "resolveCrmGestoriaEmpresa": "gestoria",
        "resolveCrmInmoEmpresa": "inmobiliaria",
    }

    def test_la_matriz_va_antes_que_la_empresa_activa(self):
        for funcion, servicio in self.CASOS.items():
            with self.subTest(funcion=funcion):
                cuerpo = bloque(funcion)
                primera = cuerpo.index(f'resolveWorkspaceDefaultEmpresa("{servicio}")')
                activa = cuerpo.index("state.currentWorkspaceCompanyId")
                self.assertLess(
                    primera,
                    activa,
                    f"{funcion} deja ganar a la empresa activa sobre la del servicio",
                )


if __name__ == "__main__":
    unittest.main()
