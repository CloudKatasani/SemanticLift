"""Small, dependency-free helpers shared by every stage."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable

# Tokens that must survive camel/snake conversion as one word (units, acronyms).
_SPECIAL_TOKENS = [
    "MMBTU", "KVARh", "kVARh", "SAIFI", "MAIFI", "SAIDI", "PRC004", "CO2", "NPS", "USD",
    "MWh", "KWh", "kWh", "MVA", "MW", "KW", "kW", "KV", "kV", "REC", "EV", "GL", "ID",
]
_SPECIAL_RE = re.compile("|".join(sorted(map(re.escape, _SPECIAL_TOKENS), key=len, reverse=True)))


def snake_upper(name: str) -> str:
    """Convert a Cognos business name to an UPPER_SNAKE platform identifier.

    >>> snake_upper("CO2FactorKgKWh")
    'CO2_FACTOR_KG_KWH'
    >>> snake_upper("RECID")
    'REC_ID'
    """
    if not name:
        return name
    if re.fullmatch(r"[A-Z0-9_]+", name):
        if "_" not in name and len(name) > 3 and name.endswith("ID"):
            return name[:-2] + "_ID"
        return name.strip("_")
    parts: list[str] = []
    i = 0
    buf = ""
    while i < len(name):
        ch = name[i]
        if ch in " _-./":
            if buf:
                parts.append(buf)
                buf = ""
            i += 1
            continue
        m = _SPECIAL_RE.match(name, i)
        # Only treat as special token at a word boundary (start, after lower/digit, or after another token)
        if m and (not buf or buf[-1].islower() or buf[-1].isdigit() or buf.isupper()):
            tok = m.group(0)
            nxt = name[m.end():m.end() + 1]
            # Avoid splitting a capitalised word like "Mwh..." - specials must be followed by boundary
            if not nxt or nxt.isupper() or nxt.isdigit() or nxt in " _-./" or tok in ("ID",) and not nxt.islower():
                if buf:
                    parts.append(buf)
                    buf = ""
                parts.append(tok)
                i = m.end()
                continue
        if ch.isupper() and buf and (buf[-1].islower() or buf[-1].isdigit()):
            parts.append(buf)
            buf = ch
        elif ch.isupper() and buf and buf[-1].isupper() and i + 1 < len(name) and name[i + 1].islower():
            parts.append(buf)
            buf = ch
        else:
            buf += ch
        i += 1
    if buf:
        parts.append(buf)
    return "_".join(p.upper() for p in parts if p)


def snake_lower(name: str) -> str:
    return snake_upper(name).lower()


def title_words(name: str) -> str:
    """'CapacityFactorPct' -> 'capacity factor pct'"""
    return snake_lower(name).replace("_", " ")


def stable_hash(obj: Any, n: int = 12) -> str:
    data = obj if isinstance(obj, str) else json.dumps(obj, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:n]


def sql_str(value: Any) -> str:
    """Render a SQL string literal (single quotes escaped)."""
    return "'" + str(value).replace("'", "''") + "'"


def uniq(seq: Iterable) -> list:
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def mask_secret_url(url: str) -> str:
    """Mask host/credentials in JDBC URLs so exports never carry connection details."""
    if not url:
        return url
    url = re.sub(r"//[^/@]+@", "//***:***@", url)
    return re.sub(r"(@//|@)([^:/]+)(:\d+)?", lambda m: m.group(1) + "***" + ("" if not m.group(3) else ":****"), url)
