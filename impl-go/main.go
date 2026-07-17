package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// skiReexecMaxATP bounds the work a verifier will spend re-executing a
// stranger's ski@v1 reason (SPEC §3.1). The atp ceiling is uint32 (~4.3e9); a
// verifier re-running arbitrary checks caps it so a pathological-but-legal atp
// cannot be a DoS. Over the cap the reason is reported as *unverified* (a WARN,
// never a silent skip, never a verdict). MUST match the Python default
// (SKI_REEXEC_MAX_ATP) so the two implementations agree by default.
var skiReexecMaxATP = skiATPBudget()

func skiATPBudget() uint32 {
	if v := os.Getenv("WARRANT_SKI_MAX_ATP"); v != "" {
		if n, err := strconv.ParseUint(v, 10, 32); err == nil {
			return uint32(n)
		}
	}
	return 100_000_000
}

var (
	hex64Re   = regexp.MustCompile(`^[0-9a-f]{64}$`)
	intJSONRe = regexp.MustCompile(`^-?(0|[1-9][0-9]*)$`)

	bodyFields = map[string]bool{
		"warrant": true, "decision": true, "subject": true, "under": true,
		"because": true, "evidence": true, "actor": true, "prior": true,
		"ts": true,
	}
	decisions = map[string]bool{
		"propose": true, "accept": true, "reject": true, "supersede": true,
	}
	specVectors = map[string]string{
		"policy.txt":           "cb3a0afe6ee6219867b9c3f9b860080918fe1042f315fe02ff62300f780beb73",
		"check.sh":             "05d234bec21803c6fa007d848c1773b9fd05cfdf852d6d09542ed3b127c02b6c",
		"propose.warrant.json": "00f79fca5c9c8de5c08ce3c9f1c928dddfb032134e84321bee4176182ea8cda1",
		"reject.warrant.json":  "5f5d4035a4ae04a3eec255105eee7dda7c98daaf9962c92cbbbad38ac21509d8",
		"accept.warrant.json":  "bc602a70a11624387066b7ead21e19d3768a4c970d2c8bdcc2f8dedf36afbc78",
	}
)

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	switch os.Args[1] {
	case "conformance":
		dir := "examples"
		if len(os.Args) > 2 {
			dir = os.Args[2]
		}
		if !conformance(dir) {
			os.Exit(1)
		}
	case "sigma-conformance":
		path := "../sigma-glyph/tests/spec_conformance/vectors.json"
		if len(os.Args) > 2 {
			path = os.Args[2]
		}
		if !sigmaConformance(path) {
			os.Exit(1)
		}
	case "verify":
		dir := "examples"
		settlement := false
		trustConfig := ""
		var genesis []string
		args := os.Args[2:]
		for i := 0; i < len(args); i++ {
			switch args[i] {
			case "--settlement", "-settlement":
				settlement = true
			case "--trust-config", "-trust-config":
				if i+1 >= len(args) {
					fmt.Fprintln(os.Stderr, "verify: --trust-config requires a file")
					os.Exit(2)
				}
				i++
				trustConfig = args[i]
			case "--genesis", "-genesis":
				if i+1 >= len(args) {
					fmt.Fprintln(os.Stderr, "verify: --genesis requires a WarrantID")
					os.Exit(2)
				}
				i++
				genesis = append(genesis, args[i])
			default:
				dir = args[i]
			}
		}
		var errs int
		if settlement {
			errs, _ = verifyDirSettlement(dir, trustConfig, genesis, false)
		} else {
			errs, _ = verifyDir(dir, false)
		}
		if errs != 0 {
			os.Exit(1)
		}
	case "settle":
		if len(os.Args) < 5 {
			fmt.Fprintln(os.Stderr, "usage: warrant-go settle <store> <settling-wid> <candidate-body.json>")
			os.Exit(2)
		}
		_, records, blobs, err := loadVerifyData(os.Args[2])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		body, err := readJSON(os.Args[4])
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(2)
		}
		if errs := validateBody(body); len(errs) > 0 {
			// a schema-invalid candidate is never admissible
			fmt.Println("invalid candidate: " + errs[0])
			os.Exit(1)
		}
		verdict := settlementAdmissibility(records, blobs, os.Args[3], body)
		fmt.Println(verdict)
		if strings.HasPrefix(verdict, "inadmissible") {
			os.Exit(1)
		}
	case "selftest":
		dir := "examples"
		if len(os.Args) > 2 {
			dir = os.Args[2]
		}
		if !selftest(dir) {
			os.Exit(1)
		}
	case "canon":
		// canon <body.json>: print {warrant_id, canon_hex} for a bare body.
		// Exists so a differential harness can compare canonicalization across
		// implementations (the design rule in SPEC line 5).
		if len(os.Args) < 3 {
			fmt.Fprintln(os.Stderr, "usage: warrant-go canon <body.json>")
			os.Exit(2)
		}
		body, err := readJSON(os.Args[2])
		if err != nil {
			fmt.Fprintln(os.Stderr, "canon:", err)
			os.Exit(2)
		}
		canon, err := canonicalJSON(body)
		if err != nil {
			fmt.Fprintln(os.Stderr, "canon:", err)
			os.Exit(2)
		}
		id, _ := warrantID(body)
		fmt.Printf("{\"warrant_id\":%q,\"canon_hex\":%q}\n", id, hex.EncodeToString(canon))
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: warrant-go conformance [examples_dir] | sigma-conformance [vectors.json] | verify [--settlement] [--trust-config file] [--genesis wid] [dir] | settle <store> <settling-wid> <candidate-body.json> | selftest [examples_dir]")
}

func readJSON(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	// SPEC §4 / RFC 7493 I-JSON: duplicate member names are invalid. Go's
	// decoder silently keeps the last (same as Python's stock json.loads); we
	// reject them so both implementations — and any strict reimplementation —
	// agree that a dup-key record is malformed, not last-wins.
	if dup, err := jsonHasDupKeys(data); err != nil {
		return nil, err
	} else if dup {
		return nil, errors.New("duplicate member name (invalid I-JSON)")
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	// Reject trailing content after the JSON value (SPEC §4 / GOV-anchors §3):
	// Go's decoder stops at the first value and would silently ignore a second,
	// so a record with junk appended verified in Go while Python (json.loads)
	// rejected it — a real consensus split found by tests/fuzz_differential.py.
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return nil, errors.New("trailing content after JSON value")
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("top-level JSON is not an object")
	}
	return m, nil
}

// jsonHasDupKeys reports whether any object in the JSON stream repeats a member
// name (SPEC §4). Walks the token stream because stock decoding has already
// collapsed duplicates by the time you hold a map.
func jsonHasDupKeys(data []byte) (bool, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	return scanDupKeys(dec)
}

func scanDupKeys(dec *json.Decoder) (bool, error) {
	t, err := dec.Token()
	if err != nil {
		return false, err
	}
	delim, ok := t.(json.Delim)
	if !ok {
		return false, nil // scalar
	}
	switch delim {
	case '{':
		seen := map[string]bool{}
		for dec.More() {
			kt, err := dec.Token()
			if err != nil {
				return false, err
			}
			key, ok := kt.(string)
			if !ok {
				return false, errors.New("object member name is not a string")
			}
			if seen[key] {
				return true, nil
			}
			seen[key] = true
			if dup, err := scanDupKeys(dec); err != nil || dup {
				return dup, err
			}
		}
		if _, err := dec.Token(); err != nil { // consume '}'
			return false, err
		}
	case '[':
		for dec.More() {
			if dup, err := scanDupKeys(dec); err != nil || dup {
				return dup, err
			}
		}
		if _, err := dec.Token(); err != nil { // consume ']'
			return false, err
		}
	}
	return false, nil
}

// canonicalJSON implements the exact v0.1 JCS subset used by SPEC §4:
// UTF-8, compact separators, sorted object keys, and integers only. The
// bytewise sort is equivalent to JCS UTF-16 ordering for v0.1 schema-fixed
// ASCII keys; future free-form keys must revisit this shortcut.
func canonicalJSON(v any) ([]byte, error) {
	var b bytes.Buffer
	if err := writeCanonical(&b, v); err != nil {
		return nil, err
	}
	return b.Bytes(), nil
}

func writeCanonical(b *bytes.Buffer, v any) error {
	switch x := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if x {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		enc, _ := quoteJSONString(x)
		b.Write(enc)
	case json.Number:
		s := x.String()
		if !intJSONRe.MatchString(s) {
			return fmt.Errorf("non-integer JSON number: %s", s)
		}
		b.WriteString(s)
	case []any:
		b.WriteByte('[')
		for i, item := range x {
			if i > 0 {
				b.WriteByte(',')
			}
			if err := writeCanonical(b, item); err != nil {
				return err
			}
		}
		b.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			enc, _ := quoteJSONString(k)
			b.Write(enc)
			b.WriteByte(':')
			if err := writeCanonical(b, x[k]); err != nil {
				return err
			}
		}
		b.WriteByte('}')
	default:
		return fmt.Errorf("unsupported JSON value %T", v)
	}
	return nil
}

