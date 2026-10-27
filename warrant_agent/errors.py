"""Typed refusals of the application API. A refusal is never a semantic result."""

CODES = ("BAD_REQUEST", "UNSUPPORTED_VERSION", "NOT_PERMITTED", "UNKNOWN_WORKSPACE", "NOT_FOUND", "CHAIN_MOVED",
         "RESOURCE_LIMIT", "NO_SIGNER", "SIGNER_NOT_TRUSTED", "INVALID_RECORD", "REFUSED")


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


def need(ok, code, message, **details):
    if not ok:
        raise AgentError(code, message, **details)
