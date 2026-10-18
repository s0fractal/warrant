"""Ed25519 keys and the record signature (SPEC §3).

A key binding authenticates an actor's records. It authorizes nothing (SPEC §6)."""
import hashlib
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIG_DOMAIN = b"warrant-sig-v1:"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX128 = re.compile(r"^[0-9a-f]{128}$")

_P = (1 << 255) - 19
# Small-order points and the non-canonical encodings of the x=0 torsion points:
# a key from this set lets a forged signature verify for many messages.
_WEAK = {bytes.fromhex(h) for h in (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
    "0100000000000000000000000000000000000000000000000000000000000080",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
)}


def weak_public_key(raw):
    if len(raw) != 32 or raw in _WEAK:
        return True
    return (int.from_bytes(raw, "little") & ((1 << 255) - 1)) >= _P


def sig_message(record_id):
    return SIG_DOMAIN + bytes.fromhex(record_id)


def key_id(public_hex):
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()


def verify(public_hex, sig_hex, message):
    """True iff `sig_hex` is a valid Ed25519 signature of `message` by a strong key."""
    if not (isinstance(public_hex, str) and HEX64.match(public_hex)
            and isinstance(sig_hex, str) and HEX128.match(sig_hex)):
        return False
    raw = bytes.fromhex(public_hex)
    if weak_public_key(raw):
        return False
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(bytes.fromhex(sig_hex), message)
        return True
    except (InvalidSignature, ValueError):
        return False


class Key:
    """A private signing key held by its owner. Never written into a store."""

    def __init__(self, sk):
        self._sk = sk
        self.public = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        self.id = key_id(self.public)

    @classmethod
    def generate(cls):
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed_hex(cls, seed_hex):
        return cls(Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex.strip())))

    def seed_hex(self):
        return self._sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                      serialization.NoEncryption()).hex()

    def sign(self, message):
        return self._sk.sign(message).hex()
