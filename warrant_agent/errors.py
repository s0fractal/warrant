"""Typed refusals of the application API. A refusal is never a semantic result."""

CODES = ("BAD_REQUEST", "UNSUPPORTED_VERSION", "NOT_PERMITTED", "UNKNOWN_WORKSPACE", "UNKNOWN_EXPECTATION",
         "VIEW_UNKNOWN", "VIEW_EXPIRED", "VIEW_DAMAGED", "CURSOR_MISMATCH", "NOT_FOUND", "CONFLICT", "RESOURCE_LIMIT",
         "NO_ASSESSMENT", "IMPORT_INCOMPLETE", "IMPORT_BLOCKED", "SIGNER_CHANGED", "NO_SIGNER",
         "PROVIDER", "REFUSED")


class AgentError(Exception):
    def __init__(self, code, message, **details):
        assert code in CODES, code
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def to_json(self):
        out = {"error": self.code, "message": self.message}
        if self.details:
            out["details"] = self.details
        return out


def need_op(req, ops, message):
    """The request's `op`, refused BAD_REQUEST unless the request is an object whose `op` is a string naming one of
    `ops`. The type is checked before the lookup: a JSON list or object is unhashable, and a lookup of one would
    escape the interface as a TypeError (Codex finding 3456ece28888 on #209)."""
    op = req.get("op") if isinstance(req, dict) else None
    need(isinstance(op, str) and op in ops, "BAD_REQUEST", message)
    return op


def need(ok, code, message, **details):
    if not ok:
        raise AgentError(code, message, **details)
