import os
import unittest
from unittest import mock

from cryptography.fernet import Fernet

from web import server


def _reset_field_cache():
    # Fuerza a los helpers a releer la clave del entorno (evita cache entre tests).
    server._FIELD_FERNET_CACHE["key"] = None
    server._FIELD_FERNET_CACHE["fernet"] = None


class FieldEncryptionPassthroughTests(unittest.TestCase):
    """Sin APP_FIELD_ENCRYPTION_KEY el cifrado es NO-OP (privacy opt-in)."""

    def setUp(self):
        _reset_field_cache()

    def test_encrypt_without_key_is_identity(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APP_FIELD_ENCRYPTION_KEY", None)
            _reset_field_cache()
            text = "Salario bruto 2500 EUR IRPF 15%"
            self.assertEqual(server.encrypt_field(text), text)

    def test_decrypt_without_key_is_identity(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APP_FIELD_ENCRYPTION_KEY", None)
            _reset_field_cache()
            text = "Neto 1980,45 SS 158,75"
            self.assertEqual(server.decrypt_field(text), text)

    def test_empty_and_none_passthrough(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("APP_FIELD_ENCRYPTION_KEY", None)
            _reset_field_cache()
            self.assertEqual(server.encrypt_field(""), "")
            self.assertEqual(server.decrypt_field(""), "")
            self.assertIsNone(server.encrypt_field(None))
            self.assertIsNone(server.decrypt_field(None))


class FieldEncryptionWithKeyTests(unittest.TestCase):
    """Con clave Fernet válida encrypt cifra con prefijo y decrypt recupera."""

    def setUp(self):
        self._key = Fernet.generate_key().decode("ascii")
        _reset_field_cache()

    def tearDown(self):
        _reset_field_cache()

    def test_encrypt_produces_prefixed_token_and_roundtrips(self):
        with mock.patch.dict(os.environ, {"APP_FIELD_ENCRYPTION_KEY": self._key}, clear=False):
            _reset_field_cache()
            plain = "Salario bruto 2500 EUR IRPF 15% SS 158,75"
            token = server.encrypt_field(plain)
            self.assertTrue(token.startswith(server.FIELD_ENCRYPTION_PREFIX))
            self.assertNotEqual(token, plain)
            self.assertNotIn("2500", token)  # el dato sensible no aparece en claro
            self.assertEqual(server.decrypt_field(token), plain)

    def test_encrypt_is_idempotent_on_already_encrypted(self):
        with mock.patch.dict(os.environ, {"APP_FIELD_ENCRYPTION_KEY": self._key}, clear=False):
            _reset_field_cache()
            token = server.encrypt_field("dato")
            self.assertEqual(server.encrypt_field(token), token)

    def test_decrypt_plaintext_legacy_returns_asis(self):
        # Un valor SIN prefijo (dato legacy en claro) se devuelve tal cual, con clave activa.
        with mock.patch.dict(os.environ, {"APP_FIELD_ENCRYPTION_KEY": self._key}, clear=False):
            _reset_field_cache()
            legacy = "Nomina en claro previa al cifrado"
            self.assertEqual(server.decrypt_field(legacy), legacy)

    def test_decrypt_corrupt_token_is_best_effort_empty(self):
        with mock.patch.dict(os.environ, {"APP_FIELD_ENCRYPTION_KEY": self._key}, clear=False):
            _reset_field_cache()
            corrupt = server.FIELD_ENCRYPTION_PREFIX + "not-a-valid-token"
            self.assertEqual(server.decrypt_field(corrupt), "")


if __name__ == "__main__":
    unittest.main()
