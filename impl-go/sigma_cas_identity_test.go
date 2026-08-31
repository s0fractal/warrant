package main

// Go mirror of tests/sigma_cas_identity.py: the ski@v1 re-executor enforces
// Identity by Hash at the CAS fetch boundary. A store that returns bytes under a
// FOREIGN key (bytes whose SHA-256 is not the requested key) yields an
// inadmissible check with the SAME path-free reason class Python uses —
// "content does not match its address" — never an executed `pass`/`fail`.
//
// This is the differential control the campaign asks for: both implementations
// refuse the forged fetch. Valid, correctly-addressed checks are unaffected
// (see also `conformance` 67/67 and `sigma-conformance`).

import (
	"encoding/json"
	"testing"
)

func mkCheck(t *testing.T, termHex, expectHex string, atp int) []byte {
	t.Helper()
	b, err := json.Marshal(map[string]any{
		"ski": 1, "term": termHex, "atp": atp, "expect": expectHex})
	if err != nil {
		t.Fatalf("marshal check: %v", err)
	}
	return b
}

func TestSigmaCASIdentity_ForeignRootKey(t *testing.T) {
	iBytes := sigmaGenesis[sigmaIHash] // the intrinsic I literal
	var foreign [32]byte
	foreign[0] = 0xaa // a key that is NOT sha256(iBytes)
	if foreign == sigmaIHash {
		t.Fatal("test setup: foreign key collided with I")
	}
	// bytes of I filed under a foreign address — the forged store
	store := sigmaStore{foreign: iBytes}
	expect := hash32Hex(sigmaIHash) // if it ran, I normalises to I

	verdict, _, _, err := runSkiCheck(mkCheck(t, hash32Hex(foreign), expect, 64), store)
	if err == nil {
		t.Fatalf("foreign root key was NOT refused: verdict=%q (must be an "+
			"inadmissible check, not a computed verdict)", verdict)
	}
	if err.Error() != "content does not match its address" {
		t.Fatalf("foreign root key reason = %q, want the stable path-free "+
			"Identity-by-Hash class", err.Error())
	}
}

func TestSigmaCASIdentity_ValidCheckStillPasses(t *testing.T) {
	// A correctly-addressed term (I is a genesis leaf) is unaffected by the guard.
	iH := hash32Hex(sigmaIHash)
	verdict, rh, spent, err := runSkiCheck(
		mkCheck(t, iH, iH, 64), sigmaStore{})
	if err != nil {
		t.Fatalf("valid ski@v1 check errored: %v", err)
	}
	if verdict != "pass" || rh != iH {
		t.Fatalf("valid ski@v1 check: verdict=%q rh=%q spent=%d (want pass, I)",
			verdict, rh, spent)
	}
}

func TestSigmaCASIdentity_ForceRefusesMisaddressedBytes(t *testing.T) {
	// Unit-level: sigmaForce itself refuses store bytes that do not hash to the
	// requested key, and reports "unresolved" for a genuinely absent key — the
	// two must stay distinct (a mismatch is corruption, not absence).
	iBytes := sigmaGenesis[sigmaIHash]
	var foreign [32]byte
	foreign[0] = 0xbb
	if _, fault := sigmaForce(foreign, sigmaStore{foreign: iBytes}); fault != "cas-mismatch" {
		t.Fatalf("sigmaForce on misaddressed bytes: fault=%q want cas-mismatch", fault)
	}
	var absent [32]byte
	absent[0] = 0xcc
	if _, fault := sigmaForce(absent, sigmaStore{}); fault != "unresolved" {
		t.Fatalf("sigmaForce on absent key: fault=%q want unresolved", fault)
	}
}
