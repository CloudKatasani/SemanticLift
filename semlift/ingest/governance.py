"""GOV adapter: business and technical metadata exported from data governance tools.

Reads asset exports from Collibra, Atlan, Alation (and a generic template) as CSV, XLSX or JSON. Column names vary
by tool and by how the export was configured, so headers are matched against a list of synonyms and every record is
normalised to one shape::

    {tool, asset_type: table|column|term|domain|data_product|other, name, qualified_name,
     database, schema, table, column, domain, description, owner, steward,
     classifications: [..], certified: bool|None, terms: [..], synonyms: [..], loc}

Matching to SemanticLift objects happens later, in ``semlift.analyze.governance``.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..model import MetaGraph

FIELDS: dict[str, tuple[str, ...]] = {
    "name": ("name", "assetname", "title", "displayname", "termname", "businessname", "objectname"),
    "qualified_name": ("qualifiedname", "fullname", "assetfullname", "key", "fullpath", "path", "fullyqualifiedname",
                       "fqn", "guid_path"),
    "asset_type": ("assettype", "typename", "type", "objecttype", "otype", "asset_type_name", "kind"),
    "domain": ("domain", "domainname", "datadomain", "businessdomain", "community", "domains", "subjectarea"),
    "description": ("description", "definition", "userdescription", "businessdescription", "descriptionbusiness",
                    "summary", "longdescription"),
    "owner": ("owner", "dataowner", "ownerusers", "businessowner", "technicalowner", "owners", "assetowner"),
    "steward": ("steward", "datasteward", "stewards", "ownergroups", "businesssteward", "technicalsteward"),
    "classifications": ("classification", "classifications", "atlantags", "tags", "sensitivity", "dataclassification",
                        "securityclassification", "personaldata", "pii", "labels", "privacy"),
    "certified": ("certificatestatus", "certification", "certified", "endorsement", "trustcheck", "trustflags",
                  "status", "assetstatus"),
    "terms": ("meanings", "assignedterms", "glossaryterms", "businessterms", "terms", "glossary", "relatedterms",
              "businessterm", "isrepresentedby", "represents"),
    "synonyms": ("synonyms", "synonym", "alias", "aliases", "acronym", "abbreviation"),
    "database": ("databasename", "database", "db", "catalog", "datasource", "dsname"),
    "schema": ("schemaname", "schema"),
    "table": ("tablename", "table", "parenttable"),
    "column": ("columnname", "column", "field", "fieldname", "attributename"),
}
# headers that are characteristic of governance exports (a plain source catalog has none of them)
SIGNALS = {"description", "definition", "userdescription", "owner", "dataowner", "ownerusers", "steward",
           "datasteward", "classification", "classifications", "atlantags", "certificatestatus", "certification",
           "certified", "endorsement", "trustcheck", "meanings", "assignedterms", "glossaryterms", "businessterms",
           "community", "datadomain", "businessdomain", "domain"}
NAMEISH = {"name", "assetname", "title", "displayname", "qualifiedname", "fullname", "key", "termname"}
CERTIFIED_YES = {"verified", "certified", "approved", "yes", "true", "y", "1", "endorsed", "accepted", "trusted"}
CERTIFIED_NO = {"draft", "deprecated", "rejected", "no", "false", "n", "0", "obsolete", "warning", "untrusted",
                "candidatefordeprecation"}
SENSITIVE_WORDS = ("pii", "personal", "sensitive", "confidential", "restricted", "cpni", "gdpr", "pci", "phi",
                   "financial", "secret")


def norm_header(h: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(h or "").lower())


def looks_like_governance(headers: list[str]) -> bool:
    hs = {norm_header(h) for h in headers}
    return bool(hs & NAMEISH) and len(hs & SIGNALS) >= 1 and not {"reportname", "runsperday"} <= hs


def detect_tool(headers: list[str], filename: str) -> str:
    f = filename.lower()
    for tool in ("collibra", "atlan", "alation"):
        if tool in f:
            return tool
    hs = {norm_header(h) for h in headers}
    if {"qualifiedname", "typename"} <= hs or hs & {"atlantags", "certificatestatus", "ownerusers", "meanings"}:
        return "atlan"
    if "community" in hs or {"assettype", "fullname"} <= hs:
        return "collibra"
    if hs & {"otype", "trustcheck", "trustflags"} or ("key" in hs and "title" in hs):
        return "alation"
    return "generic"


def _split_list(v: Any) -> list[str]:
    if v is None or v == "":
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            if isinstance(x, dict):
                x = x.get("displayText") or x.get("name") or x.get("typeName") or x.get("title") or ""
            out.extend(_split_list(x))
        return out
    return [p.strip() for p in re.split(r"[;,|\n]", str(v)) if p.strip() and p.strip().lower() not in ("none", "null", "[]")]


def _type(v: str) -> str:
    t = norm_header(v)
    if not t:
        return ""
    if "column" in t or t in ("field", "attribute"):
        return "column"
    if "term" in t or t in ("glossaryterm", "atlasglossaryterm", "businessterm"):
        return "term"
    if "dataproduct" in t:
        return "data_product"
    if "domain" in t or t in ("community", "subjectarea"):
        return "domain"
    if "table" in t or "view" in t or t in ("dataset", "file"):
        return "table"
    return "other"


def _parts(qn: str) -> list[str]:
    """Split a qualified name from any of the tools into its meaningful segments."""
    segs = [s.strip().strip('"') for s in re.split(r"[>/.]", qn) if s and s.strip()]
    # drop connector prefixes such as Atlan's default/snowflake/<epoch> and Alation's numeric data-source id
    while segs and (segs[0].isdigit() or segs[0].lower() in ("default", "snowflake", "oracle", "databricks", "bigquery",
                                                             "redshift", "postgres", "mssql", "teradata", "sap")):
        segs = segs[1:]
    return segs


def normalise(raw: dict, tool: str, loc: str) -> dict | None:
    rec = dict(raw)
    if isinstance(rec.get("attributes"), dict):           # Atlan API shape: {"typeName":..,"attributes":{..}}
        rec = {**rec["attributes"], **{k: v for k, v in rec.items() if k != "attributes"}}
    by = {norm_header(k): v for k, v in rec.items()}

    def pick(field: str) -> Any:
        for syn in FIELDS[field]:
            if syn in by and by[syn] not in (None, ""):
                return by[syn]
        # headers such as "Personal Data Classification" or "Business Data Owner": match on the longer synonyms
        for syn in FIELDS[field]:
            if len(syn) >= 5:
                for h, v in by.items():
                    if syn in h and v not in (None, "") and not any(h == s for f in FIELDS.values() for s in f):
                        return v
        return None

    name = str(pick("name") or "").strip()
    qn = str(pick("qualified_name") or "").strip()
    if not name and not qn:
        return None
    atype = _type(str(pick("asset_type") or ""))
    db, schema, table, column = (str(pick(f) or "").strip() for f in ("database", "schema", "table", "column"))
    segs = _parts(qn) if qn else []
    if not atype:
        atype = "column" if column else "table" if table else "other"
    if atype == "column" and segs:
        column = column or segs[-1]
        table = table or (segs[-2] if len(segs) >= 2 else "")
        schema = schema or (segs[-3] if len(segs) >= 3 else "")
        db = db or (segs[-4] if len(segs) >= 4 else "")
    elif atype == "table" and segs:
        table = table or segs[-1]
        schema = schema or (segs[-2] if len(segs) >= 2 else "")
        db = db or (segs[-3] if len(segs) >= 3 else "")
    if atype == "column" and not column:
        column = name
    if atype == "table" and not table:
        table = name
    cert_raw = pick("certified")
    certified = None
    if cert_raw is not None:
        c = norm_header(cert_raw)
        certified = True if c in CERTIFIED_YES else False if c in CERTIFIED_NO else None
    return {
        "tool": tool, "asset_type": atype, "name": name or (segs[-1] if segs else qn), "qualified_name": qn,
        "database": db, "schema": schema, "table": table, "column": column,
        "domain": ", ".join(_split_list(pick("domain"))[:3]),
        "description": re.sub(r"<[^>]+>", "", str(pick("description") or "")).strip()[:1000],
        "owner": ", ".join(_split_list(pick("owner"))[:3]),
        "steward": ", ".join(_split_list(pick("steward"))[:3]),
        "classifications": _split_list(pick("classifications"))[:8],
        "certified": certified,
        "terms": _split_list(pick("terms"))[:8],
        "synonyms": _split_list(pick("synonyms"))[:8],
        "loc": loc,
    }


def is_sensitive(rec: dict) -> bool:
    return any(w in c.lower() for c in rec.get("classifications", []) for w in SENSITIVE_WORDS)


def _json_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        for k in ("entities", "assets", "results", "data", "items", "records", "objects"):
            if isinstance(data.get(k), list):
                data = data[k]
                break
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def json_headers(path: Path) -> list[str]:
    try:
        rows = _json_rows(path)[:20]
    except (ValueError, UnicodeDecodeError):
        return []
    keys: set[str] = set()
    for r in rows:
        keys |= set(r)
        if isinstance(r.get("attributes"), dict):
            keys |= set(r["attributes"])
    return sorted(keys)


def parse_governance(path: Path, rel: str, g: MetaGraph) -> int:
    from .sheets import iter_rows
    assets = g.analysis.setdefault("governance_assets", [])
    n = 0
    if path.suffix.lower() == ".json":
        rows = _json_rows(path)
        tool = detect_tool(json_headers(path), path.name)
        for i, r in enumerate(rows):
            rec = normalise(r, tool, f"{rel}:[{i}]")
            if rec:
                assets.append(rec)
                n += 1
        return n
    header: list[str] | None = None
    tool = "generic"
    cur = None
    for sheet, i, row in iter_rows(path):
        if sheet != cur:
            cur, header = sheet, None
        cells = ["" if v is None else str(v).strip() for v in row]
        if header is None:
            if i <= 10 and looks_like_governance(cells):
                header, tool = cells, detect_tool(cells, path.name)
            continue
        if not any(cells):
            continue
        rec = normalise(dict(zip(header, row)), tool, f"{rel}:{sheet}!{i}")
        if rec:
            assets.append(rec)
            n += 1
    return n
