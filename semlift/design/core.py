"""CORE / REF layer design: conformed dimensions, facts, outriggers, stubs (spec 6.1, 6.3)."""
from __future__ import annotations

import re
from collections import Counter

from .. import expr as cx
from ..model import LogicalAttribute, Measure, MetaGraph
from ..util import snake_upper, title_words
from .model import ColumnDesign, Design, ForeignKey, JoinDesign, TableDesign
from .naming import constants_table, dim_name, fact_name

TYPE_MAP = {"string": "VARCHAR", "integer": "NUMBER(38,0)", "decimal": "NUMBER(18,4)", "date": "DATE",
            "datetime": "TIMESTAMP_NTZ", "boolean": "BOOLEAN", "number": "NUMBER(18,4)", "varchar": "VARCHAR",
            "float": "FLOAT", "timestamp": "TIMESTAMP_NTZ", "text": "VARCHAR"}


def sf_type(t: str) -> str:
    t = (t or "string").lower()
    if t in TYPE_MAP:
        return TYPE_MAP[t]
    return t.upper()


def classification(g: MetaGraph) -> str:
    gov = next(iter(g.governance.values()), {}) if g.governance else {}
    return (gov.get("classification") or "Internal").replace("–", "-").replace("—", "-")


def retention(g: MetaGraph) -> str:
    gov = next(iter(g.governance.values()), {}) if g.governance else {}
    r = gov.get("retention") or ""
    m = re.search(r"(\d+)\s*years?", r, re.I)
    reg = re.search(r"\b(FERC|SOX|NERC|GDPR)\b", r, re.I)
    if m:
        return f"{m.group(1)} years" + (f" ({reg.group(1).upper()})" if reg else "")
    return r


def owner(g: MetaGraph, cfg: dict) -> str:
    gov = next(iter(g.governance.values()), {}) if g.governance else {}
    return cfg["owners"]["default_owner"] or gov.get("owner") or "Data Platform Team"


def steward(g: MetaGraph, cfg: dict) -> str:
    gov = next(iter(g.governance.values()), {}) if g.governance else {}
    return cfg["owners"]["default_steward"] or gov.get("steward") or "data-stewards"


# --------------------------------------------------------------------------- routing
def route_entity(g: MetaGraph, cfg: dict, ent_name: str) -> tuple[str, str, str, bool]:
    """Return (source_system, raw_schema, table, todo) for an entity's primary landed source (rule SRC-01/02)."""
    e = g.entities[ent_name]
    report_pkgs = {r.package for r in g.reports.values()}
    if e.origin == "FM":
        so = g.source_objects.get(e.source_objects[0]) if e.source_objects else None
        table = so.table if so else snake_upper(e.name)
        if so and so.origin == "CATALOG":
            return so.system, so.schema, so.table, False
        if e.conformed:
            # SRC-02: conformed dimensions come from the FM model's own (enterprise) data source
            sysname = so.system if so else ""
        else:
            # SRC-01: domain entities are routed to the landed source of their package (MAP)
            pkg = next((p for p in e.packages if p in report_pkgs), "")
            p = g.packages.get(pkg)
            sysname = p.source_system if p and p.source_system else (so.system if so else "")
    else:
        if e.source_objects and e.source_objects[0] in g.source_objects:
            so = g.source_objects[e.source_objects[0]]
            return so.system, so.schema, so.table, False
        pkg = next((p for p in e.packages if p in report_pkgs), "")
        p = g.packages.get(pkg)
        sysname = p.source_system if p else ""
        table = snake_upper(e.name)
    ss = g.source_systems.get(sysname)
    raw = ss.raw_schema if ss else cfg["target"]["raw_schema_prefix"] + "UNKNOWN"
    return sysname, raw, table, e.origin != "FM"


def pkg_system(g: MetaGraph, pkg: str) -> tuple[str, str]:
    p = g.packages.get(pkg)
    ss = g.source_systems.get(p.source_system) if p else None
    return (ss.name, ss.raw_schema) if ss else ("", "")


