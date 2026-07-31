"""Trece endpoints no comprobaban a qué workspace pertenecías.

Autorizaban con `workspace_session_is_privileged(session)`, que solo mira el rol
de la sesión y NO recibe el `workspace_id`: no puede comprobar pertenencia. Once
de los trece eran de RRHH — nóminas, ausencias, documentos personales, ficha del
empleado — más la exportación del registro de jornada y el borrado de fichas.

Combinado con que en producción los 6 usuarios activos eran `Administrador`,
cualquiera podía leer, exportar o modificar datos de RRHH de cualquier persona de
cualquiera de los cuatro workspaces. El panel llama a los workspaces "clientes
operativos": con un cliente externo dentro, eso es acceso entre tenants.

`workspace_delete` NO estaba afectado aunque el primer barrido lo señalara: exige
además superadmin de allowlist, confirmación tecleada y tiene lista de protegidos.
"""

import re
import unittest
from pathlib import Path

SERVER = (Path(__file__).resolve().parents[1] / "web" / "server.py").read_text(encoding="utf-8")

AFECTADOS = [
    "/api/workspace_kiosk_token",
    "/api/workspace_registro_personal_delete",
    "/api/workspace_rrhh_profile",
    "/api/workspace_rrhh_turnos",
    "/api/workspace_rrhh_ausencia",
    "/api/workspace_rrhh_ausencia_estado",
    "/api/workspace_rrhh_gasto",
    "/api/workspace_rrhh_gasto_estado",
    "/api/workspace_rrhh_documento",
    "/api/workspace_rrhh_nomina_ocr",
    "/api/workspace_registro_alerts",
    "/api/workspace_registro_horario_pdf",
    "/api/workspace_registro_horario_xlsx",
]


def _bloques():
    marcas = [(m.start(), m.group(1)) for m in
              re.finditer(r'(?:if path == |elif parsed\.path == )"(/api/[a-z_0-9]+)":', SERVER)]
    marcas.append((len(SERVER), "FIN"))
    salida = {}
    for i in range(len(marcas) - 1):
        ini, ruta = marcas[i]
        salida.setdefault(ruta, []).append(SERVER[ini: marcas[i + 1][0]])
    return salida


class NingunEndpointAutorizaSoloPorRolTests(unittest.TestCase):
    def test_barrido_general(self):
        """Ninguno que reciba workspace_id puede autorizar solo por rol de sesión.

        Se barre todo el fichero, no una lista: así también salta si alguien añade
        un endpoint nuevo con el mismo patrón.
        """
        colados = []
        for ruta, bloques in _bloques().items():
            for b in bloques:
                if "workspace_session_is_privileged(session)" not in b:
                    continue
                if "workspace_id" not in b:
                    continue
                if "enforce_workspace_membership" in b or "workspace_actor_can_manage_workspace" in b:
                    continue
                if "workspace_actor_is_privileged" in b:  # superadmin: control más fuerte
                    continue
                colados.append(ruta)
        self.assertEqual(sorted(set(colados)), [], "autorizan sin comprobar el workspace")

    def test_los_trece_conocidos_comprueban_pertenencia(self):
        bloques = _bloques()
        for ruta in AFECTADOS:
            with self.subTest(endpoint=ruta):
                self.assertIn(ruta, bloques, "el endpoint desapareció")
                juntos = "".join(bloques[ruta])
                self.assertIn("workspace_actor_can_manage_workspace", juntos)

    def test_la_autorizacion_va_despues_de_leer_el_workspace(self):
        """El orden importa: comprobar antes de saber sobre qué se actúa no sirve."""
        bloques = _bloques()
        for ruta in AFECTADOS:
            for b in bloques.get(ruta, []):
                if "workspace_actor_can_manage_workspace" not in b:
                    continue
                with self.subTest(endpoint=ruta):
                    pos_check = b.index("workspace_actor_can_manage_workspace")
                    antes = b[:pos_check]
                    self.assertRegex(
                        antes, r"workspace_id\s*=",
                        f"{ruta} autoriza antes de leer workspace_id",
                    )


class WorkspaceDeleteSigueProtegidoTests(unittest.TestCase):
    """No estaba afectado, y su control no debe debilitarse al tocar lo demás."""

    def _bloque(self):
        i = SERVER.index('elif parsed.path == "/api/workspace_delete":')
        return SERVER[i: SERVER.index("elif parsed.path ==", i + 100)]

    def test_exige_superadmin_y_confirmacion(self):
        b = self._bloque()
        self.assertIn("workspace_actor_is_privileged", b)
        self.assertIn('confirm != "ELIMINAR"', b)

    def test_mantiene_la_lista_de_protegidos(self):
        self.assertIn("protected", self._bloque())


if __name__ == "__main__":
    unittest.main()
