import csv
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from semlift.service.workspace import ReviewError, Workspace

from .conftest import BUNDLE, ESTATE


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    w = Workspace(tmp_path_factory.mktemp("ws"))
    w.set_config(ESTATE)
    w.run(BUNDLE)
    return w


def test_package_written(ws):
    out = ws.output
    for rel in ("findings.md", "design_workbook.xlsx", "lineage.json", "traceability.csv", "manifest.json",
                "contracts/customer-billing-and-metering.yaml", "semantic/snowflake/SV_BILLING_REVENUE.yaml",
                "semantic/databricks/sv_billing_revenue.yaml", "dbt/dbt_project.yml", "dbt/models/schema.yml",
                "validation/parity_index.json", "meta/load_semlift_meta.sql"):
        assert (out / rel).exists(), rel
    rows = list(csv.DictReader(io.StringIO((out / "traceability.csv").read_text())))
    assert len(rows) == 4101
    billing = [r for r in rows if r["report"] == "Customer_Billing_Summary" and r["report_column"] == "BillAmount"][0]
    assert billing["fm_item"] == "Business Layer.Billing.BillAmount"
    assert billing["source_column"] == "RAW_CCB.BILLING.BILL_AMOUNT"
    assert billing["target_column"] == "CORE.FCT_BILLING.BILL_AMOUNT"
    assert "SEM.SV_BILLING_REVENUE" in billing["semantic_objects"]
    assert json.loads((out / "lineage.json").read_text())


def test_review_rules_and_persistence(ws):
    with pytest.raises(ReviewError):
        ws.review("CORE.FCT_LOAD_FORECAST", "approve")          # inferred, below 0.6
    ws.review("CORE.FCT_LOAD_FORECAST", "approve", acknowledge_low_confidence=True)
    ws.review("CORE.DIM_TARIFF", "reject", comment="not needed")
    edited = (ws.output / next(o for o in ws.state()["objects"] if o["id"] == "CORE.DIM_METER")["file"]).read_text()
    edited = edited.replace("COMMENT = 'Dimension", "COMMENT = 'Edited dimension")
    ws.review("CORE.DIM_METER", "edit", ddl=edited)
    ws.review("CORE.DIM_METER", "approve")
    with pytest.raises(ReviewError):
        ws.review("CORE.DIM_DATE", "edit", ddl="CREATE VIEW x AS\nSELECT (1;")
        ws.review("CORE.DIM_DATE", "approve")
    st = ws.run(BUNDLE)                                          # re-run: decisions persist
    objs = {o["id"]: o for o in st["objects"]}
    assert objs["CORE.FCT_LOAD_FORECAST"]["status"] == "approved"
    assert objs["CORE.DIM_TARIFF"]["status"] == "rejected"
    assert objs["CORE.DIM_METER"]["status"] == "approved" and "Edited dimension" in objs["CORE.DIM_METER"]["edited_ddl"]
    assert st["diff"]["baseline"] is False and not st["diff"]["changed"] and not st["diff"]["added"]


def test_deploy_writes_git_branch(ws):
    ws.auto_approve()
    res = ws.deploy(branch="semlift/test")
    assert res["commit"] and res["branch"] == "semlift/test"
    repo = ws.root / "deploy" / "repo"
    man = json.loads((repo / "manifest.json").read_text())
    assert man["objects"] and (repo / ".github/workflows/semlift-deploy.yml").exists()
    ids = [o["id"] for o in man["objects"]]
    assert "CORE.DIM_TARIFF" not in ids                          # rejected objects never deploy
    meter = next(o for o in man["objects"] if o["id"] == "CORE.DIM_METER")
    assert meter["edited"] and "Edited dimension" in (repo / meter["file"]).read_text()


