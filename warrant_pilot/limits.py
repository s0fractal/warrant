"""Aggregate admission limits of one assessment (SPEC §9). Operational, not
semantics: a view within them is assessed exactly as without them, and a view
beyond one is refused before the unbounded work, never assessed in part. The
limits are not an operand of the assessment identity."""

DEFAULTS = {
    "snapshot_records": 100_000,             # files under records/, and records in a snapshot
    "snapshot_blobs": 100_000,               # files under blobs/, and blobs in a snapshot
    "snapshot_bytes": 1024 * 1024 * 1024,    # all record and blob bytes together
    "requires_edges": 1_000_000,             # requires entries the dependency traversal follows
    "duty_periods": 10_000,                  # period entries of one scheduled duty
    "report_periods": 100_000,               # period entries of all scheduled duties of a report
}


class LimitExceeded(ValueError):
    """An operational refusal: the view exceeds an admission limit. Never a verdict."""

    def __init__(self, limit, value, bound):
        super().__init__(f"{limit}: {value} exceeds the admitted {bound}; nothing was assessed")
        self.limit, self.value, self.bound = limit, value, bound


def resolve(overrides=None, defaults=DEFAULTS):
    """`defaults` (DEFAULTS, or another family's: warrant.pilot.LIMITS) with `overrides`
    ({name: positive int}); an unknown name or another value is a ValueError, not a limit."""
    out = dict(defaults)
    for name, value in (overrides or {}).items():
        if name not in defaults:
            raise ValueError(f"limits: unknown limit {name!r}")
        if type(value) is not int or value < 1:
            raise ValueError(f"limits: {name} must be a positive integer")
        out[name] = value
    return out


def admit(limits, name, value):
    if value > limits[name]:
        raise LimitExceeded(name, value, limits[name])