// quoteJSONString serializes a string per RFC 8785 (JCS). We deliberately do
// NOT delegate to encoding/json: Go's encoder emits short escapes only for
// \\ \" \n \r \t and uses \u00xx for every other control byte — but JCS
// (ECMAScript JSON.stringify) also requires the two-char \b (U+0008) and
// \f (U+000C) short forms. Delegating diverges from the Python reference and
// from RFC 8785 on those two code points, silently splitting the WarrantID.
func quoteJSONString(s string) ([]byte, error) {
	var b bytes.Buffer
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\b':
			b.WriteString(`\b`)
		case '\t':
			b.WriteString(`\t`)
		case '\n':
			b.WriteString(`\n`)
		case '\f':
			b.WriteString(`\f`)
		case '\r':
			b.WriteString(`\r`)
		default:
			if r < 0x20 {
				fmt.Fprintf(&b, `\u%04x`, r) // lowercase hex, matches JCS + Python
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.Bytes(), nil
}

func blobHash(data []byte) string {
	sum := sha256.Sum256(data)
	return hex.EncodeToString(sum[:])
}

func warrantID(body map[string]any) (string, error) {
	canon, err := canonicalJSON(body)
	if err != nil {
		return "", err
	}
	return blobHash(canon), nil
}

func validateBody(b map[string]any) []string {
	var errs []string
	for k := range b {
		if !bodyFields[k] {
			errs = append(errs, "unknown field: "+k)
		}
	}
	for k := range bodyFields {
		if _, ok := b[k]; !ok {
			errs = append(errs, "missing field: "+k)
		}
	}
	if len(errs) > 0 {
		sort.Strings(errs)
		return errs
	}

	warrantVersion, ok := b["warrant"].(string)
	if !ok || (warrantVersion != "0.1" && warrantVersion != "0.2") {
		errs = append(errs, `warrant version must be one of ("0.1", "0.2")`)
	}
	decision, ok := b["decision"].(string)
	if !ok || !decisions[decision] {
		errs = append(errs, "decision must be propose|accept|reject|supersede")
	}
	errs = append(errs, validateSubject(b["subject"])...)
	errs = append(errs, validateHexArray("under", b["under"], true)...)
	errs = append(errs, validateHexArray("evidence", b["evidence"], false)...)
	errs = append(errs, validateActor(b["actor"])...)
	errs = append(errs, validateHexArray("prior", b["prior"], false)...)
	if n, ok := b["ts"].(json.Number); !ok || !intJSONRe.MatchString(n.String()) {
		errs = append(errs, "ts must be an integer")
	} else if v, err := n.Int64(); err != nil || v < 0 {
		// SPEC s2: ts in 0..2^63-1; out-of-range is schema-invalid — never
		// silently narrowed (a clamped Int64 here once split PY/GO warnings)
		errs = append(errs, "ts must be an integer (unix seconds) in 0..2^63-1")
	}

	because, ok := b["because"].([]any)
	if !ok {
		errs = append(errs, "because must be a list")
		because = nil
	}
	for i, r := range because {
		for _, msg := range validateReason(r, warrantVersion) {
			errs = append(errs, fmt.Sprintf("because[%d]: %s", i, msg))
		}
	}
	if (decision == "reject" || decision == "supersede") && len(because) < 1 {
		errs = append(errs, decision+" requires >=1 reason")
	}
	return errs
}

func validateSubject(v any) []string {
	m, ok := v.(map[string]any)
	if !ok {
		return []string{"subject must be {hash, note?}"}
	}
	var errs []string
	for k := range m {
		if k != "hash" && k != "note" {
			errs = append(errs, "subject has unknown field: "+k)
		}
	}
	h, ok := m["hash"].(string)
	if !ok || !isHex64(h) {
		errs = append(errs, "subject.hash must be hex64")
	}
	if note, exists := m["note"]; exists {
		s, ok := note.(string)
		if !ok || utf8.RuneCountInString(s) > 200 { // chars = code points, per SPEC §2 (matches Python)
			errs = append(errs, "subject.note must be a string of <=200 chars")
		}
	}
	return errs
}

func validateActor(v any) []string {
	m, ok := v.(map[string]any)
	if !ok || len(m) != 1 {
		return []string{"actor must be {id: <nonempty string>}"}
	}
	id, ok := m["id"].(string)
	if !ok || id == "" {
		return []string{"actor must be {id: <nonempty string>}"}
	}
	return nil
}

func validateHexArray(name string, v any, nonEmpty bool) []string {
	a, ok := v.([]any)
	if !ok {
		return []string{name + " must be a list of hex64 hashes"}
	}
	if nonEmpty && len(a) == 0 {
		return []string{name + " must contain >=1 hex64 hashes"}
	}
	for _, item := range a {
		s, ok := item.(string)
		if !ok || !isHex64(s) {
			return []string{name + " must be a list of hex64 hashes"}
		}
	}
	return nil
}

func validateReason(v any, warrantVersion string) []string {
	r, ok := v.(map[string]any)
	if !ok {
		return []string{"reason is not an object"}
	}
	kind, _ := r["kind"].(string)
	switch kind {
	case "prose":
		if len(r) != 2 {
			return []string{"prose reason must be {kind, text}"}
		}
		if _, ok := r["text"].(string); !ok {
			return []string{"prose reason must be {kind, text}"}
		}
		return nil
	case "check":
		allowed := map[string]bool{
			"kind": true, "check": true, "runtime": true, "verdict": true, "transcript": true,
		}
		var errs []string
		for k := range r {
			if !allowed[k] {
				errs = append(errs, "check reason has unknown field: "+k)
			}
		}
		check, ok := r["check"].(string)
		if !ok || !isHex64(check) {
			errs = append(errs, "check must be hex64")
		}
		runtime, ok := r["runtime"].(string)
		if runtime == "ski@v1" && warrantVersion == "0.1" {
			errs = append(errs, "runtime ski@v1 is reserved and MUST be rejected in v0.1")
		} else if !ok || runtime != "cmd@v1" && !(warrantVersion == "0.2" && runtime == "ski@v1") {
			errs = append(errs, "runtime must be cmd@v1")
		}
		verdict, ok := r["verdict"].(string)
		if !ok || (verdict != "pass" && verdict != "fail") {
			errs = append(errs, "verdict must be pass|fail")
		}
		if tr, exists := r["transcript"]; exists {
			s, ok := tr.(string)
			if !ok || !isHex64(s) {
				errs = append(errs, "transcript must be hex64")
			}
		}
		return errs
	default:
		return []string{fmt.Sprintf("unknown reason kind: %q", kind)}
	}
}

func isHex64(s string) bool {
	return hex64Re.MatchString(s)
}

type skiCheck struct {
	term   [32]byte
	atp    uint32
	expect [32]byte
}

type sigmaStore map[[32]byte][]byte

type sigmaTerm struct {
	kind        string
	h           [32]byte
	left, right *sigmaTerm
}

type sigmaNode struct {
	op          byte
	atom        [32]byte
	left, right [32]byte
}

var (
	sigmaIHash      = mustHash32("2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162")
	sigmaKHash      = mustHash32("bc0c2fe26e44e2aed8ce500a74963bc270fd4a49ec0c2e4837ce7a64bb0a486c")
	sigmaSHash      = mustHash32("887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6")
	sigmaInvalid    = mustHash32("7cc62bcc7c921683532cec1c1c331ca81d76b001e0c7f407a4078df7f696efe8")
	sigmaATP        = mustHash32("dc435a08513893bacd07abd802b9c526e92ae57ca6db40c1c8f369fd7032e090")
	sigmaUnresolved = mustHash32("75daae55453d9a98bfadb847d70b73fdd0be91d3b6ef8511d22fc42aa2c7c8e2")
	sigmaGenesis    = map[[32]byte][]byte{
		sigmaIHash: mustHexBytes("0001a83dd0ccbffe39d071cc317ddf6e97f5c6b1c87af91919271f9fa140b0508c6c"),
		sigmaKHash: mustHexBytes("000186be9a55762d316a3026c2836d044f5fc76e34da10e1b45feee5f18be7edb177"),
		sigmaSHash: mustHexBytes("00018de0b3c47f112c59745f717a626932264c422a7563954872e237b223af4ad643"),
	}
)

func mustHash32(s string) [32]byte {
	h, err := parseHash32(s)
	if err != nil {
		panic(err)
	}
	return h
}

func mustHexBytes(s string) []byte {
	b, err := hex.DecodeString(s)
	if err != nil {
		panic(err)
	}
	return b
}

func parseHash32(s string) ([32]byte, error) {
	var out [32]byte
	if !isHex64(s) {
		return out, fmt.Errorf("not hex64: %q", s)
	}
	b, err := hex.DecodeString(s)
	if err != nil {
		return out, err
	}
	copy(out[:], b)
	return out, nil
}

func hash32(data []byte) [32]byte {
	return sha256.Sum256(data)
}

func hash32Hex(h [32]byte) string {
	return hex.EncodeToString(h[:])
}

func parseSkiCheckBlob(data []byte) (skiCheck, error) {
	var out skiCheck
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return out, err
	}
	var extra any
	if err := dec.Decode(&extra); err != io.EOF {
		return out, errors.New("ski check blob must contain exactly one JSON value")
	}
	m, ok := v.(map[string]any)
	if !ok || len(m) != 4 {
		return out, errors.New("ski check blob must be exactly {ski, term, atp, expect}")
	}
	for _, k := range []string{"ski", "term", "atp", "expect"} {
		if _, ok := m[k]; !ok {
			return out, errors.New("ski check blob must be exactly {ski, term, atp, expect}")
		}
	}
	canon, err := canonicalJSON(m)
	if err != nil || !bytes.Equal(canon, data) {
		return out, errors.New("ski check blob must be JCS-canonical I-JSON")
	}
	ski, ok := m["ski"].(json.Number)
	if !ok || ski.String() != "1" {
		return out, errors.New("ski field must be 1")
	}
	term, ok := m["term"].(string)
	if !ok || !isHex64(term) {
		return out, errors.New("term must be hex64")
	}
	expect, ok := m["expect"].(string)
	if !ok || !isHex64(expect) {
		return out, errors.New("expect must be hex64")
	}
	atp, ok := m["atp"].(json.Number)
	if !ok || !intJSONRe.MatchString(atp.String()) {
		return out, errors.New("atp must be uint32")
	}
	n, err := atp.Int64()
	if err != nil || n < 0 || n > 0xffffffff {
		return out, errors.New("atp must be uint32")
	}
	out.term, _ = parseHash32(term)
	out.expect, _ = parseHash32(expect)
	out.atp = uint32(n)
	return out, nil
}

