"""Stage 4a - demand-driven aggregate planning (spec 6.4, FR-10)."""
from __future__ import annotations

import math
import re
from collections import defaultdict

import networkx as nx

from ..design.naming import TIME_TOKENS, fact_name
from ..model import MetaGraph
from ..util import snake_upper
from .joins import build_graph


def cardinality(cfg: dict, ref: str) -> int:
    est = cfg["cardinality_estimates"]
    ent, item = ref.split(".", 1)
    for key in (ref, item):
        if key in est:
            return int(est[key])
    low = item.lower()
    for suffix in ("id", "date", "name", "flag", "status", "type", "category", "segment"):
        if low.endswith(suffix) and f"_{suffix}" in est:
            return int(est[f"_{suffix}"])
    if low.startswith("is"):
        return int(est.get("_flag", 2))
    return int(est.get("_default", 50))


def _hier_parent_map(cfg: dict) -> dict[str, list[str]]:
    """ref -> list of coarser refs it can roll up to."""
    out: dict[str, list[str]] = {}
    for ent, levels in cfg["hierarchies"].items():
        for i, lvl in enumerate(levels):
            out[f"{ent}.{lvl}"] = [f"{ent}.{x}" for x in levels[:i]]
    if "Date" in cfg["hierarchies"]:
        out.setdefault("Date.MonthNumber", ["Date.FiscalYear", "Date.Quarter"])
        out.setdefault("Date.ISOWeek", ["Date.FiscalYear"])
        if "Date.FullDate" in out:
            out["Date.FullDate"] = out["Date.FullDate"] + ["Date.MonthNumber", "Date.ISOWeek", "Date.IsWeekend",
                                                           "Date.IsHoliday"]
    return out


def covers(grain: set[str], sig: set[str], parents: dict[str, list[str]]) -> bool:
    derivable = set(grain)
    for gref in grain:
        derivable.update(parents.get(gref, []))
    return sig <= derivable


def est_rows(grain: set[str], cfg: dict, parents: dict) -> int:
    finest = {r for r in grain if not any(r in parents.get(o, []) for o in grain if o != r)}
    return int(math.prod(cardinality(cfg, r) for r in finest)) if finest else 1


def reachable_attrs(g: MetaGraph, G: nx.MultiDiGraph, fact: str) -> set[str]:
    ents = {fact} | (set(nx.descendants(G, fact)) if G.has_node(fact) else set())
    return {k for k, a in g.attributes.items() if a.entity in ents and not (a.entity == fact and a.usage == "identifier")}


def grain_label(grain: list[str], usage_weight: dict[str, float]) -> str:
    times = [TIME_TOKENS[r.split(".")[1]] for r in grain if r.startswith("Date.") and r.split(".")[1] in TIME_TOKENS]
    order = ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]
    t = next((o for o in order if o in times), None)
    others = [r for r in grain if not r.startswith("Date.")]
    others.sort(key=lambda r: (-usage_weight.get(r, 0), r))
    toks: list[str] = []
    for r in others:
        ent, item = r.split(".")
        tok = snake_upper(item)
        for e_tok in (snake_upper(ent), snake_upper(ent).split("_")[0]):
            if tok.startswith(e_tok + "_") and tok != e_tok:
                tok = tok[len(e_tok) + 1:]
                break
        head = tok.split("_")[0]
        merged = False
        for i, existing in enumerate(toks):
            if existing.split("_")[0] == head:
                toks[i] = head
                merged = True
        if not merged:
            toks.append(tok)
    toks = toks[:2]
    return "_".join(([t] if t else []) + toks) or "ALL"


