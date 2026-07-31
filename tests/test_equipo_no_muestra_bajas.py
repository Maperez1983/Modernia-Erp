"""Dar de baja a alguien y seguir viéndolo como "En plantilla".

El día después de dar de baja a Lucas Narváez y a Rubén Miera, la cuadrícula de
Equipo los seguía mostrando con la etiqueta "En plantilla". El dato estaba bien
en la base —`activo = 0`— pero la pantalla no lo miraba:

    activo: Number(emp.activo ?? 1) === 1,     // se calculaba...
    const filtered = members.filter((m) => {   // ...y no se usaba
      if (!query) return true;

Y la etiqueta salía de `hasFicha`, que es cierto para cualquier ficha, esté
activa o no. En una pantalla que se llama "plantilla", eso es decir que un
extrabajador sigue contratado.

Las bajas no se esconden del todo: el registro de jornada hay que poder
consultarlo cuatro años, así que quedan detrás de "Ver bajas".
"""

import unittest
from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")


def _bloque_equipo():
    i = APP.index("const renderMemberList = ()")
    return APP[i - 3000: APP.index("const renderMemberDetail", i) if "const renderMemberDetail" in APP[i:] else i + 12000]


class LaCuadriculaDeEquipoTests(unittest.TestCase):
    def test_las_bajas_quedan_fuera_por_defecto(self):
        self.assertIn("if (!incluirBajas && m.hasFicha && !m.activo) return false;", APP)

    def test_pero_se_pueden_ver(self):
        self.assertIn('id="workspaceRrhhRosterIncluirBajas"', APP)
        self.assertIn("state.workspaceRrhhRosterIncluirBajas = Boolean(rosterBajas.checked);", APP)

    def test_el_interruptor_arranca_apagado(self):
        self.assertIn("workspaceRrhhRosterIncluirBajas: false,", APP)

    def test_la_etiqueta_no_dice_que_sigue_en_plantilla(self):
        self.assertIn('const status = m.hasFicha ? (m.activo ? "En plantilla" : "Baja") : "Sin ficha";', APP)

    def test_una_busqueda_sin_resultados_no_resucita_a_las_bajas(self):
        # El respaldo `filtered.length ? filtered : members` enseñaba la lista entera
        # —bajas incluidas— en cuanto una búsqueda no encontraba a nadie.
        self.assertNotIn("filtered.length ? filtered : members", APP)

    def test_se_cuentan_las_bajas_para_no_esconderlas_sin_avisar(self):
        self.assertIn("const bajas = members.filter((m) => m.hasFicha && !m.activo).length;", APP)
        self.assertIn("Ver bajas (${bajas})", APP)


if __name__ == "__main__":
    unittest.main()
