"""RRHH · Equipo decía "Sin ficha" a quien la tenía, mientras cargaba.

Equipo se pinta primero con la lista filtrada por la empresa activa, y la plantilla
completa llega después en una petición aparte (arreglo del 2026-07-31). En ese
intervalo, alguien sin empresa asignada no aparece en la lista filtrada y su tarjeta
decía "Sin ficha" en ámbar, lo que invita a crearle otra ficha y duplicarlo. Se vio el
2026-09-18 con Daniel García Campos, que tiene ficha en Modernia y ninguna empresa.
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


def _bloque(inicio, fin):
    i = APP.index(inicio)
    return APP[i : APP.index(fin, i)]


class MientrasCargaNoDiceSinFichaTests(unittest.TestCase):
    def test_equipo_usa_la_etiqueta_de_carga(self):
        equipo = _bloque("const renderEquipo = () => {", "const renderHorario = () => {")
        self.assertIn("const plantillaPendiente = isWorkspaceRrhhRosterPending();", equipo)
        self.assertIn('plantillaPendiente ? "Cargando…" : "Sin ficha"', equipo)
        # Ni la tarjeta ni el detalle vuelven a escribir "Sin ficha" a pelo.
        self.assertNotIn('"Baja") : "Sin ficha"', equipo)
        self.assertNotIn('? "Sin empresa" : "Sin ficha"', equipo)
        self.assertNotIn('"En plantilla" : "Sin ficha"', equipo)

    def test_mientras_carga_no_se_pinta_en_ambar(self):
        equipo = _bloque("const renderEquipo = () => {", "const renderHorario = () => {")
        self.assertIn('m.hasFicha || plantillaPendiente ? "rrhh-pill" : "rrhh-pill rrhh-pill-warn"', equipo)

    def test_una_plantilla_vacia_o_fallida_no_deja_cargando_para_siempre(self):
        carga = _bloque("const loadWorkspaceRrhhRoster = async () => {", "const loadRrhhKpis")
        corte = carga.index("rosterRrhhIntentado.add(wsId);")
        self.assertLess(corte, carga.index("if (!filas.length) {"))
        # Repinta una sola vez: si repintara siempre, cada repintado pediría otra vez.
        self.assertIn("if (primerIntento) renderWorkspaceRrhhHub();", carga)


if __name__ == "__main__":
    unittest.main()