func runSkiCheckFromStore(blobs map[string][]byte, checkHex string) (string, string, uint32, error) {
	data, ok := blobs[checkHex]
	if !ok {
		short := checkHex
		if len(short) > 12 {
			short = short[:12]
		}
		return "", "", 0, fmt.Errorf("check blob %s not in store", short)
	}
	store := sigmaStore{}
	for h, b := range blobs {
		parsed, err := parseHash32(h)
		if err == nil {
			store[parsed] = b
		}
	}
	return runSkiCheck(data, store)
}

func runSkiCheck(checkBytes []byte, store sigmaStore) (string, string, uint32, error) {
	check, err := parseSkiCheckBlob(checkBytes)
	if err != nil {
		return "", "", 0, fmt.Errorf("invalid ski check blob: %w", err)
	}
	if check.atp > skiReexecMaxATP { // SPEC §3.1: local re-execution budget
		return "", "", 0, errors.New("atp exceeds re-execution budget")
	}
	result, spent := sigmaEval(check.term, check.atp, store)
	resultHash := sigmaTermHash(result)
	verdict := "fail"
	if resultHash == check.expect {
		verdict = "pass"
	}
	return verdict, hash32Hex(resultHash), spent, nil
}

func sigmaEval(term [32]byte, atp uint32, store sigmaStore) (*sigmaTerm, uint32) {
	t := &sigmaTerm{kind: "thunk", h: term}
	spent := uint32(0)
	for {
		next, cost, outcome := sigmaStep(t, atp-spent, store)
		switch outcome {
		case "normal":
			return t, spent
		case "atp":
			return &sigmaTerm{kind: "dis", h: sigmaATP}, spent
		case "unresolved":
			return &sigmaTerm{kind: "dis", h: sigmaUnresolved}, spent
		}
		t = next
		spent += cost
		// The memory bound `size − 1 ≤ spent` is a THEOREM (Book I §3.4,
		// Lean-proved); it needs no runtime re-check. The fence that used to
		// sit here returned a canonical DISSONANCE(ATP) if it ever fired —
		// laundering a would-be implementation bug into a canonical outcome,
		// which Book I §3.6 forbids (local faults MUST NOT serialize as
		// DISSONANCE). Neither the Python oracle nor the Rust impl has such
		// a fence. (Fable 5 sigma-glyph review, 2026-07.)
	}
}

func sigmaStep(t *sigmaTerm, remaining uint32, store sigmaStore) (*sigmaTerm, uint32, string) {
	switch t.kind {
	case "thunk":
		if isSigmaGenesis(t.h) {
			return nil, 0, "normal"
		}
		if remaining < 1 {
			return nil, 0, "atp"
		}
		v, ok := sigmaForce(t.h, store)
		if !ok {
			return nil, 0, "unresolved"
		}
		cost := uint32(sigmaSize(v))
		if cost > remaining {
			return nil, 0, "atp"
		}
		return v, cost, "step"
	case "ref":
		if remaining < 1 {
			return nil, 0, "atp"
		}
		return &sigmaTerm{kind: "thunk", h: t.h}, 1, "step"
	case "app":
		f, a := t.left, t.right
		if sigmaGlyphEq(f, sigmaIHash) {
			if remaining < 1 {
				return nil, 0, "atp"
			}
			return a, 1, "step"
		}
		if f.kind == "app" {
			if sigmaGlyphEq(f.left, sigmaKHash) {
				if remaining < 1 {
					return nil, 0, "atp"
				}
				return f.right, 1, "step"
			}
			if f.left.kind == "app" && sigmaGlyphEq(f.left.left, sigmaSHash) {
				x, y, z := f.left.right, f.right, a
				// R-S cost = 1 + size(z), computed in uint64: size(z) can
				// legally approach 2³² at near-max budgets (size ≤ 1 + spent),
				// and a uint32 narrowing here made an unaffordable step look
				// affordable — a Book I §3.4 violation ("a step costing more
				// than 2³²−1 is unreachable for any canonical budget → ATP
				// Exhausted, not implementation-defined") and a consensus
				// split against the Python (bignum) and Rust (u64) impls.
				// (Fable 5 sigma-glyph review, 2026-07.)
				cost64 := 1 + sigmaSize(z)
				if cost64 > uint64(remaining) {
					return nil, 0, "atp"
				}
				cost := uint32(cost64)
				return &sigmaTerm{
					kind: "app",
					left: &sigmaTerm{
						kind:  "app",
						left:  x,
						right: z,
					},
					right: &sigmaTerm{
						kind:  "app",
						left:  y,
						right: z,
					},
				}, cost, "step"
			}
		}
		nf, cost, outcome := sigmaStep(f, remaining, store)
		if outcome == "step" {
			return &sigmaTerm{kind: "app", left: nf, right: a}, cost, "step"
		}
		if outcome != "normal" {
			return nil, 0, outcome
		}
		na, cost, outcome := sigmaStep(a, remaining, store)
		if outcome == "step" {
			return &sigmaTerm{kind: "app", left: f, right: na}, cost, "step"
		}
		return nil, 0, outcome
	default:
		return nil, 0, "normal"
	}
}

func sigmaForce(h [32]byte, store sigmaStore) (*sigmaTerm, bool) {
	data, ok := sigmaGenesis[h]
	if !ok {
		data, ok = store[h]
	}
	if !ok {
		return nil, false
	}
	node, valid := sigmaDeserialize(data)
	if !valid {
		return &sigmaTerm{kind: "dis", h: sigmaInvalid}, true
	}
	switch node.op {
	case 0x00:
		return &sigmaTerm{kind: "lit", h: node.atom}, true
	case 0x01:
		return &sigmaTerm{kind: "ref", h: node.atom}, true
	case 0x02:
		return &sigmaTerm{
			kind:  "app",
			left:  &sigmaTerm{kind: "thunk", h: node.left},
			right: &sigmaTerm{kind: "thunk", h: node.right},
		}, true
	case 0xff:
		return &sigmaTerm{kind: "dis", h: node.atom}, true
	default:
		return &sigmaTerm{kind: "dis", h: sigmaInvalid}, true
	}
}

func sigmaDeserialize(data []byte) (sigmaNode, bool) {
	var node sigmaNode
	if len(data) < 2 {
		return node, false
	}
	op, flags := data[0], data[1]
	if flags&^0x07 != 0 {
		return node, false
	}
	required := byte(0)
	switch op {
	case 0x00, 0x01, 0xff:
		required = 0x01
	case 0x02:
		required = 0x06
	default:
		return node, false
	}
	if flags != required {
		return node, false
	}
	count := 0
	for _, bit := range []byte{0x01, 0x02, 0x04} {
		if flags&bit != 0 {
			count++
		}
	}
	if len(data) != 2+32*count {
		return node, false
	}
	node.op = op
	off := 2
	if flags&0x01 != 0 {
		copy(node.atom[:], data[off:off+32])
		off += 32
	}
	if flags&0x02 != 0 {
		copy(node.left[:], data[off:off+32])
		off += 32
	}
	if flags&0x04 != 0 {
		copy(node.right[:], data[off:off+32])
	}
	return node, true
}

func sigmaTermBytes(t *sigmaTerm) []byte {
	switch t.kind {
	case "lit":
		return sigmaSer(0x00, 0x01, t.h, [32]byte{}, [32]byte{})
	case "ref":
		return sigmaSer(0x01, 0x01, t.h, [32]byte{}, [32]byte{})
	case "dis":
		return sigmaSer(0xff, 0x01, t.h, [32]byte{}, [32]byte{})
	case "app":
		return sigmaSer(0x02, 0x06, [32]byte{}, sigmaTermHash(t.left), sigmaTermHash(t.right))
	default:
		return t.h[:]
	}
}

func sigmaSer(op, flags byte, atom, left, right [32]byte) []byte {
	out := []byte{op, flags}
	if flags&0x01 != 0 {
		out = append(out, atom[:]...)
	}
	if flags&0x02 != 0 {
		out = append(out, left[:]...)
	}
	if flags&0x04 != 0 {
		out = append(out, right[:]...)
	}
	return out
}

func sigmaTermHash(t *sigmaTerm) [32]byte {
	if t.kind == "thunk" {
		return t.h
	}
	return hash32(sigmaTermBytes(t))
}

func sigmaSize(t *sigmaTerm) uint64 {
	switch t.kind {
	case "app":
		return 1 + sigmaSize(t.left) + sigmaSize(t.right)
	case "ref":
		return 2
	default:
		return 1
	}
}

func sigmaGlyphEq(t *sigmaTerm, h [32]byte) bool {
	switch t.kind {
	case "thunk":
		return t.h == h
	case "lit":
		return hash32(sigmaSer(0x00, 0x01, t.h, [32]byte{}, [32]byte{})) == h
	default:
		return false
	}
}

func isSigmaGenesis(h [32]byte) bool {
	_, ok := sigmaGenesis[h]
	return ok
}

func isUnverifiable(body map[string]any) bool {
	if body["decision"] != "reject" {
		return false
	}
	reasons, ok := body["because"].([]any)
	if !ok || len(reasons) == 0 {
		return false
	}
	for _, item := range reasons {
		r, ok := item.(map[string]any)
		if !ok || r["kind"] != "prose" {
			return false
		}
	}
	return true
}

func verifySig(wid string, sig any) bool {
	s, ok := sig.(map[string]any)
	if !ok {
		return false
	}
	keyHex, ok1 := s["key"].(string)
	sigHex, ok2 := s["sig"].(string)
	if !ok1 || !ok2 {
		return false
	}
	key, err := hex.DecodeString(keyHex)
	if err != nil || len(key) != ed25519.PublicKeySize {
		return false
	}
	rawSig, err := hex.DecodeString(sigHex)
	if err != nil || len(rawSig) != ed25519.SignatureSize {
		return false
	}
	if weakEd25519PubKey(key) {
		return false
	}
	msg, err := hex.DecodeString(wid)
	if err != nil || len(msg) != 32 {
		return false
	}
	return ed25519.Verify(ed25519.PublicKey(key), msg, rawSig)
}