def test_findings_state_and_suggestions(ws):
    f = ws.state()["findings"][0]
    ws.update_finding(f["id"], owner="alice", status="accepted")
    st = ws.run(BUNDLE)
    f2 = next(x for x in st["findings"] if x["id"] == f["id"])
    assert f2["owner"] == "alice" and f2["status"] == "accepted"
    sug = ws.suggestions()
    sid = next(k for k, v in sug.items() if v["target"].startswith("SEM.SV_BILLING_REVENUE.billing.total_bill_amount"))
    ws.decide_suggestion(sid, "accepted", description="Total billed amount before tax", synonyms=["revenue billed"])
    st = ws.run(BUNDLE)
    ddl = (ws.output / next(o for o in st["objects"] if o["id"] == "SEM.SV_BILLING_REVENUE")["file"]).read_text()
    assert "Total billed amount before tax" in ddl and "revenue billed" in ddl
    assert "SEM.SV_BILLING_REVENUE" in st["diff"]["changed"]


def test_catalog_matching_raises_confidence(tmp_path):
    cat = tmp_path / "catalog.csv"
    cat.write_text("table_schema,table_name,column_name,data_type,row_count\n"
                   "RAW_ENERGY_OPS,LOAD_FORECAST,LOAD_FORECAST_ID,VARCHAR,3650000\n"
                   "RAW_ENERGY_OPS,LOAD_FORECAST,DATE_KEY,NUMBER,3650000\n"
                   "RAW_ENERGY_OPS,LOAD_FORECAST,LOCATION_ID,VARCHAR,3650000\n"
                   "RAW_ENERGY_OPS,LOAD_FORECAST,FORECASTED_LOAD_MW,NUMBER,3650000\n"
                   "RAW_ENERGY_OPS,LOAD_FORECAST,ACTUAL_LOAD_MW,NUMBER,3650000\n")
    from semlift.pipeline import run
    r = run(BUNDLE, tmp_path / "w", ESTATE, extra_sources=[cat])
    assert r.graph.catalog_loaded
    e = r.graph.entities["LoadForecast"]
    assert e.confidence == 0.6
    assert r.graph.measures["LoadForecast.ActualLoadMW"].confidence == 0.6
    assert any(m["entity"] == "LoadForecast" for m in r.graph.analysis["catalog_matches"])


def test_api_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv("SEMLIFT_WORKSPACE", str(tmp_path / "api"))
    import semlift.api.app as appmod
    appmod._ws = None
    c = TestClient(appmod.app)
    assert c.get("/api/health").json()["status"] == "ok"
    assert c.get("/api/summary").status_code == 404
    up = c.post("/api/uploads", files=[("files", (BUNDLE.name, BUNDLE.read_bytes(), "application/zip"))])
    assert up.status_code == 200
    r = c.post("/api/run", json={"config": "energy_estate"})
    assert r.status_code == 200 and r.json()["entities"] == 32
    assert c.get("/api/model").json()["entities"]
    ldm = c.get("/api/logical-model").json()
    billing = next(t for t in ldm["tables"] if t["id"] == "CORE.FCT_BILLING")
    assert billing["kind"] == "fact" and billing["primary_key"] == ["BILL_ID"]
    assert {f["ref_table"] for f in billing["foreign_keys"]} == {"CORE.DIM_DATE", "CORE.DIM_METER"}
    assert any(c["role"] == "measure" and c["sensitive"] for c in billing["columns"])
    sv = next(a for a in ldm["subject_areas"] if a["name"] == "SV_BILLING_REVENUE")
    assert "CORE.DIM_CUSTOMER" in sv["tables"] and len(ldm["products"]) == 7
    o = c.get("/api/objects/SEM.SV_BILLING_REVENUE").json()
    assert "CREATE OR REPLACE SEMANTIC VIEW" in o["ddl"]
    bad = c.post("/api/objects/CORE.FCT_LOAD_FORECAST/review", json={"action": "approve"})
    assert bad.status_code == 409
    assert c.post("/api/objects/CORE.DIM_DATE/review", json={"action": "approve"}).json()["status"] == "approved"
    z = c.get("/api/download/package")
    assert z.status_code == 200 and zipfile.ZipFile(io.BytesIO(z.content)).namelist()
    assert c.get("/api/files/../../etc/passwd").status_code == 404
