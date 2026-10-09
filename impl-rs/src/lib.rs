//! # warrant-verify (Rust)
//!
//! An independent, from-scratch implementation of the
//! [Warrant](https://github.com/s0fractal/warrant) decision-record format: a
//! decision is a small JSON body naming the policy it was made under, its
//! reasons and evidence, its actor and its prior decisions; its identity
//! (WarrantID) is the SHA-256 of the body's RFC 8785 canonical bytes, and it is
//! signed with Ed25519 over a domain-separated message.
//!
//! This crate is held to the reference implementation (`impl/warrant.py`,
//! published on PyPI as `warrant-verify`) by differential tests that compare
//! output byte for byte: the same store gives the same report, the same counts,
//! the same exit status, and the same written records.
//!
//! It has **no dependencies**: SHA-256, SHA-512, Ed25519 and the JSON parser
//! are written here, so that agreeing with the reference is evidence about the
//! specification rather than about a shared library.
//!
//! ```
//! use warrant_verify::{json, schema, store};
//!
//! let body = json::parse_ijson(br#"{"warrant":"0.2","decision":"propose",
//!   "subject":{"hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
//!   "under":["bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"],
//!   "because":[],"evidence":[],"actor":{"id":"a@example"},"prior":[],"ts":1}"#).unwrap();
//! assert!(schema::validate_body(&body).is_empty());
//! let wid = store::warrant_id(&body).unwrap();
//! assert_eq!(wid.len(), 64);
//! ```
//!
//! Modules, in the order the format builds on them: [`hash`], [`json`]
//! (I-JSON parsing and canonicalization, SPEC §4), [`schema`] (§2/§3),
//! [`sig`] and [`ed25519`] (§5), [`ski`] (the `ski@v1` evaluator, §3.1),
//! [`store`], [`settlement`] (§5.1/§7/§9), [`verify`] (§6 and the §11 report),
//! [`ops`] (filing, `why`, `resign`, `settle`), [`conformance`] (§8 and the
//! `warrant-conformance/1` probe) and [`cli`].

#![forbid(unsafe_code)]

pub mod cli;
pub mod conformance;
pub mod ed25519;
pub mod hash;
pub mod json;
pub mod ops;
pub mod schema;
pub mod settlement;
pub mod sig;
pub mod ski;
pub mod store;
pub mod verify;
