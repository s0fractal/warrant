// A starting point for a Warrant verifier in Go, wired to the conformance pack.
//
//	go run conformance-skeletons/go/main.go        # speaks warrant-conformance/1 on stdin
//	python3 conformance/run.py --candidate "go run <abs path>/main.go" --claim base
//
// Standard library only, one file, no go.mod, no build step. It answers
// `capabilities`, implements `canon`, and declines every other class with
// `unsupported` — which is the honest state of a verifier that has not been
// written yet. Do not make it answer a class it cannot compute: an UNRUN vector
// costs you the grade, a wrong answer costs you the ability to trust the report.
//
// WHAT TO DO NEXT, IN THIS ORDER
//
//  1. `blob-hash` — SHA-256 over base64-decoded bytes, no framing. Ten minutes,
//     and it is the fixture the store classes are built on.
//  2. `sig-message` — the 47 bytes a key signs. Ten minutes, and getting it
//     wrong is invisible to every other class (that is why it has its own
//     battery). Reject a WarrantID that is not 64 lowercase hex characters.
//  3. `validate` — the schema. Largest of the base classes and the one with the
//     most MUST-REJECT vectors; write it against the negative vectors first,
//     because an implementation that returns true always passes every positive.
//  4. `parse` — I-JSON strictness over raw bytes. In Go the stock decoder gets
//     you most of the way (it rejects NaN, trailing content, invalid UTF-8) but
//     silently accepts duplicate member names and a leading BOM, so you need a
//     token-level pass over json.Decoder rather than Unmarshal.
//  5. `verify-sig` — crypto/ed25519 over the step-2 message. The small-order and
//     non-canonical public keys must fail, and nothing here may panic.
//  6. `verify-store` — walk records/ and blobs/, recompute every address.
//     That completes base grade.
//
// Settlement grade (`ski-run`, `verify-store` with a trust config) comes after
// all of base is green. Claiming base and reaching base is a complete result.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"unicode/utf16"
	"unicode/utf8"
)

const protocol = "1"

type request struct {
	Protocol string          `json:"warrant_conformance"`
	ID       string          `json:"id"`
	Class    string          `json:"class"`
	Input    json.RawMessage `json:"input"`
}

// The classes this build actually computes. Everything else is declined by
// name, so the report says which classes are missing rather than implying they
// passed. Add to this list only when the vectors for that class go green.
var implemented = []string{"canon"}

func main() {
	// Exit nonzero ONLY when no answer was produced. "The signature does not
	// verify" is an answer and exits 0; a panic is not and exits 1.
	if err := run(os.Stdin, os.Stdout); err != nil {
		fmt.Fprintln(os.Stderr, "skeleton:", err)
		os.Exit(1)
	}
}

func run(stdin io.Reader, stdout io.Writer) error {
	raw, err := io.ReadAll(stdin)
	if err != nil {
		return err
	}
	var req request
	if err := json.Unmarshal(raw, &req); err != nil {
		return fmt.Errorf("request is not JSON: %w", err)
	}
	if req.Protocol != protocol {
		return fmt.Errorf("request protocol %q, expected %q", req.Protocol, protocol)
	}

	resp := map[string]any{"warrant_conformance": protocol, "id": req.ID}
	switch req.Class {
	case "capabilities":
		resp["output"] = map[string]any{
			"name": "warrant-skeleton-go", "version": "0.1.0",
			"grade": "base", "classes": implemented,
		}
	case "canon":
		out, err := doCanon(req.Input)
		if err != nil {
			return err
		}
		resp["output"] = out
	default:
		resp["unsupported"] = "not implemented in this skeleton: " + req.Class
	}

	enc := json.NewEncoder(stdout)
	enc.SetEscapeHTML(false)
	return enc.Encode(resp)
}

// ---------------------------------------------------------------- canon

