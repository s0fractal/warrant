package main

import (
	"bytes"
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

const version = "0.1"

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
	default:
		usage()
		os.Exit(2)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: warrant-go conformance [examples_dir] | verify [dir] | selftest [examples_dir]")
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

func quoteJSONString(s string) ([]byte, error) {
	var b bytes.Buffer
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(s); err != nil {
		return nil, err
	}
	return bytes.TrimRight(b.Bytes(), "\n"), nil
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

	if s, ok := b["warrant"].(string); !ok || s != version {
		errs = append(errs, `warrant version must be "0.1"`)
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
		for _, msg := range validateReason(r) {
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
		if !ok || len(s) > 200 {
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

func validateReason(v any) []string {
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
		if !ok {
			errs = append(errs, "runtime must be cmd@v1")
		} else if runtime == "ski@v1" {
			errs = append(errs, "runtime ski@v1 is reserved and MUST be rejected in v0.1")
		} else if runtime != "cmd@v1" {
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
	blobs := map[string]bool{}

	for _, path := range blobFiles {
		if storeMode {
			name := filepath.Base(path)
			if isHex64(name) {
				blobs[name] = true
			}
			continue
		}
		data, err := os.ReadFile(path)
		if err == nil {
			blobs[blobHash(data)] = true
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
			} else if sm, ok := s.(map[string]any); ok && sm["actor"] == actorID {
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
			if !blobs[h] && records[h] == nil {
				out("WARN", wid, "unresolved blob "+h[:12])
			}
		}
		if body["decision"] == "supersede" {
			if subj, ok := body["subject"].(map[string]any); ok {
				if h, ok := subj["hash"].(string); ok && records[h] == nil {
					out("WARN", wid, "supersede subject is not a stored WarrantID")
				}
			}
		}
		if isUnverifiable(body) {
			out("WARN", wid, "UNVERIFIABLE: reject with prose-only reasons")
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
