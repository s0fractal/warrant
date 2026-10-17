# Creusot proof: canonical hex

[`impl-rs/src/hexcanon.rs`](../../impl-rs/src/hexcanon.rs) is the decoder that the
Rust implementation uses for the hex strings in P-256 keys and signatures (WRT-019:
lowercase, nothing else). This crate compiles **that file**, not a copy
(`#[path]`), and [Creusot](https://creusot.rs) proves its contracts.

## What is proved

- `encode(b)` writes the canonical spelling of `b`: `encodes(result, b)`, which
  means two lowercase digits per byte, high half first.
- `decode(s)` returns `Some(b)` only when `encodes(s, b)`.
- `decode(s)` returns `None` only when **no** byte string is spelled by `s`. This is
  completeness: nothing canonical is refused.
- `round_trip`: `decode(encode(b)) == Some(b)`. The `None` arm is proved
  unreachable.
- `canonical`: if `decode(s) == Some(b)` then `encode(b) == s`. Each byte string
  has exactly one accepted spelling, so `AB`, `0A` and the like cannot decode.
- Every function is free of panics and of arithmetic overflow.

## What is not proved

- That `sig.rs` calls `hexcanon::decode`. That is plain code; review it.
- Anything about P-256 itself. The primitives `p256-decode` vectors cover the
  decoder that comes after the hex.
- Creusot, Why3 and the solvers are trusted. The spec (`hex_digit`, `nibble`,
  `encodes`) is trusted to say what WRT-019 means.

## Run

You need Creusot installed: its `./INSTALL` sets up the toolchain, the solvers, and
a `[patch]` for `creusot-std` in `~/.cargo/config.toml`. Measured with Creusot
`cc8b768` and `nightly-2026-08-03`, using Alt-Ergo 2.6.4, Z3 and CVC5 1.4.1. CVC4 is
left out because it failed to calibrate on this machine.

```sh
cargo creusot              # Proved (8 files) ✔
python3 mutants.py         # each mutant must make the proof fail
```

`mutants.py` breaks a copy of `hexcanon.rs` in named ways and expects the proof to
fail for each one:
- accepting uppercase;
- dropping the parity check;
- swapping the halves when encoding;
- swapping the halves when decoding;
- an off-by-one in the letter digits.

A proof that still closes on broken code would show nothing about the code.

This does not run in CI: installing Creusot takes about half an hour. Under a normal
`cargo build`, `cfg(creusot)` is off, the contracts vanish, and impl-rs stays free
of dependencies.
