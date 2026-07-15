"""
Regresiones para el hallazgo crítico de escalada de privilegios.

Estos tests describen el comportamiento seguro esperado. Con el código actual,
deben fallar porque:
- los servicios administrativos se aceptan en la validación;
- `workspace_session_is_privileged()` trata etiquetas como "Administración" o "Dirección" como privilegios;
- `workspace_actor_is_privileged()` refresca `rol` y `servicio` desde DB y hereda esos valores mutables.
"""

import sqlite3
import unittest

from web import server


class PrivilegeEscalationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE workspace_modulos (
              workspace_id TEXT NOT NULL,
              modulo_key TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE usuarios (
              id TEXT PRIMARY KEY,
              rol TEXT,
              servicio TEXT,
              activo INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        self.conn.executemany(
            """
            INSERT INTO workspace_modulos (workspace_id, modulo_key, enabled)
            VALUES (?, ?, ?)
            """,
            [
                ("ws-1", "gestoria", 1),
                ("ws-1", "seguros", 1),
            ],
        )
        self.conn.execute(
            """
            INSERT INTO usuarios (id, rol, servicio, activo)
            VALUES ('u-1', 'Miembro', 'Gestoría', 1)
            """
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_validate_usuario_services_rejects_admin_like_service_labels(self):
        invalid_modules = server.validate_usuario_services_for_workspace(
            self.conn,
            "ws-1",
            "Gestoría, Administración, Dirección",
        )
        self.assertTrue(
            invalid_modules,
            (
                "La validación debe bloquear servicios administrativos. "
                "Hoy devuelve [] porque `resolve_workspace_module_key_for_user_service()` ignora "
                "las etiquetas administrativas y permite que el cambio pase a `/api/usuarios_update`."
            ),
        )

    def test_workspace_session_is_privileged_rejects_admin_service_label(self):
        self.assertFalse(
            server.workspace_session_is_privileged({"rol": "Miembro", "servicio": "Administración"}),
            (
                "Una sesión no privilegiada no debe convertirse en privilegiada solo por el valor "
                "de `servicio`. Hoy esta función devuelve True para `Administración`."
            ),
        )

    def test_workspace_actor_is_privileged_rejects_db_service_elevation(self):
        self.conn.execute(
            """
            UPDATE usuarios
            SET rol = 'Miembro', servicio = 'Administración'
            WHERE id = 'u-1'
            """
        )
        self.conn.commit()
        self.assertFalse(
            server.workspace_actor_is_privileged(
                self.conn,
                {"user_id": "u-1", "rol": "Miembro", "servicio": "Gestoría"},
            ),
            (
                "La recarga de sesión desde DB no debe elevar privilegios por `servicio`. "
                "Hoy la función refresca la fila de usuarios y acaba devolviendo True."
            ),
        )

    def test_workspace_actor_is_privileged_rejects_db_role_elevation(self):
        self.conn.execute(
            """
            UPDATE usuarios
            SET rol = 'ADMINISTRADOR', servicio = 'Gestoría'
            WHERE id = 'u-1'
            """
        )
        self.conn.commit()
        self.assertFalse(
            server.workspace_actor_is_privileged(
                self.conn,
                {"user_id": "u-1", "rol": "Miembro", "servicio": "Gestoría"},
            ),
            (
                "La recarga de sesión desde DB no debe elevar privilegios por `rol`. "
                "Hoy la función considera `ADMINISTRADOR` como privilegio aunque el usuario parta "
                "de una sesión no privilegiada."
            ),
        )
