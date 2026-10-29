"""Inputs as a Cognos administrator exports them (see the Cognos export guide in the UI)."""
from semlift.config import load_config
from semlift.ingest import ingest_folder

SPEC = """<?xml version="1.0" encoding="UTF-8"?>
<report xmlns="http://developer.cognos.com/schemas/report/16.0/" expressionLocale="en-us">
  <modelPath>/content/package[@name='Sales_Package']/model[@name='model']</modelPath>
  <queries>
    <query name="Query1">
      <source><model/></source>
      <selection>
        <dataItem name="Region"><expression>[Sales_Package].[Location].[Region]</expression></dataItem>
        <dataItem name="Revenue" aggregate="total"><expression>[Sales_Package].[Orders].[Revenue]</expression></dataItem>
      </selection>
      <detailFilters>
        <detailFilter><filterExpression>[Sales_Package].[Date].[FiscalYear] = ?p_FiscalYear?</filterExpression></detailFilter>
      </detailFilters>
    </query>
  </queries>
  <layouts><layout/></layouts>
</report>
"""

USAGE = """report_name,report_path,package,folder_category,duplicate_group_id,runs_per_day,last_run_date,avg_duration_min
Revenue_by_Region,Team Content/Sales/Revenue_by_Region,Sales_Package,Active,SAL_001,4,2026-10-01,2.5
Revenue_by_Region_Copy,My Folders/jdoe/Revenue_by_Region_Copy,Sales_Package,Community,SAL_001,0,2025-01-15,2.0
"""

NATIVE_FM = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://www.developer.cognos.com/schemas/bmt/60/12">
  <name locale="en">Sales</name>
  <namespace><name locale="en">Physical</name>
    <querySubject status="valid"><name locale="en">Orders</name>
      <queryItem><name locale="en">Revenue</name><externalName>REVENUE</externalName><usage>fact</usage></queryItem>
    </querySubject>
  </namespace>
</project>
"""


def test_raw_report_specs_with_usage_csv(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "Revenue_by_Region.xml").write_text(SPEC)
    (tmp_path / "reports" / "Revenue_by_Region_Copy.xml").write_text(SPEC)
    (tmp_path / "usage.csv").write_text(USAGE)
    g = ingest_folder(tmp_path, load_config(None))
    r = g.reports["Revenue_by_Region"]
    assert r.package == "Sales_Package"                              # from modelPath
    assert (r.folder, r.dup_group, r.path) == ("Active", "SAL_001", "Team Content/Sales/Revenue_by_Region")  # from usage
    assert r.runs_per_day == 4 and r.last_run == "2026-10-01"
    assert g.reports["Revenue_by_Region_Copy"].folder == "Community"
    assert {i.name for i in g.report_items if i.report == r.name} == {"Region", "Revenue"}
    assert any(f.parameter == "p_FiscalYear" for f in g.report_filters if f.report == r.name)
    assert g.analysis["usage_join"]["matched"] == 2


def test_native_fm_model_is_reported_not_misread(tmp_path):
    (tmp_path / "model.xml").write_text(NATIVE_FM)
    g = ingest_folder(tmp_path, load_config(None))
    rec = next(f for f in g.files if f.path == "model.xml")
    assert rec.status == "rejected" and "not supported yet" in rec.warnings[0]
    assert not g.entities
