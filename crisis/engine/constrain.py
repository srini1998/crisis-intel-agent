"""JSON-schema-constrained decoding over byte tokens.

A schema compiles into a generator that yields the set of bytes allowed next and receives the byte
the model picked. The engine masks every other token before sampling, so output always parses and
always has the schema's keys, enums and array bounds. When only one byte is allowed (keys,
punctuation), the engine skips sampling and appends it directly ("jump-forward").

Supported: object (all properties, in schema order), array (minItems/maxItems), string
(maxLength, printable ASCII, no escapes), integer, number, boolean, null, enum, and schema-less
JSON (any value, bounded depth).

Budget-aware wrap-up: each constraint knows a conservative bound (`reserve`) on how many bytes it
takes to close the value from any point. Once the remaining `max_tokens` falls to that bound, the
mask keeps only closing moves (end the string, close the array or object, end the number), so a
request that runs long still returns parseable, schema-shaped JSON instead of a cut-off string.
"""

from __future__ import annotations

import json
from typing import Generator

from .tokenizer import EOS

PRINTABLE = frozenset(range(32, 127)) - {ord('"'), ord("\\")}
DIGITS = frozenset(b"0123456789")
STR_MAX, ARR_MAX, INT_DIGITS, DEPTH = 160, 6, 7, 4

Gen = Generator[frozenset, int, None]


class _State:
    pending: int | None = None


def _take(allowed: frozenset, st: _State):
    if st.pending is not None:
        b, st.pending = st.pending, None
        if b not in allowed:
            raise ValueError(f"byte {b!r} not allowed here")
        return b
    b = yield allowed
    if b not in allowed:
        raise ValueError(f"byte {b!r} not allowed here")
    return b


def _lit(s: str, st: _State):
    for b in s.encode():
        yield from _take(frozenset([b]), st)


def first(schema: dict | None) -> frozenset:
    if not schema:
        return frozenset(b'{["-tfn') | DIGITS
    if "enum" in schema:
        return frozenset(json.dumps(v)[0].encode()[0] for v in schema["enum"])
    t = schema.get("type")
    return {"object": frozenset(b"{"), "array": frozenset(b"["), "string": frozenset(b'"'),
            "integer": frozenset(b"-") | DIGITS, "number": frozenset(b"-") | DIGITS,
            "boolean": frozenset(b"tf"), "null": frozenset(b"n")}.get(t, first(None))


def _string(schema: dict, st: _State):
    yield from _take(frozenset(b'"'), st)
    lo, hi = schema.get("minLength", 0), min(schema.get("maxLength", STR_MAX), STR_MAX)
    n = 0
    while True:
        allowed = frozenset()
        if n < hi:
            allowed |= PRINTABLE
        if n >= lo:
            allowed |= frozenset(b'"')
        b = yield from _take(allowed, st)
        if b == ord('"'):
            return
        n += 1


def _number(follow: frozenset, st: _State, integer: bool):
    b = yield from _take(frozenset(b"-") | DIGITS, st)
    if b == ord("-"):
        b = yield from _take(DIGITS, st)
    digits, frac = 1, False
    lead_zero = b == ord("0")
    while True:
        allowed = set(follow)
        if digits < INT_DIGITS and not lead_zero:
            allowed |= DIGITS
        if not integer and not frac:
            allowed.add(ord("."))
        b = yield from _take(frozenset(allowed), st)
        if b in follow:
            st.pending = b  # hand the terminator back to the enclosing value
            return
        if b == ord("."):
            frac, lead_zero, digits = True, False, 0
            yield from _take(DIGITS, st)
        digits += 1


def _enum(values: list, st: _State):
    cands = [json.dumps(v).encode() for v in values]
    i = 0
    while True:
        done = [c for c in cands if len(c) == i]
        if done:
            return
        b = yield from _take(frozenset(c[i] for c in cands), st)
        cands = [c for c in cands if c[i] == b]
        i += 1


def _array(schema: dict, st: _State, depth: int):
    yield from _take(frozenset(b"["), st)
    items = schema.get("items") or {}
    lo, hi = schema.get("minItems", 0), min(schema.get("maxItems", ARR_MAX), ARR_MAX)
    n = 0
    while True:
        allowed = set()
        if n >= lo:
            allowed.add(ord("]"))
        if n < hi:
            allowed |= (first(items) if n == 0 else {ord(",")})
        b = yield from _take(frozenset(allowed), st)
        if b == ord("]"):
            return
        if b != ord(","):
            st.pending = b
        n += 1
        yield from value(items, st, frozenset(b"]" if n >= hi else b",]"), depth + 1)