// SPEC §5: small-order and non-canonical Ed25519 public keys are rejected.
// Such a key lets an all-zero signature verify for a fraction of messages
// (small-order forgery), and Python `cryptography` / Go `crypto/ed25519`
// disagree on which they accept — so the same envelope can verify in one impl
// and not the other. Byte/integer checks only, so every impl agrees. (Fable 5
// review, 2026-07: reproduced a 16/64 vs 17/64 accept split on the all-zero
// key.)
var ed25519SmallOrder = map[string]bool{
	"0100000000000000000000000000000000000000000000000000000000000000": true,
	"c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a": true,
	"0000000000000000000000000000000000000000000000000000000000000080": true,
	"26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05": true,
	"ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f": true,
	"26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85": true,
	"0000000000000000000000000000000000000000000000000000000000000000": true,
	"c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa": true,
}

var ed25519P = new(big.Int).Sub(new(big.Int).Lsh(big.NewInt(1), 255), big.NewInt(19))

func weakEd25519PubKey(raw []byte) bool {
	if len(raw) != 32 || ed25519SmallOrder[hex.EncodeToString(raw)] {
		return true
	}
	be := make([]byte, 32) // little-endian -> big-endian, sign bit cleared
	for i := 0; i < 32; i++ {
		be[i] = raw[31-i]
	}
	be[0] &= 0x7f
	return new(big.Int).SetBytes(be).Cmp(ed25519P) >= 0 // non-canonical y
}

func conformance(dir string) bool {
	var ok []bool
	chk := func(name string, cond bool, detail string) {
		ok = append(ok, cond)
		if cond {
			fmt.Println("OK  ", name)
		} else {
			fmt.Println("FAIL", name, detail)
		}
	}

	for _, name := range []string{"policy.txt", "check.sh"} {
		data, err := os.ReadFile(filepath.Join(dir, name))
		got := ""
		if err == nil {
			got = blobHash(data)
		}
		chk("blob "+name, err == nil && got == specVectors[name], got)
	}

	type chainItem struct {
		wid  string
		body map[string]any
	}
	chain := map[string]chainItem{}
	for _, name := range []string{"propose.warrant.json", "reject.warrant.json", "accept.warrant.json"} {
		env, err := readJSON(filepath.Join(dir, name))
		if err != nil {
			chk("read "+name, false, err.Error())
			continue
		}
		body, _ := env["body"].(map[string]any)
		errs := validateBody(body)
		chk("schema "+name, len(errs) == 0, strings.Join(errs, "; "))
		wid, err := warrantID(body)
		if err != nil {
			chk("WarrantID "+name, false, err.Error())
		} else {
			chk("WarrantID "+name, wid == specVectors[name], wid)
		}
		sigs, _ := env["sigs"].([]any)
		for _, s := range sigs {
			actor := "?"
			if sm, ok := s.(map[string]any); ok {
				if a, ok := sm["actor"].(string); ok {
					actor = a
				}
			}
			chk("sig "+name+" by "+actor, verifySig(wid, s), "")
		}
		chain[name] = chainItem{wid: wid, body: body}
	}
	p := chain["propose.warrant.json"].wid
	r := chain["reject.warrant.json"]
	a := chain["accept.warrant.json"]
	chk("chain reject.prior -> propose", stringArrayEqual(getStringArray(r.body, "prior"), []string{p}), "")
	chk("chain accept.prior -> reject", stringArrayEqual(getStringArray(a.body, "prior"), []string{r.wid}), "")
	ts := []int64{getInt(chain["propose.warrant.json"].body, "ts"), getInt(r.body, "ts"), getInt(a.body, "ts")}
	chk("ts non-decreasing", ts[0] <= ts[1] && ts[1] <= ts[2], fmt.Sprint(ts))

	skiDir := filepath.Join(dir, "ski")
	if isDir(skiDir) {
		env, err := readJSON(filepath.Join(skiDir, "accept-ski.warrant.json"))
		if err != nil {
			chk("ski: read warrant", false, err.Error())
		} else {
			body, _ := env["body"].(map[string]any)
			wid, err := warrantID(body)
			if err != nil {
				chk("ski: warrant id", false, err.Error())
			} else {
				chk("ski: warrant id", wid == "8c9267bccbc217db2f3f16e6928acaf062a1c78443b2317985567b238ccfe8a0", wid)
			}
			errs := validateBody(body)
			chk("ski: schema (0.2 body)", len(errs) == 0, strings.Join(errs, "; "))
			sigs, _ := env["sigs"].([]any)
			for _, s := range sigs {
				actor := "?"
				if sm, ok := s.(map[string]any); ok {
					if a, ok := sm["actor"].(string); ok {
						actor = a
					}
				}
				chk("ski: sig by "+actor, verifySig(wid, s), "")
			}
			v01 := cloneMap(body)
			v01["warrant"] = "0.1"
			chk("ski: 0.1 body MUST reject ski@v1", hasValidationMessage(v01, "runtime ski@v1 is reserved and MUST be rejected in v0.1"), "")
		}

		blobs := map[string][]byte{}
		entries, err := listFiles(skiDir)
		if err != nil {
			chk("ski: list blobs", false, err.Error())
		} else {
			for _, path := range entries {
				if strings.HasSuffix(filepath.Base(path), ".warrant.json") {
					continue
				}
				data, err := os.ReadFile(path)
				if err == nil {
					blobs[blobHash(data)] = data
				}
			}
		}
		checkBytes, err := os.ReadFile(filepath.Join(skiDir, "check.json"))
		checkHash := ""
		if err == nil {
			checkHash = blobHash(checkBytes)
		}
		chk("ski: check blob hash", err == nil && checkHash == "0c30960435e9c9302a6a1538682e5864f2a754475369979bd3d635543976b2ad", checkHash)
		verdict, result, spent, err := runSkiCheckFromStore(blobs, checkHash)
		chk("ski: re-run -> pass, H(S), 20 ATP",
			err == nil && verdict == "pass" && result == "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6" && spent == 20,
			fmt.Sprintf("%s %s %d %v", verdict, result, spent, err))
	}

	passed := 0
	for _, v := range ok {
		if v {
			passed++
		}
	}
	if passed == len(ok) {
		fmt.Printf("\nCONFORMANCE: ALL PASS (%d/%d)\n", passed, len(ok))
		return true
	}
	fmt.Printf("\nCONFORMANCE: FAILURES PRESENT (%d/%d)\n", passed, len(ok))
	return false
}

func sigmaConformance(path string) bool {
	root, err := readJSON(path)
	if err != nil {
		fmt.Println("FAIL read vectors", err)
		return false
	}
	rawObjects, ok := root["objects"].(map[string]any)
	if !ok {
		fmt.Println("FAIL objects map missing")
		return false
	}
	allStore := sigmaStore{}
	for h, v := range rawObjects {
		bs, ok := v.(string)
		if !ok {
			fmt.Println("FAIL object", h, "bytes not string")
			return false
		}
		hash, err := parseHash32(h)
		if err != nil {
			fmt.Println("FAIL object", h, err)
			return false
		}
		data, err := hex.DecodeString(bs)
		if err != nil {
			fmt.Println("FAIL object", h, err)
			return false
		}
		allStore[hash] = data
	}
	vectors, ok := root["vectors"].([]any)
	if !ok {
		fmt.Println("FAIL vectors list missing")
		return false
	}
	total, passed := 0, 0
	for _, item := range vectors {
		v, ok := item.(map[string]any)
		if !ok || v["kind"] != "eval" {
			continue
		}
		total++
		id, _ := v["id"].(string)
		termHex, _ := v["term"].(string)
		term, termErr := parseHash32(termHex)
		atpN, atpOK := v["atp"].(json.Number)
		atp64, atpErr := atpN.Int64()
		expected, _ := v["expected"].(map[string]any)
		wantHash, _ := expected["result_hash"].(string)
		spentN, spentOK := expected["atp_spent"].(json.Number)
		wantSpent64, spentErr := spentN.Int64()
		store := allStore
		if subsetRaw, ok := v["store_subset"].([]any); ok {
			store = sigmaStore{}
			for _, item := range subsetRaw {
				h, ok := item.(string)
				if !ok {
					continue
				}
				parsed, err := parseHash32(h)
				if err == nil {
					if data, ok := allStore[parsed]; ok {
						store[parsed] = data
					}
				}
			}
		}
		if termErr != nil || !atpOK || atpErr != nil || atp64 < 0 || atp64 > 0xffffffff || wantHash == "" || !spentOK || spentErr != nil {
			fmt.Println("FAIL", id, "malformed vector")
			continue
		}
		result, spent := sigmaEval(term, uint32(atp64), store)
		gotHash := hash32Hex(sigmaTermHash(result))
		matched := gotHash == wantHash && uint32(wantSpent64) == spent
		if matched {
			passed++
			fmt.Println("OK  ", id)
		} else {
			fmt.Printf("FAIL %s result=%s spent=%d want=%s spent=%d\n", id, gotHash, spent, wantHash, wantSpent64)
		}
	}
	if passed == total {
		fmt.Printf("\nSIGMA CONFORMANCE: ALL PASS (%d/%d eval)\n", passed, total)
		return true
	}
	fmt.Printf("\nSIGMA CONFORMANCE: FAILURES PRESENT (%d/%d eval)\n", passed, total)
	return false
}

type verifyRecord struct {
	label string
	claim string
	env   map[string]any
	err   error
}

