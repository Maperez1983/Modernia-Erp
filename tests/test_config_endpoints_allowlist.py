"""Regresión: los endpoints POST de configuración del workspace deben estar en el
allowlist de rutas de _do_POST.

_do_POST empieza con `if parsed.path not in ( ...tuple... ): return 404 "Endpoint
no valido"`. Si un handler existe (elif parsed.path == "/api/x") pero su ruta no
está en ese allowlist, el endpoint es INALCANZABLE (404) aunque el código exista.
Fue el caso de workspace_company_create/update y workspace_link_upsert/delete:
crear/editar empresa y crear/borrar vínculos daban 404 en producción.
"""
import re
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "web" / "server.py"

# Endpoints de escritura de la home de configuración del workspace.
CONFIG_POST_ENDPOINTS = [
    "/api/empresa_update",
    "/api/empresa_delete",
    "/api/workspace_empresa_link",
    "/api/workspace_empresa_unlink",
    "/api/workspace_company_create",
    "/api/workspace_company_update",
    "/api/workspace_company_logo_upload",
    "/api/workspace_member_upsert",
    "/api/workspace_member_delete",
    "/api/workspace_members_reset",
    "/api/workspace_customer_create",
    "/api/workspace_update",
    "/api/workspace_delete",
    "/api/workspace_module_update",
    "/api/workspace_link_upsert",
    "/api/workspace_link_delete",
]


def _extract_post_allowlist(source: str) -> set:
    """Extrae las rutas /api/... del tuple `if parsed.path not in ( ... ):`."""
    start = source.index("if parsed.path not in (")
    # El tuple cierra en la primera línea que sea exactamente "):" (con indentación).
    rest = source[start:]
    end = re.search(r"\n\s*\):", rest)
    assert end, "No se encontró el cierre del allowlist de _do_POST"
    block = rest[: end.start()]
    return set(re.findall(r'"(/api/[^"]+)"', block))


class ConfigEndpointsAllowlistTests(unittest.TestCase):
    def setUp(self):
        self.source = SERVER.read_text(encoding="utf-8", errors="ignore")
        self.allowlist = _extract_post_allowlist(self.source)

    def test_todos_los_endpoints_de_config_tienen_handler(self):
        for ep in CONFIG_POST_ENDPOINTS:
            self.assertIn(
                f'parsed.path == "{ep}"',
                self.source,
                f"Falta el handler de {ep} en server.py",
            )

    def test_todos_los_endpoints_de_config_estan_en_el_allowlist(self):
        faltan = [ep for ep in CONFIG_POST_ENDPOINTS if ep not in self.allowlist]
        self.assertEqual(
            faltan,
            [],
            f"Endpoints de configuración con handler pero AUSENTES del allowlist "
            f"(darían 404 'Endpoint no valido'): {faltan}",
        )


if __name__ == "__main__":
    unittest.main()
