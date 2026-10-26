"""AGG, SEM and DP layer design (spec 6.4 - 6.6)."""
from __future__ import annotations

import re
from collections import deque

from ..model import Measure, MetaGraph
from ..util import snake_lower, snake_upper, title_words, uniq
from .core import classification, owner, retention, steward
from .model import (AggregateDesign, Design, OutputViewDesign, ProductDesign, SemanticViewDesign, SVField,
                    SVRelationship, SVTable, VerifiedQuery)
from .naming import domain_code, product_name, product_slug

AGG_SQL = {"sum": "SUM", "avg": "AVG", "max": "MAX", "min": "MIN", "count": "COUNT"}
METRIC_PREFIX = {"sum": "total", "avg": "avg", "max": "max", "min": "min", "count": "count"}
TIME_ADJ = {"DAY": "DAILY", "WEEK": "WEEKLY", "MONTH": "MONTHLY", "QUARTER": "QUARTERLY", "YEAR": "ANNUAL"}


def clip(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n].rsplit(" ", 1)[0] + " ..."


def fk_graph(d: Design) -> dict[str, list[tuple[str, list[str], list[str]]]]:
    out: dict[str, list] = {}
    for t in d.tables.values():
        for fk in t.foreign_keys:
            if fk.ref_table in d.tables:
                out.setdefault(t.id, []).append((fk.ref_table, fk.columns, fk.ref_columns))
    return out


def join_path(d: Design, start: str, target: str) -> list[tuple[str, str, list[str], list[str]]] | None:
    """Shortest n:1 path start -> target as [(from_table, to_table, from_cols, to_cols)]."""
    if start == target:
        return []
    G = fk_graph(d)
    prev: dict[str, tuple] = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        for nxt, fc, tc in sorted(G.get(cur, []), key=lambda x: x[0]):
            if nxt in prev:
                continue
            prev[nxt] = (cur, fc, tc)
            if nxt == target:
                path = []
                node = nxt
                while prev[node] is not None:
                    p, fcols, tcols = prev[node]
                    path.append((p, node, fcols, tcols))
                    node = p
                return list(reversed(path))
            q.append(nxt)
    return None


