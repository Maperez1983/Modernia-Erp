"""El código de firma no se saca a fuerza bruta.

Auditando la firma electrónica del CRM inmobiliario (2026-08-09). Casi todo estaba
bien hecho: el token es `secrets.token_urlsafe(32)`, se guarda **hasheado** con índice
único —un volcado de la base no da enlaces usables—, la búsqueda va por hash, hay
caducidad, y cada paso deja evento con IP y user-agent.

El hueco estaba en el segundo factor. El OTP son seis dígitos —un millón de
combinaciones— y `sign_inmueble_signature_request` no contaba los intentos: devolvía
403 y registraba `otp_failed`, sin más. Se podía probar el millón.

Eso importa porque el OTP existe precisamente para el caso en que el enlace se ha ido
de las manos: un correo reenviado, un móvil compartido, un buzón comprometido. Si el
enlace es lo único que hace falta porque el código se agota probando, el segundo
factor no aporta nada.

El tope se cuenta sobre los eventos `otp_failed` que ya se registraban, así que no
hizo falta columna nueva. Se cuentan sólo los posteriores a `sent_at`: reenviar el
código regenera token y OTP, y los intentos viejos no valen contra el código nuevo.

Efecto secundario asumido: pasados los cinco intentos, el firmante legítimo también
queda fuera hasta que le reenvíen el código. Con cinco intentos para seis dígitos eso
sólo pasa tecleando muy mal, y la salida —reenviar— ya existía en el CRM.
"""

import os
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = ""

from web import server as S  # noqa: E402

OTP_BUENO = "424242"


def ahora():
    return datetime.now(timezone.utc).isoformat()


class FirmaOtpIntentosTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "firma.sqlite"
        S.ensure_tables(self.db)
        self.conn = S.open_sqlite_conn(str(self.db), with_row_factory=True)
        S.ensure_inmueble_signature_schema(self.conn)
        self.token = S.make_signature_token()
        self._crear_solicitud(self.token, OTP_BUENO, enviado=ahora())

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def _crear_solicitud(self, token, otp, *, enviado):
        momento = ahora()
        self.conn.execute(
            """
            INSERT INTO inmueble_signature_requests
              (id, empresa_id, doc_url, doc_nombre, signer_nombre, status, token_hash,
               otp_hash, otp_required, sent_at, created_at, updated_at)
            VALUES ('req1', 'emp1', '/uploads/x.pdf', 'x.pdf', 'Firmante', 'pending',
                    ?, ?, 1, datetime(?), ?, ?)
            """,
            (S.hash_signature_token(token), S.hash_signature_token(otp), enviado, momento, momento),
        )
        self.conn.commit()

    def _firmar(self, token, otp, nombre="Firmante Real", nif="12345678Z"):
        resultado, estado = S.sign_inmueble_signature_request(
            self.conn, token,
            {"otp": otp, "signed_name": nombre, "signed_nif": nif,
             "acceptance_text": "acepto y firmo"},
            now=ahora(),
        )
        self.conn.commit()
        return resultado, estado

    # ---------- el tope ----------

    def test_a_partir_del_sexto_intento_se_bloquea(self):
        for intento in range(1, S.SIGNATURE_OTP_MAX_ATTEMPTS + 1):
            resultado, estado = self._firmar(self.token, f"{secrets.randbelow(1000000):06d}")
            with self.subTest(intento=intento):
                # Un acierto por azar tiene una probabilidad de 1 entre un millón;
                # si pasara, el test avisaría en vez de fallar en falso.
                self.assertEqual(estado, 403, resultado)
                self.assertEqual(
                    resultado["intentos_restantes"],
                    S.SIGNATURE_OTP_MAX_ATTEMPTS - intento,
                )
        resultado, estado = self._firmar(self.token, "000000")
        self.assertEqual(estado, 429, resultado)

    def test_el_bloqueo_tambien_frena_al_codigo_correcto(self):
        """Si no, bastaría con probar hasta acertar: el tope sería decorativo."""
        for _ in range(S.SIGNATURE_OTP_MAX_ATTEMPTS):
            self._firmar(self.token, "000000")
        resultado, estado = self._firmar(self.token, OTP_BUENO)
        self.assertEqual(estado, 429, resultado)
        fila = self.conn.execute(
            "SELECT status FROM inmueble_signature_requests WHERE id = 'req1'"
        ).fetchone()
        self.assertNotEqual(str(fila["status"]).lower(), "signed")

    def test_el_bloqueo_queda_registrado(self):
        for _ in range(S.SIGNATURE_OTP_MAX_ATTEMPTS + 1):
            self._firmar(self.token, "000000")
        eventos = [
            r["event"] for r in self.conn.execute(
                "SELECT event FROM inmueble_signature_events WHERE request_id = 'req1'"
            )
        ]
        self.assertIn("otp_blocked", eventos)
        self.assertEqual(eventos.count("otp_failed"), S.SIGNATURE_OTP_MAX_ATTEMPTS)

    # ---------- la salida ----------

    def test_reenviar_el_codigo_devuelve_los_intentos(self):
        for _ in range(S.SIGNATURE_OTP_MAX_ATTEMPTS + 1):
            self._firmar(self.token, "000000")

        # Reenviar es lo que hace /api/inmueble_signature_remind: token y OTP nuevos
        # y `sent_at` al día. Se fecha en el futuro para no depender del reloj.
        token_nuevo = S.make_signature_token()
        otp_nuevo = "999111"
        futuro = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
        self.conn.execute(
            """
            UPDATE inmueble_signature_requests
            SET token_hash = ?, otp_hash = ?, sent_at = datetime(?), updated_at = ?
            WHERE id = 'req1'
            """,
            (S.hash_signature_token(token_nuevo), S.hash_signature_token(otp_nuevo), futuro, futuro),
        )
        self.conn.commit()

        resultado, estado = self._firmar(token_nuevo, otp_nuevo)
        self.assertEqual(estado, 200, resultado)

    def test_el_token_viejo_no_sirve_tras_el_reenvio(self):
        token_nuevo = S.make_signature_token()
        self.conn.execute(
            "UPDATE inmueble_signature_requests SET token_hash = ? WHERE id = 'req1'",
            (S.hash_signature_token(token_nuevo),),
        )
        self.conn.commit()
        resultado, estado = self._firmar(self.token, OTP_BUENO)
        self.assertEqual(estado, 404, resultado)

    # ---------- lo que ya estaba bien, para que no se caiga ----------

    def test_el_token_no_se_guarda_en_claro(self):
        fila = self.conn.execute(
            "SELECT token_hash, otp_hash FROM inmueble_signature_requests WHERE id = 'req1'"
        ).fetchone()
        self.assertNotIn(self.token, str(fila["token_hash"]))
        self.assertNotIn(OTP_BUENO, str(fila["otp_hash"]))

    def test_una_solicitud_caducada_no_se_firma(self):
        pasado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self.conn.execute(
            "UPDATE inmueble_signature_requests SET expires_at = ? WHERE id = 'req1'",
            (pasado,),
        )
        self.conn.commit()
        resultado, estado = self._firmar(self.token, OTP_BUENO)
        self.assertEqual(estado, 410, resultado)


if __name__ == "__main__":
    unittest.main()
