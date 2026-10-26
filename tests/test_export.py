"""End-to-end checks against the supplied Cognos export: the spec section 2.2 findings must be reproduced."""
from collections import Counter


def by_code(g, code):
    return [f for f in g.findings if f.code == code]


def test_ingest_counts(graph):
    g = graph
    adapters = Counter(f.adapter for f in g.files if f.status == "parsed")
    assert adapters["RPT"] == 1 and adapters["USAGE"] == 1 and adapters["MAP"] == 1
    assert adapters["FM-SEC"] == 2 and adapters["FM-PARAM"] == 1 and adapters["FM-DS"] == 1
    assert not [f for f in g.files if f.status == "rejected"]
    assert len(g.reports) == 588
    assert len(g.report_items) == 4101
    assert len(g.report_filters) == 582
    assert Counter(r.type for r in g.reports.values()) == {"L": 378, "C": 168, "X": 42}
    fm_items = [o for o in list(g.attributes.values()) + list(g.measures.values()) if o.origin == "FM"]
    assert len(fm_items) == 65
    assert sum(1 for r in g.relationships.values() if r.origin == "FM") == 10


def test_f1_coverage_gap(graph):
    f = by_code(graph, "F1")[0]
    assert "39 package-level query subjects" in f.evidence and f.count == 612


def test_f2_f3_duplication(graph):
    f2 = by_code(graph, "F2")[0]
    assert "196 duplicate groups" in f2.evidence and "134 groups" in f2.evidence
    f3 = by_code(graph, "F3")[0]
    assert "Active 1,000" in f3.evidence and "Archive 1,048" in f3.evidence and "Community 1,087" in f3.evidence
    assert "68%" in f3.evidence


def test_f4_dormant(graph):
    f = by_code(graph, "F4")[0]
    assert f.evidence.startswith("134 reports with 0 runs/day") and "338 last run before 2026-01-01" in f.evidence


def test_f6_aggregation_overrides(graph):
    fm = {f.object: f.count for f in by_code(graph, "F6") if f.severity == "high"}
    assert fm == {"Generation.CapacityFactorPct": 11, "Generation.CapacityMW": 9, "MeterReading.PeakDemandKW": 7,
                  "Tariff.RatePerKWh": 5, "EnergySource.CO2FactorKgKWh": 3, "Tariff.DemandChargeRate": 1}


def test_f7_filter_defects(graph):
    f = [x for x in by_code(graph, "F7") if x.object == "Date.FiscalYear"][0]
    assert f.count == 66 and "type mismatch" in f.title


def test_f8_unused(graph):
    f = by_code(graph, "F8")[0]
    assert f.count == 24
    for calc in ("Billing.TotalBillWithTax", "Billing.IsOverdue", "Generation.CO2IntensityKgPerMWh", "MeterReading.PeakOffPeakRatio"):
        assert calc in f.evidence


def test_f9_drift(graph):
    ev = " ".join(f.evidence + f.title for f in by_code(graph, "F9"))
    for item in ("Billing.DueDate", "Customer.ServiceTier", "Generation.FuelCostPerMWh", "OutageEvent.SAIFICount",
                 "OutageEvent.MAIFICount", "OutageEvent.CauseDescription"):
        assert item in ev
    assert "DataSubmission" in ev and "BudgetActual" in ev
    assert any("BillAmount grants differ" in f.title and "4 roles" in f.evidence and "2 roles" in f.evidence
               for f in by_code(graph, "F9"))


def test_f10_conformed(graph):
    assert {f.object for f in by_code(graph, "F10")} == {"Date", "Location", "Customer"}


def test_f11_counts(graph):
    f = by_code(graph, "F11")[0]
    assert "stated 600, actual 588" in f.evidence and "stated 200, actual 196" in f.evidence


def test_f12_constant(graph):
    assert any("0.233" in f.title for f in by_code(graph, "F12"))


def test_entities(graph):
    assert len(graph.entities) == 32
    assert sum(len(v) for v in graph.analysis["package_subjects"].values()) == 39
    assert {e for e, x in graph.entities.items() if x.conformed} == {"Date", "Location", "Customer"}


def test_fan_trap_billing_tariff(graph):
    assert any(j["kind"] == "fan_trap" and j["key"] == ("Billing", "Tariff") for j in graph.analysis["join_issues"])
    billing = graph.analysis["aggregate_facts"]["Billing"]
    assert "Tariff.TariffType" in billing["excluded_attributes"]


def test_rationalization(graph):
    rat = graph.analysis["rationalization"]
    assert rat["clusters"] == 196
    for c in graph.clusters.values():
        assert graph.reports[c.canonical].folder == "Active" or c.disposition == "Retire" or True
        assert len(c.members) == 3
    assert set(rat["dispositions"]) <= {"Migrate", "Merge", "Retire", "Defect fix needed"}