type settlementContext struct {
	records        map[string]map[string]any
	blobs          map[string][]byte
	roots          map[string]bool
	activeRoots    map[string]bool
	activeRecords  map[string]bool
	invalidPolicy  map[string]bool
	globalWarnings [][2]string
	conflictActors map[string]bool
	keysBefore     func(string) map[string]map[string]bool
}

func loadVerifyData(dir string) ([]verifyRecord, map[string]map[string]any, map[string][]byte, error) {
	recordsDir := filepath.Join(dir, "records")
	blobsDir := filepath.Join(dir, "blobs")
	storeMode := isDir(recordsDir) && isDir(blobsDir)
	recordFiles, blobFiles, err := verifyInputs(dir, recordsDir, blobsDir, storeMode)
	if err != nil {
		return nil, nil, nil, err
	}
	var recList []verifyRecord
	records := map[string]map[string]any{}
	blobs := map[string][]byte{}
	for _, path := range blobFiles {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if storeMode {
			name := filepath.Base(path)
			if isHex64(name) {
				blobs[name] = data
			}
		} else {
			blobs[blobHash(data)] = data
		}
	}
	for _, path := range recordFiles {
		label := filepath.Base(path)
		claim := ""
		if storeMode {
			claim = strings.TrimSuffix(label, ".json")
		}
		env, err := readJSON(path)
		rec := verifyRecord{label: label, claim: claim, env: env, err: err}
		recList = append(recList, rec)
		if err != nil || env == nil {
			continue
		}
		body, ok := env["body"].(map[string]any)
		if !ok {
			continue
		}
		if storeMode {
			records[claim] = env
		} else if wid, err := warrantID(body); err == nil {
			records[wid] = env
		}
	}
	return recList, records, blobs, nil
}

func citedBlobs(body map[string]any) map[string]bool {
	out := map[string]bool{}
	for _, h := range getStringArray(body, "under") {
		out[h] = true
	}
	for _, h := range getStringArray(body, "evidence") {
		out[h] = true
	}
	if subj, ok := body["subject"].(map[string]any); ok {
		if h, ok := subj["hash"].(string); ok {
			out[h] = true
		}
	}
	for _, item := range getArray(body, "because") {
		r, ok := item.(map[string]any)
		if !ok || r["kind"] != "check" {
			continue
		}
		if h, ok := r["check"].(string); ok {
			out[h] = true
		}
		if h, ok := r["transcript"].(string); ok {
			out[h] = true
		}
	}
	return out
}

func priorClosure(records map[string]map[string]any, wid string) map[string]bool {
	seen := map[string]bool{}
	env := records[wid]
	if env == nil {
		return seen
	}
	body, _ := env["body"].(map[string]any)
	stack := append([]string{}, getStringArray(body, "prior")...)
	for len(stack) > 0 {
		cur := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if seen[cur] || records[cur] == nil {
			continue
		}
		seen[cur] = true
		b, _ := records[cur]["body"].(map[string]any)
		stack = append(stack, getStringArray(b, "prior")...)
	}
	return seen
}

func fingerprint(reason, body map[string]any, blobs map[string][]byte) (string, bool) {
	if reason["kind"] != "check" {
		return "", false
	}
	runtime, _ := reason["runtime"].(string)
	verdict, _ := reason["verdict"].(string)
	switch runtime {
	case "cmd@v1":
		transcript, ok := reason["transcript"].(string)
		if !ok || transcript == "" {
			return "", false
		}
		check, _ := reason["check"].(string)
		if blobs[check] == nil || blobs[transcript] == nil {
			return "", false
		}
		evidence := getStringArray(body, "evidence")
		for _, h := range evidence {
			if blobs[h] == nil {
				return "", false
			}
		}
		sort.Strings(evidence)
		return "cmd@v1\x00" + strings.Join(evidence, ",") + "\x00" + verdict + "\x00" + transcript, true
	case "ski@v1":
		check, ok := reason["check"].(string)
		if !ok || blobs[check] == nil {
			return "", false
		}
		parsed, err := parseSkiCheckBlob(blobs[check])
		if err != nil {
			return "", false
		}
		_, result, _, err := runSkiCheckFromStore(blobs, check)
		if err != nil {
			return "", false
		}
		return "ski@v1\x00" + hash32Hex(parsed.term) + "\x00" + hash32Hex(parsed.expect) + "\x00" + verdict + "\x00" + result, true
	default:
		return "", false
	}
}

func tunnelFingerprints(records map[string]map[string]any, blobs map[string][]byte, wid string) map[string]bool {
	out := map[string]bool{}
	for rwid := range priorClosure(records, wid) {
		body, _ := records[rwid]["body"].(map[string]any)
		for _, item := range getArray(body, "because") {
			if r, ok := item.(map[string]any); ok {
				if fp, ok := fingerprint(r, body, blobs); ok {
					out[fp] = true
				}
			}
		}
	}
	return out
}

func settlementAdmissibility(records map[string]map[string]any, blobs map[string][]byte, settlingWid string, candidateBody map[string]any) string {
	knownBlobs := map[string]bool{}
	for rwid := range priorClosure(records, settlingWid) {
		body, _ := records[rwid]["body"].(map[string]any)
		for h := range citedBlobs(body) {
			knownBlobs[h] = true
		}
	}
	if env := records[settlingWid]; env != nil {
		if body, ok := env["body"].(map[string]any); ok {
			for h := range citedBlobs(body) {
				knownBlobs[h] = true
			}
		}
	}
	evidence := getStringArray(candidateBody, "evidence")
	sort.Strings(evidence)
	for _, h := range evidence {
		if !knownBlobs[h] {
			return "admissible: (a) new evidence"
		}
	}
	old := tunnelFingerprints(records, blobs, settlingWid)
	if env := records[settlingWid]; env != nil {
		if body, ok := env["body"].(map[string]any); ok {
			for _, item := range getArray(body, "because") {
				if r, ok := item.(map[string]any); ok {
					if fp, ok := fingerprint(r, body, blobs); ok {
						old[fp] = true
					}
				}
			}
		}
	}
	for _, item := range getArray(candidateBody, "because") {
		r, ok := item.(map[string]any)
		if !ok {
			continue
		}
		if fp, ok := fingerprint(r, candidateBody, blobs); ok && !old[fp] {
			return "admissible: (b) new outcome fingerprint"
		}
	}
	return "inadmissible: cites nothing new"
}

func parsePolicyBlob(blobs map[string][]byte, h string) (map[string]any, bool) {
	raw := blobs[h]
	if raw == nil {
		return nil, false
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, false
	}
	doc, ok := v.(map[string]any)
	if !ok || doc["warrant_policy"] != "0.3" {
		return nil, false
	}
	canon, err := canonicalJSON(doc)
	if err != nil || !bytes.Equal(canon, raw) || len(doc) != 2 {
		return nil, true
	}
	th, ok := doc["threshold"].(map[string]any)
	if !ok || len(th) != 2 {
		return nil, true
	}
	minN, ok := th["min_sigs"].(json.Number)
	if !ok || !intJSONRe.MatchString(minN.String()) {
		return nil, true
	}
	min64, err := minN.Int64()
	if err != nil {
		return nil, true
	}
	rawActors, ok := th["actors"].([]any)
	if !ok || len(rawActors) == 0 {
		return nil, true
	}
	seen := map[string]bool{}
	actors := make([]string, 0, len(rawActors))
	for _, item := range rawActors {
		a, ok := item.(string)
		if !ok || a == "" || seen[a] {
			return nil, true
		}
		seen[a] = true
		actors = append(actors, a)
	}
	if min64 < 1 || min64 > int64(len(actors)) {
		return nil, true
	}
	return map[string]any{"min_sigs": int(min64), "actors": actors}, false
}

func recordPolicy(blobs map[string][]byte, body map[string]any) ([]map[string]any, bool) {
	var policies []map[string]any
	invalid := false
	for _, h := range getStringArray(body, "under") {
		p, bad := parsePolicyBlob(blobs, h)
		if bad {
			invalid = true
		}
		if p != nil {
			policies = append(policies, p)
		}
	}
	return policies, invalid
}

func validSigActors(wid string, env map[string]any, keys map[string]map[string]bool) map[string]bool {
	out := map[string]bool{}
	for _, s := range getArray(env, "sigs") {
		if !verifySig(wid, s) {
			continue
		}
		sm, _ := s.(map[string]any)
		actor, _ := sm["actor"].(string)
		key, _ := sm["key"].(string)
		if keys != nil {
			if keys[actor] == nil || !keys[actor][key] {
				continue
			}
		}
		out[actor] = true
	}
	return out
}

func thresholdSatisfied(wid string, env map[string]any, policy map[string]any, keys map[string]map[string]bool, conflicted map[string]bool) bool {
	rawActors, _ := policy["actors"].([]string)
	var actors []string
	for _, a := range rawActors {
		if conflicted == nil || !conflicted[a] {
			actors = append(actors, a)
		}
	}
	if len(actors) == 0 {
		return false
	}
	minSigs, _ := policy["min_sigs"].(int)
	if minSigs > len(actors) {
		minSigs = len(actors)
	}
	signers := validSigActors(wid, env, keys)
	n := 0
	for _, a := range actors {
		if signers[a] {
			n++
		}
	}
	return n >= minSigs
}

func policiesSatisfied(blobs map[string][]byte, wid string, env map[string]any, keys map[string]map[string]bool) bool {
	body, _ := env["body"].(map[string]any)
	policies, invalid := recordPolicy(blobs, body)
	if invalid {
		return false
	}
	if len(policies) == 0 {
		for _, s := range getArray(env, "sigs") {
			if verifySig(wid, s) {
				return true
			}
		}
		return false
	}
	for _, p := range policies {
		if !thresholdSatisfied(wid, env, p, keys, nil) {
			return false
		}
	}
	return true
}

