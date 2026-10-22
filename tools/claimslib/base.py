"""The vocabulary every module of the claims tool shares: record schemas, id and test-file shapes,
the mutant harnesses, the refusal type, and small helpers (normalization, hashing, git)."""
import hashlib
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]       # the checkout this tool belongs to
AUTHOR = "claude"
CLAIM, RETIRE = "warrant-claims/claim@1", "warrant-claims/retire@1"
PINS_VERSION = "warrant-claims/pins@1"
ID_RE = re.compile(r"^SPEC-([0-9]+(?:\.[0-9]+)*)-([1-9][0-9]*)\Z")    # \Z: `$` admits a trailing newline
TEST_RE = re.compile(r"^[a-z][a-z0-9_]*_test\Z")
RESIDUE_OK = frozenset(" |-.0123456789")    # layout characters: table rules, list markers, numbers
BACKED_RESIDUAL = ("this record cites its witness cases and mutants and does not run them; "
                   "CI runs the suites and tests/mutants.py before tools/claims.py check")
UNBACKED_RESIDUAL = "UNBACKED: no witness case or no mutant cites this sentence yet"
CLAIM_FIELDS = ("schema", "id", "source", "section", "text", "kind", "duty", "witnesses", "mutants",
                "reason", "because", "previous")
RETIRE_FIELDS = ("schema", "id", "because", "counter", "challenge", "previous")
PREVIOUS_FIELDS = ("transition", "duty", "statement_sha256")

# The mutant harnesses and the id prefix each one owns: an id resolves in exactly one of them.
HARNESSES = (("mutants.py", "M"), ("agent_mutants.py", "A"))
HARNESS_PACKAGE = {"mutants.py": "warrant", "agent_mutants.py": "warrant_agent"}
COUNTER = "warrant-claims/counter@1"
COUNTER_FIELDS = ("counter", "claim", "against", "patch", "passes", "fails", "why")
WITNESSES = "WITNESSES.md"
PREAMBLE = "0"              # the section before the first numbered heading
WIDTH = 80                  # the fill width of a sentence whose recorded layout no longer applies
GONE = "\x00"               # placeholder of a retired sentence while SPEC.md is rendered


class Refused(Exception):
    """An authoring command that cannot be carried out; nothing was written. `code`, when
    given, names the refusal (printed before the detail; tests read it, never the wording)."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


def norm(s):
    return " ".join(s.split())


def replace_wrapped(s, old, new):
    """Replace the first occurrence of `old` in `s`, however `s` wraps it across lines."""
    pattern = r"\s+".join(re.escape(w) for w in old.split())
    out, n = re.subn(pattern, lambda m: new, s, count=1)
    if n != 1:
        raise ValueError(f"not found: {old[:60]!r}")
    return out


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def id_key(cid):
    m = ID_RE.match(cid)
    return (tuple(int(x) for x in m.group(1).split(".")), int(m.group(2))) if m else ((99999,), 0)


def statement_for(cid, text):
    """The duty statement: the id and the sentence, within SPEC §3.1's 400 code points.
    A longer sentence is cut here; the duty's subject blob and the transition carry it whole."""
    s = f"{cid}: {text}"
    return s if len(s) <= 400 else s[:399] + "…"


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo.root), *args], input=data, capture_output=True, check=True).stdout


GIT_NO_GC = ("-c", "gc.auto=0")             # no automatic gc while a fixture is cloned (run 39537906378)