# --------------------------------------------------------------------------- builder
class CoreBuilder:
    def __init__(self, g: MetaGraph, cfg: dict, d: Design):
        self.g, self.cfg, self.d = g, cfg, d
        self.cls = classification(g)
        self.ret = retention(g)
        self.own = owner(g, cfg)
        self.splits = g.analysis.get("splits", {})
        self.outriggers = g.analysis.get("outriggers", {})
        self.out_ref = {k: dim for dim, o in self.outriggers.items() for k in o["keys"] + o["attributes"]}
        self.used_refs = self._used_refs()
        self.constants: list[dict] = []

    def _used_refs(self) -> set[str]:
        used = set()
        for c in self.g.clusters.values():
            used.update(c.items)
        return used

    # ------------------------------------------------------------ helpers
    def table_tags(self, domain: str) -> dict[str, str]:
        return {"DOMAIN": domain, "DATA_OWNER": self.own, "DATA_CLASSIFICATION": self.cls, "RETENTION": self.ret}

    def comment_for(self, obj, entity: str) -> str:
        if getattr(obj, "description", ""):
            return obj.description
        kind = "Measure" if isinstance(obj, Measure) else ("Identifier" if getattr(obj, "usage", "") == "identifier" else "Attribute")
        origin = f"FM Business Layer.{entity}.{obj.name}" if obj.origin == "FM" else f"inferred from report usage ({', '.join(obj.packages)})"
        extra = ""
        if isinstance(obj, Measure):
            add = "additive" if obj.additivity == "additive" else f"{obj.additivity}-additive"
            extra = f"; default aggregation {obj.default_aggregation.upper()} ({add})"
        return f"{kind} '{title_words(obj.name)}'{extra}. Origin: {origin}"

    def phys_resolver(self, entity: str, alias: str = "src"):
        def res(node):
            if isinstance(node, cx.Ref):
                return f"{alias}.{node.parts[-1]}"
            if isinstance(node, cx.Name):
                if len(node.parts) == 2 and node.parts[0].startswith("ref_"):
                    return ".".join(node.parts)
                return f"{alias}.{node.parts[-1]}"
            raise cx.ParseError("unexpected")
        return res

    def item_column(self, obj, entity: str, raw: str, alias: str = "src") -> ColumnDesign | None:
        """Build the CORE column for an FM/inferred attribute or measure; None for ratio metrics."""
        g = self.g
        name = obj.physical_column if (obj.origin == "FM" and not obj.is_calculated and obj.physical_column) else snake_upper(obj.name)
        is_measure = isinstance(obj, Measure)
        col = ColumnDesign(name=name, expr="", data_type=sf_type(obj.data_type), comment=self.comment_for(obj, entity),
                           kind="measure" if is_measure else ("key" if obj.usage == "identifier" else "attribute"),
                           ref=f"{entity}.{obj.name}", sensitive=getattr(obj, "sensitive", False),
                           confidence=obj.confidence,
                           additivity=getattr(obj, "additivity", ""), default_aggregation=getattr(obj, "default_aggregation", ""),
                           rule=getattr(obj, "rule", ""))
        if obj.origin == "FM" and obj.is_calculated:
            if is_measure and obj.is_ratio:
                return None
            node, err = cx.try_parse(obj.expression)
            if node is None:
                col.expr, col.todo = f"NULL /* TODO: untranslatable Cognos expression: {obj.expression} */", True
                return col
            consts = cx.numeric_constants(node)
            if consts:
                node = self._externalize(node, obj, entity, consts)
            col.expr = cx.to_sql(node, self.phys_resolver(entity, alias))
            col.kind = "derived" if not is_measure else "measure"
            col.rule = (col.rule + ",CORE-04").strip(",")
            col.source_column = ", ".join(f"{raw}.{r.parts[-1]}" for r in cx.refs(node))
            return col
        if obj.physical_column:
            col.expr = f"{alias}.{obj.physical_column}"
            col.source_column = f"{raw}.{obj.physical_column}"
        else:
            col.expr = f"{alias}.{snake_upper(obj.name)}"
            col.source_column = f"{raw}.{snake_upper(obj.name)}"
            col.todo = True
        return col

    def _externalize(self, node, obj, entity: str, consts: list[float]):
        """F12: replace hard-coded factors with a governed, effective-dated reference value (CORE-05)."""
        g = self.g
        date_attr = next((a for a in sorted(g.attributes.values(), key=lambda a: a.name)
                          if a.entity == entity and a.data_type in ("date", "datetime") and a.physical_column), None)
        for i, val in enumerate(consts):
            code = f"{snake_upper(entity)}_{snake_upper(obj.name)}" + (f"_{i + 1}" if len(consts) > 1 else "")
            ref_alias = f"ref_{len(self.constants) + 1}"
            self.constants.append({
                "code": code, "value": val, "entity": entity, "item": obj.name, "alias": ref_alias,
                "description": getattr(obj, "description", "") or f"Constant used in {entity}.{obj.name}",
                "date_column": date_attr.physical_column if date_attr else "",
                "unit": "kg/kWh" if "kg" in (obj.description or obj.name).lower() else "",
            })

            def swap(n):
                if isinstance(n, cx.BinOp):
                    n.left, n.right = swap(n.left), swap(n.right)
                    return n
                if isinstance(n, cx.Literal) and n.kind == "number" and n.value == val:
                    return cx.Name([ref_alias, "FACTOR_VALUE"])
                return n
            node = swap(node)
        return node

    def new_table(self, tid: str, kind: str, entity: str, domain: str, source: str, system: str, origin: str,
                  confidence: float) -> TableDesign:
        schema, name = tid.split(".")
        t = TableDesign(id=tid, schema=schema, name=name, kind=kind, entity=entity, source=source, source_system=system,
                        domain=domain, tags=self.table_tags(domain), origin=origin, confidence=confidence,
                        stub=confidence < self.cfg["confidence"]["auto_approve_min"])
        self.d.tables[tid] = t
        self.d.entity_tables.setdefault(entity, []).append(tid)
        return t

    # ------------------------------------------------------------ build
    def build(self) -> None:
        g = self.g
        order = sorted(g.entities.values(), key=lambda e: (e.role != "dimension", e.name))
        for e in order:
            if e.name in self.splits:
                self.build_split(e)
            elif e.role == "dimension":
                self.build_entity(e, kind="dimension")
            else:
                self.build_entity(e, kind="fact")
        self.build_outriggers()
        self.add_foreign_keys()
        self.d.constants = self.constants
        if self.constants:
            self.d.ref_tables[constants_table(self.cfg)] = {"kind": "constants", "rows": self.constants}

    def _items(self, entity: str, include_unused: bool) -> tuple[list[LogicalAttribute], list[Measure]]:
        g = self.g
        attrs = sorted((a for a in g.attributes.values() if a.entity == entity), key=lambda a: (a.usage != "identifier", a.name))
        meas = sorted((m for m in g.measures.values() if m.entity == entity), key=lambda m: m.name)
        return attrs, meas

    def build_entity(self, e, kind: str) -> None:
        g, cfg = self.g, self.cfg
        system, raw, table, todo = route_entity(g, cfg, e.name)
        tid = f"CORE.{dim_name(cfg, e.name) if kind == 'dimension' else fact_name(cfg, e.name)}"
        t = self.new_table(tid, kind, e.name, e.domain, f"{raw}.{table}", system, e.origin, e.confidence)
        t.rule_ids = ["CORE-01" if kind == "dimension" else "CORE-02"]
        if e.conformed:
            t.rule_ids.append("CORE-06")
        if todo:
            t.rule_ids.append("CORE-03")
        src_desc = f"{system}.{table}" if system else f"{raw}.{table}"
        origin_txt = f"FM Business Layer.{e.name}" if e.origin == "FM" else f"inferred from {', '.join(e.packages)} report usage"
        attrs, meas = self._items(e.name, include_unused=True)
        if e.prov:
            t.evidence.append(f"{e.prov.source_file}:{e.prov.locator}")
        # keys
        pk_cols = []
        for a in attrs:
            if a.name in e.primary_key:
                c = self.item_column(a, e.name, f"{raw}.{table}")
                c.kind = "key"
                t.columns.append(c)
                pk_cols.append(c.name)
        if not pk_cols:
            key = snake_upper(e.name) + "_ID"
            t.columns.append(ColumnDesign(name=key, expr=f"src.{key}", data_type="VARCHAR", kind="key", todo=True,
                                          comment="Grain key - TODO: confirm against landed source",
                                          source_column=f"{raw}.{table}.{key}", confidence=0.3, rule="CORE-03"))
            pk_cols = [key]
        t.primary_key = pk_cols
        if kind == "dimension" and not any(c.name.endswith("_KEY") for c in t.columns if c.kind == "key"):
            sk = re.sub(r"^DIM_", "", t.name) + "_SK"
            t.columns.insert(0, ColumnDesign(name=sk, expr="HASH(" + ", ".join(f"src.{c.expr.split('.')[-1]}" for c in t.columns if c.kind == 'key') + ")",
                                             data_type="NUMBER(19,0)", kind="sk", comment="Surrogate key (hash of natural key)", rule="CORE-01"))
        # foreign keys (FM relationships + inferred)
        self._fk_columns(t, e.name, f"{raw}.{table}")
        # attributes & measures
        ext_joins: dict[str, None] = {}
        for obj in list(attrs) + list(meas):
            if obj.name in e.primary_key:
                continue
            ref = f"{e.name}.{obj.name}"
            if ref in self.out_ref:
                dim = self.out_ref[ref]
                if ref in [k for k in self.outriggers[dim]["keys"]]:
                    c = self.item_column(obj, e.name, f"{raw}.{table}")
                    c.kind = "fk"
                    c.rule = "DIM-03"
                    t.columns.append(c)
                continue  # grouped attributes live on the outrigger dimension
            if isinstance(obj, LogicalAttribute) and obj.usage == "identifier" and obj.origin == "FM" and not obj.is_calculated:
                if t.col(obj.physical_column):
                    continue
            if t.origin == "FM" and obj.origin == "inferred" and not obj.physical_column:
                # CORE-08: demanded by reports but absent from FM and catalog -> typed placeholder + finding
                pkg = next((p for p in obj.packages if p in {r.package for r in g.reports.values()}), "")
                psys, _ = pkg_system(g, pkg)
                c = ColumnDesign(name=snake_upper(obj.name), expr=f"CAST(NULL AS {sf_type(obj.data_type)})",
                                 data_type=sf_type(obj.data_type), kind="measure" if isinstance(obj, Measure) else "attribute",
                                 comment=f"{self.comment_for(obj, e.name)}. TODO: map from {psys or 'source'} ({pkg}); not in FM model or catalog",
                                 ref=ref, todo=True, confidence=obj.confidence, rule="CORE-08",
                                 additivity=getattr(obj, "additivity", ""), default_aggregation=getattr(obj, "default_aggregation", ""))
                t.columns.append(c)
                t.cognos_source.append(f"{ref} := (used by {pkg} reports; no FM definition)")
                ext_joins[psys] = None
                continue
            c = self.item_column(obj, e.name, f"{raw}.{table}")
            if c is None:
                continue
            t.columns.append(c)
            t.cognos_source.append(f"{ref} := {obj.expression or '(inferred from reports)'}")
        if ext_joins:
            t.confidence = min(t.confidence, self.cfg["confidence"]["inferred_matched"])
            t.rule_ids.append("CORE-08")
        for cst in self.constants:
            if cst["entity"] == e.name and not any(j.alias == cst["alias"] for j in t.joins):
                on = f"{cst['alias']}.FACTOR_CODE = '{cst['code']}'"
                if cst["date_column"]:
                    on += (f" AND src.{cst['date_column']} >= {cst['alias']}.EFFECTIVE_FROM"
                           f" AND src.{cst['date_column']} < COALESCE({cst['alias']}.EFFECTIVE_TO, '9999-12-31'::DATE)")
                else:
                    on += f" AND {cst['alias']}.EFFECTIVE_TO IS NULL"
                t.joins.append(JoinDesign(alias=cst["alias"], table=constants_table(self.cfg), on=on,
                                          comment="F12: externalized constant"))
        t.grain = list(e.grain)
        t.comment = (f"{'Dimension' if kind == 'dimension' else 'Fact'} at {e.name} grain. Source: {src_desc}. Origin: {origin_txt}"
                     + (" (conformed across " + ", ".join(sorted(p for p in e.packages if p in {r.package for r in g.reports.values()})) + ")" if e.conformed else ""))
        t.alias = re.sub(r"^(DIM|FCT)_", "", t.name).lower()
        self._register(t)

    def _fk_columns(self, t: TableDesign, entity: str, raw: str) -> None:
        g = self.g
        for r in sorted(g.relationships.values(), key=lambda r: r.name):
            if r.from_entity != entity:
                continue
            for fk_src, pk_dst in r.join_keys:
                out = pk_dst if not t.col(pk_dst) else fk_src
                if t.col(out):
                    continue
                if r.role_name.startswith("derived:"):
                    attr = g.attributes.get(f"{entity}.{r.role_name.split(':', 1)[1]}")
                    pc = attr.physical_column if attr else "TODO_DATE"
                    expr = f"TO_NUMBER(TO_CHAR({'src.' + pc}, 'YYYYMMDD'))"
                    t.columns.append(ColumnDesign(name=out, expr=expr, data_type="NUMBER(38,0)", kind="fk",
                                                  comment=f"Date key derived from {pc} (assumes YYYYMMDD DATE_KEY) - rule REL-INF-02",
                                                  source_column=f"{raw}.{pc}", confidence=r.confidence, rule="REL-INF-02"))
                    continue
                todo = r.origin != "FM"
                t.columns.append(ColumnDesign(
                    name=out, expr=f"src.{fk_src}", data_type="VARCHAR" if not out.endswith("_KEY") else "NUMBER(38,0)",
                    kind="fk", comment=f"Foreign key to {r.to_entity} ({r.name}{', inferred from co-usage' if todo else ''})",
                    source_column=f"{raw}.{fk_src}", todo=todo, confidence=r.confidence,
                    rule="CORE-07" if not todo else "REL-INF-01"))
        if t.kind == "fact" and not any(c.kind == "fk" for c in t.columns):
            t.rule_ids.append("WARN-NO-FK")

    def build_split(self, e) -> None:
        """DIM-02: inferred master with dynamic measures -> DIM_<E> (descriptive + static) + FCT_<process>."""
        g, cfg = self.g, self.cfg
        sp = self.splits[e.name]
        system, raw, table, todo = route_entity(g, cfg, e.name)
        attrs, meas = self._items(e.name, include_unused=True)
        key = snake_upper(e.name) + "_ID"
        dim_id = f"CORE.DIM_{sp['dimension']}"
        dt_ = self.new_table(dim_id, "dimension", e.name, e.domain, f"{raw}.{table}", system, e.origin, e.confidence)
        dt_.rule_ids = ["DIM-02", "CORE-03"]
        dt_.distinct = True
        dt_.columns.append(ColumnDesign(name=key, expr=f"src.{key}", data_type="VARCHAR", kind="key", todo=True,
                                        comment=f"{e.name} natural key - TODO: confirm", confidence=0.3, rule="DIM-02",
                                        source_column=f"{raw}.{table}.{key}"))
        dt_.primary_key = [key]
        fct_id = f"CORE.FCT_{sp['fact']}"
        ft = self.new_table(fct_id, "fact", e.name, e.domain, f"{raw}.{table}", system, e.origin, e.confidence)
        ft.rule_ids = ["DIM-02", "CORE-02", "CORE-03"]
        reading = snake_upper(sp["fact"]) + "_ID"
        ft.columns.append(ColumnDesign(name=reading, expr=f"src.{reading}", data_type="VARCHAR", kind="key", todo=True,
                                       comment="Degenerate grain key - TODO: confirm", confidence=0.3, rule="CORE-03"))
        ft.primary_key = [reading]
        ft.columns.append(ColumnDesign(name=key, expr=f"src.{key}", data_type="VARCHAR", kind="fk", todo=True,
                                       comment=f"Foreign key to {dim_id}", confidence=0.3, rule="DIM-02",
                                       source_column=f"{raw}.{table}.{key}"))
        self._fk_columns(ft, e.name, f"{raw}.{table}")
        static = set(sp["static_measures"])
        for a in attrs:
            c = self.item_column(a, e.name, f"{raw}.{table}")
            if c and not dt_.col(c.name):
                dt_.columns.append(c)
                dt_.cognos_source.append(f"{e.name}.{a.name} := (inferred from reports)")
        for m in meas:
            c = self.item_column(m, e.name, f"{raw}.{table}")
            if c is None:
                continue
            target = dt_ if m.name in static else ft
            if m.name in static:
                c.kind = "attribute"
                c.comment += " (static attribute of the master record)"
            target.columns.append(c)
            target.cognos_source.append(f"{e.name}.{m.name} := (inferred from reports)")
        dt_.comment = f"Dimension for {e.name} (split from report usage, rule DIM-02). Source: {raw}.{table} (TODO confirm)"
        ft.comment = f"Fact {sp['fact']} for {e.name} measurements (rule DIM-02). Source: {raw}.{table} (TODO confirm)"
        ft.foreign_keys.append(ForeignKey([key], dim_id, [key], f"{e.name}_fact_to_dim", 0.3))
        dt_.alias, ft.alias = sp["dimension"].lower(), sp["fact"].lower()
        self._register(dt_)
        self._register(ft)

    def build_outriggers(self) -> None:
        """DIM-03: reference attributes on facts become derived outrigger dimensions."""
        g, cfg = self.g, self.cfg
        for dim, o in self.outriggers.items():
            tid = f"CORE.DIM_{dim}"
            first = o["keys"][0]
            ent, item = first.split(".", 1)
            src_tid = next((t for t in self.d.entity_tables.get(ent, []) if self.d.tables[t].kind == "fact"), None)
            e = g.entities[ent]
            system, raw, table, todo = route_entity(g, cfg, ent)
            conf = min(e.confidence, self.cfg["confidence"]["inferred_matched"])
            t = self.new_table(tid, "dimension", f"{dim}", e.domain if len({g.entities[k.split('.')[0]].domain for k in o['keys']}) == 1 else "ENTERPRISE",
                               f"{raw}.{table}", system, e.origin, conf)
            t.rule_ids = ["DIM-03"]
            t.distinct = True
            key = snake_upper(item)
            a = g.attributes[first]
            t.columns.append(ColumnDesign(name=key, expr=f"src.{a.physical_column or key}", data_type=sf_type(a.data_type),
                                          kind="key", comment=f"Reference key from {first}", ref=first, rule="DIM-03",
                                          source_column=f"{raw}.{table}.{a.physical_column or key}"))
            t.primary_key = [key]
            for ref in (o["attributes"] if len(o["keys"]) == 1 else []):
                aa = g.attributes[ref]
                if e.origin == "FM" and aa.origin == "inferred" and not aa.physical_column:
                    t.columns.append(ColumnDesign(name=snake_upper(aa.name), expr=f"CAST(NULL AS {sf_type(aa.data_type)})",
                                                  data_type=sf_type(aa.data_type), ref=ref, todo=True, confidence=aa.confidence,
                                                  comment=f"{self.comment_for(aa, aa.entity)}. TODO: not in FM model or catalog",
                                                  rule="CORE-08"))
                    continue
                c = self.item_column(aa, aa.entity, f"{raw}.{table}")
                if c:
                    t.columns.append(c)
            if len(o["keys"]) > 1:
                t.comment = (f"Reference dimension {dim} derived from {', '.join(o['keys'])}; union of distinct values "
                             f"until a master table is mapped (rule DIM-03)")
                for k in o["keys"]:
                    ke, ki = k.split(".", 1)
                    _s, kraw, ktable, _t = route_entity(g, cfg, ke)
                    ka = g.attributes[k]
                    t.union_sources.append(f"{kraw}.{ktable}|{ka.physical_column or snake_upper(ki)}")
            else:
                t.comment = f"Reference dimension {dim} derived from distinct {first} values until a master table is mapped (rule DIM-03)"
            t.alias = dim.lower()
            t.evidence.append(f"outrigger from {', '.join(o['keys'])}")
            self._register(t)
            for k in o["keys"]:
                fe, fi = k.split(".", 1)
                for ftid in self.d.entity_tables.get(fe, []):
                    ft = self.d.tables[ftid]
                    c = ft.col(snake_upper(fi))
                    if c is not None and ft.id != tid:
                        ft.foreign_keys.append(ForeignKey([c.name], tid, [key], f"{fe}_{fi}_to_{dim}", 0.6))

    def add_foreign_keys(self) -> None:
        g = self.g
        for r in sorted(g.relationships.values(), key=lambda r: r.name):
            src_tables = [self.d.tables[t] for t in self.d.entity_tables.get(r.from_entity, [])]
            src = next((t for t in src_tables if t.kind == "fact"), src_tables[0] if src_tables else None)
            dst_tables = [self.d.tables[t] for t in self.d.entity_tables.get(r.to_entity, [])]
            dst = next((t for t in dst_tables if t.kind == "dimension"), dst_tables[0] if dst_tables else None)
            if not src or not dst:
                continue
            for fk_src, pk_dst in r.join_keys:
                col = src.col(pk_dst) or src.col(fk_src)
                if col is None or not dst.primary_key:
                    continue
                if not any(fk.ref_table == dst.id and fk.columns == [col.name] for fk in src.foreign_keys):
                    src.foreign_keys.append(ForeignKey([col.name], dst.id, list(dst.primary_key), r.name, r.confidence))

    def _register(self, t: TableDesign) -> None:
        for c in t.columns:
            if c.ref and c.ref not in self.d.ref_to_column:
                self.d.ref_to_column[c.ref] = (t.id, c.name)
            if c.todo and t.origin != "FM":
                t.confidence = min(t.confidence, max(c.confidence, 0.3))
        t.stub = t.confidence < self.cfg["confidence"]["auto_approve_min"]
