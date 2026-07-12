import hashlib
import hmac
import os


PBKDF2_SHA256 = "pbkdf2_sha256"
DEFAULT_PBKDF2_ITERATIONS = max(240000, int(os.environ.get("APP_PASSWORD_HASH_ITERATIONS", "390000")))


def hash_password(password, iterations=None):
    if not password:
        return None
    rounds = max(120000, int(iterations or DEFAULT_PBKDF2_ITERATIONS))
    salt = os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds).hex()
    return f"{PBKDF2_SHA256}${rounds}${salt}${digest}"


def verify_password(password, password_hash):
    if not password or not password_hash:
        return False
    raw = str(password_hash).strip()
    if raw.startswith(f"{PBKDF2_SHA256}$"):
        parts = raw.split("$", 3)
        if len(parts) != 4:
            return False
        _, raw_rounds, salt, stored = parts
        try:
            rounds = max(1, int(raw_rounds))
        except (TypeError, ValueError):
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), rounds).hex()
        return hmac.compare_digest(digest, stored)
    if "$" not in raw:
        return False
    salt, stored = raw.split("$", 1)
    if not salt or not stored:
        return False
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored)


def needs_password_rehash(password_hash):
    raw = str(password_hash or "").strip()
    if not raw:
        return True
    if not raw.startswith(f"{PBKDF2_SHA256}$"):
        return True
    parts = raw.split("$", 3)
    if len(parts) != 4:
        return True
    try:
        rounds = int(parts[1])
    except (TypeError, ValueError):
        return True
    return rounds < DEFAULT_PBKDF2_ITERATIONS
