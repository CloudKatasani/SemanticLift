"""Stage 2b - classify measures (additivity, FR-08) and entities (fact/dimension, conformed, FR-07)."""
from __future__ import annotations

import re

from ..model import Hierarchy, LogicalAttribute, MetaGraph, Measure
from ..util import snake_upper
from .resolve import own_key_of

FM_AGG = {
    "total": ("sum", "additive", "ADD-01"), "sum": ("sum", "additive", "ADD-01"),
    "count": ("count", "additive", "ADD-01"), "maximum": ("max", "semi", "ADD-01"),
    "minimum": ("min", "semi", "ADD-01"), "average": ("avg", "non", "ADD-01"),
    "calculated": ("ratio", "non", "ADD-01"), "none": ("sum", "additive", "ADD-01"),
}
UNITS = ["MMBTU", "KVARH", "MWH", "KWH", "MVA", "MW", "KW", "KV", "PCT", "USD", "KG", "MINUTES", "DAYS",
         "CYCLES", "COUNT", "RATIO"]


def tokens(name: str) -> list[str]:
    return [t for t in snake_upper(name).split("_") if t]


def _has(name: str, patterns: list[str]) -> str | None:
    toks = [t.upper() for t in tokens(name)]
    camel = name
    for p in patterns:
        pu = snake_upper(p)
        if "_" in pu:
            if pu in "_".join(toks):
                return p
        elif pu in toks or (p[0].isupper() and re.search(rf"{p}(?=[A-Z0-9_]|$)", camel)):
            return p
    return None


def classify_measure(m: Measure, cfg: dict) -> None:
    c = cfg["classification"]
    toks = [t.upper() for t in tokens(m.name)]
    m.unit = next((u for u in reversed(toks) if u in UNITS), "")
    if m.origin == "FM" and m.regular_aggregate:
        agg, add, rule = FM_AGG.get(m.regular_aggregate, ("sum", "additive", "ADD-01"))
        if m.regular_aggregate == "calculated" and not m.is_ratio:
            agg = "avg"
        m.default_aggregation, m.additivity, m.rule = agg, add, rule
        return
    if (p := _has(m.name, c["non_additive_patterns"])):
        m.default_aggregation, m.additivity, m.rule = "avg", "non", f"ADD-02:{p}"
    elif (p := _has(m.name, c["semi_additive_patterns"])):
        m.default_aggregation, m.additivity, m.rule = "max", "semi", f"ADD-03:{p}"
    elif toks and toks[-1] in [s.upper() for s in c["power_unit_suffixes"]]:
        m.default_aggregation, m.additivity, m.rule = "avg", "semi", f"ADD-04:{toks[-1]}"
    elif (p := _has(m.name, c["additive_patterns"])):
        m.default_aggregation, m.additivity, m.rule = "sum", "additive", f"ADD-05:{p}"
    else:
        m.default_aggregation, m.additivity, m.rule = "sum", "additive", "ADD-06:default"


def is_static_measure(name: str, cfg: dict) -> bool:
    return _has(name, cfg["classification"]["static_measure_patterns"]) is not None


