// `warrant.verify-report@v1` sealed observation — Go reference.
//
// Round 2 of WRT-004 §6, rebuilt after round 1 was refuted. Two defects were
// mine, in this file: the walk silently skipped symlinks a live verifier
// follows, and `encoding/json` escaped U+2028 even with SetEscapeHTML(false),
// which SPEC §4 forbids outright. The encoder below is written out rather
// than delegated, for that reason.
//
// One atomic observation: seal() produces the byte view once, and everything
// else derives from it, so the manifest and the judgement cannot disagree
// about what exists.
//
//	input_manifest <store-dir> [--trust-config PATH]   # JCS bytes
//	input_manifest <store-dir> --root                  # input_root only
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf16"
)

const domain = "warrant.verify-report.input@v1:"

type entry struct {
	Path   string
	Role   string
	State  string // read | unreadable | refused
	Sha256 string // present iff State == "read"
	Reason string // present iff State == "refused"
}

// jcsString implements SPEC §4 string escaping exactly: the seven short
// escapes, \u00xx LOWERCASE below U+0020, and everything else raw UTF-8 —
// including < > & / and U+2028/U+2029, which encoding/json escapes and §4
// says MUST NOT be escaped.
func jcsString(s string) string {
	var b strings.Builder
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
				b.WriteString(fmt.Sprintf(`\u%04x`, r))
			} else {
				b.WriteRune(r)
			}
		}
	}
	b.WriteByte('"')
	return b.String()
}

// utf16Less orders keys by UTF-16 code units, which is JCS's rule. Every key
// here is ASCII, where it coincides with byte order; it is written out so a
// future non-ASCII key does not silently change meaning.
func utf16Less(a, b string) bool {
	ua, ub := utf16.Encode([]rune(a)), utf16.Encode([]rune(b))
	for i := 0; i < len(ua) && i < len(ub); i++ {
		if ua[i] != ub[i] {
			return ua[i] < ub[i]
		}
	}
	return len(ua) < len(ub)
}

// jcsEntry emits one entry as a JCS object with its members in key order.
// The optional members are omitted, not emitted as null: an entry that was
// never read has no digest, and "sha256": null would be a claim about bytes
// that do not exist.
func jcsEntry(e entry) string {
	kv := map[string]string{
		"path": jcsString(e.Path), "role": jcsString(e.Role),
		"state": jcsString(e.State),
	}
	if e.State == "read" {
		kv["sha256"] = jcsString(e.Sha256)
	}
	if e.State == "refused" {
		kv["reason"] = jcsString(e.Reason)
	}
	keys := make([]string, 0, len(kv))
	for k := range kv {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return utf16Less(keys[i], keys[j]) })
	parts := make([]string, 0, len(keys))
	for _, k := range keys {
		parts = append(parts, jcsString(k)+":"+kv[k])
	}
	return "{" + strings.Join(parts, ",") + "}"
}

func jcsView(view []entry) string {
	parts := make([]string, 0, len(view))
	for _, e := range view {
		parts = append(parts, jcsEntry(e))
	}
	return "[" + strings.Join(parts, ",") + "]"
}

func roleOf(rel string) string {
	parts := strings.Split(rel, "/")
	if parts[0] == "records" && len(parts) == 2 && strings.HasSuffix(rel, ".json") {
		return "record"
	}
	if parts[0] == "blobs" && len(parts) == 2 {
		return "blob"
	}
	if rel == "genesis.json" {
		return "genesis"
	}
	return "other"
}

// seal is the observation. A symlink is REFUSED — not followed, not skipped:
// following it leaves the store's byte universe, and skipping it silently is
// what made round 1's manifest disagree with the judgement.
func seal(storeDir, trustConfig string) ([]entry, error) {
	base, err := filepath.Abs(storeDir)
	if err != nil {
		return nil, err
	}
	var view []entry
	err = filepath.WalkDir(base, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if p == base {
			return nil
		}
		rel, err := filepath.Rel(base, p)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		e := entry{Path: rel, Role: roleOf(rel)}
		switch {
		case d.Type()&fs.ModeSymlink != 0:
			e.State, e.Reason = "refused", "symlink"
			view = append(view, e)
			return nil
		case d.IsDir():
			return nil
		case !d.Type().IsRegular():
			e.State, e.Reason = "refused", "not-a-regular-file"
			view = append(view, e)
			return nil
		}
		raw, rerr := os.ReadFile(p)
		if rerr != nil {
			e.State = "unreadable"
		} else {
			sum := sha256.Sum256(raw)
			e.State, e.Sha256 = "read", hex.EncodeToString(sum[:])
		}
		view = append(view, e)
		return nil
	})
	if err != nil {
		return nil, err
	}
	if trustConfig != "" {
		e := entry{Path: filepath.Base(trustConfig), Role: "trust-config"}
		raw, rerr := os.ReadFile(trustConfig)
		if rerr != nil {
			e.State = "unreadable"
		} else {
			sum := sha256.Sum256(raw)
			e.State, e.Sha256 = "read", hex.EncodeToString(sum[:])
		}
		view = append(view, e)
	}
	sort.Slice(view, func(i, j int) bool { return view[i].Path < view[j].Path })
	seen := map[string]bool{}
	for _, e := range view {
		if seen[e.Path] {
			return nil, fmt.Errorf("duplicate path in the observation: %q", e.Path)
		}
		seen[e.Path] = true
	}
	return view, nil
}

func inputRoot(view []entry) string {
	sum := sha256.Sum256([]byte(domain + jcsView(view)))
	return hex.EncodeToString(sum[:])
}

func main() {
	args := os.Args[1:]
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: input_manifest <store-dir> [--trust-config PATH] [--root]")
		os.Exit(2)
	}
	trust, rootOnly := "", false
	for i, a := range args {
		if a == "--trust-config" && i+1 < len(args) {
			trust = args[i+1]
		}
		if a == "--root" {
			rootOnly = true
		}
	}
	view, err := seal(args[0], trust)
	if err != nil {
		fmt.Fprintln(os.Stderr, "REFUSED:", err)
		os.Exit(1)
	}
	if rootOnly {
		fmt.Println(inputRoot(view))
		return
	}
	os.Stdout.WriteString(jcsView(view))
}
