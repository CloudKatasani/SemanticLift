"""SEC layer design: row access policies, masking policies, ABAC, grants (spec 6.1 security rows)."""
from __future__ import annotations

from collections import defaultdict

from .. import expr as cx
from ..model import MetaGraph, SecurityRule
from ..util import snake_upper, sql_str
from .core import route_entity
from .model import Design, PolicyDesign
from .naming import policy_name, role_name

ROLE_ALIASES = {"ALL_AUTHENTICATED_USERS": "PUBLIC"}


def sf_role(cfg: dict, r: str) -> str:
    n = role_name(cfg, r)
    return ROLE_ALIASES.get(n, n)


def any_role(cfg: dict, roles: list[str]) -> str:
    return " OR ".join(f"IS_ROLE_IN_SESSION({sql_str(sf_role(cfg, r))})" for r in sorted(set(roles)))


def base_type(sf: str) -> str:
    sf = sf.upper()
    if sf.startswith(("NUMBER", "FLOAT", "INT", "DECIMAL")):
        return "NUMBER"
    if sf.startswith(("DATE", "TIMESTAMP")):
        return sf.split("(")[0]
    if sf == "BOOLEAN":
        return "BOOLEAN"
    return "STRING"


class SecurityBuilder:
    def __init__(self, g: MetaGraph, cfg: dict, d: Design):
        self.g, self.cfg, self.d = g, cfg, d
        self.tag_schema = cfg["target"]["tag_schema"]
        self.unmapped: list[dict] = []
        self.maps: dict[str, dict] = {}
        self.issues: list[dict] = []

    # ------------------------------------------------------------ helpers
    def entity_table(self, ent: str):
        ids = self.d.entity_tables.get(ent, [])
        if not ids:
            return None
        dims = [self.d.tables[i] for i in ids if self.d.tables[i].kind == "dimension"]
        facts = [self.d.tables[i] for i in ids if self.d.tables[i].kind == "fact"]
        return (dims or facts)[0]

    def column_for(self, ent: str, item: str):
        tid_col = self.d.ref_to_column.get(f"{ent}.{item}")
        if tid_col:
            t = self.d.tables[tid_col[0]]
            return t, t.col(tid_col[1])
        return None, None

    def mapping_table(self, rule: SecurityRule, sq: cx.SubQuery) -> tuple[str, str]:
        """Subselect on a USER_*_ACCESS table -> SEC.MAP_USER_<scope> view (returns name, value column)."""
        tbl = sq.table[-1].upper()
        col = sq.select[0].split(".")[-1].upper()
        name = self.cfg["naming"]["mapping_table_names"].get(rule.name)
        if not name:
            stem = tbl.replace("USER_", "").replace("_ACCESS", "")
            name = f"MAP_USER_{stem}"
        src_db = sq.table[0].upper() if len(sq.table) > 1 else ""
        ss = self.g.source_systems.get(src_db)
        raw = ss.raw_schema if ss else self.cfg["target"]["raw_schema_prefix"] + (src_db or "SECURITY")
        known = any(tbl == t[1] for ds in self.g.analysis.get("datasources", []) for t in ds["tables"])
        m = self.maps.setdefault(name, {"name": name, "columns": set(), "source": f"{raw}.{tbl}", "known": known,
                                        "rules": []})
        m["columns"].add(col)
        m["rules"].append(rule.name)
        return f"SEC.{name}", col

    # ------------------------------------------------------------ row access
    def build_rap(self, rule: SecurityRule) -> None:
        cfg = self.cfg
        t = self.entity_table(rule.target_entity)
        pname = policy_name(cfg, rule.name, "RAP")
        if t is None:
            self.unmapped.append({"rule": rule.name, "reason": f"target {rule.target_entity} has no CORE object"})
            return
        node, err = cx.try_parse(rule.predicate)
        if node is None:
            self.unmapped.append({"rule": rule.name, "reason": f"predicate not parseable: {err}"})
            return
        args: dict[str, tuple[str, str]] = {}      # column -> (arg, type)

        def arg_for(col_name: str) -> str:
            c = t.col(col_name)
            typ = base_type(c.data_type) if c else "STRING"
            a = "p_" + col_name.lower()
            args.setdefault(col_name, (a, typ))
            return a

        def owner_of(ref: cx.Ref) -> str:
            return ref.parts[-2] if len(ref.parts) >= 2 else rule.target_entity

        def column_of(ent: str, item: str) -> str:
            tc = self.column_for(ent, item)
            if tc[1] is not None:
                return tc[1].name
            return snake_upper(item)

        def sub_sql(sq: cx.SubQuery) -> str:
            mt, col = self.mapping_table(rule, sq)
            return f"SELECT m.{col} FROM {mt} m WHERE m.USERNAME = CURRENT_USER()"

        def local(n) -> str:
            def res(x):
                if isinstance(x, cx.Ref):
                    return arg_for(column_of(rule.target_entity, x.parts[-1]))
                return ".".join(x.parts)
            return trans(n, res)

        def trans(n, res) -> str:
            if isinstance(n, cx.InList) and n.subquery is not None:
                return f"{cx.to_sql(n.expr, res)} {'NOT ' if n.negated else ''}IN ({sub_sql(n.subquery)})"
            if isinstance(n, cx.BinOp) and n.op in ("and", "or"):
                return f"({trans(n.left, res)} {n.op.upper()} {trans(n.right, res)})"
            return cx.to_sql(n, res)

        def cross(n, other: str) -> str:
            rel = next((r for r in sorted(self.g.relationships.values(), key=lambda r: r.name)
                        if r.from_entity == rule.target_entity and r.to_entity == other), None)
            if rel is None:
                raise ValueError(f"no relationship from {rule.target_entity} to {other}")
            fk_col = rel.join_keys[0][1] if t.col(rel.join_keys[0][1]) else rel.join_keys[0][0]
            _sys, raw, table, _todo = route_entity(self.g, cfg, other)
            key = rel.join_keys[0][1]

            def res(x):
                if isinstance(x, cx.Ref):
                    tc = self.column_for(other, x.parts[-1])
                    src_col = tc[1].expr.split(".")[-1] if tc[1] is not None else snake_upper(x.parts[-1])
                    return f"x.{src_col}"
                return ".".join(x.parts)
            return (f"EXISTS (SELECT 1 FROM {raw}.{table} x WHERE x.{key} = {arg_for(fk_col)} "
                    f"AND {trans(n, res)})")

        def walk(n) -> str:
            if isinstance(n, cx.BinOp) and n.op in ("and", "or"):
                return f"({walk(n.left)} {n.op.upper()} {walk(n.right)})"
            owners = {owner_of(r) for r in cx.refs(n)}
            others = owners - {rule.target_entity}
            if not others:
                return local(n)
            if len(others) == 1:
                return cross(n, others.pop())
            raise ValueError("predicate spans several entities")

        try:
            pred = walk(node)
        except ValueError as e:
            self.unmapped.append({"rule": rule.name, "reason": str(e)})
            return
        parts = []
        if rule.roles_exempt:
            parts.append(any_role(cfg, rule.roles_exempt))
        if not cfg["security"]["rls_default_deny"] and rule.roles_in:
            parts.append(f"NOT ({any_role(cfg, rule.roles_in)})")
        parts.append(pred)
        body = "\n    OR ".join(parts)
        sig = [args[c] for c in sorted(args, key=lambda c: args[c][0])]
        cols = [c for c in sorted(args, key=lambda c: args[c][0])]
        pid = f"SEC.{pname}"
        self.d.policies[pid] = PolicyDesign(
            id=pid, name=pname, kind="row_access", signature=sig, returns="BOOLEAN", body=body,
            cognos_rule=rule.name, cognos_source=rule.predicate,
            attachments=[{"table": t.id, "columns": cols}], confidence=min(t.confidence, 0.8 if len(args) > 1 else 1.0),
            comment=(f"From Cognos securityFilter {rule.name} on {rule.target_entity}; applies to "
                     f"{', '.join(rule.roles_in) or 'all'}; exempt {', '.join(rule.roles_exempt) or 'none'}"),
            depends_on=sorted(f"SEC.{m}" for m in self.maps if rule.name in self.maps[m]["rules"]))
        t.row_access_policy = (pid, cols)

    # ------------------------------------------------------------ ABAC
    def abac_conditions(self) -> dict[str, str]:
        out = {}
        for rule in sorted((r for r in self.g.security_rules.values() if r.type == "abac"), key=lambda r: r.name):
            node, err = cx.try_parse(rule.predicate)
            if node is None:
                self.unmapped.append({"rule": rule.name, "reason": f"condition not parseable: {err}"})
                continue

            def res(x):
                if isinstance(x, cx.Name) and len(x.parts) == 2 and x.parts[0].lower() == "user":
                    return (f"COALESCE((SELECT MAX(a.ATTRIBUTE_VALUE) FROM SEC.MAP_USER_ATTRIBUTE a "
                            f"WHERE a.USERNAME = CURRENT_USER() AND a.ATTRIBUTE_NAME = {sql_str(x.parts[1])}), '')")
                return ".".join(x.parts)

            def tr(n):
                if isinstance(n, cx.InList) and isinstance(n.expr, cx.Name) and n.expr.parts[-1].lower() == "role":
                    roles = [i.value for i in n.items if isinstance(i, cx.Literal)]
                    s = f"({any_role(self.cfg, roles)})"
                    return f"NOT {s}" if n.negated else s
                if isinstance(n, cx.BinOp) and n.op in ("and", "or"):
                    return f"({tr(n.left)} {n.op.upper()} {tr(n.right)})"
                return cx.to_sql(n, res)
            cond = tr(node)
            if rule.effect.lower() != "deny":
                cond = f"NOT ({cond})"
            out[rule.name] = cond
            self.d.sec_tables["SEC.MAP_USER_ATTRIBUTE"] = {"kind": "user_attribute"}
        return out

    # ------------------------------------------------------------ masking & grants
    def build_masks(self) -> None:
        g, cfg, d = self.g, self.cfg, self.d
        abac = self.abac_conditions()
        abac_targets: dict[tuple[str, str], str] = {}
        for rule in sorted((r for r in g.security_rules.values() if r.type == "abac"), key=lambda r: r.name):
            for tg in rule.targets:
                key = (tg["entity"], tg["item"])
                # a column carries one ABAC_POLICY tag value: several policies are comma-joined
                abac_targets[key] = ",".join(sorted(set(filter(None, abac_targets.get(key, "").split(","))) | {snake_upper(rule.name)}))
        tag_abac = f"{self.tag_schema}.ABAC_POLICY"
        tag_group = f"{self.tag_schema}.ACCESS_GROUP"

        def abac_clauses(masked: str) -> list[str]:
            tag = f"SYSTEM$GET_TAG_ON_CURRENT_COLUMN({sql_str(tag_abac)})"
            return [f"WHEN CONTAINS(',' || COALESCE({tag}, '') || ',', {sql_str(',' + snake_upper(n) + ',')}) AND {c} THEN {masked}"
                    for n, c in sorted(abac.items())]

        grants = [r for r in g.security_rules.values() if r.type == "column_grant"]
        masks = [r for r in g.security_rules.values() if r.type == "mask"]
        dedicated = {(m.target_entity, m.target_item) for m in masks}
        grant_rows = []
        attached: dict[str, list[dict]] = defaultdict(list)

        for m in sorted(masks, key=lambda r: r.name):
            t, c = self.column_for(m.target_entity, m.target_item)
            pname = policy_name(cfg, m.name, "MP")
            typ = base_type(c.data_type) if c is not None else "STRING"
            masked = sql_str(m.masked_value) if typ == "STRING" and m.masked_value else "NULL"
            allowed = list(m.roles_in)
            for gr in grants:      # merge a column grant on the same item into the dedicated mask
                if (gr.target_entity, gr.target_item) == (m.target_entity, m.target_item):
                    allowed += gr.roles_in
            lines = ["CASE"] + abac_clauses(masked)
            if m.roles_denied:
                lines.append(f"WHEN {any_role(cfg, m.roles_denied)} THEN {masked}")
            lines.append(f"WHEN {any_role(cfg, allowed)} THEN v" if allowed else "WHEN FALSE THEN v")
            lines += [f"ELSE {masked}", "END"]
            pid = f"SEC.{pname}"
            p = PolicyDesign(id=pid, name=pname, kind="masking", signature=[("v", typ)], returns=typ,
                             body="\n    ".join(lines), cognos_rule=m.name,
                             cognos_source=f"{m.target_entity}.{m.target_item}: allowed {m.roles_in}; masked {m.roles_denied} -> {m.masked_value}",
                             comment=m.description or f"From Cognos masking rule {m.name}",
                             depends_on=[])
            if typ == "NUMBER" and m.masked_value and not m.masked_value.replace(".", "").isdigit():
                p.comment += f". Cognos masked value '{m.masked_value}' cannot be returned for a NUMBER column; NULL is returned"
            d.policies[pid] = p
            if c is not None:
                c.masking_policy = pid
                c.sensitive = True
                c.tags["SENSITIVE"] = "true"
                c.tags["DATA_CLASSIFICATION"] = "Restricted"
                if (m.target_entity, m.target_item) in abac_targets:
                    c.tags["ABAC_POLICY"] = abac_targets[(m.target_entity, m.target_item)]
                p.attachments.append({"table": t.id, "columns": [c.name]})
                p.confidence = 1.0 if not t.stub else t.confidence
            else:
                self.issues.append({"rule": m.name, "issue": f"target {m.target_entity}.{m.target_item} not in design; policy created, attachment pending"})

        # Column grants + ABAC targets without a dedicated mask -> MP_RESTRICTED_AMOUNT / _TEXT
        generic: dict[str, PolicyDesign] = {}

        def generic_policy(typ: str) -> PolicyDesign:
            pname = "MP_RESTRICTED_AMOUNT" if typ == "NUMBER" else f"MP_RESTRICTED_{typ if typ != 'STRING' else 'TEXT'}"
            if pname in generic:
                return generic[pname]
            masked = sql_str("*** Restricted ***") if typ == "STRING" else "NULL"
            grp = f"SYSTEM$GET_TAG_ON_CURRENT_COLUMN({sql_str(tag_group)})"
            lines = ["CASE"] + abac_clauses(masked) + [
                f"WHEN {grp} IS NULL THEN v",
                f"WHEN EXISTS (SELECT 1 FROM SEC.MAP_ROLE_GRANT g WHERE g.ACCESS_GROUP = {grp} AND g.GRANT_TYPE = 'DENY' AND IS_ROLE_IN_SESSION(g.ROLE_NAME)) THEN {masked}",
                f"WHEN EXISTS (SELECT 1 FROM SEC.MAP_ROLE_GRANT g WHERE g.ACCESS_GROUP = {grp} AND g.GRANT_TYPE = 'ALLOW' AND IS_ROLE_IN_SESSION(g.ROLE_NAME)) THEN v",
                f"ELSE {masked}", "END"]
            p = PolicyDesign(id=f"SEC.{pname}", name=pname, kind="masking", signature=[("v", typ)], returns=typ,
                             body="\n    ".join(lines), cognos_rule="objectLevelSecurity / ABAC",
                             comment="Column grants (SEC.MAP_ROLE_GRANT keyed by ACCESS_GROUP tag) and ABAC deny rules (ABAC_POLICY tag)",
                             depends_on=["SEC.MAP_ROLE_GRANT"])
            generic[pname] = p
            d.policies[p.id] = p
            return p

        for gr in sorted(grants, key=lambda r: r.name):
            key = (gr.target_entity, gr.target_item)
            group = snake_upper(gr.name)
            for r in gr.roles_in:
                grant_rows.append((group, sf_role(cfg, r), "ALLOW", gr.name))
            for r in gr.roles_denied:
                grant_rows.append((group, sf_role(cfg, r), "DENY", gr.name))
            if key in dedicated:
                continue
            t, c = self.column_for(*key)
            if c is None:
                self.issues.append({"rule": gr.name, "issue": f"target {key[0]}.{key[1]} not in design; grant recorded, attachment pending"})
                continue
            p = generic_policy(base_type(c.data_type))
            c.masking_policy = p.id
            c.sensitive = True
            c.tags.update({"ACCESS_GROUP": group, "SENSITIVE": "true", "DATA_CLASSIFICATION": "Restricted"})
            attached[p.id].append({"table": t.id, "columns": [c.name]})
        for key, pol in sorted(abac_targets.items()):
            if key in dedicated:
                continue
            t, c = self.column_for(*key)
            if c is None:
                self.issues.append({"rule": pol, "issue": f"ABAC target {key[0]}.{key[1]} not in design; attachment pending"})
                continue
            c.tags["ABAC_POLICY"] = pol
            c.tags.setdefault("SENSITIVE", "true")
            c.tags.setdefault("DATA_CLASSIFICATION", "Restricted")
            if not c.masking_policy:
                p = generic_policy(base_type(c.data_type))
                c.masking_policy = p.id
                attached[p.id].append({"table": t.id, "columns": [c.name]})
        for pid, att in attached.items():
            d.policies[pid].attachments.extend(att)
            live = [d.tables[a["table"]].confidence for a in att if not d.tables[a["table"]].stub]
            d.policies[pid].confidence = 1.0 if live else min(d.tables[a["table"]].confidence for a in att)
        d.sec_tables["SEC.MAP_ROLE_GRANT"] = {"kind": "role_grant", "rows": sorted(set(grant_rows))}

    def build_grants(self) -> None:
        cfg = self.cfg
        rows = []
        for rule in sorted((r for r in self.g.security_rules.values() if r.type == "namespace"), key=lambda r: r.name):
            ns = self.g.fm_models and next(iter(self.g.fm_models.values()))["namespaces"].get(rule.name)
            kind = ns["type"] if ns else ("presentation" if rule.name in self.g.packages else "unknown")
            schemas = {"physical": sorted({ss.raw_schema for ss in self.g.source_systems.values()}),
                       "business": ["CORE", "REF", "AGG"], "presentation": ["SEM"]}.get(kind, [])
            if kind == "presentation":
                schemas = schemas + sorted({p.schema for p in self.d.products.values()})
            if not schemas:
                self.unmapped.append({"rule": rule.name, "reason": f"namespace type {kind} not mapped"})
                continue
            rows.append({"rule": rule.name, "kind": kind, "schemas": schemas,
                         "allow": [sf_role(cfg, r) for r in rule.roles_in],
                         "deny": [sf_role(cfg, r) for r in rule.roles_denied]})
        self.d.sec_tables["SEC.GRANTS"] = {"kind": "grants", "rows": rows}

    def build(self) -> None:
        for rule in sorted((r for r in self.g.security_rules.values() if r.type == "row"), key=lambda r: r.name):
            if rule.enabled:
                self.build_rap(rule)
        self.build_masks()
        for name, m in sorted(self.maps.items()):
            self.d.sec_tables[f"SEC.{name}"] = {"kind": "user_map", "columns": sorted(m["columns"]),
                                               "source": m["source"], "known": m["known"], "rules": m["rules"]}
        self.d.issues.extend({"layer": "sec", **i} for i in self.issues)
        self.d.issues.extend({"layer": "sec", "unmapped": True, **u} for u in self.unmapped)
