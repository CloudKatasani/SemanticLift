"""Report rationalization, KPI catalog, source inventory, data products view and steward decisions."""
from collections import Counter

import pytest
from fastapi.testclient import TestClient

from semlift.pipeline import run

from .conftest import BUNDLE, ESTATE


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return run(BUNDLE, tmp_path_factory.mktemp("p"), ESTATE)


def reports(r):
    return {x["report"]: x for x in r.graph.analysis["portfolio"]["reports"]}


def test_every_report_has_one_disposition_with_reasons(base):
    P = reports(base)
    assert len(P) == 588
    assert set(Counter(x["disposition"] for x in P.values())) == {"Keep", "Review", "Consolidate", "Retire"}
    for x in P.values():
        assert x["reasons"], x["report"]
        assert x["rule"] in ("R1", "R2", "R3", "R4", "R5")
        if x["disposition"] == "Consolidate":
            assert x["target"] and P[x["target"]]["disposition"] in ("Keep", "Review"), x["report"]


def test_rules_are_consistent_with_clusters(base):
    g = base.graph
    P = reports(base)
    for c in g.clusters.values():
        if c.disposition == "Retire":
            assert all(P[m]["disposition"] == "Retire" for m in c.members)
        else:
            for m in c.members:
                if m != c.canonical:
                    canon = P[c.canonical]
                    final = canon["target"] if canon["disposition"] == "Consolidate" else c.canonical
                    assert P[m]["rule"] == "R2" and P[m]["target"] == final


def test_common_kpi_consolidation(base):
    P = reports(base)
    x = P["Outage_Event_Log"]
    assert x["rule"] == "R4" and x["target"] == "Emergency_Operations_Dashboard"
    assert x["overlap"]["kpis_shared"] == x["overlap"]["kpis_total"] == 3


def test_review_reasons_explain_totals_change(base):
    x = reports(base)["Ancillary_Services_Dispatch"]
    assert x["disposition"] == "Review"
    assert any("Totals will change" in r and "approve the rule" in r for r in x["reasons"])


def test_kpi_catalog_groups(base):
    cat = base.graph.analysis["kpi_catalog"]
    kinds = Counter(gr["kind"] for gr in cat["groups"])
    assert kinds["aggregation"] == 30 and kinds["filter"] > 0 and kinds["concept"] > 0
    cf = next(gr for gr in cat["groups"] if gr["kind"] == "aggregation" and gr["kpis"] == ["Generation.CapacityFactorPct"])
    rec = next(v for v in cf["variants"] if v["recommended"])
    assert rec["aggregation"] == "AVG" and not rec["reports"]
    assert next(v for v in cf["variants"] if v["aggregation"] == "SUM")["reports"]
    bill = next(k for k in cat["kpis"] if k["id"] == "Billing.BillAmount")
    src = bill["sources"][0]
    assert (src["database"], src["schema"], src["table"], src["column"]) == ("ENERGY_DW", "ENERGY_DW", "BILLING", "BILL_AMOUNT")
    assert src["landed"] == "RAW_CCB.BILLING.BILL_AMOUNT"
    lf = next(k for k in cat["kpis"] if k["id"] == "LoadForecast.ActualLoadMW")
    assert lf["sources"][0]["database"] == "ENERGY_OPS_DW" and not lf["sources"][0]["confirmed"]


def test_source_inventory(base):
    si = base.graph.analysis["source_inventory"]
    dbs = {d["database"] for d in si["databases"]}
    assert {"ENERGY_DW", "SAP_FICA_PROD", "SF_SERVICE_CLOUD"} <= dbs
    billing = next(t for t in si["tables"] if t["id"] == "ENERGY_DW.ENERGY_DW.BILLING")
    assert billing["confirmed"] and billing["keep_reports"] and "RAW_CCB.BILLING" in billing["landed"]
    assert any(t["review_only"] and t["scope"] == "Review" for t in si["tables"])
    keep = {n for n, x in reports(base).items() if x["disposition"] == "Keep"}
    assert all(set(t["keep_reports"]) <= keep for t in si["tables"])