class SemanticBuilder:
    def __init__(self, g: MetaGraph, cfg: dict, d: Design):
        self.g, self.cfg, self.d = g, cfg, d
        self.live = [c for c in g.clusters.values() if c.disposition != "Retire"]
        self.used = set()
        for c in self.live:
            self.used.update(c.items)
        self.param_targets = self._param_targets()

    def _param_targets(self) -> dict[str, list[str]]:
        """Entity.Item -> parameters used against it in non-defective filters."""
        out: dict[str, list[str]] = {}
        for f in self.g.report_filters:
            if f.parameter and not f.defect and f.ref_subject:
                ref = f"{f.ref_subject}.{f.ref_item}"
                if f.parameter not in out.setdefault(ref, []):
                    out[ref].append(f.parameter)
        return out

    # ------------------------------------------------------------ aggregates
    def build_aggregates(self) -> None:
        g, d, cfg = self.g, self.d, self.cfg
        for p in g.analysis.get("aggregates", []):
            fid = next((t for t in d.entity_tables.get(p["fact"], []) if d.tables[t].kind == "fact"), None)
            if not fid:
                continue
            ft = d.tables[fid]
            joins, groups, aliases = [], [], {fid: "f"}
            ok = True
            excluded = []
            grain = list(p["grain"])
            if "Date.MonthName" in grain and "Date.MonthNumber" not in grain and "Date.MonthNumber" in d.ref_to_column:
                grain.append("Date.MonthNumber")       # AGG-03 sort companion
            for ref in grain:
                tc = d.ref_to_column.get(ref)
                if not tc:
                    excluded.append(ref)
                    continue
                tid, col = tc
                path = join_path(d, fid, tid)
                if path is None:
                    excluded.append(ref)
                    continue
                for frm, to, fcols, tcols in path:
                    if to not in aliases:
                        aliases[to] = re.sub(r"[^a-z]", "", d.tables[to].alias[:1]) + str(len(aliases))
                        joins.append((aliases[to], to, " AND ".join(f"{aliases[frm]}.{a} = {aliases[to]}.{b}" for a, b in zip(fcols, tcols))))
                out = col if col not in [x[2] for x in groups] else f"{d.tables[tid].alias.upper()}_{col}"
                groups.append((aliases[tid], col, out))
            measures = []
            for c in ft.columns:
                if c.kind != "measure":
                    continue
                if c.additivity == "additive" or c.default_aggregation == "sum":
                    measures.append((c.name, f"SUM(f.{c.name})", "sum"))
                elif c.default_aggregation in ("max", "min"):
                    measures.append((c.name, f"{c.default_aggregation.upper()}(f.{c.name})", c.default_aggregation))
                else:      # AGG-04: store re-aggregable components for non-additive measures
                    measures.append((f"{c.name}_SUM", f"SUM(f.{c.name})", "component_sum"))
                    measures.append((f"{c.name}_COUNT", f"COUNT(f.{c.name})", "component_count"))
            measures.append((f"{ft.name[4:]}_COUNT", "COUNT(*)", "count"))
            impl = p["implementation"]
            aid = f"AGG.{p['name']}"
            d.aggregates[aid] = AggregateDesign(
                id=aid, name=p["name"], fact=p["fact"], fact_table=fid, grain_refs=grain, group_columns=groups,
                joins=joins, measures=measures, implementation=impl, target_lag=p["target_lag"],
                warehouse=cfg["aggregates"]["warehouse"], coverage_pct=p["coverage_pct"], clusters=p["clusters"],
                est_rows=p["est_rows"], credits_per_day=p["credits_per_day"], domain=ft.domain,
                confidence=min([ft.confidence] + [d.tables[t].confidence for _, t, _ in joins]),
                stub=ft.stub or not ok or any(d.tables[t].stub for _, t, _ in joins), excluded=excluded)

    # ------------------------------------------------------------ semantic views
    def subject_areas(self) -> dict[str, dict]:
        g, cfg = self.g, self.cfg
        conf = cfg["naming"]["subject_areas"]
        areas: dict[str, dict] = {}
        covered = set()
        for name, sa in conf.items():
            facts = [f for f in sa.get("facts", []) if f in g.entities]
            if not facts:
                continue
            areas[name] = {"domain": sa.get("domain") or g.entities[facts[0]].domain, "entities": facts,
                           "description": sa.get("description", "")}
            covered.update(facts)
        for e in sorted(g.entities.values(), key=lambda e: e.name):
            if e.role == "fact" and e.name not in covered:
                dom = e.domain if e.domain != "ENTERPRISE" else (e.packages[0] if e.packages else "")
                name = f"SV_{domain_code(cfg, dom)}_{snake_upper(e.name)}"
                areas[name] = {"domain": dom, "entities": [e.name], "description": f"{title_words(e.name).title()} subject area"}
        return dict(sorted(areas.items()))

    def build_semantic_views(self) -> None:
        g, d = self.g, self.d
        for name, sa in self.subject_areas().items():
            sv = SemanticViewDesign(id=f"SEM.{name}", name=name, domain=sa["domain"], description=sa["description"],
                                    entities=sa["entities"])
            members = [t for e in sa["entities"] for t in d.entity_tables.get(e, [])]
            included = list(dict.fromkeys(members))
            G = fk_graph(d)
            q = deque(included)
            while q:
                cur = q.popleft()
                for nxt, _fc, _tc in sorted(G.get(cur, []), key=lambda x: x[0]):
                    if nxt not in included:
                        included.append(nxt)
                        q.append(nxt)
            aliases = {}
            for tid in included:
                t = d.tables[tid]
                a = t.alias or tid.split(".")[1].lower()
                a = {"date": "dt"}.get(a, a)
                while a in aliases.values():
                    a += "_t"
                aliases[tid] = a
                syn = uniq([title_words(t.entity)] + ([title_words(t.entity) + "s"] if t.kind == "fact" else []))
                sv.tables.append(SVTable(alias=a, table=tid, primary_key=list(t.primary_key), synonyms=syn,
                                         comment=clip(t.comment, 240)))
            for tid in included:
                t = d.tables[tid]
                for fk in t.foreign_keys:
                    if fk.ref_table in aliases:
                        rn = f"{aliases[tid]}_to_{aliases[fk.ref_table]}"
                        if any(r.name == rn for r in sv.relationships):
                            rn += f"_{len(sv.relationships)}"
                        sv.relationships.append(SVRelationship(rn, aliases[tid], fk.columns, aliases[fk.ref_table], fk.ref_columns))
            sv.clusters = sorted(c.id for c in self.live if set(c.facts) & set(sa["entities"]) or
                                 (not c.facts and {r.split('.')[0] for r in c.items} & set(sa["entities"])))
            sv_used = set()
            for cid in sv.clusters:
                sv_used.update(g.clusters[cid].items)
            sv_params = {f"{f.ref_subject}.{f.ref_item}" for f in g.report_filters
                         if f.parameter and not f.defect and g.reports[f.report].cluster in sv.clusters}
            names: set[str] = set()

            def uname(base: str, alias: str) -> str:
                n = base
                if n in names:
                    n = f"{alias}_{base}"
                i = 2
                while n in names:
                    n = f"{alias}_{base}_{i}"
                    i += 1
                names.add(n)
                return n

            for tid in included:
                t = d.tables[tid]
                a = aliases[tid]
                for c in t.columns:
                    if c.kind == "sk":
                        continue
                    obj = g.item(*c.ref.split(".", 1)) if c.ref else None
                    demanded = c.ref in sv_used or c.ref in sv_params
                    labels = list(getattr(obj, "labels", []) or [])
                    syn = uniq([title_words(obj.name)] + [title_words(l) for l in labels]) if obj else []
                    if isinstance(obj, Measure) or c.kind == "measure":
                        if not demanded and not (obj is not None and obj.origin == "FM"):
                            continue
                        f = SVField(a, uname(snake_lower(c.name), a), c.name, c.data_type, clip(c.comment, 200), syn, ref=c.ref)
                        sv.facts.append(f)
                        self._metric(sv, a, f, obj, c, uname)
                    elif c.kind in ("attribute", "derived") or (c.kind == "key" and demanded):
                        if not demanded and c.kind != "derived":
                            continue
                        samples = []
                        for prm in self.param_targets.get(c.ref, []):
                            p = g.parameters.get(prm)
                            if p:
                                samples += [i["value"] for i in p.pick_list if i["value"] != "All"]
                                if p.required:
                                    sv.default_filters.append({"parameter": prm, "dimension": snake_lower(c.name),
                                                               "default": p.default, "required": True})
                        if c.ref == "Date.FiscalYear":
                            syn = uniq(syn + ["FY"])
                        sv.dimensions.append(SVField(a, uname(snake_lower(c.name), a), c.name, c.data_type,
                                                     clip(c.comment, 200), syn, samples[:10], ref=c.ref))
                    if c.ref:
                        d.ref_to_semantic.setdefault(c.ref, [])
                # FM ratio metrics (never stored) - spec 6.1
                for m in sorted(g.measures.values(), key=lambda m: m.name):
                    if m.entity != t.entity or not m.is_ratio or t.kind != "fact":
                        continue
                    num, den = m.ratio_parts
                    for part in (num, den):
                        if not any(f.alias == a and f.expr == part for f in sv.facts):
                            pc = t.col(part)
                            if pc is not None:
                                sv.facts.append(SVField(a, uname(snake_lower(part), a), part, pc.data_type, pclip(c.comment, 200)))
                    fn = next(f.name for f in sv.facts if f.alias == a and f.expr == num) if any(f.alias == a and f.expr == num for f in sv.facts) else None
                    fd = next(f.name for f in sv.facts if f.alias == a and f.expr == den) if any(f.alias == a and f.expr == den for f in sv.facts) else None
                    if fn and fd:
                        mname = uname(snake_lower(m.name), a)
                        sv.metrics.append(SVField(a, mname, f"SUM({a}.{fn}) / NULLIF(SUM({a}.{fd}), 0)", "NUMBER",
                                                  f"Ratio metric from FM calculation {m.entity}.{m.name} (regularAggregate=calculated)",
                                                  [title_words(m.name)], ref=f"{m.entity}.{m.name}", aggregation="ratio"))
                        d.ref_to_semantic.setdefault(f"{m.entity}.{m.name}", []).append(f"{sv.id}.{a}.{mname}")
                if t.kind == "fact" and t.primary_key:
                    sv.metrics.append(SVField(a, uname(f"{a}_count", a), f"COUNT({a}.{snake_lower(t.primary_key[0])})" if False else f"COUNT(*)",
                                              "NUMBER", f"Number of {title_words(t.entity)} rows", [f"number of {title_words(t.entity)}s"],
                                              aggregation="count"))
            # Prefer counting via a fact (semantic views require metric expressions over table columns)
            for m in sv.metrics:
                if m.expr == "COUNT(*)":
                    t = d.tables[next(tid for tid, al in aliases.items() if al == m.alias)]
                    pk = t.primary_key[0]
                    if not any(f.alias == m.alias and f.expr == pk for f in sv.facts):
                        sv.facts.append(SVField(m.alias, uname(snake_lower(pk), m.alias), pk, "VARCHAR", f"Grain key of {t.name}"))
                    fk_name = next(f.name for f in sv.facts if f.alias == m.alias and f.expr == pk)
                    m.expr = f"COUNT({m.alias}.{fk_name})"
            for f in sv.dimensions + sv.facts + sv.metrics:
                if f.ref:
                    entry = f"{sv.id}.{f.alias}.{f.name}"
                    if entry not in d.ref_to_semantic.setdefault(f.ref, []):
                        d.ref_to_semantic[f.ref].append(entry)
            sv.confidence = min([d.tables[t].confidence for t in included] or [1.0])
            sv.stub = any(d.tables[t].stub for t in included)
            dedup = []
            for f in sv.default_filters:
                if f not in dedup:
                    dedup.append(f)
            sv.default_filters = dedup
            self._verified_queries(sv, aliases)
            d.semantic_views[sv.id] = sv

    def _metric(self, sv, a, f: SVField, obj, c, uname) -> None:
        agg = (getattr(obj, "default_aggregation", "") or c.default_aggregation or "sum")
        if agg == "ratio":
            return
        sql = AGG_SQL.get(agg, "SUM")
        prefix = METRIC_PREFIX.get(agg, "total")
        base = f"{f.name}_{agg}" if f.name.startswith(prefix + "_") else f"{prefix}_{f.name}"
        mname = uname(base, a)
        additivity = getattr(obj, "additivity", c.additivity)
        add_txt = "additive" if additivity == "additive" else f"{additivity}-additive"
        comment = f"{sql} of {title_words(obj.name if obj else c.name)} ({add_txt}; default aggregation from {'FM' if obj is not None and obj.origin == 'FM' else 'rule ' + (getattr(obj, 'rule', '') or 'ADD')})"
        sv.metrics.append(SVField(a, mname, f"{sql}({a}.{f.name})", "NUMBER", comment,
                                  uniq([title_words(base)] + list(f.synonyms)),
                                  ref=f.ref, aggregation=agg))

    def _verified_queries(self, sv: SemanticViewDesign, aliases: dict[str, str]) -> None:
        g, d = self.g, self.d
        cands = sorted((c for c in self.live if c.id in sv.clusters), key=lambda c: (-c.weighted_demand, c.id))[:10]
        dim_by_ref = {f.ref: f for f in sv.dimensions if f.ref}
        met_by_ref = {}
        for m in sv.metrics:
            if m.ref and m.ref not in met_by_ref:
                met_by_ref[m.ref] = m
        alias_table = {v: k for k, v in aliases.items()}
        for c in cands:
            dims = [dim_by_ref[r] for r in c.items if r in dim_by_ref][:6]
            mets = [met_by_ref[r] for r in c.items if r in met_by_ref][:6]
            if not mets:
                continue
            rep = g.reports[c.canonical]
            dims_txt = ", ".join(title_words(x.name) for x in dims[:3])
            fy = next((f for f in sv.default_filters if f["parameter"] == "p_FiscalYear"), None)
            where_sem = f" WHERE fiscal_year = {fy['default']}" if fy and any(x.name == "fiscal_year" for x in dims) else ""
            question = (f"What is the {(rep.description or title_words(rep.name)).lower()}"
                        + (f" by {dims_txt}" if dims_txt else "") + (f" for fiscal year {fy['default']}" if where_sem else "") + "?")
            sem = (f"SELECT * FROM SEMANTIC_VIEW(\n  {sv.id}\n  DIMENSIONS {', '.join(f'{x.alias}.{x.name}' for x in dims) or ''}\n"
                   f"  METRICS {', '.join(f'{x.alias}.{x.name}' for x in mets)}\n){where_sem}")
            if not dims:
                sem = sem.replace("  DIMENSIONS \n", "")
            # logical-table SQL (Cortex Analyst style: __<alias>)
            base = mets[0].alias
            joined, joins = {base}, []
            for x in dims + mets:
                if x.alias in joined:
                    continue
                path = join_path(d, alias_table[base], alias_table[x.alias])
                if path is None:
                    continue
                for frm, to, fc, tc in path:
                    ta, fa = aliases.get(to), aliases.get(frm)
                    if ta is None or fa is None or ta in joined:
                        continue
                    joins.append(f"JOIN __{ta} AS {ta} ON " + " AND ".join(f"{fa}.{p} = {ta}.{q}" for p, q in zip(fc, tc)))
                    joined.add(ta)
            sel = [f"{x.alias}.{x.expr} AS {x.name}" for x in dims] + [f"{x.expr} AS {x.name}" for x in mets]
            exprs = []
            for x in mets:
                e = x.expr
                for fct in sv.facts:
                    e = e.replace(f"{fct.alias}.{fct.name})", f"{fct.alias}.{fct.expr})").replace(f"{fct.alias}.{fct.name},", f"{fct.alias}.{fct.expr},")
                exprs.append(f"{e} AS {x.name}")
            sel = [f"{x.alias}.{x.expr} AS {x.name}" for x in dims] + exprs
            sql = (f"SELECT {', '.join(sel)}\nFROM __{base} AS {base}\n" + "".join(j + "\n" for j in joins)
                   + (f"WHERE dt.FISCAL_YEAR = {fy['default']}\n" if where_sem and "dt" in joined else "")
                   + (f"GROUP BY {', '.join(str(i + 1) for i in range(len(dims)))}" if dims else "")).strip()
            sv.verified_queries.append(VerifiedQuery(name=snake_lower(rep.name), question=question, sql=sql,
                                                     semantic_sql=sem, cluster=c.id, reports=c.members))

    # ------------------------------------------------------------ data products
    def build_products(self) -> None:
        g, d, cfg = self.g, self.d, self.cfg
        own, stw, cls, ret = owner(g, cfg), steward(g, cfg), classification(g), retention(g)
        lag = cfg["target"]["refresh_cadence_lag"].get(cfg["target"]["default_refresh_cadence"], "24 hours")
        sla = re.sub(r"(\d+)\s*hours?", r"\1h", lag)
        keys = sorted({r.package for r in g.reports.values()}) + ["ENTERPRISE"]
        for key in keys:
            code = domain_code(cfg, key) if key != "ENTERPRISE" else cfg["naming"]["domain_codes"].get("ENTERPRISE", "REFERENCE")
            p = ProductDesign(key=key, name=product_name(cfg, key) if key != "ENTERPRISE" else cfg["naming"]["product_names"].get("ENTERPRISE", "Enterprise Reference"),
                              slug="", domain_code=code, schema=f"DP_{code}", owner=own, steward=stw,
                              classification=cls, retention=ret, source_systems=[], freshness_sla=sla)
            p.slug = re.sub(r"[^a-z0-9]+", "-", p.name.lower()).strip("-")
            p.core_tables = sorted(t.id for t in d.tables.values() if t.domain == key)
            p.semantic_views = sorted(sv.id for sv in d.semantic_views.values() if sv.domain == key)
            systems = sorted({d.tables[t].source_system for t in p.core_tables if d.tables[t].source_system})
            p.source_systems = systems
            pk = g.packages.get(key)
            p.data_modules = list(pk.data_modules) if pk else []
            p.clusters = sum(1 for c in g.clusters.values() if c.package == key)
            p.reports = sum(1 for r in g.reports.values() if r.package == key)
            p.confidence = min([d.tables[t].confidence for t in p.core_tables] or [1.0])
            for svid in p.semantic_views:
                p.default_filters += [f for f in d.semantic_views[svid].default_filters if f not in p.default_filters]
            self._outputs(p)
            self._quality(p)
            d.products[key] = p

    def _outputs(self, p: ProductDesign) -> None:
        d = self.d
        used_names = set()
        if p.key == "ENTERPRISE":
            for tid in p.core_tables:
                t = d.tables[tid]
                cols = [c.name for c in t.columns if c.kind != "sk"]
                name = f"OUT_{t.name[4:]}"
                self._add_output(p, name, f"SELECT {', '.join(cols)}\nFROM {tid}", cols, [tid], t.confidence, t.stub,
                                 f"Conformed {t.entity} published once for all data products")
            return
        aggs = sorted((a for a in d.aggregates.values() if a.domain == p.key), key=lambda a: a.id)
        facts_with_out = set()
        for a in aggs:
            fstem = d.tables[a.fact_table].name[4:]
            time = next((tok for tok in ("DAY", "WEEK", "MONTH", "QUARTER", "YEAR") if f"_{tok}" in a.name), None)
            name = f"OUT_{fstem}_{TIME_ADJ.get(time, 'SUMMARY')}"
            i = 2
            while name in used_names:
                name = f"OUT_{fstem}_{TIME_ADJ.get(time, 'SUMMARY')}_{i}"
                i += 1
            used_names.add(name)
            cols = [g[2] for g in a.group_columns] + [m[0] for m in a.measures]
            self._add_output(p, name, f"SELECT {', '.join(cols)}\nFROM {a.id}", cols, [a.id], a.confidence, a.stub,
                             f"Contracted output over {a.id} ({a.coverage_pct}% of {a.fact} demand)")
            facts_with_out.add(a.fact_table)
        for tid in p.core_tables:
            t = d.tables[tid]
            if t.kind != "fact" or tid in facts_with_out:
                continue
            sel = [f"f.{c.name}" for c in t.columns if c.kind in ("key", "fk", "attribute", "measure", "derived")]
            joins, deps = [], [tid]
            for i, fk in enumerate(t.foreign_keys):
                dt_ = d.tables.get(fk.ref_table)
                if not dt_:
                    continue
                al = f"d{i + 1}"
                joins.append(f"LEFT JOIN {dt_.id} {al} ON " + " AND ".join(f"f.{a} = {al}.{b}" for a, b in zip(fk.columns, fk.ref_columns)))
                deps.append(dt_.id)
                for c in dt_.columns:
                    if c.kind in ("attribute", "derived") and c.ref in self.used and c.name not in [s.split(".")[-1].split(" AS ")[-1] for s in sel]:
                        sel.append(f"{al}.{c.name}")
            name = f"OUT_{t.name[4:]}"
            cols = [s.split(".")[-1] for s in sel]
            self._add_output(p, name, f"SELECT {', '.join(sel)}\nFROM {tid} f\n" + "\n".join(joins), cols, deps,
                             t.confidence, t.stub, f"Atomic contracted output for {t.entity}")

    def _add_output(self, p, name, sql, cols, deps, conf, stub, comment):
        oid = f"{p.schema}.{name}"
        self.d.outputs[oid] = OutputViewDesign(id=oid, schema=p.schema, name=name, sql=sql, product=p.key, comment=comment,
                                               columns=cols, depends_on=deps, confidence=conf, stub=stub)
        p.outputs.append(oid)

    def _quality(self, p: ProductDesign) -> None:
        g, d = self.g, self.d
        q = []
        for tid in p.core_tables:
            t = d.tables[tid]
            if t.primary_key:
                q.append({"rule": "not_null", "table": t.name, "columns": list(t.primary_key)})
                q.append({"rule": "unique", "table": t.name, "columns": list(t.primary_key)})
            for fk in t.foreign_keys:
                q.append({"rule": "referential", "table": t.name, "columns": fk.columns,
                          "references": f"{fk.ref_table.split('.')[1]}.{','.join(fk.ref_columns)}"})
            for c in t.columns:
                for prm in self.param_targets.get(c.ref, []):
                    pp = g.parameters.get(prm)
                    if pp and pp.pick_list:
                        vals = [i["value"] for i in pp.pick_list if i["value"] != "All"]
                        q.append({"rule": "accepted_values", "table": t.name, "columns": [c.name], "values": vals,
                                  "parameter": prm})
        q.append({"rule": "freshness", "max_lag": p.freshness_sla})
        p.quality = q
