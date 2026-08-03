"""Un solo estado por concepto en el CRM hipotecario.

En producción convivían "FIRMADA" (46) y "Firmada" (21), y "ESTUDIO" con
"Estudio". Las consultas de firmadas usan LOWER(), así que no rompían ningún
cálculo, pero cualquier informe agrupado por estado enseñaba la misma cosa dos
veces con el dinero partido: 130.300 € en una fila y 59.400 € en otra, cuando
son 189.700 € de comisiones firmadas.

El origen estaba en el alta, que usaba "FIRMADA" como valor por defecto mientras
el resto de la aplicación escribe en capitalización normal.
"""

import unittest
from pathlib import Path

from web import server

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")


class CanonizarElEstadoTests(unittest.TestCase):
    def test_unifica_mayusculas(self):
        for crudo in ("FIRMADA", "firmada", "  Firmada  ", "FiRmAdA"):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.canonical_hipoteca_estado(crudo), "Firmada")

    def test_unifica_acentos(self):
        for crudo in ("INDEMNIZACIÓN", "indemnizacion", "Indemnizacion"):
            with self.subTest(crudo=crudo):
                self.assertEqual(server.canonical_hipoteca_estado(crudo), "Indemnización")

    def test_no_inventa_equivalencias(self):
        """"CAIDA" no es "Cancelada": cambiar eso sería cambiar el significado."""
        self.assertEqual(server.canonical_hipoteca_estado("CAIDA"), "CAIDA")
        self.assertEqual(server.canonical_hipoteca_estado("lo que sea"), "lo que sea")

    def test_el_vacio_sigue_vacio(self):
        self.assertEqual(server.canonical_hipoteca_estado(""), "")
        self.assertEqual(server.canonical_hipoteca_estado(None), "")

    def test_cubre_todo_el_catalogo(self):
        for canonico in server.HIPOTECA_BDT_STATE_ORDER:
            with self.subTest(estado=canonico):
                self.assertEqual(server.canonical_hipoteca_estado(canonico.upper()), canonico)


class LaEscrituraCanonizaTests(unittest.TestCase):
    def test_el_alta_ya_no_guarda_en_mayusculas(self):
        # Era el origen del lío: `payload.get("estado", "FIRMADA")`.
        self.assertNotIn('payload.get("estado", "FIRMADA")', SERVER)
        self.assertIn('canonical_hipoteca_estado(payload.get("estado") or "Firmada")', SERVER)

    def test_ninguna_escritura_guarda_el_estado_en_crudo(self):
        self.assertNotIn('(payload.get("estado") or None),', SERVER)


if __name__ == "__main__":
    unittest.main()
