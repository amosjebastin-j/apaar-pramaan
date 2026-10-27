"""Security helpers.
Secrets come from environment variables (for hosting) or are generated once into key files next to this file.
  VERISEAT_DATA_KEY      -> AES-256-GCM key for field-level encryption (APAAR ID, name)
  VERISEAT_HMAC_KEY      -> key for the HMAC hash of APAAR IDs (dedup without exposing the ID)
  VERISEAT_SESSION_SECRET-> cookie session secret
"""
import os, hmac, hashlib, base64, secrets
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = os.path.dirname(os.path.abspath(__file__))


def _secret(env, fname):
    v = os.environ.get(env)
    if v:
        return hashlib.sha256(v.encode()).digest()          # always 32 bytes
    p = os.path.join(BASE, fname)
    if not os.path.exists(p):
        with open(p, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(p, "rb") as f:
        return f.read()


_AES = AESGCM(_secret("VERISEAT_DATA_KEY", "data.key"))      # AES-256-GCM
_HK = _secret("VERISEAT_HMAC_KEY", "hmac.key")
SESSION_SECRET = _secret("VERISEAT_SESSION_SECRET", "session.key").hex()


def enc(s):
    if s is None or s == "":
        return s
    n = os.urandom(12)
    return base64.urlsafe_b64encode(n + _AES.encrypt(n, str(s).encode(), None)).decode()


def dec(s):
    if not s:
        return s
    try:
        raw = base64.urlsafe_b64decode(s)
        return _AES.decrypt(raw[:12], raw[12:], None).decode()
    except Exception:
        return s                                              # tolerate plain text


def h(a):
    """HMAC-SHA256 of an APAAR ID (used for lookups and duplicate detection)."""
    return hmac.new(_HK, str(a).encode(), hashlib.sha256).hexdigest()


def mask(a):
    return "XXXX-XXXX-" + str(a)[-4:]


def hash_pw(p, salt=None):
    salt = salt or secrets.token_hex(16)
    d = hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 120_000).hex()
    return f"{salt}${d}"


def check_pw(p, stored):
    try:
        salt, d = stored.split("$")
        return hmac.compare_digest(hash_pw(p, salt).split("$")[1], d)
    except Exception:
        return False