def plan_aggregates(g: MetaGraph, cfg: dict) -> None:
    ac = cfg["aggregates"]
    parents = _hier_parent_map(cfg)
    G = build_graph(g)
    by_fact: dict[str, list[tuple[str, set[str], float]]] = defaultdict(list)
    heat: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    excluded: dict[str, set[str]] = defaultdict(set)
    for cl in sorted(g.clusters.values(), key=lambda c: c.id):
        if cl.disposition == "Retire":
            continue
        for f, sig in cl.grain_signature.items():
            ok = reachable_attrs(g, G, f)
            s = {r for r in sig if r in ok}
            excluded[f].update(r for r in sig if r not in ok)
            w = cl.weighted_demand
            by_fact[f].append((cl.id, s, w))
            for r in s:
                heat[f][r] += w
    plans = []
    fact_summary = {}
    for f in sorted(by_fact):
        ent = g.entities[f]
        demand = by_fact[f]
        total_w = sum(w for _, _, w in demand) or 0.0
        fact_rows = int(ac["default_fact_rows"])
        for k in ent.source_objects:
            so = g.source_objects.get(k)
            if so and so.row_count:
                fact_rows = so.row_count
        low_volume = ent.domain in ac.get("low_volume_domains", [])
        max_rows = fact_rows / float(ac["min_reduction_ratio"])
        cands: dict[frozenset, int] = {}
        sigs = [frozenset(s) for _, s, _ in demand if s]
        for s in sigs:
            r = est_rows(set(s), cfg, parents)
            if r <= max_rows:
                cands[s] = r
        for i, a in enumerate(sorted(set(sigs), key=sorted)):
            for b in sorted(set(sigs), key=sorted)[i + 1:]:
                u = a | b
                if u not in cands:
                    r = est_rows(set(u), cfg, parents)
                    if r <= max_rows:
                        cands[u] = r
        chosen = []
        covered: set[str] = set()
        min_gain = float(ac.get("min_aggregate_coverage", 0.05)) * total_w
        if not low_volume and total_w > 0:
            while len(chosen) < int(ac["max_per_fact"]):
                cov_w = sum(w for cid, _, w in demand if cid in covered)
                if cov_w / total_w >= float(ac["coverage_target"]):
                    break
                best = None
                for cand, rows in sorted(cands.items(), key=lambda x: (x[1], sorted(x[0]))):
                    gain_ids = {cid for cid, s, w in demand if cid not in covered and covers(set(cand), s, parents)}
                    gain = sum(w for cid, _, w in demand if cid in gain_ids)
                    score = gain / math.log10(rows + 10)
                    if gain >= min_gain and gain > 0 and (best is None or score > best[0] + 1e-12):
                        best = (score, cand, rows, gain_ids, gain)
                if best is None:
                    break
                _, cand, rows, gain_ids, gain = best
                covered |= gain_ids
                chosen.append((cand, rows, gain_ids, gain))
        cov_total = sum(w for cid, _, w in demand if cid in covered)
        refresh_lag = cfg["target"]["refresh_cadence_lag"].get(cfg["target"]["default_refresh_cadence"], "24 hours")
        lag_hours = _lag_hours(refresh_lag)
        for cand, rows, gain_ids, gain in chosen:
            grain = sorted(cand, key=lambda r: (0 if r.startswith("Date.") else 1, r))
            label = grain_label(grain, heat[f])
            name = cfg["naming"]["aggregate_names"].get(f"{f}:{label}") or f"AGG_{fact_name(cfg, f)[4:]}_{label}"
            secs = max(60.0, fact_rows / float(ac["scan_rows_per_second"]))
            credits_day = round(secs / 3600.0 * float(ac["warehouse_credits_per_hour"]) * (24.0 / lag_hours), 4)
            impl = "dynamic_table"
            if fact_rows < int(ac["plain_view_below_rows"]):
                impl = "view"
            plans.append({
                "name": name, "fact": f, "grain": grain, "clusters": sorted(gain_ids),
                "weight": round(gain, 4), "coverage_pct": round(100.0 * gain / total_w, 2) if total_w else 0.0,
                "est_rows": rows, "fact_rows": fact_rows, "credits_per_day": credits_day, "target_lag": refresh_lag,
                "implementation": impl,
            })
        fact_summary[f] = {
            "clusters": len(demand), "total_weight": round(total_w, 4),
            "covered_weight": round(cov_total, 4),
            "coverage_pct": round(100.0 * cov_total / total_w, 2) if total_w else 0.0,
            "aggregates": [p["name"] for p in plans if p["fact"] == f],
            "low_volume": low_volume,
            "excluded_attributes": sorted(excluded[f]),
            "heat": {k: round(v, 4) for k, v in sorted(heat[f].items(), key=lambda x: (-x[1], x[0]))},
            "demand": [{"cluster": cid, "signature": sorted(s), "weight": w} for cid, s, w in demand],
        }
    # de-duplicate names (two grains could produce the same label)
    seen: dict[str, int] = {}
    for p in plans:
        if p["name"] in seen:
            seen[p["name"]] += 1
            p["name"] = f"{p['name']}_{seen[p['name']]}"
        else:
            seen[p["name"]] = 1
    g.analysis["aggregates"] = plans
    g.analysis["aggregate_facts"] = fact_summary


def _lag_hours(lag: str) -> float:
    m = re.match(r"(\d+)\s*(minute|hour|day)", lag)
    if not m:
        return 24.0
    n = float(m.group(1))
    return {"minute": n / 60.0, "hour": n, "day": n * 24}[m.group(2)]
