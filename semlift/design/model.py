"""Platform-neutral physical design produced by the design engine and read by every generator."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ColumnDesign:
    name: str
    expr: str                       # SQL expression over source alias(es)
    data_type: str = "VARCHAR"      # platform-neutral upper-case type
    comment: str = ""
    kind: str = "attribute"         # sk | key | fk | attribute | measure | derived
    ref: str = ""                   # canonical Entity.Item
    source_column: str = ""         # RAW_SCHEMA.TABLE.COLUMN
    sensitive: bool = False
    todo: bool = False
    tags: dict[str, str] = field(default_factory=dict)
    masking_policy: str = ""
    additivity: str = ""
    default_aggregation: str = ""
    confidence: float = 1.0
    rule: str = ""


@dataclass
class JoinDesign:
    alias: str
    table: str                      # RAW_SCHEMA.TABLE or REF.X
    on: str
    kind: str = "LEFT JOIN"
    todo: bool = False
    comment: str = ""


@dataclass
class ForeignKey:
    columns: list[str]
    ref_table: str                  # table id CORE.DIM_X
    ref_columns: list[str]
    relationship: str = ""
    confidence: float = 1.0


@dataclass
class TableDesign:
    id: str                         # CORE.FCT_BILLING
    schema: str
    name: str
    kind: str                       # fact | dimension | reference | mapping
    entity: str = ""
    source: str = ""                # RAW_SCHEMA.TABLE
    source_alias: str = "src"
    source_system: str = ""
    joins: list[JoinDesign] = field(default_factory=list)
    columns: list[ColumnDesign] = field(default_factory=list)
    primary_key: list[str] = field(default_factory=list)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    distinct: bool = False
    domain: str = ""                # owning package (or ENTERPRISE)
    comment: str = ""
    tags: dict[str, str] = field(default_factory=dict)
    row_access_policy: Optional[tuple[str, list[str]]] = None
    confidence: float = 1.0
    stub: bool = False
    origin: str = "FM"
    rule_ids: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    cognos_source: list[str] = field(default_factory=list)
    grain: list[str] = field(default_factory=list)
    alias: str = ""
    union_sources: list[str] = field(default_factory=list)   # outriggers: "RAW.TABLE|COLUMN"

    def col(self, name: str) -> Optional[ColumnDesign]:
        return next((c for c in self.columns if c.name == name), None)

    def col_for_ref(self, ref: str) -> Optional[ColumnDesign]:
        return next((c for c in self.columns if c.ref == ref), None)


@dataclass
class AggregateDesign:
    id: str
    name: str
    fact: str                       # entity
    fact_table: str                 # CORE.FCT_X
    grain_refs: list[str]
    group_columns: list[tuple[str, str, str]]           # (table_alias, column, output name)
    joins: list[tuple[str, str, str]]                   # (alias, table_id, on)
    measures: list[tuple[str, str, str]]                # (output name, sql, kind)
    implementation: str = "dynamic_table"
    target_lag: str = "24 hours"
    warehouse: str = "WH_SEMANTIC_REFRESH"
    coverage_pct: float = 0.0
    clusters: list[str] = field(default_factory=list)
    est_rows: int = 0
    credits_per_day: float = 0.0
    domain: str = ""
    confidence: float = 1.0
    stub: bool = False
    excluded: list[str] = field(default_factory=list)


@dataclass
class SVTable:
    alias: str
    table: str
    primary_key: list[str]
    synonyms: list[str] = field(default_factory=list)
    comment: str = ""


@dataclass
class SVRelationship:
    name: str
    from_alias: str
    from_columns: list[str]
    to_alias: str
    to_columns: list[str]


@dataclass
class SVField:
    alias: str                      # table alias
    name: str                       # logical name
    expr: str                       # SQL expression (qualified with alias)
    data_type: str = ""
    comment: str = ""
    synonyms: list[str] = field(default_factory=list)
    sample_values: list[str] = field(default_factory=list)
    ref: str = ""
    aggregation: str = ""
    suggested: bool = False


@dataclass
class VerifiedQuery:
    name: str
    question: str
    sql: str
    semantic_sql: str
    cluster: str = ""
    reports: list[str] = field(default_factory=list)


@dataclass
class SemanticViewDesign:
    id: str
    name: str
    domain: str
    description: str = ""
    tables: list[SVTable] = field(default_factory=list)
    relationships: list[SVRelationship] = field(default_factory=list)
    facts: list[SVField] = field(default_factory=list)
    dimensions: list[SVField] = field(default_factory=list)
    metrics: list[SVField] = field(default_factory=list)
    verified_queries: list[VerifiedQuery] = field(default_factory=list)
    default_filters: list[dict] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    confidence: float = 1.0
    stub: bool = False
    clusters: list[str] = field(default_factory=list)


@dataclass
class PolicyDesign:
    id: str
    name: str
    kind: str                       # row_access | masking
    signature: list[tuple[str, str]]        # (arg, type)
    returns: str
    body: str
    cognos_rule: str = ""
    cognos_source: str = ""
    attachments: list[dict] = field(default_factory=list)   # {table, columns}
    confidence: float = 1.0
    comment: str = ""
    depends_on: list[str] = field(default_factory=list)


@dataclass
class OutputViewDesign:
    id: str
    schema: str
    name: str
    sql: str
    product: str
    comment: str = ""
    columns: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    confidence: float = 1.0
    stub: bool = False


@dataclass
class ProductDesign:
    key: str                        # package or ENTERPRISE
    name: str
    slug: str
    domain_code: str
    schema: str                     # DP_<DOMAIN>
    owner: str
    steward: str
    classification: str
    retention: str
    source_systems: list[str]
    freshness_sla: str
    semantic_views: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    core_tables: list[str] = field(default_factory=list)
    quality: list[dict] = field(default_factory=list)
    clusters: int = 0
    reports: int = 0
    data_modules: list[str] = field(default_factory=list)
    confidence: float = 1.0
    default_filters: list[dict] = field(default_factory=list)


@dataclass
class Design:
    tables: dict[str, TableDesign] = field(default_factory=dict)
    aggregates: dict[str, AggregateDesign] = field(default_factory=dict)
    semantic_views: dict[str, SemanticViewDesign] = field(default_factory=dict)
    policies: dict[str, PolicyDesign] = field(default_factory=dict)
    outputs: dict[str, OutputViewDesign] = field(default_factory=dict)
    products: dict[str, ProductDesign] = field(default_factory=dict)
    ref_tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    sec_tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    entity_tables: dict[str, list[str]] = field(default_factory=dict)   # entity -> [table ids]
    ref_to_column: dict[str, tuple[str, str]] = field(default_factory=dict)   # Entity.Item -> (table, column)
    ref_to_semantic: dict[str, list[str]] = field(default_factory=dict)       # Entity.Item -> [SV.alias.name]
    issues: list[dict] = field(default_factory=list)
    constants: list[dict] = field(default_factory=list)