func parseKeyBlob(blobs map[string][]byte, h string) (string, string, bool) {
	raw := blobs[h]
	if raw == nil {
		return "", "", false
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return "", "", false
	}
	doc, ok := v.(map[string]any)
	if !ok || len(doc) != 2 {
		return "", "", false
	}
	canon, err := canonicalJSON(doc)
	if err != nil || !bytes.Equal(canon, raw) {
		return "", "", false
	}
	actor, ok1 := doc["actor"].(string)
	key, ok2 := doc["key"].(string)
	if !ok1 || !ok2 || actor == "" || !isHex64(key) {
		return "", "", false
	}
	return actor, key, true
}

func settlementCtx(dir string, records map[string]map[string]any, blobs map[string][]byte, trustPath string, explicitGenesis []string) settlementContext {
	ctx := settlementContext{
		records:        records,
		blobs:          blobs,
		roots:          map[string]bool{},
		activeRoots:    map[string]bool{},
		activeRecords:  map[string]bool{},
		invalidPolicy:  map[string]bool{},
		conflictActors: map[string]bool{},
	}
	trust := map[string]any{}
	if trustPath != "" {
		if m, err := readJSON(trustPath); err == nil {
			trust = m
		}
	}
	genesis := map[string]bool{}
	for _, g := range explicitGenesis {
		genesis[g] = true
	}
	for _, g := range getStringArray(trust, "genesis_roots") {
		genesis[g] = true
	}
	gpath := filepath.Join(dir, "genesis.json")
	if raw, err := os.ReadFile(gpath); err == nil {
		if trust["genesis_json_sha256"] == blobHash(raw) {
			dec := json.NewDecoder(bytes.NewReader(raw))
			dec.UseNumber()
			var v any
			if err := dec.Decode(&v); err == nil {
				if doc, ok := v.(map[string]any); ok {
					for _, g := range getStringArray(doc, "roots") {
						genesis[g] = true
					}
				}
			}
		} else {
			ctx.globalWarnings = append(ctx.globalWarnings, [2]string{"store", "genesis.json unverified"})
		}
	}
	for wid, env := range records {
		body, _ := env["body"].(map[string]any)
		if len(getStringArray(body, "prior")) == 0 {
			ctx.roots[wid] = true
		}
		_, bad := recordPolicy(blobs, body)
		if bad {
			ctx.invalidPolicy[wid] = true
		}
	}
	wellSigned := map[string]bool{}
	for wid, env := range records {
		body, _ := env["body"].(map[string]any)
		if len(validateBody(body)) != 0 {
			continue
		}
		actorID := ""
		if a, ok := body["actor"].(map[string]any); ok {
			actorID, _ = a["id"].(string)
		}
		for _, sg := range getArray(env, "sigs") {
			sm, _ := sg.(map[string]any)
			if verifySig(wid, sg) && sm["actor"] == actorID {
				wellSigned[wid] = true
				break
			}
		}
	}
	// SPEC s9: settlement-active eligibility requires well-signedness
	for g := range genesis {
		if records[g] != nil && wellSigned[g] {
			ctx.activeRoots[g] = true
		}
	}
	recordRootsCache := map[string]map[string]bool{}
	// iterative + cycle-safe (Codex v0.3 hardening audit P1): the previous
	// memoized recursion wrote the cache only AFTER recursing, so a `prior`
	// cycle recursed forever (stack overflow) — the same defect as Python.
	recordRoots := func(wid string) map[string]bool {
		if cached := recordRootsCache[wid]; cached != nil {
			return cached
		}
		roots := map[string]bool{}
		seen := map[string]bool{}
		stack := []string{wid}
		for len(stack) > 0 {
			cur := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			if seen[cur] {
				continue
			}
			seen[cur] = true
			env := records[cur]
			if env == nil {
				continue
			}
			body, _ := env["body"].(map[string]any)
			if body == nil {
				continue
			}
			prior := getStringArray(body, "prior")
			if len(prior) == 0 {
				roots[cur] = true
			} else {
				stack = append(stack, prior...)
			}
		}
		recordRootsCache[wid] = roots
		return roots
	}
	genesisKeys := map[string]map[string]bool{}
	if actors, ok := trust["actors"].(map[string]any); ok {
		for actor, raw := range actors {
			genesisKeys[actor] = map[string]bool{}
			if arr, ok := raw.([]any); ok {
				for _, item := range arr {
					if key, ok := item.(string); ok {
						genesisKeys[actor][key] = true
					}
				}
			}
		}
	}
	ancestorsCache := map[string]map[string]bool{}
	ancestors := func(wid string) map[string]bool {
		if ancestorsCache[wid] == nil {
			ancestorsCache[wid] = priorClosure(records, wid)
		}
		return ancestorsCache[wid]
	}
	depth := func(wid string) int { return len(ancestors(wid)) }
	rotationCache := map[string][2]string{}
	rotationOK := map[string]bool{}
	rotation := func(wid string) (string, string, bool) {
		if _, seen := rotationCache[wid]; seen || rotationOK[wid] {
			v := rotationCache[wid]
			return v[0], v[1], rotationOK[wid]
		}
		env := records[wid]
		if env == nil {
			rotationCache[wid] = [2]string{}
			return "", "", false
		}
		body, _ := env["body"].(map[string]any)
		if body["decision"] == "accept" {
			a, k, ok := parseKeyBlob(blobs, getSubjectHash(body))
			if ok {
				rotationCache[wid] = [2]string{a, k}
				rotationOK[wid] = true
				return a, k, true
			}
		}
		rotationCache[wid] = [2]string{}
		return "", "", false
	}
	keysCache := map[string]map[string]map[string]bool{}
	var keysBefore func(string) map[string]map[string]bool
	var rotationAuthorized func(string) bool
	keysBefore = func(wid string) map[string]map[string]bool {
		if cached := keysCache[wid]; cached != nil {
			return cloneKeyMap(cached)
		}
		keys := cloneKeyMap(genesisKeys)
		aws := keysOfBool(ancestors(wid))
		sort.Slice(aws, func(i, j int) bool {
			di, dj := depth(aws[i]), depth(aws[j])
			if di != dj {
				return di < dj
			}
			return aws[i] < aws[j]
		})
		for _, awid := range aws {
			if actor, key, ok := rotation(awid); ok && rotationAuthorized(awid) {
				keys[actor] = map[string]bool{key: true}
			}
		}
		keysCache[wid] = cloneKeyMap(keys)
		return keys
	}
	rotationAuthorized = func(wid string) bool {
		actor, incoming, ok := rotation(wid)
		if !ok || ctx.invalidPolicy[wid] || !ctx.activeRecords[wid] {
			return false
		}
		env := records[wid]
		proof := false
		for _, s := range getArray(env, "sigs") {
			sm, _ := s.(map[string]any)
			if verifySig(wid, s) && sm["actor"] == actor && sm["key"] == incoming {
				proof = true
			}
		}
		if !proof {
			return false
		}
		priorKeys := keysBefore(wid)
		body, _ := env["body"].(map[string]any)
		policies, bad := recordPolicy(blobs, body)
		if bad {
			return false
		}
		if len(policies) > 0 {
			for _, p := range policies {
				if !thresholdSatisfied(wid, env, p, priorKeys, nil) {
					return false
				}
			}
			return true
		}
		for _, s := range getArray(env, "sigs") {
			sm, _ := s.(map[string]any)
			key, _ := sm["key"].(string)
			if verifySig(wid, s) && sm["actor"] == actor && priorKeys[actor] != nil && priorKeys[actor][key] {
				return true
			}
		}
		return false
	}
	// Fixpoint (SPEC s5.1/s9): adoption thresholds count only keys bound at
	// the adopting warrant's DAG position; key state depends on the active
	// set, so iterate to stability. Roots and adopting records must be
	// well-signed.
	recomputeActive := func() {
		ctx.activeRecords = map[string]bool{}
		for wid := range records {
			if ctx.invalidPolicy[wid] || !wellSigned[wid] {
				continue
			}
			for r := range recordRoots(wid) {
				if ctx.activeRoots[r] {
					ctx.activeRecords[wid] = true
				}
			}
		}
	}
	for {
		recomputeActive()
		keysCache = map[string]map[string]map[string]bool{}
		grew := false
		for root := range ctx.roots {
			if ctx.activeRoots[root] || !wellSigned[root] {
				continue
			}
			for _, wid := range sortedRecordIDs(records) {
				env := records[wid]
				body, _ := env["body"].(map[string]any)
				if !ctx.activeRecords[wid] || body["decision"] != "accept" || getSubjectHash(body) != root {
					continue
				}
				if policiesSatisfied(blobs, wid, env, keysBefore(wid)) {
					ctx.activeRoots[root] = true
					grew = true
					break
				}
			}
		}
		if !grew {
			break
		}
	}

	authorizedRotations := map[string]map[string]bool{}
	for _, wid := range sortedRecordIDs(records) {
		if actor, _, ok := rotation(wid); ok && rotationAuthorized(wid) {
			if authorizedRotations[actor] == nil {
				authorizedRotations[actor] = map[string]bool{}
			}
			authorizedRotations[actor][wid] = true
		}
	}
	for actor, wids := range authorizedRotations {
		maximal := map[string]bool{}
		for wid := range wids {
			maximal[wid] = true
		}
		for a := range wids {
			for b := range wids {
				if a != b && ancestors(b)[a] {
					delete(maximal, a)
				}
			}
		}
		if len(maximal) > 1 {
			ctx.conflictActors[actor] = true
		}
	}
	ctx.keysBefore = keysBefore
	return ctx
}

