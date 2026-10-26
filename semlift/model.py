"""Canonical, platform-neutral metadata graph (spec section 5).

Adapters write here, generators read only from here. Every record carries a
``Provenance`` so any generated object can be traced to the input line.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Optional


@dataclass
class Provenance:
    source_file: str
    locator: str = ""          # xpath or sheet!row
    parser_confidence: float = 1.0


@dataclass
class SourceSystem:
    name: str                  # e.g. CC_AND_B_PROD
    vendor: str                # Oracle / SAP HANA / OSIsoft PI / Salesforce
    database: str
    schema: str = ""
    refresh_cadence: str = "daily"
    raw_schema: str = ""       # landed schema on the platform (RAW_<SYSTEM>)
    connection: str = ""       # masked
    origin: str = "MAP"
    prov: Optional[Provenance] = None


@dataclass
class SourceColumn:
    name: str
    data_type: str = ""
    usage: str = ""
    regular_aggregate: str = ""
    sensitive: bool = False


@dataclass
class SourceObject:
    key: str                   # FM physical query subject name or catalog id
    system: str
    schema: str
    table: str
    columns: list[SourceColumn] = field(default_factory=list)
    row_count: Optional[int] = None
    origin: str = "FM"         # FM | CATALOG
    sql: str = ""
    prov: Optional[Provenance] = None

    def column(self, name: str) -> Optional[SourceColumn]:
        for c in self.columns:
            if c.name.upper() == name.upper():
                return c
        return None


@dataclass
class Package:
    name: str
    fm_project: str = ""
    data_modules: list[str] = field(default_factory=list)
    source_system: str = ""
    stated_reports: Optional[int] = None
    prov: Optional[Provenance] = None


@dataclass
class LogicalAttribute:
    entity: str
    name: str
    physical_column: str = ""      # column in source object
    source_object: str = ""        # SourceObject key
    data_type: str = "string"
    usage: str = "attribute"       # identifier | attribute
    sensitive: bool = False
    description: str = ""
    expression: str = ""           # Cognos expression (business layer)
    is_calculated: bool = False
    origin: str = "FM"             # FM | inferred
    confidence: float = 0.8
    packages: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)   # report data-item labels (synonyms)
    prov: Optional[Provenance] = None


@dataclass
class Measure:
    entity: str
    name: str
    physical_column: str = ""
    source_object: str = ""
    data_type: str = "decimal"
    expression: str = ""
    default_aggregation: str = "sum"   # sum | avg | max | min | count | ratio
    regular_aggregate: str = ""        # raw FM value
    additivity: str = "additive"       # additive | semi | non
    unit: str = ""
    format: str = ""
    is_calculated: bool = False
    is_ratio: bool = False
    ratio_parts: list[str] = field(default_factory=list)   # [numerator_col, denominator_col]
    sensitive: bool = False
    description: str = ""
    origin: str = "FM"
    confidence: float = 0.8
    rule: str = ""
    packages: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    prov: Optional[Provenance] = None


@dataclass
class LogicalEntity:
    name: str
    role: str = "dimension"            # fact | dimension | bridge | reference
    grain: list[str] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    origin: str = "FM"                 # FM | inferred
    confidence: float = 0.8
    packages: list[str] = field(default_factory=list)
    source_objects: list[str] = field(default_factory=list)
    description: str = ""
    domain: str = ""                   # owning package (or ENTERPRISE for conformed)
    conformed: bool = False
    tags: dict[str, str] = field(default_factory=dict)
    prov: Optional[Provenance] = None


@dataclass
class Relationship:
    name: str
    from_entity: str
    to_entity: str
    cardinality: str = "n:1"
    join_type: str = "inner"
    join_keys: list[tuple[str, str]] = field(default_factory=list)   # (from_attr_or_col, to_attr_or_col)
    role_name: str = ""
    origin: str = "FM"                 # FM | inferred
    confidence: float = 0.8
    expression: str = ""
    prov: Optional[Provenance] = None


@dataclass
class Hierarchy:
    name: str
    entity: str
    levels: list[str] = field(default_factory=list)
    origin: str = "pattern"


@dataclass
class Parameter:
    name: str
    data_type: str = "string"
    default: Any = None
    pick_list: list[dict] = field(default_factory=list)
    required: bool = False
    multi_select: bool = False
    validation: str = ""
    prompt_text: str = ""
    origin: str = "FM-PARAM"
    used_by_filters: int = 0
    prov: Optional[Provenance] = None


@dataclass
class SecurityRule:
    name: str
    type: str                          # row | column_grant | mask | abac | namespace
    target_entity: str = ""
    target_item: str = ""
    targets: list[dict] = field(default_factory=list)   # for abac
    predicate: str = ""
    roles_in: list[str] = field(default_factory=list)
    roles_exempt: list[str] = field(default_factory=list)
    roles_denied: list[str] = field(default_factory=list)
    masked_value: str = ""
    description: str = ""
    effect: str = ""
    origin: str = "FM-SEC"             # FM-SEC (file) | FM-MODEL (embedded)
    enabled: bool = True
    prov: Optional[Provenance] = None


@dataclass
class Report:
    name: str
    type: str = "L"                    # L list, C crosstab, X chart
    package: str = ""
    folder: str = ""                   # Active | Archive | Community
    path: str = ""
    dup_group: str = ""
    similarity: Optional[float] = None
    description: str = ""
    query_names: list[str] = field(default_factory=list)
    runs_per_day: Optional[float] = None
    last_run: Optional[str] = None     # ISO date
    avg_duration: Optional[float] = None
    column_count: Optional[int] = None
    usage_matched: bool = False
    disposition: str = ""              # Migrate | Merge | Retire | Defect
    canonical: str = ""                # canonical report of its cluster
    cluster: str = ""
    defects: list[str] = field(default_factory=list)
    prov: Optional[Provenance] = None


@dataclass
class ReportItem:
    report: str
    query: str
    name: str
    expression: str
    usage: str = ""
    aggregate: str = ""
    rollup_aggregate: str = ""
    ref_package: str = ""
    ref_subject: str = ""
    ref_item: str = ""
    resolved_entity: str = ""
    resolved_kind: str = ""            # attribute | measure | ""
    resolution: str = ""               # fm | inferred | unresolved
    duplicate_name: bool = False
    prov: Optional[Provenance] = None

    @property
    def ref(self) -> str:
        return f"{self.ref_subject}.{self.ref_item}" if self.ref_subject else ""


@dataclass
class ReportFilter:
    report: str
    query: str
    expression: str
    kind: str = "detail"               # detail | summary
    ref_subject: str = ""
    ref_item: str = ""
    operator: str = ""
    literal: Any = None
    parameter: str = ""
    defect: str = ""                   # "" | type_mismatch | malformed
    defect_reason: str = ""
    prov: Optional[Provenance] = None


@dataclass
class IntentCluster:
    id: str
    canonical: str
    members: list[str] = field(default_factory=list)
    package: str = ""
    items: list[str] = field(default_factory=list)          # union of resolved refs (Entity.Item)
    filters: list[str] = field(default_factory=list)
    grain_signature: dict[str, list[str]] = field(default_factory=dict)   # fact -> sorted dim refs
    facts: list[str] = field(default_factory=list)
    runs_per_day: float = 0.0
    weighted_demand: float = 0.0
    disposition: str = "Migrate"       # Migrate | Retire
    reason: str = ""


@dataclass
class TargetObject:
    id: str                            # e.g. CORE.FCT_BILLING
    layer: str                         # setup | ref | sec | core | agg | sem | dp | meta
    object_type: str                   # view | table | dynamic_table | semantic_view | row_access_policy ...
    schema: str
    name: str
    ddl: str = ""
    comment: str = ""
    owner: str = ""
    classification: str = ""
    domain: str = ""
    product: str = ""
    confidence: float = 1.0
    status: str = "proposed"           # proposed | stub | approved | rejected | deployed
    rule_ids: list[str] = field(default_factory=list)
    lineage: list[str] = field(default_factory=list)       # source evidence strings
    depends_on: list[str] = field(default_factory=list)
    order: int = 0
    cognos_source: str = ""            # side-by-side Cognos expressions for review
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Finding:
    id: str
    code: str
    title: str
    severity: str = "medium"           # high | medium | low | info
    object: str = ""
    evidence: str = ""
    owner: str = ""
    resolution: str = ""
    status: str = "open"               # open | accepted | resolved | wont_fix
    count: int = 1
    blocking: bool = False


@dataclass
class IngestFile:
    path: str
    adapter: str
    status: str = "parsed"             # parsed | rejected | skipped
    records: int = 0
    warnings: list[str] = field(default_factory=list)
    size: int = 0


class MetaGraph:
    """In-memory canonical graph. Lists are kept in deterministic insertion order."""

    def __init__(self) -> None:
        self.files: list[IngestFile] = []
        self.source_systems: dict[str, SourceSystem] = {}
        self.source_objects: dict[str, SourceObject] = {}
        self.packages: dict[str, Package] = {}
        self.entities: dict[str, LogicalEntity] = {}
        self.attributes: dict[str, LogicalAttribute] = {}   # key Entity.Name
        self.measures: dict[str, Measure] = {}              # key Entity.Name
        self.relationships: dict[str, Relationship] = {}
        self.hierarchies: dict[str, Hierarchy] = {}
        self.parameters: dict[str, Parameter] = {}
        self.security_rules: dict[str, SecurityRule] = {}
        self.reports: dict[str, Report] = {}
        self.report_items: list[ReportItem] = []
        self.report_filters: list[ReportFilter] = []
        self.clusters: dict[str, IntentCluster] = {}
        self.targets: dict[str, TargetObject] = {}
        self.findings: list[Finding] = []
        # Raw FM parse kept for drift checks and governance metadata
        self.fm_models: dict[str, dict] = {}
        self.governance: dict[str, Any] = {}
        self.stated_counts: dict[str, Any] = {}
        self.export_date: Optional[str] = None
        self.usage_rows: list[dict] = []
        self.catalog_loaded: bool = False
        self.analysis: dict[str, Any] = {}

    # ------------------------------------------------------------------ helpers
    def item(self, entity: str, name: str):
        key = f"{entity}.{name}"
        return self.attributes.get(key) or self.measures.get(key)

    def entity_items(self, entity: str) -> list:
        return [a for a in self.attributes.values() if a.entity == entity] + \
               [m for m in self.measures.values() if m.entity == entity]

    def add_finding(self, code: str, title: str, *, severity: str = "medium", obj: str = "",
                    evidence: str = "", owner: str = "", resolution: str = "", count: int = 1,
                    blocking: bool = False) -> Finding:
        fid = f"{code}-{len([f for f in self.findings if f.code == code]) + 1:04d}"
        f = Finding(id=fid, code=code, title=title, severity=severity, object=obj, evidence=evidence,
                    owner=owner, resolution=resolution, count=count, blocking=blocking)
        self.findings.append(f)
        return f

    def to_dict(self) -> dict:
        def conv(v):
            if is_dataclass(v):
                return {f.name: conv(getattr(v, f.name)) for f in fields(v)}
            if isinstance(v, dict):
                return {k: conv(x) for k, x in v.items()}
            if isinstance(v, (list, tuple)):
                return [conv(x) for x in v]
            return v
        return {k: conv(v) for k, v in self.__dict__.items()}


def as_dict(obj) -> dict:
    return asdict(obj)
