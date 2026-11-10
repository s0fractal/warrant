#!/usr/bin/env python3
"""Warrant 3 package verifier: one file, the standard library only (docs/VERIFY.md).

You were handed a `package/3` file: the records a result rests on and the verdicts on them. Copy this file anywhere
and ask whether you may rely on it, under your own trust (which keys are whose) and profile (who holds which role):

    python3 -I warrant_verify.py PACKAGE --trust TRUST.json --profile PROFILE.json [--require ROOT ...]
                                 [--checkout DIR] [--as-of N] [--max-bytes N]
    python3 -I warrant_verify.py PACKAGE --config V3.json          # a file holding both: {trust, profile}

The exit status is the answer: 0 only when every root asked for is one you may rely on now; 1 when one is not, or
the package was refused; 2 for a command line or a file of your own that cannot be read; 3 for an error of this file
itself, never the code of a refusal. Standard output is one line of canonical JSON: per root its lineage, its guard,
who accepted it under which of your roles, the challenges, and the files its acceptances name; and two lists in
sentences, `established` and `not_established`. No package can show what its sender left out, and that is always in
the second list.

It needs no installation, no store, no network and no Git, and writes nothing. `--checkout DIR` asks Git for the
tree of DIR's HEAD, to compare the files an acceptance names with it; without Git they read NOT_CHECKED, never fresh.
`-I` keeps Python from importing a file that happens to lie beside this one.

This file is built, not written: `python3 tools/build_verify.py` puts the modules of the `warrant` package that
`warrant verify` runs (SOURCES below, each byte for byte, its SHA-256 in DIGESTS) after the few functions here: an
Ed25519 verification for an interpreter without the `cryptography` library, and the loader. `warrant verify` of the
installed package gives the same bytes on the same input; tests/verify_test.py holds both to that, and this file to
its build."""
import hashlib
import sys
import types

# @@BUILD@@ the build replaces this block with DIGESTS, ORDER and SOURCES
DIGESTS = {}
ORDER = ()
SOURCES = {}
# @@END@@

# ---------------------------------------------------------------- Ed25519, verification only (RFC 8032 §5.1.7)
#
# The check OpenSSL makes, which the `cryptography` library calls: S below the group order, the public key a point
# of the curve, and the bytes of [S]B - [h]A equal to the signature's first half. No cofactor is multiplied in, and
# R is never decoded: another encoding of the same point, or a point off by a small-order one, is another signature.
# warrant/keys.py refuses the small-order and non-canonical public keys before either implementation sees one.

_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _x_of(y, sign):
    """The x of the curve's point with this y and this sign of x, or None when there is none."""
    if y >= _P:
        return None
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if xx == 0:
        return None if sign else 0
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P:
        x = x * _I % _P
    if (x * x - xx) % _P:
        return None
    return _P - x if x & 1 != sign else x


def _add(p, q):
    """The sum of two points in extended coordinates (the unified, complete addition of RFC 8032 §5.1.4)."""
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a, b = (y1 - x1) * (y2 - x2) % _P, (y1 + x1) * (y2 + x2) % _P
    c, d = 2 * t1 * t2 * _D % _P, 2 * z1 * z2 % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return e * f % _P, g * h % _P, f * g % _P, e * h % _P


def _encode(p):
    x, y, z, _ = p
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | (x & 1) << 255).to_bytes(32, "little")


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _x_of(_BY, 0)
_B = (_BX, _BY, 1, _BX * _BY % _P)


def ed25519_verify(public, signature, message):
    """True iff `signature` (64 bytes) is the Ed25519 signature of `message` under `public` (32 bytes)."""
    if len(public) != 32 or len(signature) != 64:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    y = int.from_bytes(public, "little")
    x = _x_of(y & ((1 << 255) - 1), y >> 255)
    if x is None:
        return False
    y &= (1 << 255) - 1
    minus_a = ((_P - x) % _P, y, 1, (_P - x) * y % _P)
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    both, acc = _add(_B, minus_a), (0, 1, 1, 0)
    for i in range(max(s.bit_length(), h.bit_length()) - 1, -1, -1):        # [s]B + [h](-A), one pass over the bits
        acc = _add(acc, acc)
        bs, bh = s >> i & 1, h >> i & 1
        if bs or bh:
            acc = _add(acc, both if bs and bh else _B if bs else minus_a)
    return _encode(acc) == signature[:32]