def test_decisions_flow_into_design(base, tmp_path):
    cat = base.graph.analysis["kpi_catalog"]
    vp = next(gr for gr in cat["groups"] if gr["kind"] == "aggregation" and gr["kpis"] == ["BudgetActual.VariancePct"])
    v_sum = next(v for v in vp["variants"] if v["aggregation"] == "SUM")
    mwh = next(gr for gr in cat["groups"] if gr["kind"] == "concept" and gr["title"] == "Energy volume (MWh)")
    v_gen = next(v for v in mwh["variants"] if v["kpi"] == "Generation.GeneratedMWh")
    retired = next(x["report"] for x in base.graph.analysis["portfolio"]["reports"] if x["rule"] == "R1" and x["folder"] == "Active")
    dec = {"kpis": {vp["id"]: {"variant": v_sum["id"], "kind": "aggregation", "kpi": v_sum["kpi"], "aggregation": "SUM"},
                    mwh["id"]: {"variant": v_gen["id"], "kind": "concept", "kpi": v_gen["kpi"]}},
           "reports": {retired: {"disposition": "Keep", "comment": "still needed"}}}
    r = run(BUNDLE, tmp_path, ESTATE, decisions=dec)
    g = r.graph
    assert g.measures["BudgetActual.VariancePct"].default_aggregation == "sum"
    assert any(f.code == "F21" for f in g.findings)
    assert all(v["passed"] in (True, None) for v in g.analysis["validation"])
    sv = next(o for o in r.objects if o.id == "SEM.SV_FINANCE_PERFORMANCE").ddl
    assert "SUM(budget_actual.variance_pct)" in sv
    P = reports(r)
    assert P[retired]["disposition"] == "Keep" and g.clusters[g.reports[retired].cluster].disposition != "Retire"
    assert any("approved definition is Generation.GeneratedMWh" in x for x in P["Wholesale_Market_Settlement"]["reasons"])


def test_portfolio_api(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMLIFT_WORKSPACE", str(tmp_path / "api"))
    import semlift.api.app as appmod
    appmod._ws = None
    c = TestClient(appmod.app)
    c.post("/api/uploads", files=[("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))])
    assert c.post("/api/run", json={"config": "energy_estate"}).status_code == 200
    p = c.get("/api/portfolio").json()
    assert p["pending_rerun"] is False and len(p["rules"]) == 5
    assert c.post("/api/portfolio/Outage_Event_Log", json={"disposition": "Keep", "comment": "ops want it"}).json()["disposition"] == "Keep"
    assert c.post("/api/portfolio/Outage_Event_Log", json={"disposition": "Bogus"}).status_code == 409
    assert c.get("/api/portfolio").json()["pending_rerun"] is True
    k = c.get("/api/kpis").json()
    grp = k["groups"][0]
    assert c.post(f"/api/kpis/{grp['id']}", json={"variant": grp["variants"][0]["id"], "comment": "x"}).json()["status"] == "approved"
    s = c.get("/api/sources").json()
    tid = s["tables"][0]["id"]
    assert c.post(f"/api/sources/{tid}", json={"scope": "Exclude"}).json()["scope"] == "Exclude"
    pv = c.get("/api/products-view").json()
    billing = next(x for x in pv["products"] if x["key"] == "Energy_Billing_Package")
    assert billing["semantic_views"] and billing["business_logic"] and billing["lineage"]["edges"]
    assert any(b["kind"] == "Calculation" and "TotalBillWithTax" in b["cognos"] for b in billing["business_logic"])
    assert c.post("/api/rerun").status_code == 200
    p2 = c.get("/api/portfolio").json()
    assert p2["pending_rerun"] is False
    assert next(r for r in p2["reports"] if r["report"] == "Outage_Event_Log")["disposition"] == "Keep"
    assert next(t for t in c.get("/api/sources").json()["tables"] if t["id"] == tid)["scope"] == "Exclude"
