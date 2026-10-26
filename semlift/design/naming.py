"""Naming and placement rules (spec 6.7). Single source of truth for object names."""
from __future__ import annotations

import re

from ..util import snake_upper

LAYER_SCHEMA = {"core": "CORE", "ref": "REF", "agg": "AGG", "sem": "SEM", "sec": "SEC"}
TIME_TOKENS = {"FullDate": "DAY", "ISOWeek": "WEEK", "MonthName": "MONTH", "MonthNumber": "MONTH",
               "Quarter": "QUARTER", "FiscalYear": "YEAR"}


def pkg_stem(pkg: str) -> str:
    s = re.sub(r"^Energy_", "", pkg)
    s = re.sub(r"_Package$", "", s)
    return snake_upper(s)


def domain_code(cfg: dict, pkg: str) -> str:
    return cfg["naming"]["domain_codes"].get(pkg) or pkg_stem(pkg)


def product_name(cfg: dict, pkg: str) -> str:
    return cfg["naming"]["product_names"].get(pkg) or pkg_stem(pkg).replace("_", " ").title()


def product_slug(cfg: dict, pkg: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", product_name(cfg, pkg).lower()).strip("-")


def dim_name(cfg: dict, entity: str) -> str:
    return "DIM_" + (cfg["naming"]["dimension_names"].get(entity) or snake_upper(entity))


def fact_name(cfg: dict, entity: str) -> str:
    return "FCT_" + (cfg["naming"]["fact_names"].get(entity) or snake_upper(entity))


def policy_name(cfg: dict, rule_name: str, prefix: str) -> str:
    over = cfg["naming"]["policy_names"].get(rule_name)
    if over:
        return over
    stem = re.sub(r"(Filter|_Mask|Mask)$", "", rule_name)
    return f"{prefix}_{snake_upper(stem)}"


def role_name(cfg: dict, cognos_role: str) -> str:
    r = snake_upper(cognos_role) if not cognos_role.isupper() else cognos_role
    return r.upper() if cfg["security"].get("role_case", "upper") == "upper" else r


def column_name(attr_or_measure) -> str:
    return attr_or_measure.physical_column or snake_upper(attr_or_measure.name)


def alias(name: str) -> str:
    """Logical table alias used in semantic views."""
    s = snake_upper(re.sub(r"^(FCT|DIM)_", "", name)).lower()
    return {"date": "dt"}.get(s, s)
