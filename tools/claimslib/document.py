"""The document (W5): SPEC.md's parts in order (headings, claims with their recorded layout, and
literal gaps that carry layout only), its versions as records, and SPEC.md rendered from them."""
import re

from warrant import shapes as S

from .base import GONE, id_key, ID_RE, norm, PREAMBLE, Refused, RESIDUE_OK, sha, WIDTH


HEADING = re.compile(r"^#+ ([0-9]+(?:\.[0-9]+)*)\.? ")

# The document (W5): SPEC.md's parts in order. A literal gap carries layout only, never words.
DOCUMENT = "warrant-claims/document@1"
DOCUMENT_FIELDS = ("schema", "source", "parts", "because", "previous")
DOCUMENT_PREVIOUS = ("transition", "sha256")
DOCUMENT_RESIDUAL = "the document orders and lays out the claims; it states no rule"
LITERAL_OK = RESIDUE_OK | {"\n"}

# A literal gap: spaces up to its first line break; after each line break, an indentation
# and at most a list marker ("- ", "12. "), or a table rule. No digit can touch a sentence.
LITERAL_LINE = re.compile(r"^(?: *(?:- |[0-9]{1,3}\. )?|\| ---(?: \| ---)* \|)\Z")

# A heading line: one to six #, a space, a title with no control character and no
# space at either end. \Z, not $: `$` admits a trailing newline.
HEADING_LINE = re.compile(r"^#{1,6} [^\x00-\x20\x7f-\x9f](?:[^\x00-\x1f\x7f-\x9f]*[^\x00-\x20\x7f-\x9f])?\Z")
GAP_RUN = re.compile(r"^[ \n]+\Z")

# What a Markdown reader takes for a heading line (CommonMark): an ATX heading, up to three
# spaces then one to six # then a space, a tab or the line's end; a setext underline, a line
# of = or of - under a non-blank line. Fenced blocks are not exempt: such a line anywhere is
# counted, and refused unless it is the document's own heading part (AMEND 2 of #166).
ATX_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|\Z)")
SETEXT_LINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*\Z")


