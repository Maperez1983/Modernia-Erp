"""Un `workspace_id` que llega en el cuerpo no prueba nada.

Muchos endpoints leen el workspace del propio payload y lo usan tal cual para
filtrar o para escribir. Eso solo es seguro si además se comprueba que **quien
llama** pertenece a ese workspace. Si no, basta con conocer el id de otro tenant.

Encontrado auditando fincas el 2026-08-04. `workspace_fincas_comunidad_delete`
iba directo del payload al SQL:

    workspace_id = str(payload.get("workspace_id") or "").strip()
    row = conn.execute("SELECT ... WHERE id = ? AND workspace_id = ?", ...)
    ...  # y a borrar

Comprobar que la comunidad pertenece a ese workspace no comprueba nada sobre el
que la borra. Y no hay ninguna puerta genérica antes de los manejadores: las 18
llamadas a `enforce_workspace_membership` del tramo previo están todas dentro de
un manejador concreto.

Este test cubre el módulo de fincas, que es el que se ha revisado y arreglado.
Quedan 44 manejadores más con el mismo patrón, 28 de ellos de escritura; están
listados en la auditoría y pendientes de repasar uno a uno, porque algunos
necesitan permiso de escritura y otros no, y eso no se decide en bloque.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")


def manejadores_post():
    """Trocea `_do_POST` en (ruta, cuerpo) por cada `if parsed.path == ...`."""
    i = SERVER.index("def _do_POST")
    cuerpo = SERVER[i:]
    anclas = [
        (m.start(), m.group(1))
        for m in re.finditer(r'(?:el)?if parsed\.path == "(/api/[a-z0-9_/]+)"', cuerpo)
    ]
    for k, (pos, ruta) in enumerate(anclas):
        fin = anclas[k + 1][0] if k + 1 < len(anclas) else len(cuerpo)
        yield ruta, cuerpo[pos:fin]


class NingunEndpointDeFincasSeFiaDelCuerpoTests(unittest.TestCase):
    def test_todos_comprueban_pertenencia(self):
        desnudos = [
            ruta
            for ruta, cuerpo in manejadores_post()
            if "fincas" in ruta
            and 'payload.get("workspace_id")' in cuerpo
            and "enforce_workspace_membership" not in cuerpo
        ]
        self.assertEqual(
            desnudos,
            [],
            "endpoints de fincas que usan el workspace del cuerpo sin comprobar "
            "que quien llama pertenece a él:\n  " + "\n  ".join(desnudos),
        )

    def test_el_borrado_de_comunidades_exige_escritura(self):
        cuerpo = next(c for r, c in manejadores_post() if r.endswith("fincas_comunidad_delete"))
        self.assertIn("enforce_workspace_membership(conn, session, workspace_id, write=True)", cuerpo)

    def test_la_comprobacion_va_antes_de_tocar_la_base(self):
        """De poco sirve comprobar después de haber borrado."""
        cuerpo = next(c for r, c in manejadores_post() if r.endswith("fincas_comunidad_delete"))
        guarda = cuerpo.index("enforce_workspace_membership")
        borrado = cuerpo.index("DELETE FROM")
        self.assertLess(guarda, borrado)


class NoHayPuertaGenericaAsiQueCadaUnoSeGuardaTests(unittest.TestCase):
    """Si algún día se añade una puerta común, este test lo detecta y sobra el resto.

    Mientras no la haya, cada manejador es responsable de comprobarlo, y por eso el
    test de arriba tiene sentido.
    """

    def test_las_comprobaciones_viven_dentro_de_los_manejadores(self):
        sueltas = 0
        i = SERVER.index("def _do_POST")
        cuerpo = SERVER[i:]
        primera = cuerpo.index('if parsed.path == "/api/')
        # Todo lo anterior al primer manejador es el tramo común.
        if "enforce_workspace_membership" in cuerpo[:primera]:
            sueltas += 1
        self.assertEqual(
            sueltas,
            0,
            "hay una comprobación de pertenencia en el tramo común: revisa si este "
            "test y el de fincas siguen haciendo falta",
        )


if __name__ == "__main__":
    unittest.main()
