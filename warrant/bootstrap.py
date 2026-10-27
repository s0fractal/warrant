"""The schema records `warrant bootstrap` files (docs/V3.md §4): the domain rules of claims, goals,
obligations, pull request reviews and findings as data. The roles they name are bound to actors
by each receiver's profile, never here."""
from .records import guard

ACCEPT = {"verdict": "accept"}
# What a version says about the work that made it, kept verbatim from the transition that filed it.
NOTES = {"established": "strs?", "residual": "strs?", "opened": "obj?", "subject": "str?"}


def _accepted_by(role):
    return guard(1, [role], ACCEPT)


SCHEMAS = [
    {"name": "claim@1",
     "fields": {"state": "str", "id": "str", "source": "str", "section": "str", "text": "str", "witnesses": "strs",
                "mutants": "strs", "reason": "str?", "because": "str?", "counter": "ref?", "challenge": "ref?", "evidence": "refs?", **NOTES},
     "states": {"unbacked": None, "informative": None, "backed": _accepted_by("claim/verifier"), "retired": None},
     "closed": ["backed"], "successors": {}},
    {"name": "goal@1",
     "fields": {"state": "str", "key": "str", "text": "str", "because": "str?", "refs": "strs?", "sources": "obj?", **NOTES},
     "states": {"open": None, "reformulated": _accepted_by("roadmap/acceptor"), "met": _accepted_by("roadmap/acceptor"),
                "withdrawn": _accepted_by("roadmap/acceptor")},
     "closed": ["met"], "successors": {}},
    {"name": "obligation@1",
     "fields": {"state": "str", "statement": "str", "answers": "ref?", "serves": "refs", "evidence": "refs?",
                "refs": "strs?", **NOTES},
     # Forgiveness is the creditor's alone (v2 SPEC §4.1 release): only the owner files `released`, with no
     # acceptance; it is not `closed`, so nothing that requires the obligation counts it as delivered.
     "states": {"open": None, "done": _accepted_by("roadmap/acceptor"), "released": None},
     "closed": ["done"], "successors": {"released": ["roadmap/owner"]}},
    {"name": "pr-head@1",
     "fields": {"state": "str", "repository": "str?", "pr": "int?", "title": "str?", "serves": "refs?",
                "commit": "str?", "tree": "str?", "answers": "refs?", **NOTES},
     "states": {"open": None, "head": _accepted_by("pr/acceptor")},
     "closed": ["head"], "successors": {}},
    {"name": "finding@1",
     "fields": {"statement": "str", "severity": "str", "what": "str", "where": "strs", "commit": "str", "tree": "str",
                "test": "obj?"},
     "states": None, "closed": [], "successors": {}},
]
