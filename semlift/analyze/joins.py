"""Stage 2c - relationship inference from co-usage and join-path diagnostics (FR-09).

Directed graph: edge F -> D for every n:1 relationship (F on the many side).
For a report query that uses a fact F and an entity X:
  * X reachable from F along n:1 edges         -> safe join (multiple simple paths -> ambiguous)
  * X only reachable by also walking 1:n edges -> fan trap (measures of F would be multiplied)
  * two facts sharing a dimension in one query -> chasm trap (needs separate fact grains / stitch)
  * no path at all                              -> missing relationship
"""
from __future__ import annotations

import re
from collections import defaultdict

import networkx as nx

from ..model import MetaGraph, Provenance, Relationship
from ..util import snake_upper


def entity_key_column(g: MetaGraph, ent: str) -> str:
    e = g.entities.get(ent)
    if e and e.primary_key:
        a = g.attributes.get(f"{ent}.{e.primary_key[0]}")
        if a is not None:
            return a.physical_column or snake_upper(a.name)
    return snake_upper(ent) + "_ID"


def build_graph(g: MetaGraph) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for e in g.entities:
        G.add_node(e)
    for r in sorted(g.relationships.values(), key=lambda r: r.name):
        if r.cardinality.startswith("n") or r.cardinality in ("n:1", "*:1"):
            G.add_edge(r.from_entity, r.to_entity, key=r.name)
        else:
            G.add_edge(r.to_entity, r.from_entity, key=r.name)
    return G


def queries(g: MetaGraph, active_only: bool = True) -> dict[tuple[str, str], list[str]]:
    q: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ri in g.report_items:
        rep = g.reports.get(ri.report)
        if active_only and rep and rep.disposition == "Retire":
            continue
        if ri.resolved_entity and ri.resolved_entity not in q[(ri.report, ri.query)]:
            q[(ri.report, ri.query)].append(ri.resolved_entity)
    return q


def infer_relationships(g: MetaGraph, cfg: dict) -> None:
    """REL-INF-01: an inferred fact co-used with a dimension gets an inferred n:1 relationship."""
    splits = g.analysis.get("splits", {})
    G = build_graph(g)
    added: dict[tuple[str, str], int] = defaultdict(int)
    for (_rep, _q), ents in sorted(queries(g, active_only=False).items()):
        for f in ents:
            fe = g.entities[f]
            if fe.role != "fact":
                continue
            for d in ents:
                if d == f:
                    continue
                de = g.entities[d]
                # Facts (including split masters) are never join targets: that is a chasm, not a lookup.
                if de.role != "dimension" or d in splits:
                    continue
                # FM-defined fact to FM-defined dimension without a relationship stays a finding.
                if fe.origin == "FM" and de.origin == "FM" and not (d == "Date" and _date_attr(g, f)):
                    continue
                if G.has_node(f) and G.has_node(d) and nx.has_path(G, f, d):
                    continue
                added[(f, d)] += 1
    for (f, d), n in sorted(added.items()):
        key = entity_key_column(g, d)
        name = f"{f}_to_{d}"
        if name in g.relationships:
            continue
        role, conf = "", cfg["confidence"]["inferred_only"]
        if g.entities[f].origin == "FM" and d == "Date":
            role = f"derived:{_date_attr(g, f)}"      # REL-INF-02: date key derived from an FM date attribute
            conf = cfg["confidence"]["inferred_matched"]
        g.relationships[name] = Relationship(
            name=name, from_entity=f, to_entity=d, cardinality="n:1", join_type="inner",
            join_keys=[(key, key)], role_name=role, origin="inferred", confidence=conf,
            expression=f"inferred from co-usage in {n} report queries",
            prov=Provenance("all_reports.xml", f"co-usage:{f}+{d}", 0.3))


def _date_attr(g: MetaGraph, ent: str) -> str:
    cands = [a for a in g.attributes.values()
             if a.entity == ent and a.data_type in ("date", "datetime") and a.origin == "FM"]
    # prefer the event's start / business date over end or audit timestamps
    rank = lambda a: (0 if re.search(r"(Start|Begin|Date)$", a.name) else 1 if not re.search(r"End$", a.name) else 2, a.name)
    return sorted(cands, key=rank)[0].name if cands else ""


def fm_graph(g: MetaGraph) -> nx.MultiDiGraph:
    G = nx.MultiDiGraph()
    for e in g.entities:
        G.add_node(e)
    for r in g.relationships.values():
        if r.origin == "FM":
            G.add_edge(r.from_entity, r.to_entity, key=r.name)
    return G


def diagnose(g: MetaGraph, cfg: dict) -> None:
    G = build_graph(g)
    U = fm_graph(g).to_undirected(as_view=False)
    issues: dict[tuple, dict] = {}
    splits = g.analysis.get("splits", {})

    def note(kind, key, report, detail):
        rec = issues.setdefault((kind,) + key, {"kind": kind, "key": key, "reports": [], "detail": detail})
        if report not in rec["reports"]:
            rec["reports"].append(report)

    for (rep, _q), ents in sorted(queries(g).items()):
        facts = [e for e in ents if g.entities[e].role == "fact" and e not in splits]
        facts += [e for e in ents if e in splits and not any(
            G.has_node(f) and nx.has_path(G, f, e) for f in ents if f != e)]
        for f in facts:
            for x in ents:
                if x == f or x in facts:
                    continue
                if nx.has_path(G, f, x):
                    paths = list(nx.all_simple_paths(nx.DiGraph(G), f, x))
                    if len(paths) > 1:
                        note("ambiguous", (f, x), rep, " | ".join(" -> ".join(p) for p in paths))
                    continue
                if U.has_node(f) and U.has_node(x) and nx.has_path(U, f, x):
                    path = nx.shortest_path(U, f, x)
                    note("fan_trap", (f, x), rep, " - ".join(
                        f"{a}{' -> ' if G.has_edge(a, b) else ' <- '}{b}" for a, b in zip(path, path[1:])))
                else:
                    note("missing_relationship", (f, x), rep, f"no relationship path from {f} to {x}")
        if len(facts) > 1:
            for i, a in enumerate(sorted(facts)):
                for b in sorted(facts)[i + 1:]:
                    if nx.has_path(G, a, b) or nx.has_path(G, b, a):
                        continue
                    shared = sorted((set(nx.descendants(G, a)) & set(nx.descendants(G, b))) & set(ents))
                    note("chasm_trap", (a, b), rep,
                         f"facts {a} and {b} in one query" + (f" via shared {', '.join(shared)}" if shared else " with no shared dimension"))
        if not facts and len(ents) > 1:
            dims = sorted(ents)
            for i, a in enumerate(dims):
                for b in dims[i + 1:]:
                    if not nx.has_path(G.to_undirected(as_view=True), a, b):
                        note("missing_relationship", (a, b), rep, f"dimension-only query joins unrelated {a} and {b} (cross join)")
    g.analysis["join_issues"] = [v | {"count": len(v["reports"])} for _, v in sorted(issues.items())]
