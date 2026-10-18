"""Pure offline helpers for Stripe Hosted Checkout ``rv_timestamp``.

The browser bundle observed in the capture uses two deterministic transforms:

* JSON.stringify({rvTs, rv, sv}) is padded with spaces to a multiple of three;
* every character is XORed with ``5``, base64 encoded, URI encoded, then each
  printable ASCII character is shifted by ``11``.

This module only encodes/decodes supplied values and statically extracts the
three build fields from supplied HTML/JavaScript text.  It never evaluates
JavaScript and performs no I/O.
"""
from __future__ import annotations

import ast
import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Match
from urllib.parse import quote, unquote


_PRINTABLE_MIN = 32
_PRINTABLE_WIDTH = 95
_XOR_BYTE = 5
_SHIFT = 11
_MAX_OBJECT_SCAN = 8192

_STRING = r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
_IDENTIFIER = r"[A-Za-z_$][A-Za-z0-9_$]*"
_VALUE = rf"(?:{_STRING}|{_IDENTIFIER})"
_COMMENT = r"(?:(?:/\*.*?\*/|//[^\r\n]*)\s*)*"

# Accept the minified direct form and quoted/unquoted object keys.
_FIELD_RE = {
    name: re.compile(
        rf"(?:[\"']?{name}[\"']?)\s*:\s*{_COMMENT}(?P<value>{_VALUE})",
        re.DOTALL,
    )
    for name in ("rvTs", "rv", "sv")
}
_ASSIGNMENT_RE = re.compile(
    rf"(?:\b(?:var|let|const)\s+)?(?P<name>{_IDENTIFIER})\s*=\s*{_COMMENT}(?P<value>{_VALUE})",
    re.DOTALL,
)


@dataclass(frozen=True)
class RVBuildFields:
    """The three static fields embedded in a Stripe.js build."""

    rv_ts: str
    rv: str
    sv: str

    def as_dict(self) -> dict[str, str]:
        """Return the JavaScript field spelling used by the bundle."""
        return {"rvTs": self.rv_ts, "rv": self.rv, "sv": self.sv}


def _xor5(value: str) -> str:
    return "".join(chr(ord(char) ^ _XOR_BYTE) for char in value)


def _shift_printable(value: str, amount: int) -> str:
    out: list[str] = []
    for char in value:
        code = ord(char)
        if not _PRINTABLE_MIN <= code < _PRINTABLE_MIN + _PRINTABLE_WIDTH:
            raise ValueError("rv_timestamp contains a non-printable intermediate character")
        out.append(chr((code - _PRINTABLE_MIN + amount) % _PRINTABLE_WIDTH + _PRINTABLE_MIN))
    return "".join(out)


def _json_stringify_fields(fields: RVBuildFields) -> str:
    # The bundle's object literal is ordered rvTs, rv, sv and JSON.stringify
    # emits compact JSON for these ASCII build constants.
    return json.dumps(fields.as_dict(), ensure_ascii=True, separators=(",", ":"))


def encode_rv_timestamp(rv_ts: str, rv: str, sv: str) -> str:
    """Encode static build fields into the Hosted Checkout rv value.

    Values are intentionally passed in by the caller; no salts or captured
    values are bundled here.
    """
    fields = RVBuildFields(str(rv_ts), str(rv), str(sv))
    payload = _json_stringify_fields(fields)
    padding_count = 3 - len(payload) % 3
    padded = payload + (" " * padding_count)
    try:
        transformed = _xor5(padded).encode("latin1")
    except UnicodeEncodeError as exc:
        raise ValueError("rv_timestamp fields must be Latin-1 encodable") from exc
    encoded = quote(base64.b64encode(transformed).decode("ascii"), safe="~()*!.'-_")
    return _shift_printable(encoded, _SHIFT)


def decode_rv_timestamp(value: str) -> RVBuildFields | None:
    """Decode an rv value into fields, returning ``None`` for invalid input."""
    if not isinstance(value, str) or not value:
        return None
    try:
        unshifted = _shift_printable(value, -_SHIFT)
        raw = base64.b64decode(unquote(unshifted), validate=True).decode("latin1")
        payload = _xor5(raw).rstrip(" ")
        decoded = json.loads(payload)
        if not isinstance(decoded, dict):
            return None
        values = tuple(decoded.get(name) for name in ("rvTs", "rv", "sv"))
        if not all(isinstance(item, str) for item in values):
            return None
        return RVBuildFields(values[0], values[1], values[2])
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, binascii.Error):
        return None


