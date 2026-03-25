import unittest

from web.auth_security import hash_password, needs_password_rehash, verify_password


class AuthSecurityTests(unittest.TestCase):
    def test_hash_password_uses_pbkdf2_format(self):
        password_hash = hash_password("ClaveSegura123")
        self.assertTrue(password_hash.startswith("pbkdf2_sha256$"))
        self.assertTrue(verify_password("ClaveSegura123", password_hash))
        self.assertFalse(verify_password("otra", password_hash))
        self.assertFalse(needs_password_rehash(password_hash))

    def test_verify_password_accepts_legacy_sha256_hashes(self):
        legacy_hash = (
            "00112233445566778899aabbccddeeff$"
            "481028aee15157b0c113dc9e367ca5267496e5939c517e608a77e5d74223b858"
        )
        self.assertTrue(verify_password("demo", legacy_hash))
        self.assertTrue(needs_password_rehash(legacy_hash))


if __name__ == "__main__":
    unittest.main()