class Document:
    """The document records a snapshot holds: transitions whose single evidence blob is
    a DOCUMENT blob. `current` is the one no other document version supersedes (or None);
    `problems` lists malformed versions and forks."""

    def __init__(self, model):
        self.model = model
        self.nodes, self.problems = {}, []
        for rid, r in sorted(model.recs.items()):
            if r["type"] != "transition":
                continue
            heads = [h for h in r["body"]["evidence"] for d in [model.snap.json_blob(h)]
                     if isinstance(d, dict) and d.get("schema") == DOCUMENT]
            if not heads:
                continue
            doc = model.snap.json_blob(heads[0])
            code, why = self._shape(r, heads, doc)
            if why:
                self.problems.append((code, f"document transition {rid[:12]}: {why}"))
                continue
            self.nodes[rid] = (r, heads[0], doc)
        for rid, (r, h, doc) in list(self.nodes.items()):
            prev = doc["previous"]
            if prev is None:
                continue
            p = self.nodes.get(prev["transition"])
            if p is None or p[1] != prev["sha256"]:
                self.problems.append(("STRUCTURE", f"document transition {rid[:12]}: its previous version is not "
                                                   "a document transition of this store with that blob"))
                del self.nodes[rid]
            elif p[0]["actor"] != r["actor"]:
                self.problems.append(("LINEAGE_NOT_AUTHOR", f"document transition {rid[:12]} by {r['actor']!r} supersedes "
                                      f"a version by {p[0]['actor']!r}: only the document's author files its next version"))
                del self.nodes[rid]
        replaced = {s for r, _, _ in self.nodes.values() for s in r["body"]["supersedes"]}
        cur = sorted((rid for rid in self.nodes if rid not in replaced), key=lambda rid: (self.nodes[rid][0]["at"], rid))
        if len(cur) > 1:
            self.problems.append(("DOCUMENT_FORK", f"{len(cur)} current document versions: "
                                  + ", ".join(rid[:12] for rid in cur)))
        self.tid = cur[-1] if cur else None
        self.current = self.nodes[self.tid][2] if cur else None

    def _shape(self, r, heads, doc):
        """(code, why) when this transition is not a well-formed document version, else (None, None)."""
        b = r["body"]
        if len(heads) != 1 or b["evidence"] != heads:
            return "STRUCTURE", "a document transition carries its document blob and nothing else as evidence"
        if b["basis"] != "ATTESTED" or b["closes"] or b["established"] or b["opened"]:
            return "STRUCTURE", "a document transition is ATTESTED and closes, establishes and opens nothing"
        if set(doc) != set(DOCUMENT_FIELDS) or doc["source"] != "SPEC.md":
            return "STRUCTURE", f"document blob members are not {list(DOCUMENT_FIELDS)} with source SPEC.md"
        prev = doc["previous"]
        if prev is not None and not (isinstance(prev, dict) and set(prev) == set(DOCUMENT_PREVIOUS)
                                     and all(isinstance(prev[k], str) for k in DOCUMENT_PREVIOUS)):
            return "STRUCTURE", "previous must be null or {transition, sha256}"
        if not (isinstance(doc["because"], str) and doc["because"]):
            return "STRUCTURE", "every document version says because, in a non-empty string"
        if b["supersedes"] != ([] if prev is None else [prev["transition"]]):
            return "STRUCTURE", "supersedes does not name exactly its previous version"
        parts = doc["parts"]
        if not (isinstance(parts, list) and parts):
            return "STRUCTURE", "parts must be a non-empty list"
        for i, p in enumerate(parts):
            if isinstance(p, str):
                if not p:
                    return "STRUCTURE", f"part {i} is an empty literal"
                if not literal_ok(p):
                    return "DOCUMENT_LITERAL", (f"part {i} is the literal {p[:60]!r}: a gap holds spaces and line breaks, "
                                                "and at a line's start a list marker or a table rule; words are claims")
            elif isinstance(p, dict) and set(p) == {"heading"}:
                if not (isinstance(p["heading"], str) and HEADING_LINE.match(p["heading"])):
                    return "STRUCTURE", f"part {i}: {str(p['heading'])[:60]!r} is not a heading line"
            elif isinstance(p, dict) and set(p) == {"claim", "layout"}:
                if not (isinstance(p["claim"], str) and ID_RE.match(p["claim"])):
                    return "STRUCTURE", f"part {i}: {str(p['claim'])[:60]!r} is not a claim id"
                why = _layout_shape(p["layout"])
                if why:
                    return "STRUCTURE", f"part {i} ({p['claim']}): {why}"
            else:
                return "STRUCTURE", f"part {i} is not a literal, {{heading}} or {{claim, layout}}"
        return None, None

    def problems_with(self, pins):
        """(code, detail) for headings the pins do not name, references that do not match
        the claims, and claims left out.

        Headings are pinned (AMEND 1 of #166): `.warrant/claims.json` maps each pinned
        section to its exact heading line, the preamble ("0") to the document's title. A
        heading's words are free text that no witness backs, so the document may hold only
        those lines, each once, in the pinned order; a changed or new heading is a reviewed
        pin change first, then a document version."""
        out, seen, section = [], {}, PREAMBLE
        headings = pins.get("headings", {})
        order = {sec: k for k, sec in enumerate(pins["sections"])}
        headed, last = {}, -1
        model = self.model
        for i, p in enumerate(self.current["parts"]):
            if isinstance(p, str):
                continue
            if "heading" in p:
                line = p["heading"]
                sec = heading_section(line, headings)
                parts = self.current["parts"]
                before, after = (parts[i - 1] if i else None), (parts[i + 1] if i + 1 < len(parts) else None)
                if not ((i == 0 or isinstance(before, str) and before.endswith("\n"))
                        and isinstance(after, str) and after.startswith("\n")):
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} does not stand on a line of its own "
                                "(a literal ending in a line break before it, one starting with a line break after)"))
                if sec is None or headings.get(sec) != line:      # one predicate: the line is its section's pin
                    why = ("is neither a numbered heading nor the pinned title" if sec is None else
                           f"heads §{sec}, which .warrant/claims.json pins no heading for" if sec not in headings else
                           f"is not the pinned heading of §{sec}, {headings[sec][:80]!r}")
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} {why}"))
                elif sec in headed:
                    out.append(("DOCUMENT_HEADING", f"part {i}: a second heading of §{sec} (the first is part {headed[sec]})"))
                elif order.get(sec, -1) < last:
                    out.append(("DOCUMENT_HEADING", f"part {i}: the heading of §{sec} comes after a later section's"))
                else:
                    headed[sec] = i
                    last = order.get(sec, last)
                    section = sec
                continue
            cid = p["claim"]
            if cid in seen:
                out.append(("DOCUMENT_CLAIM_TWICE", f"{cid} is part {seen[cid]} and part {i}"))
                continue
            seen[cid] = i
            if cid not in model.by_id:
                out.append(("DOCUMENT_UNKNOWN_CLAIM", f"part {i} names {cid}, which no claim record states"))
            elif ID_RE.match(cid).group(1) != section:
                out.append(("DOCUMENT_SECTION", f"part {i} puts {cid} under the heading of §{section}"))
        for cid, n in sorted(model.current.items(), key=lambda kv: id_key(kv[0])):
            if not n.retired and cid not in seen:
                out.append(("CLAIM_NOT_IN_DOCUMENT", f"{cid} is a current claim and no part of the document places it"))
        for s in pins["sections"]:
            if s not in headings:
                out.append(("DOCUMENT_HEADING", f".warrant/claims.json pins §{s} and no heading for it"))
            elif s not in headed:
                out.append(("SECTION_MISSING", f"the document has no heading of §{s}"))
        return out