def _decode_js_string(token: str) -> str | None:
    token = token.strip()
    if not token:
        return None
    try:
        if token.startswith("`") and token.endswith("`"):
            # Template literals containing interpolation are not static values.
            body = token[1:-1]
            if "${" in body:
                return None
            return bytes(body, "utf-8").decode("unicode_escape")
        value = ast.literal_eval(token)
        return value if isinstance(value, str) else None
    except (SyntaxError, ValueError, UnicodeDecodeError):
        return None


def _assignment_values(text: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for match in _ASSIGNMENT_RE.finditer(text):
        value = _decode_js_string(match.group("value"))
        if value is not None:
            assignments[match.group("name")] = value
    return assignments


def _resolve_value(token: str, assignments: dict[str, str]) -> str | None:
    token = token.strip()
    literal = _decode_js_string(token)
    if literal is not None:
        return literal
    seen: set[str] = set()
    while re.fullmatch(_IDENTIFIER, token):
        if token in seen or token not in assignments:
            return None
        seen.add(token)
        token = assignments[token]
    return token if token else None


_RVTS_KEY_RE = re.compile(r"(?:[\"']rvTs[\"']|\brvTs\b)\s*:")


def _object_end(text: str, start: int) -> int | None:
    """Find one candidate object's end, bounded to avoid broad script scans."""
    quote_char: str | None = None
    escaped = False
    depth = 0
    end_limit = min(len(text), start + _MAX_OBJECT_SCAN)
    for pos in range(start, end_limit):
        char = text[pos]
        if quote_char:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                quote_char = None
            continue
        if char in "\"'`":
            quote_char = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos + 1
    return None


def _candidate_objects(text: str) -> list[str]:
    """Return only bounded objects that occur immediately before an rvTs key.

    A multi-megabyte bundle can contain tens of thousands of braces. Scanning
    every brace with an 8192-character window is needlessly quadratic. The
    build payload has a distinctive ``rvTs`` key, so each candidate starts at
    the nearest preceding brace within the same bounded window.
    """
    candidates: list[str] = []
    seen_starts: set[int] = set()
    for key_match in _RVTS_KEY_RE.finditer(text):
        start = text.rfind("{", max(0, key_match.start() - _MAX_OBJECT_SCAN), key_match.start())
        if start < 0 or start in seen_starts:
            continue
        seen_starts.add(start)
        end = _object_end(text, start)
        if end is not None:
            candidates.append(text[start:end])
    return candidates


def extract_rv_build_fields(text: str) -> RVBuildFields | None:
    """Statically extract ``rvTs``, ``rv`` and ``sv`` from HTML/JS text.

    Both direct literals and identifier aliases are supported, for example
    ``{rvTs:TS,rv:RV,sv:SV}`` with preceding ``const TS = \"...\"`` lines.
    Missing, dynamic, or malformed fields return ``None``.
    """
    if not isinstance(text, str) or not text:
        return None
    assignments = _assignment_values(text)
    for candidate in _candidate_objects(text):
        matches: dict[str, Match[str]] = {}
        for name, pattern in _FIELD_RE.items():
            match = pattern.search(candidate)
            if match:
                matches[name] = match
        if len(matches) != 3:
            continue
        values = {
            name: _resolve_value(match.group("value"), assignments)
            for name, match in matches.items()
        }
        if all(isinstance(value, str) for value in values.values()):
            return RVBuildFields(values["rvTs"], values["rv"], values["sv"])
    return None


def rv_timestamp_from_script(text: str) -> str | None:
    """Extract build fields and encode them, or return ``None`` on failure."""
    fields = extract_rv_build_fields(text)
    return encode_rv_timestamp(fields.rv_ts, fields.rv, fields.sv) if fields else None


# Explicit aliases make the small public API easy to discover.
extract_build_fields = extract_rv_build_fields
encode = encode_rv_timestamp
decode = decode_rv_timestamp

__all__ = [
    "RVBuildFields",
    "decode",
    "decode_rv_timestamp",
    "encode",
    "encode_rv_timestamp",
    "extract_build_fields",
    "extract_rv_build_fields",
    "rv_timestamp_from_script",
]