func verifyDirSettlement(dir, trustConfig string, genesis []string, quiet bool) (int, int) {
	recList, records, blobs, err := loadVerifyData(dir)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1, 0
	}
	errs, warns := 0, 0
	out := func(level, wid, msg string) {
		if level == "ERR" {
			errs++
		} else if level == "WARN" {
			warns++
		}
		if !quiet {
			fmt.Printf("%-4s %.12s  %s\n", level, wid, msg)
		}
	}
	ctx := settlementCtx(dir, records, blobs, trustConfig, genesis)
	for _, w := range ctx.globalWarnings {
		out("WARN", w[0], w[1])
	}
	for _, root := range keysOfBool(ctx.roots) {
		if !ctx.activeRoots[root] {
			out("WARN", root, "unadopted root")
		}
	}
	for _, rec := range recList {
		wid := rec.claim
		if wid == "" {
			wid = strings.TrimSuffix(rec.label, ".warrant.json")
		}
		env := rec.env
		if rec.err != nil {
			out("ERR", wid, rec.err.Error())
			continue
		}
		if len(env) != 2 {
			out("ERR", wid, "envelope must be {body, sigs}")
			continue
		}
		body, ok := env["body"].(map[string]any)
		if !ok {
			out("ERR", wid, "body is not an object")
			continue
		}
		if _, ok := env["sigs"].([]any); !ok {
			out("ERR", wid, "sigs must be a list")
			continue
		}
		if ctx.invalidPolicy[wid] {
			out("ERR", wid, "invalid threshold policy")
		}
		for _, msg := range validateBody(body) {
			out("ERR", wid, "schema: "+msg)
		}
		got, err := warrantID(body)
		if err != nil {
			out("ERR", wid, "WarrantID canonicalization: "+err.Error())
			continue
		}
		if rec.claim != "" {
			if got != rec.claim {
				out("ERR", wid, "WarrantID mismatch: recomputed "+sh12(got))
				continue
			}
		} else {
			wid = got
		}
		sigs := env["sigs"].([]any)
		if len(sigs) == 0 {
			out("ERR", wid, "no signatures")
		}
		actorID := getActorID(body)
		actorSigned := false
		for _, s := range sigs {
			if !verifySig(wid, s) {
				// SPEC §5/§6: a co-signature that fails to verify is reported
				// and EXCLUDED, not fatal — a lone junk co-sig (which anyone with
				// store write access can append) MUST NOT invalidate an
				// otherwise-good record. The ERR below still fires if no valid
				// signature by body.actor.id remains.
				out("WARN", wid, "signature does not verify (excluded)")
				continue
			}
			sm, _ := s.(map[string]any)
			actor, _ := sm["actor"].(string)
			key, _ := sm["key"].(string)
			keys := ctx.keysBefore(wid)
			bound := !ctx.conflictActors[actor] && keys[actor] != nil && keys[actor][key]
			short := key
			if len(short) > 12 {
				short = short[:12]
			}
			if bound {
				if !quiet {
					fmt.Printf("INFO %.12s  signature bound: key %s claims actor %s\n", wid, short, actor)
				}
			} else {
				out("WARN", wid, "signature unbound: key "+short+" claims actor "+actor)
			}
			if actor == actorID {
				actorSigned = true
			}
		}
		if len(sigs) > 0 && !actorSigned {
			out("ERR", wid, "no valid signature by body.actor.id")
		}
		for _, p := range getStringArray(body, "prior") {
			prev, ok := records[p]
			if !ok {
				out("ERR", wid, "prior "+sh12(p)+" not in store")
				continue
			}
			prevBody, _ := prev["body"].(map[string]any)
			if getInt(prevBody, "ts") > getInt(body, "ts") {
				out("WARN", wid, "ts decreases along prior edge "+sh12(p))
			}
		}
		for _, h := range referencedBlobs(body) {
			if blobs[h] == nil {
				out("WARN", wid, "unresolved blob "+sh12(h))
			}
		}
		if subj, ok := body["subject"].(map[string]any); ok {
			if h, ok := subj["hash"].(string); ok {
				mayBeRecord := body["decision"] == "supersede" || body["decision"] == "accept"
				if blobs[h] == nil && !(mayBeRecord && records[h] != nil) {
					out("WARN", wid, "unresolved blob "+sh12(h))
				}
			}
		}
		if body["decision"] == "supersede" && records[getSubjectHash(body)] == nil {
			out("ERR", wid, "supersede subject MUST be the superseded WarrantID (SPEC s7)")
		}
		if isUnverifiable(body) {
			out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
		}
		for _, item := range getArray(body, "because") {
			r, ok := item.(map[string]any)
			if !ok || r["kind"] != "check" || r["runtime"] != "ski@v1" {
				continue
			}
			checkHex, ok := r["check"].(string)
			if !ok {
				continue
			}
			got, _, _, err := runSkiCheckFromStore(blobs, checkHex)
			if err != nil {
				// "reran and matched" and "not executed" MUST NOT look alike
				// (SPEC §6). Settlement-grade: ERR when the claim is in an
				// active record (an unexecuted claim can't be trusted to
				// settle); otherwise a stable WARN, never a silent skip.
				lvl := "WARN"
				if ctx.activeRecords[wid] {
					lvl = "ERR"
				}
				out(lvl, wid, "ski@v1 unverified: "+err.Error())
				continue
			}
			if claimed, ok := r["verdict"].(string); ok && claimed != got {
				out("WARN", wid, "ski@v1 verdict mismatch: claimed "+claimed+", got "+got)
			}
		}
		if ctx.activeRecords[wid] {
			if ctx.conflictActors[actorID] {
				out("WARN", wid, "key-state conflict")
			}
			if body["decision"] == "accept" || body["decision"] == "reject" {
				priors := keysOfBool(priorClosure(records, wid))
				sort.Strings(priors)
				for _, prior := range priors {
					pbody, _ := records[prior]["body"].(map[string]any)
					if ctx.activeRecords[prior] && (pbody["decision"] == "accept" || pbody["decision"] == "reject") && getSubjectHash(pbody) == getSubjectHash(body) {
						if strings.HasPrefix(settlementAdmissibility(records, blobs, prior, body), "inadmissible") {
							out("WARN", wid, "re-litigation cites nothing new")
						}
						break
					}
				}
			}
		}
	}
	if !quiet {
		fmt.Printf("\nverify: %d records, %d errors, %d warnings\n", len(recList), errs, warns)
	}
	return errs, warns
}

func verifyDir(dir string, quiet bool) (int, int) {
	recordsDir := filepath.Join(dir, "records")
	blobsDir := filepath.Join(dir, "blobs")
	storeMode := isDir(recordsDir) && isDir(blobsDir)

	recordFiles, blobFiles, err := verifyInputs(dir, recordsDir, blobsDir, storeMode)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1, 0
	}

	var recList []verifyRecord
	records := map[string]map[string]any{}
	blobs := map[string][]byte{}

	for _, path := range blobFiles {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		if storeMode {
			name := filepath.Base(path)
			if isHex64(name) {
				blobs[name] = data
			}
			continue
		}
		blobs[blobHash(data)] = data
	}

	for _, path := range recordFiles {
		label := filepath.Base(path)
		claim := ""
		if storeMode {
			claim = strings.TrimSuffix(label, ".json")
		}
		env, err := readJSON(path)
		rec := verifyRecord{label: label, claim: claim, env: env, err: err}
		recList = append(recList, rec)
		if err != nil || env == nil {
			continue
		}
		body, ok := env["body"].(map[string]any)
		if !ok {
			continue
		}
		if storeMode {
			records[claim] = env
			continue
		}
		if wid, err := warrantID(body); err == nil {
			records[wid] = env
		}
	}

	errs, warns := 0, 0
	out := func(level, wid, msg string) {
		if level == "ERR" {
			errs++
		} else if level == "WARN" {
			warns++
		}
		if !quiet {
			fmt.Printf("%-4s %.12s  %s\n", level, wid, msg)
		}
	}

	for _, rec := range recList {
		wid := rec.claim
		if wid == "" {
			wid = strings.TrimSuffix(rec.label, ".warrant.json")
		}
		env := rec.env
		if rec.err != nil {
			out("ERR", wid, rec.err.Error())
			continue
		}
		if len(env) != 2 {
			out("ERR", wid, "envelope must be {body, sigs}")
			continue
		}
		body, ok := env["body"].(map[string]any)
		if !ok {
			out("ERR", wid, "body is not an object")
			continue
		}
		if _, ok := env["sigs"].([]any); !ok {
			out("ERR", wid, "sigs must be a list")
			continue
		}
		for _, msg := range validateBody(body) {
			out("ERR", wid, "schema: "+msg)
		}
		got, err := warrantID(body)
		if err != nil {
			out("ERR", wid, "WarrantID canonicalization: "+err.Error())
			continue
		}
		if rec.claim != "" {
			if got != rec.claim {
				out("ERR", wid, "WarrantID mismatch: recomputed "+sh12(got))
				continue
			}
		} else {
			wid = got
		}
		sigs := env["sigs"].([]any)
		if len(sigs) == 0 {
			out("ERR", wid, "no signatures")
		}
		actorID := getActorID(body)
		actorSigned := false
		for _, s := range sigs {
			if !verifySig(wid, s) {
				// SPEC §5/§6: a failed co-signature is reported and EXCLUDED,
				// not fatal (see settlement path). ERR still fires below if no
				// valid signature by body.actor.id remains.
				out("WARN", wid, "signature does not verify (excluded)")
				continue
			}
			// SPEC §5 MUST: no keyring configured, so the key->actor binding is
			// unverified even though the signature is cryptographically valid.
			sm, _ := s.(map[string]any)
			key, _ := sm["key"].(string)
			if len(key) > 12 {
				key = key[:12]
			}
			out("WARN", wid, fmt.Sprintf("binding unverified (no keyring): key %s claims actor %v", key, sm["actor"]))
			if sm["actor"] == actorID {
				actorSigned = true
			}
		}
		if len(sigs) > 0 && !actorSigned {
			out("ERR", wid, "no valid signature by body.actor.id")
		}
		for _, p := range getStringArray(body, "prior") {
			prev, ok := records[p]
			if !ok {
				out("ERR", wid, "prior "+sh12(p)+" not in store")
				continue
			}
			prevBody, _ := prev["body"].(map[string]any)
			if getInt(prevBody, "ts") > getInt(body, "ts") {
				out("WARN", wid, "ts decreases along prior edge "+sh12(p))
			}
		}
		for _, h := range referencedBlobs(body) {
			if blobs[h] == nil {
				out("WARN", wid, "unresolved blob "+sh12(h))
			}
		}
		if subj, ok := body["subject"].(map[string]any); ok {
			if h, ok := subj["hash"].(string); ok {
				mayBeRecord := body["decision"] == "supersede" || body["decision"] == "accept"
				if blobs[h] == nil && !(mayBeRecord && records[h] != nil) {
					out("WARN", wid, "unresolved blob "+sh12(h))
				}
			}
		}
		if body["decision"] == "supersede" {
			if subj, ok := body["subject"].(map[string]any); ok {
				if h, ok := subj["hash"].(string); ok && records[h] == nil {
					out("ERR", wid, "supersede subject MUST be the superseded WarrantID (SPEC s7)")
				}
			}
		}
		if isUnverifiable(body) {
			out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
		}
		for _, item := range getArray(body, "because") {
			r, ok := item.(map[string]any)
			if !ok || r["kind"] != "check" || r["runtime"] != "ski@v1" {
				continue
			}
			checkHex, ok := r["check"].(string)
			if !ok {
				continue
			}
			got, _, _, err := runSkiCheckFromStore(blobs, checkHex)
			if err != nil {
				// Base verification: an unexecutable ski@v1 claim is a stable
				// WARN (SPEC §6), never a silent skip — this is the PY/GO
				// divergence the Kimi review surfaced (Go used to `continue`).
				out("WARN", wid, "ski@v1 unverified: "+err.Error())
				continue
			}
			if claimed, ok := r["verdict"].(string); ok && claimed != got {
				out("WARN", wid, "ski@v1 verdict mismatch: claimed "+claimed+", got "+got)
			}
		}
	}
	if !quiet {
		fmt.Printf("\nverify: %d records, %d errors, %d warnings\n", len(recList), errs, warns)
	}
	return errs, warns
}

