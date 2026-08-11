// `warrant.verify-report@v1` input manifest — Go reference (WRT-004 §3).
//
// Design only. Written from the proposal text, not translated from the
// Python: a translation proves the translator agreed with itself, not that
// the specification is unambiguous. Where the two disagree, the disagreement
// is the finding.
//
//	input_root = sha256("warrant.verify-report.input@v1:" || JCS(entries))
//
// Usage:
//
//	input_manifest <store-dir> [--trust-config PATH]   # JCS bytes to stdout
//	input_manifest <store-dir> --root                  # the root only
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

const domain = "warrant.verify-report.input@v1:"

type entry struct {
	Path   string `json:"path"`
	Role   string `json:"role"`
	Sha256 string `json:"sha256"`
}

// roleOf maps store layout to a role. An unclassifiable file is `other`,
// never omitted: a file the verifier read but cannot classify still has to be
// named.
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

func entries(storeDir, trustConfig string) ([]entry, error) {
	base, err := filepath.Abs(storeDir)
	if err != nil {
		return nil, err
	}
	var out []entry
	err = filepath.WalkDir(base, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() || !d.Type().IsRegular() { // symlinks excluded, as in §3.1
			return nil
		}
		raw, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(base, p)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		sum := sha256.Sum256(raw)
		out = append(out, entry{Path: rel, Role: roleOf(rel),
			Sha256: hex.EncodeToString(sum[:])})
		return nil
	})
	if err != nil {
		return nil, err
	}
	if trustConfig != "" {
		raw, err := os.ReadFile(trustConfig)
		if err != nil {
			return nil, err
		}
		sum := sha256.Sum256(raw)
		out = append(out, entry{Path: filepath.Base(trustConfig),
			Role: "trust-config", Sha256: hex.EncodeToString(sum[:])})
	}
	// Ordered by the UTF-8 bytes of `path`. In Go a `string` IS its UTF-8
	// bytes, so `<` is already the specified order; the specification chose
	// it so neither implementation needs a special comparator.
	sort.Slice(out, func(i, j int) bool { return out[i].Path < out[j].Path })
	seen := map[string]bool{}
	for _, e := range out {
		if seen[e.Path] {
			return nil, fmt.Errorf("duplicate path in manifest: %q (§3.1)", e.Path)
		}
		seen[e.Path] = true
	}
	return out, nil
}

// jcs writes the SPEC §4 JCS subset. SetEscapeHTML(false) is the whole reason
// this is hand-rolled rather than a plain json.Marshal: Go escapes `<`, `>`
// and `&` into <-style sequences by default, so a path containing any of
// them would produce different bytes from a conforming implementation for the
// same manifest. The struct field order is irrelevant — the tags are `path`,
// `role`, `sha256`, already the sorted order JCS requires for these keys.
func jcs(v any) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(b.Bytes(), "\n"), nil // Encode appends a newline
}

func inputRoot(ents []entry) (string, error) {
	body, err := jcs(ents)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(append([]byte(domain), body...))
	return hex.EncodeToString(sum[:]), nil
}

func main() {
	args := os.Args[1:]
	if len(args) < 1 {
		fmt.Fprintln(os.Stderr, "usage: input_manifest <store-dir> [--trust-config PATH] [--root]")
		os.Exit(2)
	}
	trust := ""
	rootOnly := false
	for i, a := range args {
		if a == "--trust-config" && i+1 < len(args) {
			trust = args[i+1]
		}
		if a == "--root" {
			rootOnly = true
		}
	}
	ents, err := entries(args[0], trust)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	if rootOnly {
		root, err := inputRoot(ents)
		if err != nil {
			fmt.Fprintln(os.Stderr, "error:", err)
			os.Exit(1)
		}
		fmt.Println(root)
		return
	}
	body, err := jcs(ents)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
	os.Stdout.Write(body)
}
