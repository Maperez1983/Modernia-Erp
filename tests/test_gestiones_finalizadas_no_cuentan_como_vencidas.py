"""«Vencidas: 394» y las 394 filas visibles decían ESTADO = Finalizado.

`gestoria_trabajos.estado` en producción solo usa «Finalizado» —«completado» no
aparece nunca (834 de 834 filas)—. Seis sitios de app.js calculaban «vencido»
comparando `estado !== "completado"`, así que un trabajo ya finalizado con fecha
pasada seguía contando como vencido para siempre: el KPI del cuadro de mando, la
tarjeta de «Bloqueantes», el aviso de SLA en el pipeline y el desglose por
responsable.

No prueba el DOM ni un servidor: lee `web/app.js` como texto y comprueba que cada
sitio que antes comparaba solo contra «completado» ahora pasa por
`esEstadoTrabajoTerminado`, que sí reconoce «finalizado».
"""

import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
APP = (RAIZ / "web" / "app.js").read_text(encoding="utf-8")


class LaFuncionCompartidaTests(unittest.TestCase):
    def test_existe_y_reconoce_los_dos_nombres(self):
        i = APP.index("const esEstadoTrabajoTerminado")
        cuerpo = APP[i : i + 300]
        self.assertIn('"completado"', cuerpo)
        self.assertIn('"finalizado"', cuerpo)


class LosSeisSitiosRotosTests(unittest.TestCase):
    """Cada uno de estos, antes del arreglo, comparaba `estado !== "completado"` a
    secas y por eso el 100% de los trabajos —todos con estado «Finalizado»—
    contaban como vencidos."""

    def test_la_badge_de_sla_en_el_pipeline(self):
        i = APP.index("let slaBadge")
        cuerpo = APP[i : i + 200]
        self.assertIn("esEstadoTrabajoTerminado(estado)", cuerpo)

    def test_el_isdone_del_cuadro_de_mando_de_gestiones(self):
        i = APP.index("const renderGestoriaDashboardGestiones")
        cuerpo = APP[i : i + 700]
        self.assertIn("const isDone = (row) => esEstadoTrabajoTerminado(row?.estado);", cuerpo)

    def test_el_contador_de_completados_del_mismo_cuadro(self):
        i = APP.index("const renderGestoriaDashboardGestiones")
        cuerpo = APP[i : i + 1200]
        self.assertIn("esEstadoTrabajoTerminado(st)", cuerpo)

    def test_las_vencidas_del_cockpit_senior(self):
        i = APP.index("const vencidas = trabajos.filter")
        cuerpo = APP[i : i + 260]
        self.assertIn("esEstadoTrabajoTerminado(estado)", cuerpo)

    def test_las_proximas_del_mismo_cockpit(self):
        i = APP.index("const proximas = trabajos.filter")
        cuerpo = APP[i : i + 260]
        self.assertIn("esEstadoTrabajoTerminado(estado)", cuerpo)

    def test_el_desglose_por_responsable(self):
        i = APP.index("grouped[responsable].total += 1")
        cuerpo = APP[i : i + 300]
        self.assertIn("esEstadoTrabajoTerminado(estado)", cuerpo)


class NoQuedaNingunSitioSueltoTests(unittest.TestCase):
    """Guarda de regresión: si alguien vuelve a escribir `!== "completado"` a
    secas en vez de usar la función compartida, esto debe fallar."""

    SITIOS_YA_CORRECTOS_SIN_TOCAR = (
        # Ya comprobaban "finalizado" antes de este arreglo; no son el bug.
        '["hecho", "completado", "finalizado", "cancelado"].includes(estado)',
        'estado !== "finalizado" && estado !== "cancelado" && estado !== "completado"',
        # La propia función compartida y el Set más completo del cockpit senior.
        'norm === "completado" || norm === "finalizado"',
        'new Set(["completado", "finalizado", "hecho", "cerrado", "presentado", "cancelado"])',
    )

    def test_ninguna_comparacion_suelta_contra_completado(self):
        texto = APP
        for conocido in self.SITIOS_YA_CORRECTOS_SIN_TOCAR:
            self.assertIn(conocido, texto, f"el texto de referencia ya no aparece: {conocido!r}")
            texto = texto.replace(conocido, "")
        self.assertNotIn('!== "completado"', texto)
        self.assertNotIn('=== "completado"', texto)


if __name__ == "__main__":
    unittest.main()
