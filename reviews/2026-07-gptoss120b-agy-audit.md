**A. VERDICT**  
The Lean mechanisation of the §6 C1 compiler is sound and non‑vacuous: the theorems state genuine properties (preservation of free variables and closure‑preserving compilation) and are proved without any hidden axioms beyond `propext`. The Python/Go conformance‑negative battery exercises the required rejection cases, but its coverage of malformed inputs is not fully exhaustive.

---

**B. FINDINGS**

| Severity | File / Location | Concrete Issue / Observation |
|----------|----------------|------------------------------|
| **P0** | *none detected* | The Lean theorems (`mem_skiFv_abstr`, `mem_skiFv_c1`, `c1_closed`) are logically consistent; the bridge script verifies equality of hashes on 3 000 random closed λ‑terms, and the abstraction order (`A‑2` before `A‑3`) follows the specification. No discordant implementation was found. |
| **P1** | *none detected* | The specifications for negative conformance (§8.3) are correctly implemented: both the Go and Python verifiers reject weak Ed25519 keys and schema‑invalid bodies as required. No weaker‑than‑stated property was observed. |
| **P2** | `examples/conformance‑negatives.json` & `impl‑go/main.go` (and `impl/warrant.py`) | **Incomplete negative coverage** – the battery does not test several obvious malformed cases required by the spec, e.g.: <br>• JSON that fails parsing entirely (syntax errors). <br>• Missing top‑level fields such as `warrant` or `decision`. <br>• Invalid hex length for a public key (too short/long). <br>• Keys that are the correct length but have high‑order bits cleared (different weak‑key class). These cases are not enumerated in the JSON, so a conforming verifier could erroneously accept them. |
| **P3** | `proofs/C1Compiler.lean` | **Documentation / roadmap** – the file lacks a changelog or TODO section indicating future extensions (e.g., support for de Bruijn indices, proof of algorithmic optimality). Adding a brief “Roadmap” comment would improve maintainability. |

---

**C. CONFIDENCE**

| Finding | Confidence |
|---------|------------|
| P0 (no critical inconsistency) | **High** – proof structure, induction, and the bridge check align with the specification. |
| P1 (no weakened spec) | **High** – both implementations mirror the spec; no hidden relaxations detected. |
| P2 (negative‑case incompleteness) | **Medium** – the identified gaps are evident, but the impact on security depends on downstream verifier implementations. |
| P3 (roadmap omission) | **High** – simply an observation of missing metadata. |

---

**D. NEXT STEP**  
Extend the negative‑conformance test suite:

1. Add entries to `conformance‑negatives.json` for **syntactic JSON errors**, **missing required top‑level fields**, **incorrect key lengths**, and **alternative weak‑key patterns**.  
2. Update the Go and Python `conformance()` routines to iterate over these new cases (e.g., attempting to `json.Unmarshal` malformed strings and asserting failure).  
3. Document the additions in a short “Roadmap” comment at the top of `C1Compiler.lean` and in a `CONTRIBUTING.md` file for future auditors.  

These actions will raise the P2 confidence to high and ensure the verifier’s rejection guarantees are truly comprehensive.
