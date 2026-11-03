"""Match governance-tool metadata (Collibra, Atlan, Alation, ...) to the canonical model and use it.

Matching (GOV-01): governance tables are matched to entities by physical table name (FM physical layer or catalog)
or by entity name; columns to attributes and measures by physical column or item name; business terms to items by
name; terms assigned to a column flow to the item it matches. Names compare case- and punctuation-insensitively
(``BILL_AMOUNT`` = ``BillAmount`` = ``Bill Amount``).

Use:
- GOV-02 business descriptions from the governance tool become the descriptions of entities and items, and from
  there the comments of generated objects;
- GOV-03 glossary terms and synonyms become synonyms of semantic-view fields;
- GOV-04 classifications marked sensitive tag the column (``SENSITIVE``, ``DATA_CLASSIFICATION``); a sensitive
  column that Cognos does not protect raises finding F22;
- GOV-05 owners and stewards of a product's tables become the data product's owner and steward;
- GOV-06 a product whose tables span several governance domains, has uncertified tables or low glossary coverage
  gets a recommendation on the Data products page.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..design.model import Design
from ..ingest.governance import is_sensitive
from ..model import MetaGraph


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _empty_item() -> dict:
    return {"description": "", "terms": [], "synonyms": [], "classifications": [], "sensitive": False,
            "certified": None, "owner": "", "steward": "", "tools": [], "assets": []}


def match_governance(g: MetaGraph, cfg: dict) -> None:
    assets = g.analysis.get("governance_assets", [])
    if not assets:
        g.analysis["governance"] = {"loaded": False}
        return
    # entity lookup by table name and by entity name
    table_to_ent: dict[str, set[str]] = defaultdict(set)
    for e in g.entities.values():
        table_to_ent[norm(e.name)].add(e.name)
        for k in e.source_objects:
            so = g.source_objects.get(k)
            if so:
                table_to_ent[norm(so.table)].add(e.name)
    item_names: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))   # entity -> norm -> keys
    by_name: dict[str, set[str]] = defaultdict(set)                                       # norm item name -> keys
    for key in list(g.attributes) + list(g.measures):
        obj = g.attributes.get(key) or g.measures.get(key)
        for n in {norm(obj.name), norm(obj.physical_column)} - {""}:
            item_names[obj.entity][n].add(key)
        by_name[norm(obj.name)].add(key)

    items: dict[str, dict] = defaultdict(_empty_item)
    ents: dict[str, dict] = {}
    matched = Counter()
    unmatched: list[dict] = []

    def merge(info: dict, a: dict, kind: str) -> None:
        if a["description"] and (not info["description"] or kind == "column"):
            info["description"] = a["description"]
        for f in ("terms", "synonyms", "classifications"):
            info[f] = list(dict.fromkeys(info[f] + a[f]))[:8]
        info["sensitive"] = info["sensitive"] or is_sensitive(a)
        if a["certified"] is not None:
            info["certified"] = a["certified"] if info["certified"] is None else (info["certified"] and a["certified"])
        for f in ("owner", "steward", "domain"):
            if a.get(f) and not info.get(f):
                info[f] = a[f]
        if a["tool"] not in info["tools"]:
            info["tools"].append(a["tool"])
        info["assets"].append(a["qualified_name"] or a["name"])

    terms: dict[str, dict] = {}
    for a in assets:
        if a["asset_type"] == "term":
            terms[norm(a["name"])] = a
    for a in assets:
        t = a["asset_type"]
        if t == "table":
            hits = table_to_ent.get(norm(a["table"] or a["name"]), set())
            for en in hits:
                info = ents.setdefault(en, {**_empty_item(), "domain": "", "tables": []})
                merge(info, a, "table")
                q = ".".join(x for x in (a["database"], a["schema"], a["table"]) if x)
                if q and q not in info["tables"]:
                    info["tables"].append(q)
            matched["table" if hits else "table_unmatched"] += 1
            if not hits:
                unmatched.append({"type": "table", "name": a["qualified_name"] or a["name"], "tool": a["tool"]})
        elif t == "column":
            keys = set()
            for en in table_to_ent.get(norm(a["table"]), set()):
                keys |= item_names[en].get(norm(a["column"] or a["name"]), set())
            for k in keys:
                merge(items[k], a, "column")
                for term in a["terms"]:                        # a term assigned to the column brings its definition
                    ta = terms.get(norm(term))
                    if ta:
                        merge(items[k], {**ta, "description": items[k]["description"] or ta["description"]}, "term")
            matched["column" if keys else "column_unmatched"] += 1
            if not keys:
                unmatched.append({"type": "column", "name": a["qualified_name"] or f"{a['table']}.{a['column']}", "tool": a["tool"]})
        elif t == "term":
            keys = by_name.get(norm(a["name"]), set()) | {k for s in a["synonyms"] for k in by_name.get(norm(s), set())}
            for k in keys:
                merge(items[k], {**a, "terms": list(dict.fromkeys([a["name"]] + a["terms"]))}, "term")
            matched["term" if keys else "term_unmatched"] += 1
            if not keys:
                unmatched.append({"type": "term", "name": a["name"], "tool": a["tool"]})
        else:
            matched[t] += 1

    # GOV-02: governance descriptions become the business descriptions used for comments and semantic views
    for key, info in items.items():
        obj = g.attributes.get(key) or g.measures.get(key)
        if obj is not None and info["description"]:
            obj.description = info["description"]
        if obj is not None and info["sensitive"]:
            obj.sensitive = True
    for en, info in ents.items():
        if info["description"] and en in g.entities:
            g.entities[en].description = info["description"]

    tools = Counter(a["tool"] for a in assets)
    g.analysis["governance"] = {
        "loaded": True, "assets": len(assets), "tools": dict(tools),
        "by_type": dict(Counter(a["asset_type"] for a in assets)),
        "matched": {"tables": matched["table"], "columns": matched["column"], "terms": matched["term"]},
        "unmatched": {"tables": matched["table_unmatched"], "columns": matched["column_unmatched"],
                      "terms": matched["term_unmatched"], "examples": unmatched[:40]},
        "entities": {k: ents[k] for k in sorted(ents)},
        "items": {k: items[k] for k in sorted(items)},
        "domains": sorted({a["domain"] for a in assets if a["domain"]}),
    }


def governance_findings(g: MetaGraph) -> None:
    gov = g.analysis.get("governance", {})
    if not gov.get("loaded"):
        return
    protected = {(r.target_entity, r.target_item) for r in g.security_rules.values() if r.type in ("mask", "column_grant")}
    protected |= {(t["entity"], t["item"]) for r in g.security_rules.values() if r.type == "abac" for t in r.targets}
    used: Counter = Counter()
    for ri in g.report_items:
        if ri.resolved_entity:
            used[f"{ri.resolved_entity}.{ri.ref_item}"] += 1
    for key, info in gov["items"].items():
        ent, _, item = key.partition(".")
        if info["sensitive"] and (ent, item) not in protected:
            g.add_finding("F22", f"{key} is classified sensitive in {', '.join(info['tools'])} but not protected in Cognos",
                          severity="high", obj=key,
                          evidence=f"classifications: {', '.join(info['classifications'])}; used in {used[key]} report columns",
                          owner=info["steward"] or info["owner"],
                          resolution="Add a masking policy (or confirm the classification) before publishing the semantic view")
        if info["certified"] is False and used[key]:
            g.add_finding("F23", f"{key} is not certified (draft or deprecated) in {', '.join(info['tools'])}",
                          severity="medium", obj=key, evidence=f"used in {used[key]} report columns",
                          owner=info["steward"] or info["owner"],
                          resolution="Confirm the definition with its steward before it becomes a governed metric")


def apply_governance_to_design(g: MetaGraph, d: Design, cfg: dict) -> None:
    """GOV-03..05 on the physical design: synonyms, classification tags and product ownership."""
    gov = g.analysis.get("governance", {})
    if not gov.get("loaded"):
        return
    items, ents = gov["items"], gov["entities"]
    for t in d.tables.values():
        for c in t.columns:
            info = items.get(c.ref)
            if info and info["sensitive"]:
                c.sensitive = True
                c.tags["SENSITIVE"] = "true"
                c.tags["DATA_CLASSIFICATION"] = ", ".join(info["classifications"])[:120] or "Sensitive"
    for sv in d.semantic_views.values():
        for f in list(sv.dimensions) + list(sv.metrics) + list(sv.facts):
            info = items.get(f.ref)
            if not info:
                continue
            f.synonyms = list(dict.fromkeys(list(f.synonyms) + info["terms"] + info["synonyms"]))[:8]
            if not f.comment and info["description"]:
                f.comment = info["description"][:300]
    for p in d.products.values():
        # facts carry the product's business process, so their owners count three times a dimension's
        owners, stewards = Counter(), Counter()
        for t in p.core_tables:
            info = ents.get(d.tables[t].entity)
            w = 3 if d.tables[t].kind == "fact" else 1
            if info and info["owner"]:
                owners[info["owner"]] += w
            if info and info["steward"]:
                stewards[info["steward"]] += w
        if owners:
            p.owner = owners.most_common(1)[0][0]
        if stewards:
            p.steward = stewards.most_common(1)[0][0]


def product_governance(g: MetaGraph, d: Design, key: str) -> dict | None:
    """GOV-06: governance view of one data product, with recommendations."""
    gov = g.analysis.get("governance", {})
    if not gov.get("loaded"):
        return None
    p = d.products[key]
    items, ents = gov["items"], gov["entities"]
    entities = sorted({d.tables[t].entity for t in p.core_tables if d.tables[t].entity})
    cols = [c for t in p.core_tables for c in d.tables[t].columns if c.ref]
    with_info = [c for c in cols if c.ref in items]
    with_terms = [c for c in cols if items.get(c.ref, {}).get("terms")]
    sensitive = sorted({c.ref for c in cols if items.get(c.ref, {}).get("sensitive")})
    unmasked = sorted({c.ref for t in p.core_tables for c in d.tables[t].columns
                       if items.get(c.ref, {}).get("sensitive") and not c.masking_policy})
    domains = Counter(ents[e]["domain"] for e in entities if e in ents and ents[e].get("domain"))
    owners = sorted({ents[e]["owner"] for e in entities if e in ents and ents[e]["owner"]})
    stewards = sorted({ents[e]["steward"] for e in entities if e in ents and ents[e]["steward"]})
    certified = [e for e in entities if ents.get(e, {}).get("certified") is True]
    uncertified = [e for e in entities if ents.get(e, {}).get("certified") is False]
    coverage = round(100 * len(with_terms) / len(cols)) if cols else 0
    recs = []
    if len(domains) > 1:
        recs.append(f"Its tables belong to {len(domains)} governance domains ({', '.join(domains)}). Confirm the "
                    "product boundary with the domain owners, or split it along the domains.")
    if owners:
        recs.append(f"Owner taken from the governance tool: {p.owner}" + (f" (also listed: {', '.join(o for o in owners if o != p.owner)})"
                                                                           if len(owners) > 1 else "") + ".")
    if unmasked:
        recs.append(f"{len(unmasked)} column(s) are classified sensitive but have no masking policy: "
                    f"{', '.join(unmasked[:5])}{'…' if len(unmasked) > 5 else ''}.")
    if uncertified:
        recs.append(f"Not certified in the governance tool: {', '.join(uncertified)}. Certify before publishing the product.")
    if cols and coverage < 50:
        recs.append(f"Only {coverage}% of its columns map to glossary terms; add business terms so the semantic views "
                    "get business names and synonyms.")
    return {"domains": dict(domains), "owners": owners, "stewards": stewards, "entities_described": len(certified) + len(uncertified),
            "certified": certified, "uncertified": uncertified, "columns": len(cols), "columns_with_metadata": len(with_info),
            "glossary_coverage_pct": coverage, "sensitive_columns": sensitive, "unmasked_sensitive": unmasked,
            "recommendations": recs}