func verifyInputs(dir, recordsDir, blobsDir string, storeMode bool) ([]string, []string, error) {
	if storeMode {
		recordFiles, err := globFiles(filepath.Join(recordsDir, "*.json"))
		if err != nil {
			return nil, nil, err
		}
		blobFiles, err := listFiles(blobsDir)
		if err != nil {
			return nil, nil, err
		}
		return recordFiles, blobFiles, nil
	}
	entries, err := listFiles(dir)
	if err != nil {
		return nil, nil, err
	}
	var records, blobs []string
	for _, path := range entries {
		if strings.HasSuffix(filepath.Base(path), ".warrant.json") {
			records = append(records, path)
		} else {
			blobs = append(blobs, path)
		}
	}
	return records, blobs, nil
}

func globFiles(pattern string) ([]string, error) {
	files, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}
	sort.Strings(files)
	return files, nil
}

func listFiles(dir string) ([]string, error) {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, err
	}
	files := make([]string, 0, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			files = append(files, filepath.Join(dir, e.Name()))
		}
	}
	sort.Strings(files)
	return files, nil
}

func isDir(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}

func selftest(dir string) bool {
	var ok []bool
	chk := func(name string, cond bool, detail string) {
		ok = append(ok, cond)
		if cond {
			fmt.Println("OK  ", name)
		} else {
			fmt.Println("FAIL", name, detail)
		}
	}
	env, err := readJSON(filepath.Join(dir, "reject.warrant.json"))
	if err != nil {
		chk("load reject vector", false, err.Error())
		return false
	}
	body := cloneMap(env["body"].(map[string]any))

	unknown := cloneMap(body)
	unknown["extra"] = "nope"
	chk("unknown body field -> invalid", hasValidationError(unknown), "")

	ski := cloneMap(body)
	reasons := cloneArray(ski["because"].([]any))
	checkReason := cloneMap(reasons[0].(map[string]any))
	checkReason["runtime"] = "ski@v1"
	reasons[0] = checkReason
	ski["because"] = reasons
	chk("ski@v1 runtime -> invalid", hasValidationError(ski), "")

	emptyReject := cloneMap(body)
	emptyReject["because"] = []any{}
	chk("reject with zero reasons -> invalid", hasValidationError(emptyReject), "")

	proseOnly := cloneMap(body)
	proseOnly["because"] = []any{map[string]any{"kind": "prose", "text": "no proof supplied"}}
	errs := validateBody(proseOnly)
	chk("prose-only reject -> schema-valid", len(errs) == 0, strings.Join(errs, "; "))
	chk("prose-only reject -> unverifiable", isUnverifiable(proseOnly), "")

	errsN, warnsN := verifyDir(dir, true)
	chk("examples verify with unresolved blobs as warnings", errsN == 0 && warnsN > 0, fmt.Sprintf("errors=%d warnings=%d", errsN, warnsN))

	tmp, err := os.MkdirTemp("", "warrant-go-selftest-*")
	if err != nil {
		chk("tempdir", false, err.Error())
		return false
	}
	defer os.RemoveAll(tmp)
	for _, name := range []string{"reject.warrant.json", "accept.warrant.json", "policy.txt", "check.sh"} {
		if err := copyFile(filepath.Join(dir, name), filepath.Join(tmp, name)); err != nil {
			chk("copy "+name, false, err.Error())
			return false
		}
	}
	errsMissing, _ := verifyDir(tmp, true)
	chk("missing prior -> error", errsMissing > 0, fmt.Sprintf("errors=%d", errsMissing))

	passed := 0
	for _, v := range ok {
		if v {
			passed++
		}
	}
	if passed == len(ok) {
		fmt.Printf("\nSELFTEST: ALL PASS (%d/%d)\n", passed, len(ok))
		return true
	}
	fmt.Printf("\nSELFTEST: FAILURES PRESENT (%d/%d)\n", passed, len(ok))
	return false
}

func hasValidationError(body map[string]any) bool {
	return len(validateBody(body)) > 0
}

func hasValidationMessage(body map[string]any, needle string) bool {
	for _, msg := range validateBody(body) {
		if strings.Contains(msg, needle) {
			return true
		}
	}
	return false
}

func cloneMap(in map[string]any) map[string]any {
	out := make(map[string]any, len(in))
	for k, v := range in {
		switch x := v.(type) {
		case map[string]any:
			out[k] = cloneMap(x)
		case []any:
			out[k] = cloneArray(x)
		default:
			out[k] = x
		}
	}
	return out
}

func cloneArray(in []any) []any {
	out := make([]any, len(in))
	for i, v := range in {
		switch x := v.(type) {
		case map[string]any:
			out[i] = cloneMap(x)
		case []any:
			out[i] = cloneArray(x)
		default:
			out[i] = x
		}
	}
	return out
}

func copyFile(src, dst string) error {
	data, err := os.ReadFile(src)
	if err != nil {
		return err
	}
	return os.WriteFile(dst, data, 0o644)
}

func getActorID(body map[string]any) string {
	if actor, ok := body["actor"].(map[string]any); ok {
		if id, ok := actor["id"].(string); ok {
			return id
		}
	}
	return ""
}

func getSubjectHash(body map[string]any) string {
	if subj, ok := body["subject"].(map[string]any); ok {
		if h, ok := subj["hash"].(string); ok {
			return h
		}
	}
	return ""
}

func keysOfBool(m map[string]bool) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func sortedRecordIDs(records map[string]map[string]any) []string {
	out := make([]string, 0, len(records))
	for k := range records {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func cloneKeyMap(in map[string]map[string]bool) map[string]map[string]bool {
	out := make(map[string]map[string]bool, len(in))
	for actor, keys := range in {
		out[actor] = map[string]bool{}
		for key, ok := range keys {
			out[actor][key] = ok
		}
	}
	return out
}

// referencedBlobs returns the STRICT blob references (SPEC s6/s7: under,
// evidence, check, transcript resolve to blobs only; a stored record with
// the same hash does not satisfy them). subject.hash is checked separately
// because supersede and adoption/rotation accept subjects MAY be WarrantIDs.
func referencedBlobs(body map[string]any) []string {
	var refs []string
	refs = append(refs, getStringArray(body, "under")...)
	refs = append(refs, getStringArray(body, "evidence")...)
	for _, item := range getArray(body, "because") {
		r, ok := item.(map[string]any)
		if !ok || r["kind"] != "check" {
			continue
		}
		if h, ok := r["check"].(string); ok {
			refs = append(refs, h)
		}
		if h, ok := r["transcript"].(string); ok {
			refs = append(refs, h)
		}
	}
	seen := map[string]bool{}
	out := make([]string, 0, len(refs))
	for _, h := range refs {
		if !seen[h] {
			seen[h] = true
			out = append(out, h)
		}
	}
	return out
}

func getArray(m map[string]any, key string) []any {
	if a, ok := m[key].([]any); ok {
		return a
	}
	return nil
}

func getStringArray(m map[string]any, key string) []string {
	a := getArray(m, key)
	out := make([]string, 0, len(a))
	for _, item := range a {
		if s, ok := item.(string); ok {
			out = append(out, s)
		}
	}
	return out
}

// sh12 truncates to 12 chars for display WITHOUT panicking on shorter strings.
// Blob refs, prior entries and subject hashes can be attacker-controlled short
// strings in a malformed record; a raw s[:12] slice panics the whole verifier
// (found by tests/fuzz_differential.py). Python slicing is length-safe; this
// makes Go match.
func sh12(s string) string {
	if len(s) < 12 {
		return s
	}
	return s[:12]
}

func getInt(m map[string]any, key string) int64 {
	n, ok := m[key].(json.Number)
	if !ok {
		return 0
	}
	i, _ := n.Int64()
	return i
}

func stringArrayEqual(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
