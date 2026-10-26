import pytest

from semlift import expr as cx
from semlift.analyze.classify import classify_measure
from semlift.config import load_config
from semlift.model import Measure
from semlift.util import mask_secret_url, snake_upper


@pytest.mark.parametrize("name,expected", [
    ("CO2FactorKgKWh", "CO2_FACTOR_KG_KWH"), ("RECID", "REC_ID"), ("MisopID", "MISOP_ID"),
    ("SAIFICount", "SAIFI_COUNT"), ("KWhSold", "KWH_SOLD"), ("NPS_Score", "NPS_SCORE"),
    ("PRC004Requirement", "PRC004_REQUIREMENT"), ("ISOWeek", "ISO_WEEK"), ("METER_ID", "METER_ID"),
    ("QuantityMMBTU", "QUANTITY_MMBTU"), ("Identity", "IDENTITY"),
])
def test_snake_upper(name, expected):
    assert snake_upper(name) == expected


def test_parse_case_to_iff():
    n = cx.parse("case when [P].[DB_Billing].[PAYMENT_STATUS] = 'Overdue' then 'Yes' else 'No' end")
    sql = cx.to_sql(n, lambda r: "src." + r.parts[-1])
    assert sql == "IFF(src.PAYMENT_STATUS = 'Overdue', 'Yes', 'No')"


def test_parse_security_subquery():
    n = cx.parse("[BL].[Location].[Region] in ( select REGION from ENERGY_DW.USER_REGION_ACCESS where USERNAME = session_user() )")
    assert isinstance(n, cx.InList) and n.subquery.table == ["ENERGY_DW", "USER_REGION_ACCESS"]
    assert "CURRENT_USER()" in cx.to_sql(n, lambda r: r.parts[-1])


def test_malformed_comparison_rejected():
    node, err = cx.try_parse("[P].[Generation].[CapacityFactorPct] = < 0.3")
    assert node is None and "Malformed" in err


def test_prompt_and_constants():
    n = cx.parse("[P].[DB].[CONSUMPTION_KWH] * 0.233")
    assert cx.numeric_constants(n) == [0.233]
    assert isinstance(cx.parse("[P].[Date].[FiscalYear] = ?p_FiscalYear?").right, cx.Prompt)


@pytest.mark.parametrize("name,agg,add", [
    ("CapacityFactorPct", "avg", "non"), ("PeakLoadMW", "max", "semi"), ("ForecastedLoadMW", "avg", "semi"),
    ("SettlementAmount", "sum", "additive"), ("CostPerMMBTU", "avg", "non"), ("SAIFICount", "sum", "additive"),
])
def test_inferred_additivity(name, agg, add):
    m = Measure(entity="X", name=name, origin="inferred")
    classify_measure(m, load_config())
    assert (m.default_aggregation, m.additivity) == (agg, add)


def test_fm_regular_aggregate_wins():
    m = Measure(entity="X", name="Whatever", origin="FM", regular_aggregate="maximum")
    classify_measure(m, load_config())
    assert (m.default_aggregation, m.additivity) == ("max", "semi")


def test_jdbc_masked():
    assert "db-host" not in mask_secret_url("jdbc:oracle:thin:@//db-host.energy-utility.com:1521/ENERGY_DW")
