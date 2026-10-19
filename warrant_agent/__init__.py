"""warrant-agent/1: the application layer over Warrant 2 for agent handoff.

One backend (warrant_agent.api) serves the Python API, the `warrant-agent`
command and the optional stdio MCP server. It reuses Warrant's canonicalizer,
signatures, records, Store, Snapshot and engine; it adds no record type and no
admission or reliance rule. Its own files are outside `warrant/`, so they are not
part of Warrant's engine identity; results carry `adapter_id` instead."""
import hashlib
from pathlib import Path

AGENT_API = "warrant-agent/1"
_HERE = Path(__file__).resolve().parent


def adapter_id():
    """Digest of this package's source files (package-relative names)."""
    files = sorted(p for p in _HERE.rglob("*.py") if "__pycache__" not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(str(p.relative_to(_HERE)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()
