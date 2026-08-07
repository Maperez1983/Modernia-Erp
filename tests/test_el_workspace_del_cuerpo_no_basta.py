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
que la borra. Y no hay ninguna puerta genérica antes de los manejadores: las
llamadas a `enforce_workspace_membership` están todas dentro de un manejador
concreto, así que cada uno es responsable de la suya.

El repaso completo salió a 16 manejadores con este patrón —no a los 44 que dio un
primer barrido, que contaba como desnudos los que se guardan con otra función—, y
de esos 16 hicieron falta 10 arreglos. Los tres que quedan sin comprobar están en
`SE_GUARDAN_DE_OTRA_FORMA` con el motivo de cada uno; si alguien añade un cuarto
sin justificarlo, este test lo caza.
"""

import re
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
SERVER = (RAIZ / "web" / "server.py").read_text(encoding="utf-8")

# Las nueve funciones que sí atan al que llama con el tenant. Un manejador que use
# cualquiera de ellas está comprobando algo; el barrido solo busca los que no usan
# ninguna.
GUARDIANES = (
    "enforce_workspace_membership",
    "workspace_actor_can_manage_workspace",
    "workspace_actor_is_privileged",
    "workspace_session_is_privileged",
    "is_superadmin_actor",
    "enforce_empresa_membership",
    "resolve_scoped_record_access",
    "resolve_cliente_scope_access",
    "ensure_partner_membership",
    "_auth_allowed_services",
)

SE_GUARDAN_DE_OTRA_FORMA = {
    "/api/auth_set_password": (
        "es público a propósito: se entra con un token de un solo uso, no con sesión, "
        "y el workspace solo sirve para saber a qué marca pertenece el enlace"
    ),
    "/api/workspace_registro_personal_self_photo": (
        "solo escribe sobre la fila del propio `session.user_id`; el workspace del "
        "cuerpo no elige a quién se le cambia la foto"
    ),
    "/api/legal_copilot": (
        "no toca datos del tenant: consulta el corpus legal filtrando por `area`"
    ),
}


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


def se_fian_del_cuerpo():
    for ruta, cuerpo in manejadores_post():
        if 'payload.get("workspace_id")' not in cuerpo:
            continue
        if any(g in cuerpo for g in GUARDIANES):
            continue
        yield ruta, cuerpo


class NingunEndpointSeFiaDelCuerpoTests(unittest.TestCase):
    def test_todos_comprueban_pertenencia(self):
        desnudos = [ruta for ruta, _ in se_fian_del_cuerpo()]
        sin_justificar = [r for r in desnudos if r not in SE_GUARDAN_DE_OTRA_FORMA]
        self.assertEqual(
            sin_justificar,
            [],
            "endpoints que usan el workspace del cuerpo sin comprobar que quien "
            "llama pertenece a él:\n  " + "\n  ".join(sin_justificar),
        )

    def test_las_excepciones_siguen_existiendo(self):
        """Si una se arregla o se borra, que se caiga de la lista y no quede de coartada."""
        rutas = {ruta for ruta, _ in manejadores_post()}
        for ruta in SE_GUARDAN_DE_OTRA_FORMA:
            self.assertIn(ruta, rutas, f"{ruta} ya no existe: quítalo de la lista")

    def test_ninguna_excepcion_borra_nada(self):
        """Leer sin comprobar es discutible; borrar sin comprobar, no."""
        for ruta, cuerpo in se_fian_del_cuerpo():
            self.assertNotIn("DELETE FROM", cuerpo, f"{ruta} borra sin comprobar pertenencia")

    def test_los_de_fincas_estan_todos_cubiertos(self):
        """El módulo donde apareció el fallo, por si acaso."""
        desnudos = [r for r, _ in se_fian_del_cuerpo() if "fincas" in r]
        self.assertEqual(desnudos, [])


class LasEscriturasExigenPermisoDeEscrituraTests(unittest.TestCase):
    """`write=True` no es decorativo: un invitado de solo lectura no debe escribir."""

    ESCRITORES = (
        "/api/workspace_fincas_comunidad_delete",
        "/api/workspace_cobros",
        "/api/workspace_remesas",
        "/api/workspace_series",
        "/api/workspace_inbox",
        "/api/workspace_inbox_review",
        "/api/workspace_portal",
        "/api/workspace_portal_requerimientos",
        "/api/workspace_automatizaciones",
        "/api/workspace_presupuestos",
    )

    def test_todos_piden_escritura(self):
        cuerpos = dict(manejadores_post())
        for ruta in self.ESCRITORES:
            with self.subTest(ruta=ruta):
                self.assertIn(
                    "write=True",
                    cuerpos[ruta],
                    f"{ruta} escribe pero comprueba la pertenencia sin exigir escritura",
                )

    def test_la_comprobacion_va_antes_de_tocar_la_base(self):
        """De poco sirve comprobar después de haber borrado."""
        cuerpos = dict(manejadores_post())
        for ruta in self.ESCRITORES:
            cuerpo = cuerpos[ruta]
            toques = [
                m.start()
                for m in re.finditer(r"\b(DELETE FROM|INSERT INTO|UPDATE )\s", cuerpo)
            ]
            if not toques:
                continue
            with self.subTest(ruta=ruta):
                self.assertLess(cuerpo.index("enforce_workspace_membership"), min(toques))


class NoHayPuertaGenericaAsiQueCadaUnoSeGuardaTests(unittest.TestCase):
    """Si algún día se añade una puerta común, este test lo detecta y sobra el resto.

    Mientras no la haya, cada manejador es responsable de comprobarlo, y por eso el
    test de arriba tiene sentido.
    """

    def test_las_comprobaciones_viven_dentro_de_los_manejadores(self):
        i = SERVER.index("def _do_POST")
        cuerpo = SERVER[i:]
        primera = cuerpo.index('if parsed.path == "/api/')
        # Todo lo anterior al primer manejador es el tramo común.
        self.assertNotIn(
            "enforce_workspace_membership",
            cuerpo[:primera],
            "hay una comprobación de pertenencia en el tramo común: revisa si este "
            "test y el de los manejadores siguen haciendo falta",
        )


if __name__ == "__main__":
    unittest.main()
