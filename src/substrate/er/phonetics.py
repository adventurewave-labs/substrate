"""Soundex phonetic keys for name blocking (PLAN §4: phonetic keys).

Standard NARA rules: first letter kept, H/W transparent (do not reset the previous
code), vowels (incl. Y) reset it, truncate/pad to 4 characters. ASCII-only —
non-ASCII letters are stripped before coding.
"""

from __future__ import annotations

import unicodedata

_CODES = {
    **{c: "1" for c in "BFPV"},
    **{c: "2" for c in "CGJKQSXZ"},
    **{c: "3" for c in "DT"},
    "L": "4",
    **{c: "5" for c in "MN"},
    "R": "6",
}
_TRANSPARENT = set("HW")


def _to_ascii_upper(s: str) -> str:
    decomposed = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in decomposed if ch.isascii() and ch.isalpha()).upper()


def soundex(name: str) -> str:
    letters = _to_ascii_upper(name)
    if not letters:
        return ""
    out = letters[0]
    prev = _CODES.get(letters[0], "")
    for ch in letters[1:]:
        code = _CODES.get(ch, "")
        if ch in _TRANSPARENT:
            continue  # H/W never reset the previous code
        if code and code != prev:
            out += code
            if len(out) == 4:
                return out
        prev = code  # vowels (no code) reset; consonants update
    return (out + "000")[:4]