def rendered_headings(text):
    """The heading lines a Markdown reader sees in `text`: ATX lines as they are, a setext
    heading as its text line and underline joined by a line break."""
    lines, out = text.split("\n"), []
    for k, ln in enumerate(lines):
        if ATX_LINE.match(ln):
            out.append(ln)
        elif SETEXT_LINE.match(ln) and k and lines[k - 1].strip():
            out.append(lines[k - 1] + "\n" + ln)
    return out


def heading_section(line, headings):
    """The section a heading line heads: its number, PREAMBLE for the pinned title, else None."""
    m = HEADING.match(line)
    return m.group(1) if m else (PREAMBLE if line == headings.get(PREAMBLE) else None)


def literal_ok(text):
    """True iff `text` is a literal gap (LITERAL_LINE)."""
    first, *lines = text.split("\n")
    return set(first) <= {" "} and all(LITERAL_LINE.match(ln) for ln in lines)


def _layout_shape(layout):
    if layout is None:
        return None
    if not (isinstance(layout, dict) and set(layout) == {"sha256", "gaps"} and S.hex64(layout["sha256"])
            and isinstance(layout["gaps"], list)):
        return "layout must be null or {sha256: hex64, gaps: [[index, run]…]}"
    last = -1
    for g in layout["gaps"]:
        if not (isinstance(g, list) and len(g) == 2 and type(g[0]) is int and g[0] > last
                and isinstance(g[1], str) and GAP_RUN.match(g[1]) and g[1] != " "):
            return "a layout gap is [index, run]: indices ascending, runs of spaces and line breaks other than one space"
        last = g[0]
    return None


def lay_out(text, layout, before):
    """The sentence `text` as SPEC.md shows it, after the rendered text `before`: in its
    recorded layout while `text` is the sentence that layout was taken from (and every
    gap index falls inside it), else filled (fill)."""
    words = text.split(" ")
    if layout is not None and layout["sha256"] == sha(text) and all(i < len(words) - 1 for i, _ in layout["gaps"]):
        runs = [" "] * (len(words) - 1)
        for i, run in layout["gaps"]:
            runs[i] = run
        return words[0] + "".join(r + w for r, w in zip(runs, words[1:]))
    return fill(words, before, layout)


def fill(words, before, layout=None):
    """Words joined by single spaces, broken before a word that would pass column WIDTH and
    continued under the current line's indentation and list marker; never broken inside a
    fenced block or a table row (a line break there would change what the line says). In a
    fenced block the recorded run after the first word is kept, so a field line stays aligned."""
    line = before[before.rfind("\n") + 1:]
    fenced = sum(ln.startswith("```") for ln in before.split("\n")[:-1]) % 2 == 1
    if fenced:
        first = next((r for i, r in (layout or {}).get("gaps", []) if i == 0 and "\n" not in r), " ")
        return words[0] + (first + " ".join(words[1:]) if len(words) > 1 else "")
    if line.lstrip(" ").startswith("|"):
        return " ".join(words)
    indent = " " * len(re.match(r" *(?:[-*] |[0-9]+\. )?", line).group(0))
    out, col = words[0], len(line) + len(words[0])
    for w in words[1:]:
        if col + 1 + len(w) > WIDTH and col > len(indent):
            out, col = out + "\n" + indent, len(indent)
        else:
            out, col = out + " ", col + 1
        out, col = out + w, col + len(w)
    return out


