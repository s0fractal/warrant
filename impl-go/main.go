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
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"
)

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
		if len(os.Args) > 2 {
			dir = os.Args[2]
		}
		errs, _ := verifyDir(dir, false)
		if errs != 0 {
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
	fmt.Fprintln(os.Stderr, "usage: warrant-go conformance [examples_dir] | sigma-conformance [vectors.json] | verify [dir] | selftest [examples_dir]")
}

func readJSON(path string) (map[string]any, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	m, ok := v.(map[string]any)
	if !ok {
		return nil, errors.New("top-level JSON is not an object")
	}
	return m, nil
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
		if sigmaSize(t)-1 > uint64(spent) {
			return &sigmaTerm{kind: "dis", h: sigmaATP}, spent
		}
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
				cost := uint32(1 + sigmaSize(z))
				if cost > remaining {
					return nil, 0, "atp"
				}
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
	msg, err := hex.DecodeString(wid)
	if err != nil || len(msg) != 32 {
		return false
	}
	return ed25519.Verify(ed25519.PublicKey(key), msg, rawSig)
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
				out("ERR", wid, "WarrantID mismatch: recomputed "+got[:12])
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
				out("ERR", wid, "bad signature")
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
				out("ERR", wid, "prior "+p[:12]+" not in store")
				continue
			}
			prevBody, _ := prev["body"].(map[string]any)
			if getInt(prevBody, "ts") > getInt(body, "ts") {
				out("WARN", wid, "ts decreases along prior edge "+p[:12])
			}
		}
		for _, h := range referencedBlobs(body) {
			if blobs[h] == nil && records[h] == nil {
				out("WARN", wid, "unresolved blob "+h[:12])
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

func referencedBlobs(body map[string]any) []string {
	var refs []string
	refs = append(refs, getStringArray(body, "under")...)
	refs = append(refs, getStringArray(body, "evidence")...)
	if subj, ok := body["subject"].(map[string]any); ok {
		if h, ok := subj["hash"].(string); ok {
			refs = append(refs, h)
		}
	}
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
