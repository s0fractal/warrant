"""Warrant 3: one record envelope, native lineage, schemas as records, one guard (docs/V3.md)."""
from .engine import assess
from .keys import Key
from .records import guard, record
from .store import Snapshot, Store

__version__ = "3.0.0a5"
__all__ = ["Key", "Snapshot", "Store", "assess", "guard", "record"]