func doCanon(input json.RawMessage) (map[string]any, error) {
	// UseNumber, not the default float64: the format is integers only, and a
	// decoder that turns 9007199254740991 into a float has already lost the
	// vector before canonicalization starts.
	dec := json.NewDecoder(bytes.NewReader(input))
	dec.UseNumber()
	var in struct {
		Body any `json:"body"`
	}
	if err := dec.Decode(&in); err != nil {
		return nil, fmt.Errorf("canon input is not JSON: %w", err)
	}
	// Go's map[string]any loses member order, which is fine — canonicalization
	// sorts anyway — but it also silently resolves duplicate member names
	// last-wins. That does not bite here (the runner hands you a JSON object it
	// built itself) and it does bite in `parse`, which is why `parse` needs a
	// token-level decoder rather than this one.
	var buf bytes.Buffer
	if err := canon(&buf, in.Body); err != nil {
		// A body that cannot be canonicalized is an answer, not a crash.
		return map[string]any{"error": err.Error()}, nil
	}
	sum := sha256.Sum256(buf.Bytes())
	return map[string]any{
		"canon_hex":  hex.EncodeToString(buf.Bytes()),
		"warrant_id": hex.EncodeToString(sum[:]),
	}, nil
}

// canon writes RFC 8785 (JCS) canonical bytes for the I-JSON subset the format
// admits. The three places a reimplementation splits, all of them vectored:
// escaping (below), key order (UTF-16 code units), and numbers (integers only).
func canon(buf *bytes.Buffer, v any) error {
	switch t := v.(type) {
	case nil:
		buf.WriteString("null")
	case bool:
		if t {
			buf.WriteString("true")
		} else {
			buf.WriteString("false")
		}
	case json.Number:
		s := t.String()
		if strings.ContainsAny(s, ".eE") {
			return fmt.Errorf("non-integer number %s: bodies are I-JSON integers only", s)
		}
		buf.WriteString(s)
	case string:
		return canonString(buf, t)
	case []any:
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := canon(buf, e); err != nil {
				return err
			}
		}
		buf.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Slice(keys, func(i, j int) bool { return lessUTF16(keys[i], keys[j]) })
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			if err := canonString(buf, k); err != nil {
				return err
			}
			buf.WriteByte(':')
			if err := canon(buf, t[k]); err != nil {
				return err
			}
		}
		buf.WriteByte('}')
	default:
		return fmt.Errorf("value of unexpected type %T", v)
	}
	return nil
}

// canonString is the whole reason you cannot reach for encoding/json here. Its
// Marshal escapes `<`, `>` and `&` as < > & by default, and
// canonical output must carry all three raw. SetEscapeHTML(false) fixes that
// one, and leaves you still owing the short-escape set and the lowercase \u00xx
// long form below.
func canonString(buf *bytes.Buffer, s string) error {
	if !utf8.ValidString(s) {
		return fmt.Errorf("string is not valid UTF-8")
	}
	buf.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			buf.WriteString(`\"`)
		case '\\':
			buf.WriteString(`\\`)
		case '\b':
			buf.WriteString(`\b`)
		case '\t':
			buf.WriteString(`\t`)
		case '\n':
			buf.WriteString(`\n`)
		case '\f':
			buf.WriteString(`\f`)
		case '\r':
			buf.WriteString(`\r`)
		default:
			if r < 0x20 {
				// Lowercase hex, long form, only for the C0 characters that have
				// no short escape. U+007F (DEL) and the C1 block are NOT escaped.
				fmt.Fprintf(buf, `\u%04x`, r)
			} else if r == utf8.RuneError {
				// A decoder that replaced a lone surrogate or a bad byte with
				// U+FFFD has changed the content; hashing the replacement would
				// mint a WarrantID for something nobody wrote.
				return fmt.Errorf("string contains U+FFFD from a lossy decode")
			} else {
				// Raw UTF-8 for everything else, including U+2028 and U+2029.
				buf.WriteRune(r)
			}
		}
	}
	buf.WriteByte('"')
	return nil
}

// lessUTF16 orders member names by UTF-16 code unit, which is what RFC 8785
// specifies and what Go's string comparison does NOT do. The two orders differ
// for astral-plane names: U+10000 is a surrogate pair (0xD800…) in UTF-16 and
// so sorts BEFORE U+E000, while its UTF-8 bytes sort after. Every key this
// schema admits is ASCII, so today the orders coincide — the difference is here
// because a skeleton that teaches `sort.Strings` teaches the bug.
func lessUTF16(a, b string) bool {
	ua, ub := utf16.Encode([]rune(a)), utf16.Encode([]rune(b))
	for i := 0; i < len(ua) && i < len(ub); i++ {
		if ua[i] != ub[i] {
			return ua[i] < ub[i]
		}
	}
	return len(ua) < len(ub)
}