def classify(g: MetaGraph, cfg: dict) -> None:
    for m in g.measures.values():
        classify_measure(m, cfg)

    n_side = {r.from_entity for r in g.relationships.values() if r.cardinality.startswith("n")}
    one_side = {r.to_entity for r in g.relationships.values()}
    naming = cfg["naming"]
    splits: dict[str, dict] = {}
    outriggers: dict[str, dict] = {}

    report_pkgs = {r.package for r in g.reports.values()}
    for e in sorted(g.entities.values(), key=lambda x: x.name):
        attrs = [a for a in g.attributes.values() if a.entity == e.name]
        meas = [m for m in g.measures.values() if m.entity == e.name]
        rpk = [p for p in e.packages if p in report_pkgs]
        e.conformed = len(rpk) > 1
        if e.origin == "FM":
            e.role = "fact" if (e.name in n_side and meas and e.name not in one_side) else "dimension"
        else:
            eventish = _has(e.name, cfg["classification"]["event_entity_patterns"]) is not None
            e.role = "fact" if (meas or eventish) else "dimension"
            if e.name in one_side:
                e.role = "dimension"
        # primary key
        ids = [a for a in attrs if a.usage == "identifier"]
        if e.origin == "FM":
            pk = [a.name for a in ids]
            # keys referenced on the "1" side of relationships first
            one_keys = {k[1] for r in g.relationships.values() if r.to_entity == e.name for k in r.join_keys}
            pk = sorted(pk, key=lambda n: (0 if g.attributes[f"{e.name}.{n}"].physical_column in one_keys else 1, n))[:1]
        else:
            k = own_key_of(e.name, [a.name for a in attrs])
            pk = [k] if k else []
        e.primary_key = pk
        # domain
        e.domain = "ENTERPRISE" if e.conformed else (rpk[0] if rpk else (e.packages[0] if e.packages else ""))

        # Design splits for inferred masters with dynamic measures (DIM_<E> + FCT_<process>)
        master = any(p.lower() in e.name.lower() for p in cfg["classification"]["master_entity_patterns"])
        dynamic = [m for m in meas if not is_static_measure(m.name, cfg)]
        if e.origin == "inferred" and e.role == "fact" and master:
            if dynamic:
                splits[e.name] = {
                    "dimension": naming["dimension_names"].get(e.name, snake_upper(e.name)),
                    "fact": naming["fact_names"].get(e.name, snake_upper(e.name) + "_SNAPSHOT"),
                    "static_measures": sorted(m.name for m in meas if is_static_measure(m.name, cfg)),
                }
            else:
                e.role = "dimension"
        # Outrigger dimensions from reference attributes on facts
        ref_map = naming["reference_attributes"]
        is_fact = e.role == "fact" or e.name in splits
        if is_fact or any(f"{e.name}.{a.name}" in ref_map for a in attrs):
            for a in attrs:
                if a.name in (e.primary_key or []):
                    continue
                # facts: configured or *ID reference attributes; dimensions: explicitly configured outriggers only
                dim = ref_map.get(f"{e.name}.{a.name}") or (ref_map.get(a.name) if is_fact else None)
                if not dim and is_fact and a.name.endswith("ID") and len(a.name) > 2 and a.usage == "identifier":
                    dim = snake_upper(a.name[:-2])
                if dim:
                    o = outriggers.setdefault(dim, {"name": dim, "keys": [], "attributes": []})
                    o["keys"].append(f"{e.name}.{a.name}")
                    for extra in naming["attribute_groups"].get(dim, []):
                        ref = f"{e.name}.{extra}"
                        if ref in g.attributes and ref not in o["attributes"]:
                            o["attributes"].append(ref)
        # grain
        if e.role == "fact" or e.name in splits:
            fks = []
            for r in g.relationships.values():
                if r.from_entity == e.name:
                    fks.extend(k[0] for k in r.join_keys)
            e.grain = sorted(set(fks)) + [f"{e.name}.{k}" for k in e.primary_key]
        else:
            e.grain = [f"{e.name}.{k}" for k in e.primary_key]

    g.analysis["splits"] = splits
    g.analysis["outriggers"] = {k: v for k, v in sorted(outriggers.items())}

    # Conformed dimension extension columns per package (F10)
    conformed = {}
    for e in g.entities.values():
        if not e.conformed:
            continue
        per_pkg = {}
        for p in [p for p in e.packages if p in report_pkgs]:
            per_pkg[p] = sorted({ri.ref_item for ri in g.report_items if ri.resolved_entity == e.name and ri.ref_package == p})
        core = set.intersection(*(set(v) for v in per_pkg.values())) if per_pkg else set()
        conformed[e.name] = {"packages": sorted(e.packages), "per_package": per_pkg, "core": sorted(core),
                             "extensions": {p: sorted(set(v) - core) for p, v in per_pkg.items()}}
    g.analysis["conformed"] = dict(sorted(conformed.items()))

    # hierarchies (pattern library + FM)
    for ent, levels in cfg["hierarchies"].items():
        if ent in g.entities:
            present = [l for l in levels if g.item(ent, l) is not None]
            if len(present) >= 2:
                g.hierarchies[ent] = Hierarchy(name=f"{ent}_Hierarchy", entity=ent, levels=present)


def attr_role_dims(g: MetaGraph) -> dict[str, str]:
    """attribute ref -> outrigger dimension name (for design/trace)."""
    out = {}
    for dim, o in g.analysis.get("outriggers", {}).items():
        for k in o["keys"] + o["attributes"]:
            out[k] = dim
    return out


def is_identifier(a: LogicalAttribute) -> bool:
    return a.usage == "identifier"
