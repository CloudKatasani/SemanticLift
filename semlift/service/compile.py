"""Compile checks (validation rule V5): offline parse with sqlglot, optional live EXPLAIN on Snowflake."""
from __future__ import annotations

import os
import re

import sqlglot
from sqlglot.errors import ParseError

from ..model import TargetObject

_VIEW_RE = re.compile(r"\bAS\s*\n(SELECT\b.*)", re.S | re.I)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.S)
    return "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))


def _balanced(sql: str) -> bool:
    depth = 0
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            if in_str and i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return False
        i += 1
    return depth == 0 and not in_str


def offline_check(obj: TargetObject) -> dict:
    sql = _strip_comments(obj.ddl)
    sql_no_dollar = re.sub(r"\$\$.*?\$\$", "''", sql, flags=re.S)
    if not _balanced(sql_no_dollar):
        return {"status": "failed", "method": "offline", "message": "unbalanced parentheses or quotes"}
    stmts = [s for s in re.split(r";\s*(?:\n|$)", sql_no_dollar) if s.strip()]
    if not stmts:
        return {"status": "failed", "method": "offline", "message": "no statements"}
    checked = 0
    for s in stmts:
        m = _VIEW_RE.search(s)
        body = None
        if m and re.match(r"\s*CREATE\s+(OR\s+REPLACE\s+)?(SECURE\s+|MATERIALIZED\s+|DYNAMIC\s+)?(VIEW|TABLE)", s, re.I):
            body = m.group(1)
        elif re.match(r"\s*(SELECT|WITH)\b", s, re.I):
            body = s
        if body is None:
            continue
        try:
            sqlglot.parse_one(body, read="snowflake")
            checked += 1
        except ParseError as e:
            return {"status": "failed", "method": "offline", "message": f"sqlglot: {str(e).splitlines()[0][:300]}"}
    if obj.object_type == "semantic view":
        s = stmts[0].upper()
        if "TABLES (" not in s:
            return {"status": "failed", "method": "offline", "message": "semantic view without TABLES clause"}
    return {"status": "parsed", "method": "offline",
            "message": f"{len(stmts)} statement(s); {checked} SELECT bodies parsed (sqlglot/snowflake)"}


def live_connection():
    """Return a Snowflake connection when SEMLIFT_SNOWFLAKE_ACCOUNT is configured (read-only role advised)."""
    if not os.environ.get("SEMLIFT_SNOWFLAKE_ACCOUNT"):
        return None
    try:
        import snowflake.connector  # type: ignore
    except ImportError:
        return None
    return snowflake.connector.connect(
        account=os.environ["SEMLIFT_SNOWFLAKE_ACCOUNT"], user=os.environ.get("SEMLIFT_SNOWFLAKE_USER"),
        authenticator=os.environ.get("SEMLIFT_SNOWFLAKE_AUTHENTICATOR", "externalbrowser"),
        role=os.environ.get("SEMLIFT_SNOWFLAKE_ROLE"), warehouse=os.environ.get("SEMLIFT_SNOWFLAKE_WAREHOUSE"),
        database=os.environ.get("SEMLIFT_SNOWFLAKE_DATABASE"))


def explain(conn, obj: TargetObject) -> dict:
    sql = _strip_comments(obj.ddl)
    m = _VIEW_RE.search(sql)
    if not m:
        return {"status": "parsed", "method": "explain", "message": "no SELECT body to EXPLAIN"}
    body = m.group(1).rstrip().rstrip(";")
    try:
        cur = conn.cursor()
        cur.execute("EXPLAIN USING TEXT " + body)
        return {"status": "explained", "method": "explain", "message": "EXPLAIN succeeded"}
    except Exception as e:  # pragma: no cover - requires a live account
        return {"status": "failed", "method": "explain", "message": str(e)[:300]}


def check_all(objects: list[TargetObject], live: bool = False) -> dict[str, dict]:
    conn = live_connection() if live else None
    out = {}
    for o in objects:
        res = offline_check(o)
        if conn is not None and res["status"] == "parsed" and o.layer in ("core", "agg", "dp"):
            res = explain(conn, o)
        out[o.id] = res
    return out