# ---------------------------------------------------------------- the loader

def _stand_in():
    """The names warrant/keys.py imports from `cryptography`, over the verification above: for an interpreter that
    has no such library. Verification only: this file signs nothing and creates no key."""
    class InvalidSignature(Exception):
        pass

    class Ed25519PublicKey:
        def __init__(self, raw):
            self._raw = raw

        @classmethod
        def from_public_bytes(cls, raw):
            return cls(bytes(raw))

        def verify(self, signature, data):
            if not ed25519_verify(self._raw, bytes(signature), bytes(data)):
                raise InvalidSignature()

    class Ed25519PrivateKey:
        """Named by warrant/keys.py's import; never made here."""

    ed = "cryptography.hazmat.primitives.asymmetric.ed25519"
    members = {"cryptography": {"__version__": "none: the standard library"},
               "cryptography.exceptions": {"InvalidSignature": InvalidSignature},
               "cryptography.hazmat": {}, "cryptography.hazmat.primitives": {},
               "cryptography.hazmat.primitives.serialization": {}, "cryptography.hazmat.primitives.asymmetric": {},
               ed: {"Ed25519PublicKey": Ed25519PublicKey, "Ed25519PrivateKey": Ed25519PrivateKey}}
    for name, inside in members.items():
        m = types.ModuleType(name)
        m.__dict__.update(inside, __path__=[])
        sys.modules[name] = m
        if "." in name:
            setattr(sys.modules[name.rpartition(".")[0]], name.rpartition(".")[2], m)


def _signatures():
    """Use `cryptography` when this interpreter has it, as the package does; else the stand-in. Both give the same
    answer on every input (tests/verify_test.py holds them to each other and to the Ed25519 vectors)."""
    try:
        from cryptography.exceptions import InvalidSignature  # noqa: F401
        from cryptography.hazmat.primitives import serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: F401
    except Exception:                    # absent, or present and unusable: neither is a reason to verify nothing
        for name in [n for n in sys.modules if n == "cryptography" or n.startswith("cryptography.")]:
            del sys.modules[name]
        _stand_in()


def _load():
    """The modules of SOURCES as the package `warrant`, in this process only: each compiled from its text above, in
    ORDER (a module after the ones it imports). No file is read, and an installed `warrant` is never imported."""
    pkg = types.ModuleType("warrant")
    pkg.__path__, pkg.__package__ = [], "warrant"
    sys.modules["warrant"] = pkg
    for name in ORDER:
        m = types.ModuleType(f"warrant.{name}")
        m.__package__, m.__file__ = "warrant", f"<warrant/{name}.py in warrant_verify.py>"
        sys.modules[m.__name__] = m
        exec(compile(SOURCES[name], f"warrant/{name}.py", "exec"), m.__dict__)
        setattr(pkg, name, m)
    # The engine names its code by the files of an installed package; here the code is this file's SOURCES. No answer
    # of `verify` carries that name: it differs between this file and the package, and their answers do not.
    sys.modules["warrant.engine"]._CODE[:] = [hashlib.sha256(repr(sorted(DIGESTS.items())).encode()).hexdigest()]
    return sys.modules["warrant.verify"]


def main(argv):
    _signatures()
    return _load().main(argv, prog="warrant_verify.py")


if __name__ == "__main__":
    try:
        status = main(sys.argv[1:])
    except Exception as e:               # an error of this file is exit 3, never the 1 of an uncaught Python error
        print(f"warrant_verify.py: error of the verifier: {type(e).__name__}: {e}", file=sys.stderr)
        status = 3
    sys.exit(status)
