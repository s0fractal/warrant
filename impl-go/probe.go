package main

// The `warrant-conformance/1` candidate contract (conformance/CONTRACT.md).
//
// `conformance` is this binary checking itself against files in this checkout.
// `probe` is the inverse: it makes this binary a CANDIDATE that an external
// runner — one that has never seen this repository — can drive. One JSON request
// on stdin, one JSON response on stdout, exit 0 whenever an answer was produced.
//
// The exit status is deliberately NOT the verdict. "I say this body is invalid"
// and "I crashed before deciding" are different facts, and a contract that
// encodes both as a nonzero exit lets a broken candidate look like a strict one.

import (
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
)

const probeProtocol = "1"

var (
	probeBaseClasses = []string{"capabilities", "canon", "validate", "blob-hash",
		"sig-message", "verify-sig", "parse"}
	probeSettlementClasses = []string{"verify-store", "ski-run"}
)

// probeUnsupported is returned for a class this implementation genuinely cannot
// answer. The runner scores it UNRUN — a distinct outcome from both pass and
// fail, because a skipped vector class proves nothing and must not look like one
// that passed.
type probeUnsupported struct{ why string }

func (e probeUnsupported) Error() string { return e.why }

func probeString(m map[string]any, key string) (string, error) {
	v, ok := m[key].(string)
	if !ok {
		return "", fmt.Errorf("input.%s must be a string", key)
	}
	return v, nil
}

func probeBytes(m map[string]any, key string) ([]byte, error) {
	s, err := probeString(m, key)
	if err != nil {
		return nil, err
	}
	return base64.StdEncoding.DecodeString(s)
}

func probeAnswer(req map[string]any) (map[string]any, error) {
	class, _ := req["class"].(string)
	input, _ := req["input"].(map[string]any)
	if input == nil {
		input = map[string]any{}
	}

	switch class {
	case "capabilities":
		classes := append(append([]string{}, probeBaseClasses...), probeSettlementClasses...)
		return map[string]any{
			"name":    "warrant-go (independent implementation)",
			"version": "body-format/0.2",
			"grade":   "settlement",
			"classes": classes,
		}, nil

	case "canon":
		body, ok := input["body"].(map[string]any)
		if !ok {
			return map[string]any{"error": "body is not a JSON object"}, nil
		}
		canon, err := canonicalJSON(body)
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		id, err := warrantID(body)
		if err != nil {
			return map[string]any{"error": err.Error()}, nil
		}
		return map[string]any{
			"canon_hex":  hex.EncodeToString(canon),
			"warrant_id": id,
		}, nil

	case "validate":
		body, ok := input["body"].(map[string]any)
		if !ok {
			return map[string]any{"valid": false,
				"errors": []string{"body is not a JSON object"}}, nil
		}
		errs := validateBody(body)
		if errs == nil {
			errs = []string{}
		}
		return map[string]any{"valid": len(errs) == 0, "errors": errs}, nil

	case "blob-hash":
		data, err := probeBytes(input, "bytes_base64")
		if err != nil {
			return nil, err
		}
		return map[string]any{"hash": blobHash(data)}, nil

	case "sig-message":
		wid, err := probeString(input, "warrant_id")
		if err != nil {
			return nil, err
		}
		msg, ok := sigMessage(wid)
		if !ok {
			return map[string]any{"error": "WarrantID is not 64 lowercase hex characters"}, nil
		}
		return map[string]any{"message_hex": hex.EncodeToString(msg)}, nil

	case "verify-sig":
		wid, err := probeString(input, "warrant_id")
		if err != nil {
			return nil, err
		}
		key, err := probeString(input, "key")
		if err != nil {
			return nil, err
		}
		sg, err := probeString(input, "sig")
		if err != nil {
			return nil, err
		}
		sig := map[string]any{"actor": "probe", "key": key, "sig": sg}
		return map[string]any{"valid": verifySig(wid, sig)}, nil

	case "parse":
		data, err := probeBytes(input, "bytes_base64")
		if err != nil {
			return nil, err
		}
		if _, derr := decodeStrictJSON(data); derr != nil {
			return map[string]any{"ok": false, "error": derr.Error()}, nil
		}
		return map[string]any{"ok": true}, nil

	case "verify-store":
		dir, err := probeString(input, "store_path")
		if err != nil {
			return nil, err
		}
		if !isDir(filepath.Join(dir, "records")) {
			return map[string]any{"error": "not a store"}, nil
		}
		var errs, warns int
		if g, _ := input["grade"].(string); g == "settlement" {
			trust, _ := input["trust_config_path"].(string)
			var genesis []string
			if raw, ok := input["genesis"].([]any); ok {
				for _, g := range raw {
					if s, ok := g.(string); ok {
						genesis = append(genesis, s)
					}
				}
			}
			errs, warns = verifyDirSettlement(dir, trust, genesis, true, nil)
		} else {
			errs, warns = verifyDir(dir, true, nil, true)
		}
		return map[string]any{"errors": errs, "warnings": warns}, nil

	case "ski-run":
		check, err := probeBytes(input, "check_base64")
		if err != nil {
			return nil, err
		}
		blobs := map[string][]byte{}
		if raw, ok := input["blobs_base64"].(map[string]any); ok {
			// Keys are the runner's labels, not trusted addresses: the store is
			// keyed by what the bytes actually hash to, so a mislabelled blob
			// cannot smuggle itself in under another blob's address.
			names := make([]string, 0, len(raw))
			for k := range raw {
				names = append(names, k)
			}
			sort.Strings(names)
			for _, k := range names {
				s, ok := raw[k].(string)
				if !ok {
					return nil, fmt.Errorf("blobs_base64[%s] must be a string", k)
				}
				b, derr := base64.StdEncoding.DecodeString(s)
				if derr != nil {
					return nil, derr
				}
				blobs[blobHash(b)] = b
			}
		}
		checkHex := blobHash(check)
		blobs[checkHex] = check
		verdict, resultHash, spent, rerr := runSkiCheckFromStore(blobs, checkHex)
		if rerr != nil {
			return map[string]any{"error": rerr.Error()}, nil
		}
		return map[string]any{
			"verdict":          verdict,
			"result_node_hash": resultHash,
			"atp_spent":        spent,
		}, nil
	}
	return nil, probeUnsupported{fmt.Sprintf("class %q is not implemented by this candidate", class)}
}

// probeMain reads exactly one request and writes exactly one response.
func probeMain() int {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, "probe:", err)
		return 2
	}
	req, err := decodeStrictJSON(raw)
	if err != nil {
		fmt.Fprintln(os.Stderr, "probe: malformed request:", err)
		return 2
	}
	if v, _ := req["warrant_conformance"].(string); v != probeProtocol {
		fmt.Fprintf(os.Stderr, "probe: unsupported request protocol %q\n", v)
		return 2
	}
	resp := map[string]any{"warrant_conformance": probeProtocol, "id": req["id"]}
	out, err := probeAnswer(req)
	if err != nil {
		if u, ok := err.(probeUnsupported); ok {
			resp["unsupported"] = u.why
		} else {
			fmt.Fprintln(os.Stderr, "probe:", err)
			return 2
		}
	} else {
		resp["output"] = out
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(resp); err != nil {
		fmt.Fprintln(os.Stderr, "probe:", err)
		return 2
	}
	return 0
}
