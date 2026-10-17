# Creusot proofs

Three files of the Rust implementation are proved with [Creusot](https://creusot.rs).
This crate compiles the shipped files themselves through `#[path]`, not copies. The
contracts sit under `cfg_attr(creusot, ...)`, so a normal `cargo build` drops them
and impl-rs stays free of dependencies.

## `impl-rs/src/hexcanon.rs`: canonical hex

This is the decoder for the hex in P-256 keys and signatures. WRT-019 allows
lowercase only.

- `encode(b)` writes `encodes(result, b)`: two lowercase digits per byte, the high
  half first.
- `decode(s)` returns `Some(b)` only when `encodes(s, b)` holds. It returns `None`
  only when no byte string has `s` as its spelling (completeness).
- `round_trip`: `decode(encode(b)) == Some(b)`.
- `canonical`: if `decode(s) == Some(b)`, then `encode(b) == s`. A byte string has
  exactly one accepted spelling.

## `impl-rs/src/bounds.rs`: the range checks

These are the checks that make an encoding canonical. Signature vectors cannot see
them: a vector that breaks one usually fails some other way too, as measured on the
Rust P-256 decoder. Each function returns exactly the numeric statement in its
contract:

| Function | Contract | Used by |
|---|---|---|
| `lt_be(a, b)` | `be(a) < be(b)` for equal lengths | every check below |
| `ed25519_scalar_canonical(s)` | `le(s) < L` | `ed25519::verify` (RFC 8032 §5.1.7) |
| `ed25519_y_canonical(s)` | `le(y) < 2^255 - 19`, where `y` is `s` with bit 255 cleared | `pt_decompress` (§5.1.3) |
| `p256_x_in_range(x)` | `be(x) < p` | `p256::decompress` (WRT-019) |
| `p256_sig_in_range(sig)` | `0 < r < n` and `0 < s <= n/2` | `p256::verify` (WRT-019, low-S) |

The moduli in the contracts are written in their published forms: `2^255 - 19`,
`2^252 + 27742…`, the FIPS 186 forms of p and n. They are not copied from the byte
tables in the code, so the proof checks every byte of every table. Pearlite literals
stop at i128, so each modulus is built from `w() = 2^64`. A table's value is
reached in 64-bit steps (`hb(c, 8)`, `hb(c, 16)`, …). The steps are generated from
the table and are not trusted: the last step must equal the published form.

## `impl-rs/src/jcsquote.rs`: JCS string quoting

`canon` uses this to write every string and member name. It is the reason two
different bodies cannot produce the same canonical text through their strings.

- `quote_units(s, out)` appends exactly `quoted(s)`: `"`, the escape of each unit
  (`esc`), and `"`. `esc` is RFC 8785's table: `\"` and `\\`, the five short
  controls, `\u00xx` in lowercase for the other controls below U+0020, and every
  other unit unchanged.
- **Theorem `quoted_delimits`:** if `quoted(s) ++ x == quoted(t) ++ y`, then `s == t`
  and `x == y`. A quoted string is self-delimiting. Whatever canonical text
  follows two strings, the strings cannot collide.

The theorem has its own mutants, which change the escape table in the spec and in
the code together. The code then still matches its spec, so the theorem is the
thing that must break: a quote or a backslash passed through raw, or two controls
given one short form. If the theorem survived those, it would be vacuous.

## What is not proved

- The callers. That `ed25519.rs`, `p256.rs` and `json.rs` call these functions is
  plain code; review it.
- The arithmetic after the checks (field operations, scalar multiplication), and
  the rest of `canon`: member ordering, numbers, UTF-8 output. Those are held by
  the vectors and by three implementations agreeing.
- Creusot, Why3 and the solvers are trusted. The specs (`be`, `le`, `encodes`, the
  moduli) are trusted to mean what RFC 8032, FIPS 186 and WRT-019 mean.

## Run

You need Creusot installed. Its `./INSTALL` sets up the toolchain, the solvers, and
a `[patch]` for `creusot-std` in `~/.cargo/config.toml`. That patch adds
`[[patch.unused]]` to other crates' `Cargo.lock` files; do not commit that. Measured
with Creusot `cc8b768`, `nightly-2026-08-03`, Alt-Ergo 2.6.4, Z3 and CVC5 1.4.1.
CVC4 is left out because it failed to calibrate on this machine. The time limit per
goal is 5 s: at 1 s, one goal timed out under a parallel test load.

```sh
cargo creusot              # Proved (46 files) ✔
python3 mutants.py         # every mutant must make the proof fail
```

`mutants.py` breaks copies of the two files in named ways and expects each break to
fail the proof:
- one wrong byte in each table;
- `<` turned into `<=`;
- the comparison reversed;
- strict low-S;
- accepting `r = 0`;
- clearing two top bits of `y`;
- reading `S` big-endian;
- the five hex mutants;
- the five JCS mutants.

A proof that still closes on broken code would show nothing about the code.

## In CI: attested, not re-run

Installing Creusot takes about half an hour, so CI does not run it. Whoever runs
the proofs signs a warrant record instead:

```sh
python3 tools/proof_attestation.py --attest   # runs both commands above, then signs
python3 tools/proof_attestation.py --check    # what CI runs (tools/check.py)
```

The record's subject is a manifest of the proof inputs. Inputs are deny-by-default:
every file of this crate except outputs, caches and prose; every file its sources
name by path; and Cargo configuration and toolchain files in ancestor directories.
The first version listed the inputs it thought of instead, and a review showed it
missing `build.rs`, which Cargo picks up on its own. Before signing, `--attest`
also checks that every repository file rustc's dep-info says it read is in the
manifest, and that every input is tracked by git. The record carries the two logs and the environment as evidence.
`--check` recomputes the manifest from the checkout and looks for a record about
exactly it, bound to a key in [attestation/trust.json](attestation/trust.json).

The result is reported as **CLAIMED**, never as passed. A green check means a
trusted key says the proofs and mutants passed on these inputs; CI ran nothing.
If a proved file changes without a new attestation, the check turns red and names
what changed. [attestation/POLICY.md](attestation/POLICY.md) states what a record
claims and what it does not. The key is an agent's (`claude@warrant-proofs`), and
no other check consults this trust file. `tests/proof_attestation_vectors.py`
holds the attacks:
- a changed input;
- an added `build.rs`, `benches/` file, ancestor `.cargo/config.toml` or
  `rust-toolchain.toml`;
- a source naming a file outside the repository;
- a foreign key;
- edited or deleted evidence;
- an untrusted signer;
- the dep-info and git cross-checks.