def _object(schema: dict, st: _State, depth: int):
    props = schema.get("properties")
    yield from _take(frozenset(b"{"), st)
    if props:
        keys = list(props)
        for i, k in enumerate(keys):
            yield from _lit(("," if i else "") + json.dumps(k) + ":", st)
            yield from value(props[k], st, frozenset(b"}" if i == len(keys) - 1 else b","), depth + 1)
        yield from _take(frozenset(b"}"), st)
        return
    # free-form object: string keys, any values
    n = 0
    while True:
        allowed = {ord("}")} | ({ord('"')} if n == 0 else {ord(",")}) if n < ARR_MAX else {ord("}")}
        b = yield from _take(frozenset(allowed), st)
        if b == ord("}"):
            return
        if b == ord('"'):
            st.pending = b
        yield from _string({"maxLength": 40}, st)
        yield from _take(frozenset(b":"), st)
        n += 1
        yield from value(None, st, frozenset(b"}" if n >= ARR_MAX else b",}"), depth + 1)


def value(schema: dict | None, st: _State, follow: frozenset, depth: int = 0):
    if schema and "enum" in schema:
        return (yield from _enum(schema["enum"], st))
    t = (schema or {}).get("type")
    if t is None:  # any JSON value; containers only while shallow
        allowed = first(None) | frozenset(b'"')
        if depth >= DEPTH:
            allowed -= frozenset(b"{[")
        b = yield from _take(allowed, st)
        st.pending = b
        t = {ord("{"): "object", ord("["): "array", ord('"'): "string", ord("t"): "boolean",
             ord("f"): "boolean", ord("n"): "null"}.get(b, "number")
        schema = {"type": t}
    if t == "object":
        yield from _object(schema, st, depth)
    elif t == "array":
        yield from _array(schema, st, depth)
    elif t == "string":
        yield from _string(schema, st)
    elif t in ("integer", "number"):
        yield from _number(follow, st, integer=t == "integer")
    elif t == "boolean":
        yield from _enum([True, False], st)
    elif t == "null":
        yield from _lit("null", st)
    else:
        raise ValueError(f"unsupported schema type {t!r}")


def min_len(schema: dict | None) -> int:
    """Bytes in the shortest value the automaton can emit for `schema` (enums count their longest)."""
    if not schema:
        return 1
    if "enum" in schema:
        return max(len(json.dumps(v)) for v in schema["enum"])
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties") or {}
        return 2 + sum(len(json.dumps(k)) + 1 + min_len(v) for k, v in props.items()) + max(len(props) - 1, 0)
    if t == "array":
        lo = schema.get("minItems", 0)
        return 2 + lo * min_len(schema.get("items") or {}) + max(lo - 1, 0)
    if t == "string":
        return 2 + schema.get("minLength", 0)
    return {"boolean": 5, "null": 4}.get(t, 1)


def _longest_enum(schema) -> int:
    if isinstance(schema, dict):
        own = max((len(json.dumps(v)) for v in schema.get("enum", [])), default=0)
        return max([own] + [_longest_enum(v) for v in schema.values()])
    if isinstance(schema, list):
        return max((_longest_enum(v) for v in schema), default=0)
    return 0


_CLOSERS = [frozenset(b"]"), frozenset(b"}"), frozenset(b'"'), frozenset([EOS]), frozenset(b",")]


class Constraint:
    """Stateful mask for one sequence. `allowed()` is the token set; `advance(tok)` consumes one."""

    def __init__(self, schema: dict | None):
        self._st = _State()
        top = schema if schema else {"type": "object"}
        self._gen = value(top, self._st, frozenset([EOS]))
        self._allowed = next(self._gen)
        self.done = False
        self.reserve = min_len(top) + _longest_enum(top) + STR_MAX // 10

    def allowed(self, remaining: int | None = None) -> frozenset:
        """Allowed next tokens. Pass the tokens left in the budget to enable wrap-up near the end."""
        if self.done:
            return frozenset([EOS])
        a = self._allowed
        if remaining is not None and remaining <= self.reserve and len(a) > 1:
            if PRINTABLE <= a:  # inside a string: end it if the length bounds allow
                return frozenset(b'"') if ord('"') in a else a
            for c in _CLOSERS:
                if c <= a:
                    return c
        return a

    def advance(self, tok: int) -> None:
        if self.done:
            if tok != EOS:
                raise ValueError("generation continued after the JSON value closed")
            return
        try:
            self._allowed = self._gen.send(tok)
            if self._st.pending == EOS:  # a top-level number ended
                self.done = True
        except StopIteration:
            self.done = True