def render_spec(model, document):
    """SPEC.md: the document's parts in order, each claim reference as its current
    sentence (lay_out); a retired claim is left out (drop_gone)."""
    s = ""
    for p in document["parts"]:
        if isinstance(p, str):
            s += p
        elif "heading" in p:
            s += p["heading"]
        else:
            n = model.current.get(p["claim"])
            s += GONE if n is None or n.retired else lay_out(n.doc["text"], p["layout"], s)
    return drop_gone(s)


def drop_gone(s):
    """Remove each retired sentence's placeholder. Alone on its line (nothing else there but
    layout characters), the line goes, and a blank line left doubled becomes one; sharing a
    line with other text, the placeholder goes with one adjacent space."""
    while GONE in s:
        pos = s.index(GONE)
        ls, le = s.rfind("\n", 0, pos) + 1, s.find("\n", pos)
        le = len(s) if le < 0 else le
        rest = s[ls:pos] + s[pos + 1:le]
        if GONE not in rest and set(rest) <= LITERAL_OK:
            if le < len(s):
                s = s[:ls] + s[le + 1:]
                if s[max(0, ls - 2):ls] == "\n\n" and s[ls:ls + 1] == "\n":
                    s = s[:ls] + s[ls + 1:]
            else:
                s = s[:max(0, ls - 1)]
                s = s.rstrip("\n") + "\n" if s else s
        elif s[pos + 1:pos + 2] == " ":
            s = s[:pos] + s[pos + 2:]
        elif s[pos - 1:pos] == " ":
            s = s[:pos - 1] + s[pos + 1:]
        else:
            s = s[:pos] + s[pos + 1:]
    return s


def parse_spec(text, model):
    """Migration only (W5, once): the parts that reproduce `text` from the current claims,
    or raise Refused. Each section's text is matched against that section's claims, at
    each point the claim that starts earliest (then the longest, then the lowest id),
    where only layout characters lie between; every claim must be placed and nothing
    else may remain. The caller still renders the parts and compares bytes: this
    reader is trusted with nothing (PATTERNS.md: never parse Markdown to find claims)."""
    by_sec = {}
    for n in model.current.values():
        if not n.retired:
            by_sec.setdefault(n.doc["section"], []).append(n)
    parts, section, pos = [], PREAMBLE, 0
    lines = text.split("\n")
    chunks, buf, at = [], [], 0          # [(section, body text) | ("#", heading line)]
    for k, line in enumerate(lines):
        end = "\n" if k < len(lines) - 1 else ""
        if line.startswith("#"):
            chunks.append((section, "".join(buf)))
            buf = [end]
            chunks.append(("#", line))
            m = HEADING.match(line)
            section = m.group(1) if m else section
        else:
            buf.append(line + end)
    chunks.append((section, "".join(buf)))
    placed = set()
    for sec, body in chunks:
        if sec == "#":
            if not HEADING_LINE.match(body):
                raise Refused(f"{body[:60]!r} is not a heading line")
            parts.append({"heading": body})
            continue
        todo = [n for n in by_sec.get(sec, []) if n.id not in placed]
        pos = 0
        while True:
            best = None
            for n in todo:
                words = n.doc["text"].split(" ")
                m = re.compile(r"[ \n]+".join(re.escape(w) for w in words)).search(body, pos)
                if m is None or not literal_ok(body[pos:m.start()]):
                    continue
                key = (m.start(), -len(m.group(0)), id_key(n.id))
                if best is None or key < best[0]:
                    best = (key, n, m)
            if best is None:
                break
            _, n, m = best
            if m.start() > pos:
                parts.append(body[pos:m.start()])
            runs = re.findall(r"[ \n]+", m.group(0))
            gaps = [[i, r] for i, r in enumerate(runs) if r != " "]
            parts.append({"claim": n.id, "layout": {"sha256": sha(n.doc["text"]), "gaps": gaps}})
            placed.add(n.id)
            todo.remove(n)
            pos = m.end()
        rest = body[pos:]
        if not literal_ok(rest):
            raise Refused(f"§{sec} has text no current claim of §{sec} places: {norm(rest)[:120]!r}")
        if rest:
            parts.append(rest)
    left = sorted((n.id for ns in by_sec.values() for n in ns if n.id not in placed), key=id_key)
    if left:
        raise Refused(f"claims not found in SPEC.md: {', '.join(left[:10])}")
    return parts
