"""A fixed table runtime for projection-1: load a table, look rows up, nothing else.

Standard library only, and no import from stargate: no model, WPL, Boolean
evaluator or compiler is reachable from here, and nothing here takes a callable.
It is copied byte for byte next to a projection and runs without Stargate.

It never claims a table is right. A projection is checked against a certificate by
the projection verifier; this file executes whatever well-formed table it is given,
and its own correctness is not established by that check.
"""
import hashlib
import itertools
import json
import pathlib

RUNTIME_ID = 'python-table-1'
# projection.MAX_PROJECTION: derived there from the WPL rule limit, which this file
# must not know about; a test holds the two equal.
MAX_PROJECTION = 4193586
RESERVED = ('fact', 'check', 'bool', 'true', 'false')
LETTERS = frozenset('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_')
DIGITS = frozenset('0123456789')
HEX = frozenset('0123456789abcdef')


def _is_name(text):
    """A WPL name: dot-separated parts, each an ASCII letter or _ then letters, digits, _."""
    return all(part and part[0] in LETTERS and all(c in LETTERS or c in DIGITS for c in part)
               for part in text.split('.'))


def _canonical(value):
    """The canonical JSON bytes of a projection value (booleans, ints, strings, lists, objects)."""
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    if type(value) is list:
        return '[' + ','.join(_canonical(item) for item in value) + ']'
    if type(value) is dict:
        keys = sorted(value, key=lambda key: key.encode('utf-16-be'))
        return '{' + ','.join(_canonical(key) + ':' + _canonical(value[key]) for key in keys) + '}'
    raise ValueError('projection holds a value outside canonical JSON')


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _names(names, low, high):
    if (type(names) is not list or not low <= len(names) <= high or names != sorted(set(names)) or
            any(type(n) is not str or not _is_name(n) or n in RESERVED for n in names)):
        raise ValueError('projection names must be sorted unique WPL names')


def _key(value, names, word):
    if type(value) is not dict or set(value) != set(names) or any(type(v) is not bool for v in value.values()):
        raise ValueError('unknown ' + word + ': expected exactly ' + ', '.join(names) + ' as Booleans')
    return tuple(value[name] for name in names)


class ProjectionMachine:
    """A loaded projection-1 table. Build it with load() or from_bytes()."""

    def __init__(self, raw):
        if not isinstance(raw, bytes) or len(raw) > MAX_PROJECTION:
            raise ValueError('projection must be bytes within ' + str(MAX_PROJECTION))
        try:
            doc = json.loads(raw, object_pairs_hook=_unique)
        except (UnicodeError, RecursionError) as exc:
            raise ValueError('projection is not JSON') from exc
        if _canonical(doc).encode('utf-8') != raw:
            raise ValueError('projection must be canonical JSON bytes')
        if type(doc) is not dict or set(doc) != {'projection', 'model', 'state', 'events', 'rows'}:
            raise ValueError('projection fields must be exactly projection, model, state, events, rows')
        if type(doc['projection']) is not int or doc['projection'] != 1:
            raise ValueError('unsupported projection')
        if type(doc['model']) is not str or len(doc['model']) != 64 or not set(doc['model']) <= HEX:
            raise ValueError('model must be a lowercase SHA-256')
        state, events = doc['state'], doc['events']
        _names(state, 1, 6); _names(events, 0, 2)
        if set(state) & set(events):
            raise ValueError('state and event names must be disjoint')
        if type(doc['rows']) is not list:
            raise ValueError('rows must be a list')
        table, keys = {}, []
        for row in doc['rows']:
            if type(row) is not dict or set(row) != {'state', 'event', 'next'}:
                raise ValueError('a row has exactly state, event, next')
            key = (_key(row['state'], state, 'state'), _key(row['event'], events, 'event'))
            keys.append(key)
            table[key] = _key(row['next'], state, 'state')
        # domain check: begin
        if len(table) != len(keys):
            raise ValueError('duplicate row')
        domain = [(s, e) for s in itertools.product((False, True), repeat=len(state))
                  for e in itertools.product((False, True), repeat=len(events))]
        if len(keys) != len(domain):
            raise ValueError('missing row')
        if keys != domain:
            raise ValueError('rows are not in canonical order')
        # domain check: end
        self._table = table
        self._state, self._events = tuple(state), tuple(events)
        self._model = doc['model']
        self._projection_id = hashlib.sha256(raw).hexdigest()

    @staticmethod
    def from_bytes(raw):
        return ProjectionMachine(raw)

    @staticmethod
    def load(path):
        with pathlib.Path(path).open('rb') as stream:
            return ProjectionMachine(stream.read(MAX_PROJECTION + 1))

    @property
    def state_names(self):
        return list(self._state)

    @property
    def event_names(self):
        return list(self._events)

    @property
    def model(self):
        return self._model

    @property
    def projection_id(self):
        return self._projection_id

    def step(self, state, event):
        """The `next` of the one row for (state, event), as a new dict."""
        key = (_key(state, self._state, 'state'), _key(event, self._events, 'event'))
        return dict(zip(self._state, self._table[key]))
