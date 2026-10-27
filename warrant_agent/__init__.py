"""warrant-agent/3: the application layer over Warrant 3 for agents.

One backend (warrant_agent.api) serves the Python API, the `warrant-agent` command and the optional
stdio MCP server. Every operation reads the store once and assesses it in process (warrant.assess),
under the workspace's trust and profile and within the engine's and the workspace's limits; nothing
is cached between calls and no view is kept. It adds no record kind and no admission or reliance
rule. Its files are outside `warrant/`, so they are not part of the engine's code identity; results
carry `adapter` (this package's digest) beside the engine's `code`."""
import hashlib
from pathlib import Path

AGENT_API = "warrant-agent/3"
_HERE = Path(__file__).resolve().parent


def adapter_id():
    """Digest of this package's source files (package-relative names)."""
    h = hashlib.sha256()
    for p in sorted(q for q in _HERE.rglob("*.py") if "__pycache__" not in q.parts):
        h.update(str(p.relative_to(_HERE)).encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()
