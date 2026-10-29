"""Generate a synthetic Cognos Analytics 12 estate export for a telecommunications operator.

    python samples/telco/generate_telco_bundle.py          # -> samples/Cognos Telco Input.zip

The bundle has the same layout and file formats as the energy sample (``samples/Cognos Lineage Input.zip``)
so it goes through every SemanticLift adapter unchanged:

    FM/telco_fm_package_v12.zip            Framework Manager project: package.xml, model.xml (with drift),
                                           .cpf, namespaces, datasource, parameter map, security, publish
    Reports/cognos_content_export_v12/all_reports.xml
                                           Active reports per package plus Archive and Community copies
    cognos_report_usage_telco.xlsx         usage audit (runs/day, last run, duration) per report
    FM_Data_Module_Mapping_Telco.xlsx      package / data module -> source system mapping
    source_catalog_telco.csv               landed-table catalog for some systems (raises confidence)

Content is deterministic (fixed seed): re-running produces the same reports, usage, model and mapping
(only the spreadsheet files' internal save timestamps differ). The estate deliberately
contains the problems SemanticLift is built to find: dormant reports, archive and community duplicates,
reports whose KPIs are a subset of busier ones, non-additive measures summed in reports, the same KPI
under different filters and definitions, prompt type mismatches, a malformed filter, items missing from
the FM model, security on inferred entities, a hard-coded regulatory rate and model/package drift.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import random
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

SEED = 20261020
EXPORT_DATE = dt.date(2026, 10, 20)
CV = "12.1.2"
FM_PKG = "Telco_Analytics_Package"
DB = "TELCO_DW"
DS = "TelcoAnalytics_DB"
OUT = Path(__file__).resolve().parents[1] / "Cognos Telco Input.zip"

# --------------------------------------------------------------------------- FM model
# physical table -> [(column, dataType, usage, regularAggregate)]
PHYS = {
    "Subscriber": ("SUBSCRIBER", [("SUBSCRIBER_ID", "string", "identifier", "none"), ("MSISDN", "string", "attribute", "none"),
                                  ("ACCOUNT_ID", "string", "identifier", "none"), ("PLAN_ID", "string", "identifier", "none"),
                                  ("LOCATION_ID", "string", "identifier", "none"), ("ACTIVATION_DATE", "date", "attribute", "none"),
                                  ("STATUS", "string", "attribute", "none"), ("SEGMENT", "string", "attribute", "none"),
                                  ("IS_PREPAID", "boolean", "attribute", "none"), ("CREDIT_SCORE", "integer", "attribute", "none")]),
    "Account": ("ACCOUNT", [("ACCOUNT_ID", "string", "identifier", "none"), ("ACCOUNT_NAME", "string", "attribute", "none"),
                            ("ACCOUNT_TYPE", "string", "attribute", "none"), ("BILLING_CYCLE", "string", "attribute", "none")]),
    "Location": ("LOCATION", [("LOCATION_ID", "string", "identifier", "none"), ("REGION", "string", "attribute", "none"),
                              ("MARKET", "string", "attribute", "none"), ("STATE_PROVINCE", "string", "attribute", "none"),
                              ("CITY", "string", "attribute", "none"), ("POSTAL_CODE", "string", "attribute", "none"),
                              ("ADDRESS", "string", "attribute", "none")]),
    "Plan": ("RATE_PLAN", [("PLAN_ID", "string", "identifier", "none"), ("PLAN_NAME", "string", "attribute", "none"),
                           ("PLAN_TYPE", "string", "attribute", "none"), ("MONTHLY_FEE", "decimal", "fact", "average"),
                           ("DATA_ALLOWANCE_GB", "decimal", "fact", "average")]),
    "Date": ("DATE_DIM", [("DATE_KEY", "integer", "identifier", "none"), ("FULL_DATE", "date", "attribute", "none"),
                          ("ISO_WEEK", "integer", "attribute", "none"), ("MONTH_NAME", "string", "attribute", "none"),
                          ("MONTH_NUMBER", "integer", "attribute", "none"), ("QUARTER", "string", "attribute", "none"),
                          ("FISCAL_YEAR", "integer", "attribute", "none"), ("IS_WEEKEND", "boolean", "attribute", "none"),
                          ("IS_HOLIDAY", "boolean", "attribute", "none")]),
    "Device": ("DEVICE", [("DEVICE_ID", "string", "identifier", "none"), ("SUBSCRIBER_ID", "string", "identifier", "none"),
                          ("MANUFACTURER", "string", "attribute", "none"), ("MODEL", "string", "attribute", "none"),
                          ("OS", "string", "attribute", "none"), ("IS_5G_CAPABLE", "boolean", "attribute", "none")]),
    "CellSite": ("CELL_SITE", [("CELL_ID", "string", "identifier", "none"), ("SITE_NAME", "string", "attribute", "none"),
                               ("TECHNOLOGY", "string", "attribute", "none"), ("VENDOR", "string", "attribute", "none"),
                               ("LOCATION_ID", "string", "identifier", "none"), ("CAPACITY_MBPS", "decimal", "fact", "maximum")]),
    "UsageRecord": ("USAGE_CDR", [("USAGE_ID", "integer", "identifier", "none"), ("SUBSCRIBER_ID", "string", "identifier", "none"),
                                  ("CELL_ID", "string", "identifier", "none"), ("DATE_KEY", "integer", "identifier", "none"),
                                  ("VOICE_MINUTES", "decimal", "fact", "total"), ("DATA_MB", "decimal", "fact", "total"),
                                  ("SMS_COUNT", "integer", "fact", "total"), ("ROAMING_FLAG", "string", "attribute", "none"),
                                  ("USAGE_REVENUE", "decimal", "fact", "total")]),
    "Invoice": ("INVOICE", [("INVOICE_ID", "integer", "identifier", "none"), ("ACCOUNT_ID", "string", "identifier", "none"),
                            ("INVOICE_DATE_KEY", "integer", "identifier", "none"), ("INVOICE_AMOUNT", "decimal", "fact", "total"),
                            ("TAX_AMOUNT", "decimal", "fact", "total"), ("DISCOUNT_AMOUNT", "decimal", "fact", "total"),
                            ("ROAMING_CHARGE", "decimal", "fact", "total"), ("PAYMENT_STATUS", "string", "attribute", "none"),
                            ("IS_EBILL", "boolean", "attribute", "none")]),
    "NetworkKPI": ("NETWORK_KPI_DAILY", [("KPI_ID", "integer", "identifier", "none"), ("CELL_ID", "string", "identifier", "none"),
                                         ("DATE_KEY", "integer", "identifier", "none"), ("CALL_ATTEMPTS", "integer", "fact", "total"),
                                         ("DROPPED_CALLS", "integer", "fact", "total"), ("AVG_THROUGHPUT_MBPS", "decimal", "fact", "average"),
                                         ("PEAK_UTILIZATION_PCT", "decimal", "fact", "maximum"), ("TRAFFIC_GB", "decimal", "fact", "total"),
                                         ("AVAILABILITY_PCT", "decimal", "fact", "average")]),
}

# business layer: QS -> [(item, dataType, usage, regularAggregate, expression | physical column, sensitive)]
def P(qs, col):
    return f"[Physical Layer].[DB_{qs}].[{col}]"


BIZ = {
    "Subscriber": [("SubscriberID", "string", "identifier", "none", "SUBSCRIBER_ID", False), ("MSISDN", "string", "attribute", "none", "MSISDN", True),
                   ("SubscriberStatus", "string", "attribute", "none", "STATUS", False), ("CustomerSegment", "string", "attribute", "none", "SEGMENT", False),
                   ("IsPrepaid", "boolean", "attribute", "none", "IS_PREPAID", False), ("ActivationDate", "date", "attribute", "none", "ACTIVATION_DATE", False),
                   ("CreditScore", "integer", "attribute", "none", "CREDIT_SCORE", True)],
    "Account": [("AccountID", "string", "identifier", "none", "ACCOUNT_ID", False), ("AccountName", "string", "attribute", "none", "ACCOUNT_NAME", False),
                ("AccountType", "string", "attribute", "none", "ACCOUNT_TYPE", False), ("BillingCycle", "string", "attribute", "none", "BILLING_CYCLE", False)],
    "Location": [("LocationID", "string", "identifier", "none", "LOCATION_ID", False), ("Region", "string", "attribute", "none", "REGION", False),
                 ("Market", "string", "attribute", "none", "MARKET", False), ("StateProvince", "string", "attribute", "none", "STATE_PROVINCE", False),
                 ("City", "string", "attribute", "none", "CITY", False), ("PostalCode", "string", "attribute", "none", "POSTAL_CODE", False),
                 ("Address", "string", "attribute", "none", "ADDRESS", True)],
    "Plan": [("PlanID", "string", "identifier", "none", "PLAN_ID", False), ("PlanName", "string", "attribute", "none", "PLAN_NAME", False),
             ("PlanType", "string", "attribute", "none", "PLAN_TYPE", False), ("MonthlyFee", "decimal", "fact", "average", "MONTHLY_FEE", False),
             ("DataAllowanceGB", "decimal", "fact", "average", "DATA_ALLOWANCE_GB", False)],
    "Date": [("DateKey", "integer", "identifier", "none", "DATE_KEY", False), ("FullDate", "date", "attribute", "none", "FULL_DATE", False),
             ("ISOWeek", "integer", "attribute", "none", "ISO_WEEK", False), ("MonthName", "string", "attribute", "none", "MONTH_NAME", False),
             ("MonthNumber", "integer", "attribute", "none", "MONTH_NUMBER", False), ("Quarter", "string", "attribute", "none", "QUARTER", False),
             ("FiscalYear", "integer", "attribute", "none", "FISCAL_YEAR", False), ("IsWeekend", "boolean", "attribute", "none", "IS_WEEKEND", False),
             ("IsHoliday", "boolean", "attribute", "none", "IS_HOLIDAY", False)],
    "Device": [("DeviceID", "string", "identifier", "none", "DEVICE_ID", False), ("Manufacturer", "string", "attribute", "none", "MANUFACTURER", False),
               ("DeviceModel", "string", "attribute", "none", "MODEL", False), ("DeviceOS", "string", "attribute", "none", "OS", False),
               ("Is5GCapable", "boolean", "attribute", "none", "IS_5G_CAPABLE", False)],
    "CellSite": [("CellID", "string", "identifier", "none", "CELL_ID", False), ("SiteName", "string", "attribute", "none", "SITE_NAME", False),
                 ("Technology", "string", "attribute", "none", "TECHNOLOGY", False), ("SiteVendor", "string", "attribute", "none", "VENDOR", False),
                 ("CapacityMbps", "decimal", "fact", "maximum", "CAPACITY_MBPS", False)],
    "UsageRecord": [("UsageID", "integer", "identifier", "none", "USAGE_ID", False), ("VoiceMinutes", "decimal", "fact", "total", "VOICE_MINUTES", False),
                    ("DataMB", "decimal", "fact", "total", "DATA_MB", False),
                    ("DataGB", "decimal", "fact", "total", f"{P('UsageRecord', 'DATA_MB')} / 1024", False),
                    ("SMSCount", "integer", "fact", "total", "SMS_COUNT", False), ("RoamingFlag", "string", "attribute", "none", "ROAMING_FLAG", False),
                    ("UsageRevenue", "decimal", "fact", "total", "USAGE_REVENUE", False)],
    "Invoice": [("InvoiceID", "integer", "identifier", "none", "INVOICE_ID", False), ("InvoiceAmount", "decimal", "fact", "total", "INVOICE_AMOUNT", False),
                ("TaxAmount", "decimal", "fact", "total", "TAX_AMOUNT", False), ("DiscountAmount", "decimal", "fact", "total", "DISCOUNT_AMOUNT", False),
                ("RoamingCharge", "decimal", "fact", "total", "ROAMING_CHARGE", False),
                ("TotalInvoiceWithTax", "decimal", "fact", "total", f"{P('Invoice', 'INVOICE_AMOUNT')} + {P('Invoice', 'TAX_AMOUNT')}", False),
                ("USFContribution", "decimal", "fact", "total", f"{P('Invoice', 'INVOICE_AMOUNT')} * 0.364", False),
                ("PaymentStatus", "string", "attribute", "none", "PAYMENT_STATUS", False),
                ("IsOverdue", "string", "attribute", "none", f"case when {P('Invoice', 'PAYMENT_STATUS')} = 'Overdue' then 'Yes' else 'No' end", False),
                ("IsEBill", "boolean", "attribute", "none", "IS_EBILL", False)],
    "NetworkKPI": [("KPIID", "integer", "identifier", "none", "KPI_ID", False), ("CallAttempts", "integer", "fact", "total", "CALL_ATTEMPTS", False),
                   ("DroppedCalls", "integer", "fact", "total", "DROPPED_CALLS", False),
                   ("DropCallRatePct", "decimal", "fact", "calculated",
                    f"case when {P('NetworkKPI', 'CALL_ATTEMPTS')} = 0 then null else {P('NetworkKPI', 'DROPPED_CALLS')} / {P('NetworkKPI', 'CALL_ATTEMPTS')} * 100 end", False),
                   ("AvgThroughputMbps", "decimal", "fact", "average", "AVG_THROUGHPUT_MBPS", False),
                   ("PeakUtilizationPct", "decimal", "fact", "maximum", "PEAK_UTILIZATION_PCT", False),
                   ("TrafficGB", "decimal", "fact", "total", "TRAFFIC_GB", False),
                   ("AvailabilityPct", "decimal", "fact", "average", "AVAILABILITY_PCT", False)],
}

RELS = [("Subscriber", "Account", "ACCOUNT_ID", "ACCOUNT_ID"), ("Subscriber", "Location", "LOCATION_ID", "LOCATION_ID"),
        ("Subscriber", "Plan", "PLAN_ID", "PLAN_ID"), ("Device", "Subscriber", "SUBSCRIBER_ID", "SUBSCRIBER_ID"),
        ("CellSite", "Location", "LOCATION_ID", "LOCATION_ID"), ("UsageRecord", "Subscriber", "SUBSCRIBER_ID", "SUBSCRIBER_ID"),
        ("UsageRecord", "CellSite", "CELL_ID", "CELL_ID"), ("UsageRecord", "Date", "DATE_KEY", "DATE_KEY"),
        ("Invoice", "Account", "ACCOUNT_ID", "ACCOUNT_ID"), ("Invoice", "Date", "INVOICE_DATE_KEY", "DATE_KEY"),
        ("NetworkKPI", "CellSite", "CELL_ID", "CELL_ID"), ("NetworkKPI", "Date", "DATE_KEY", "DATE_KEY")]

FOLDERS = {"Subscribers and Accounts": ["Subscriber", "Account", "Plan", "Device", "Location"],
           "Usage and Traffic": ["UsageRecord", "Date"], "Billing and Revenue": ["Invoice", "Date"],
           "Network Performance": ["NetworkKPI", "CellSite", "Location", "Date"]}

PACKAGES = {  # report package -> (short code, display, source system, data modules)
    "Telco_Network_Package": ("NET", "Network Operations", "Teradata - NETWORK_PERF_DW", ["RAN_Performance_DM", "Network_Incidents_DM"]),
    "Telco_Billing_Package": ("BIL", "Billing and Revenue", "Oracle - AMDOCS_BILLING_PROD", ["Revenue_Assurance_DM"]),
    "Telco_Customer_Package": ("CUS", "Customer Experience", "Salesforce - SF_TELCO_CRM", ["Churn_Analytics_DM", "Care_Operations_DM"]),
    "Telco_Sales_Package": ("SAL", "Sales and Retail", "SAP HANA - SAP_SD_PROD", ["Retail_Sales_DM"]),
    "Telco_Finance_Package": ("FIN", "Financial Performance", "SAP HANA - SAP_FI_PROD", ["Capex_Planning_DM"]),
    "Telco_Regulatory_Package": ("REG", "Regulatory and Compliance", "SQL Server - REG_COMPLIANCE_DB", []),
}

# --------------------------------------------------------------------------- report themes per package
# theme: (title, query, primary subject, measures [(subject, item)], dims [(subject, item)], literal filters [(subject, item, value)])
T = {
    "Telco_Network_Package": [
        ("Dropped_Call_Rate", "DropCallQuery", [("NetworkKPI", "DroppedCalls"), ("NetworkKPI", "CallAttempts"), ("NetworkKPI", "DropCallRatePct")],
         [("CellSite", "Technology"), ("Location", "Market")], []),
        ("Cell_Throughput", "ThroughputQuery", [("NetworkKPI", "AvgThroughputMbps"), ("NetworkKPI", "TrafficGB")],
         [("CellSite", "SiteName"), ("CellSite", "Technology")], []),
        ("Network_Availability", "AvailabilityQuery", [("NetworkKPI", "AvailabilityPct")], [("CellSite", "SiteVendor"), ("Location", "Region")], []),
        ("Peak_Cell_Utilization", "UtilizationQuery", [("NetworkKPI", "PeakUtilizationPct"), ("CellSite", "CapacityMbps")],
         [("CellSite", "SiteName"), ("Location", "Market")], []),
        ("5G_Traffic_Share", "TrafficQuery", [("NetworkKPI", "TrafficGB")], [("CellSite", "Technology")], [("CellSite", "Technology", "5G NR")]),
        ("Trouble_Ticket_Backlog", "TicketQuery", [("TroubleTicket", "TicketCount"), ("TroubleTicket", "ResolutionHours")],
         [("TroubleTicket", "TicketPriority"), ("TroubleTicket", "TicketStatus")], []),
        ("Critical_Ticket_SLA", "TicketSLAQuery", [("TroubleTicket", "TicketCount"), ("TroubleTicket", "ResolutionHours")],
         [("TroubleTicket", "TicketStatus")], [("TroubleTicket", "TicketPriority", "P1")]),
        ("Network_Outage_Impact", "OutageQuery", [("NetworkOutage", "SubscribersAffected"), ("NetworkOutage", "OutageMinutes")],
         [("NetworkOutage", "OutageCause"), ("Location", "Region")], []),
        ("Site_Vendor_Performance", "VendorQuery", [("NetworkKPI", "DropCallRatePct"), ("NetworkKPI", "AvailabilityPct")],
         [("CellSite", "SiteVendor")], []),
        ("Data_Traffic_Growth", "TrafficGrowthQuery", [("NetworkKPI", "TrafficGB"), ("UsageRecord", "DataGB")], [("Location", "Region")], []),
    ],
    "Telco_Billing_Package": [
        ("Monthly_Invoice_Summary", "InvoiceQuery", [("Invoice", "InvoiceAmount"), ("Invoice", "TaxAmount"), ("Invoice", "DiscountAmount")],
         [("Account", "AccountType"), ("Location", "Region")], []),
        ("Overdue_Receivables", "OverdueQuery", [("Invoice", "InvoiceAmount")], [("Account", "AccountName"), ("Invoice", "PaymentStatus")],
         [("Invoice", "PaymentStatus", "Overdue")]),
        ("Roaming_Revenue", "RoamingQuery", [("Invoice", "RoamingCharge"), ("UsageRecord", "UsageRevenue")], [("Location", "Market")],
         [("UsageRecord", "RoamingFlag", "Y")]),
        ("Usage_Revenue_by_Plan", "UsageRevenueQuery", [("UsageRecord", "UsageRevenue"), ("UsageRecord", "DataGB"), ("UsageRecord", "VoiceMinutes")],
         [("Plan", "PlanName"), ("Plan", "PlanType")], []),
        ("ARPU_by_Segment", "ARPUQuery", [("Invoice", "InvoiceAmount"), ("Plan", "MonthlyFee")], [("Subscriber", "CustomerSegment")], []),
        ("Discount_Leakage", "DiscountQuery", [("Invoice", "DiscountAmount"), ("Invoice", "InvoiceAmount")], [("Plan", "PlanType")], []),
        ("eBill_Adoption", "EBillQuery", [("Invoice", "InvoiceAmount")], [("Invoice", "IsEBill"), ("Account", "BillingCycle")], []),
        ("USF_Contribution", "USFQuery", [("Invoice", "USFContribution"), ("Invoice", "TotalInvoiceWithTax")], [("Location", "StateProvince")], []),
        ("Revenue_Assurance_Variance", "RAQuery", [("Invoice", "InvoiceAmount"), ("UsageRecord", "UsageRevenue")], [("Plan", "PlanName")], []),
        ("Prepaid_Topup_Summary", "TopupQuery", [("UsageRecord", "UsageRevenue")], [("Subscriber", "IsPrepaid")], [("Subscriber", "IsPrepaid", "Y")]),
    ],
    "Telco_Customer_Package": [
        ("Churn_Rate_Trend", "ChurnQuery", [("ChurnEvent", "ChurnedSubscribers"), ("ChurnEvent", "ChurnRatePct")],
         [("Subscriber", "CustomerSegment"), ("Location", "Region")], []),
        ("Churn_Reasons", "ChurnReasonQuery", [("ChurnEvent", "ChurnedSubscribers")], [("ChurnEvent", "ChurnReason")], []),
        ("Postpaid_Churn", "PostpaidChurnQuery", [("ChurnEvent", "ChurnedSubscribers"), ("ChurnEvent", "ChurnRatePct")],
         [("Plan", "PlanType")], [("Subscriber", "IsPrepaid", "N")]),
        ("Care_Contact_Volume", "CareQuery", [("CareInteraction", "InteractionCount"), ("CareInteraction", "HandleTimeMin")],
         [("CareInteraction", "Channel"), ("CareInteraction", "ContactReason")], []),
        ("First_Contact_Resolution", "FCRQuery", [("CareInteraction", "FirstContactResolutionPct"), ("CareInteraction", "InteractionCount")],
         [("CareInteraction", "Channel")], []),
        ("NPS_Scorecard", "NPSQuery", [("NPSSurvey", "NPSScore"), ("NPSSurvey", "ResponseCount")], [("Subscriber", "CustomerSegment"), ("Location", "Market")], []),
        ("Subscriber_Base", "SubscriberQuery", [("Subscriber", "SubscriberCount")], [("Subscriber", "SubscriberStatus"), ("Plan", "PlanType")], []),
        ("Device_Mix", "DeviceQuery", [("Subscriber", "SubscriberCount")], [("Device", "Manufacturer"), ("Device", "Is5GCapable")], []),
        ("High_Value_At_Risk", "AtRiskQuery", [("ChurnEvent", "ChurnRatePct"), ("Invoice", "InvoiceAmount")],
         [("Subscriber", "CustomerSegment"), ("Subscriber", "CreditScore")], [("Subscriber", "CustomerSegment", "Business")]),
        ("Data_Usage_per_Subscriber", "DataUsageQuery", [("UsageRecord", "DataGB"), ("UsageRecord", "DataMB")], [("Plan", "PlanName")], []),
    ],
    "Telco_Sales_Package": [
        ("Gross_Adds", "GrossAddsQuery", [("SalesOrder", "Units"), ("SalesOrder", "OrderValue")], [("SalesOrder", "OrderChannel"), ("Location", "Region")], []),
        ("Store_Performance", "StoreQuery", [("SalesOrder", "OrderValue"), ("SalesOrder", "Units")], [("Store", "StoreName"), ("Store", "StoreType")], []),
        ("Device_Sales", "DeviceSalesQuery", [("SalesOrder", "Units"), ("SalesOrder", "OrderValue")], [("Device", "Manufacturer"), ("Device", "DeviceModel")], []),
        ("Promotion_Effectiveness", "PromoQuery", [("Promotion", "DiscountPct"), ("SalesOrder", "OrderValue")], [("Promotion", "PromoName")], []),
        ("Online_Orders", "OnlineQuery", [("SalesOrder", "Units"), ("SalesOrder", "OrderValue")], [("SalesOrder", "OrderStatus")],
         [("SalesOrder", "OrderChannel", "Online")]),
        ("Order_Fallout", "FalloutQuery", [("SalesOrder", "Units")], [("SalesOrder", "OrderStatus"), ("SalesOrder", "OrderChannel")],
         [("SalesOrder", "OrderStatus", "Cancelled")]),
        ("5G_Device_Attach", "AttachQuery", [("SalesOrder", "Units")], [("Device", "Is5GCapable"), ("Plan", "PlanName")], []),
        ("Plan_Mix_of_Sales", "PlanMixQuery", [("SalesOrder", "Units"), ("Plan", "MonthlyFee")], [("Plan", "PlanType")], []),
    ],
    "Telco_Finance_Package": [
        ("Budget_vs_Actual", "BudgetQuery", [("BudgetActual", "BudgetAmount"), ("BudgetActual", "ActualAmount"), ("BudgetActual", "VarianceAmount")],
         [("BudgetActual", "CostCenter"), ("BudgetActual", "GLAccount")], []),
        ("Opex_Variance", "OpexQuery", [("BudgetActual", "VarianceAmount"), ("BudgetActual", "VariancePct")], [("BudgetActual", "CostCenter")], []),
        ("Network_Capex", "CapexQuery", [("CapexProject", "CapexSpend"), ("CapexProject", "BudgetedCapex"), ("CapexProject", "SitesDeployed")],
         [("CapexProject", "ProjectName"), ("CapexProject", "ProgramType")], []),
        ("5G_Rollout_Spend", "RolloutQuery", [("CapexProject", "CapexSpend"), ("CapexProject", "SitesDeployed")], [("Location", "Region")],
         [("CapexProject", "ProgramType", "5G Rollout")]),
        ("Revenue_by_Product_Line", "RevenueQuery", [("Invoice", "InvoiceAmount"), ("UsageRecord", "UsageRevenue")], [("Plan", "PlanType")], []),
        ("Cost_per_GB", "CostPerGBQuery", [("BudgetActual", "ActualAmount"), ("NetworkKPI", "TrafficGB")], [("Location", "Region")], []),
        ("EBITDA_Bridge", "EBITDAQuery", [("BudgetActual", "ActualAmount"), ("BudgetActual", "BudgetAmount")], [("BudgetActual", "GLAccount")], []),
    ],
    "Telco_Regulatory_Package": [
        ("E911_Call_Performance", "E911Query", [("E911Call", "CallCount"), ("E911Call", "AvgAnswerSeconds"), ("E911Call", "LocationAccuracyPct")],
         [("Location", "StateProvince")], []),
        ("CPNI_Request_Log", "CPNIQuery", [("CPNIRequest", "RequestCount"), ("CPNIRequest", "DaysToFulfil")], [("CPNIRequest", "RequestType")], []),
        ("Compliance_Case_Register", "CaseQuery", [("ComplianceCase", "CaseCount"), ("ComplianceCase", "PenaltyAmount")],
         [("ComplianceCase", "Regulator"), ("ComplianceCase", "CaseStatus")], []),
        ("FCC_Outage_Reporting", "FCCOutageQuery", [("NetworkOutage", "SubscribersAffected"), ("NetworkOutage", "OutageMinutes")],
         [("NetworkOutage", "OutageCause")], [("NetworkOutage", "IsReportable", "Y")]),
        ("Lawful_Intercept_Volumes", "LIQuery", [("CPNIRequest", "RequestCount")], [("CPNIRequest", "RequestType")], [("CPNIRequest", "RequestType", "Lawful Intercept")]),
        ("Accessibility_Compliance", "AccessQuery", [("ComplianceCase", "CaseCount")], [("ComplianceCase", "CaseType")], []),
    ],
}

# grain variants: suffix, date items, extra dims flag
VARIANTS = [
    ("Daily", ["FullDate"], True), ("Weekly", ["ISOWeek", "FiscalYear"], True), ("Monthly", ["MonthName", "FiscalYear"], True),
    ("Quarterly", ["Quarter", "FiscalYear"], False), ("by_Region", ["MonthName", "FiscalYear"], "region"),
    ("Executive_Summary", ["FiscalYear"], False), ("Trend", ["MonthName", "MonthNumber", "FiscalYear"], False),
]
DATED = {"NetworkKPI", "UsageRecord", "Invoice", "TroubleTicket", "NetworkOutage", "ChurnEvent", "CareInteraction", "NPSSurvey",
         "SalesOrder", "BudgetActual", "CapexProject", "E911Call", "CPNIRequest", "ComplianceCase", "Promotion"}
NON_ADDITIVE = {"DropCallRatePct", "AvgThroughputMbps", "AvailabilityPct", "PeakUtilizationPct", "CapacityMbps", "MonthlyFee",
                "ChurnRatePct", "FirstContactResolutionPct", "NPSScore", "HandleTimeMin", "ResolutionHours", "DiscountPct",
                "VariancePct", "AvgAnswerSeconds", "LocationAccuracyPct", "DaysToFulfil"}


def build_reports(rng: random.Random) -> list[dict]:
    reports = []
    for pkg, themes in T.items():
        code = PACKAGES[pkg][0]
        n = 0
        for title, query, measures, dims, lits in themes:
            k = rng.randint(3, 6) if len(themes) > 6 else rng.randint(5, 7)
            for suffix, date_items, extra in rng.sample(VARIANTS, k):
                n += 1
                name = f"{title}_{suffix}"
                # some variants report only part of the theme's KPIs -> consolidation candidates
                ms = measures if len(measures) == 1 or rng.random() < 0.6 else rng.sample(measures, rng.randint(1, len(measures) - 1))
                ds = list(dims) if extra is True else dims[:1] if extra is False else [("Location", "Region")] + dims[:1]
                items = []
                if any(s in DATED for s, _ in ms):
                    items += [("Date", d) for d in date_items]
                items += [d for d in ds if d not in items]
                items += ms
                filters = []
                if any(s in DATED for s, _ in ms):
                    r = rng.random()
                    if r < 0.08:
                        filters.append(f"[{pkg}].[Date].[FiscalYear] = ?p_Region?")          # prompt type mismatch
                    elif r < 0.11:
                        filters.append(f"[{pkg}].[Date].[FiscalYear] = 'FY2026'")           # string literal on integer
                    elif r < 0.13:
                        filters.append(f"[{pkg}].[Location].[Region] in ?p_Region")          # malformed prompt
                    else:
                        filters.append(f"[{pkg}].[Date].[FiscalYear] = ?p_FiscalYear?")
                if lits and rng.random() < 0.85:
                    s, i, v = lits[0]
                    filters.append(f"[{pkg}].[{s}].[{i}] = '{v}'")
                if rng.random() < 0.12:
                    filters.append(f"[{pkg}].[Location].[Market] = ?p_Market?")
                typ = rng.choice("LLLCCX")
                reports.append({"name": name, "package": pkg, "code": code, "query": query, "type": typ, "items": items,
                                "filters": filters, "group": f"{code}_{n:03d}", "title": title, "suffix": suffix})
    return reports


def data_item_xml(pkg: str, subj: str, item: str, rng: random.Random) -> str:
    fact = item in NON_ADDITIVE or subj in DATED and item not in ("TicketPriority", "TicketStatus", "OutageCause", "ChurnReason",
                                                                   "Channel", "ContactReason", "OrderChannel", "OrderStatus", "PromoName",
                                                                   "CostCenter", "GLAccount", "ProjectName", "ProgramType", "RequestType",
                                                                   "Regulator", "CaseStatus", "CaseType", "IsReportable", "PaymentStatus",
                                                                   "IsEBill", "RoamingFlag") or item.endswith(("Count", "Amount", "Minutes", "GB", "MB",
                                                                                                               "Revenue", "Value", "Units", "Spend",
                                                                                                               "Capex", "Deployed", "Charge", "Fee",
                                                                                                               "Contribution", "Tax", "Subscribers",
                                                                                                               "Affected", "Calls", "Attempts"))
    if subj == "Date" or item in ("Region", "Market", "StateProvince", "CustomerSegment", "Technology", "SiteName", "SiteVendor", "PlanName",
                                  "PlanType", "AccountType", "AccountName", "BillingCycle", "Manufacturer", "DeviceModel", "Is5GCapable",
                                  "SubscriberStatus", "IsPrepaid", "CreditScore", "StoreName", "StoreType"):
        fact = False
    agg = "none"
    if fact:
        agg = "average" if item in NON_ADDITIVE and rng.random() < 0.3 else "total"
    return (f'            <dataItem name="{item}" aggregate="{agg}" rollupAggregate="{agg}">\n'
            f'              <expression>[{pkg}].[{subj}].[{item}]</expression>\n'
            f'              <usage>{"fact" if fact else "attr"}</usage>\n'
            f'            </dataItem>\n')


def report_xml(r: dict, folder: str, rng: random.Random) -> tuple[str, dict]:
    pkg, code = r["package"], r["code"]
    slug = PACKAGES[pkg][1].split()[0].lower()
    if folder == "Active":
        name, sim, qn, path, desc = r["name"], 100, r["query"], f"telco/reports/{slug}/active/{r['name'].lower()}", r["name"].replace("_", " ")
        items = list(r["items"])
    elif folder == "Archive":
        name, sim, qn = f"{r['name']}_Archive", rng.randint(97, 99), f"{r['query']}_Arc"
        path, desc = f"telco/reports/{slug}/archive/{name.lower()}", f"{r['name'].replace('_', ' ')} (Archive Copy)"
        items = list(r["items"])
        if sim == 97 and len(items) > 3:
            items = items[:-1]                    # archive copy missing the last column
    else:
        name, sim, qn = f"{r['name']}_Community", rng.randint(90, 96), f"{r['query']}_Com"
        path, desc = f"telco/reports/community/{name.lower()}", f"{r['name'].replace('_', ' ')} (Community Version)"
        items = list(r["items"])
        if sim <= 92:
            items.append(("Location", "City"))     # community variant adds a column
    body = "".join(data_item_xml(pkg, s, i, rng) for s, i in items)
    if folder == "Active" and rng.random() < 0.03:
        s, i = items[0]
        body += data_item_xml(pkg, s, i, rng)       # duplicate data item name in one query
    flt = ""
    if r["filters"]:
        flt = "          <detailFilters>\n" + "".join(
            f"            <detailFilter>\n              <filterExpression>{escape(f)}</filterExpression>\n            </detailFilter>\n"
            for f in r["filters"]) + "          </detailFilters>\n"
    xml = (f'  <report name="{name}"\n             type="{r["type"]}"\n             package="{pkg}"\n             folder="{folder}"\n'
           f'             reportPath="{path}"\n             duplicateGroupID="{r["group"]}"\n             similarityScore="{sim}"\n'
           f'             cognosVersion="{CV}">\n'
           f'      <reportProperties>\n        <reportName>{name}</reportName>\n        <description>{escape(desc)}</description>\n'
           f'        <reportLocale>en-us</reportLocale>\n      </reportProperties>\n'
           f'      <queries>\n        <query name="{qn}">\n          <source><model/></source>\n          <selection>\n{body}'
           f'          </selection>\n{flt}        </query>\n      </queries>\n    </report>\n')
    meta = {"report_name": name, "report_path": path, "package": pkg, "report_type": {"L": "List", "C": "Crosstab", "X": "Chart"}[r["type"]],
            "folder_category": folder, "duplicate_group_id": r["group"], "similarity_score": sim,
            "is_duplicate": "No" if folder == "Active" else "Yes", "query_name": qn, "column_count": len(items)}
    return xml, meta


def usage_for(reports: list[dict], rng: random.Random) -> dict[str, tuple[float, dt.date, float]]:
    """runs/day, last run date and average duration per report name, with realistic estate patterns."""
    out = {}
    for r in reports:
        profile = rng.random()
        if profile < 0.32:                       # dormant: no copy used within the window -> Retire
            act = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(200, 700)))
            arc = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(220, 900)))
            com = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(200, 800)))
        elif profile < 0.47:                     # stale or low usage -> Review
            act = (round(rng.uniform(0.1, 0.8), 1), EXPORT_DATE - dt.timedelta(days=rng.randint(95, 170)))
            arc = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(200, 600)))
            com = (round(rng.uniform(0, 0.5), 1), EXPORT_DATE - dt.timedelta(days=rng.randint(100, 175)))
        elif profile < 0.55:                     # the active report is idle but its archive copy is busy
            act = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(200, 400)))
            arc = (rng.randint(4, 25), EXPORT_DATE - dt.timedelta(days=rng.randint(0, 10)))
            com = (0, EXPORT_DATE - dt.timedelta(days=rng.randint(250, 500)))
        else:                                    # live
            act = (rng.choice([1, 2, 3, 5, 8, 12, 20, 35, 60]), EXPORT_DATE - dt.timedelta(days=rng.randint(0, 25)))
            arc = (rng.choice([0, 0, 1, 2, 4]), EXPORT_DATE - dt.timedelta(days=rng.randint(0, 300)))
            com = (rng.choice([0, 1, 2, 3, 6]), EXPORT_DATE - dt.timedelta(days=rng.randint(0, 120)))
        for folder, (runs, last) in (("Active", act), ("Archive", arc), ("Community", com)):
            nm = r["name"] if folder == "Active" else f"{r['name']}_{folder}"
            out[nm] = (runs, last, round(rng.uniform(0.6, 14.0), 2))
    return out


# --------------------------------------------------------------------------- FM XML builders
def R(roles) -> str:
    return "".join(f'<role name="{r}"/>' for r in roles)


def fm_package_xml(drift: bool = False) -> str:
    phys = []
    for qs, (table, cols) in PHYS.items():
        qi = "".join(f'        <queryItem name="{c}" dataType="{t}" usage="{u}" regularAggregate="{a}">\n'
                     f'          <expression>{DB}.{table}.{c}</expression>\n        </queryItem>\n' for c, t, u, a in cols)
        phys.append(f'    <querySubject name="DB_{qs}" type="dataSourceQuerySubject" dataSource="{DS}">\n'
                    f'      <dbQuery>SELECT * FROM {DB}.{table}</dbQuery>\n      <queryItems>\n{qi}      </queryItems>\n    </querySubject>\n')
    rels = "".join(f'    <relationship name="{a}_to_{b}" left="DB_{a}" right="DB_{b}" cardinality="n:1" joinType="inner">\n'
                   f'      <joinFilter><expression>[Physical Layer].[DB_{a}].[{ka}] = [Physical Layer].[DB_{b}].[{kb}]</expression></joinFilter>\n'
                   f'    </relationship>\n' for a, b, ka, kb in RELS)
    biz = []
    for qs, items in BIZ.items():
        qi = ""
        for name, t, u, agg, expr, sens in items:
            if drift and qs == "NetworkKPI" and name == "AvailabilityPct":
                agg = "total"                                   # model.xml differs from the published package
            e = expr if expr.startswith(("[", "case")) else P(qs, expr)
            qi += (f'        <queryItem name="{name}" dataType="{t}" usage="{u}" regularAggregate="{agg}">\n'
                   f'          <expression>{escape(e)}</expression>\n'
                   + (f'          <sensitiveData>true</sensitiveData>\n' if sens else "") + '        </queryItem>\n')
        biz.append(f'    <querySubject name="{qs}" type="modelQuerySubject">\n      <queryItems>\n{qi}      </queryItems>\n    </querySubject>\n')
    folders = "".join(f'    <folder name="{f}">\n' + "".join(f'      <item refObject="Business Layer.{q}"/>\n' for q in qs) + '    </folder>\n'
                      for f, qs in FOLDERS.items())
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!--
  FILE    : {"model.xml" if drift else "package.xml"}
  TYPE    : IBM Cognos Framework Manager - {"Model" if drift else "Package Definition"}
  PRODUCT : IBM Cognos Analytics {CV}
  DOMAIN  : Telecommunications (synthetic test estate generated by SemanticLift)
  CREATED : {EXPORT_DATE.isoformat()}
-->
<project xmlns="http://www.developer.cognos.com/schemas/bmt/60/13"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         version="13.0"
         cognosVersion="{CV}">

  <description>Telecommunications Framework Manager Package - Cognos Analytics {CV}</description>
  <lastPublished>{EXPORT_DATE.isoformat()}T00:00:00</lastPublished>

  <governanceMetadata>
    <dataOwner>Telco Data Platform Team</dataOwner>
    <dataSteward>bi-governance@telco-example.com</dataSteward>
    <dataClassification>Confidential - CPNI</dataClassification>
    <dataLineage>
      <source type="OracleDB" system="{DB}" schema="{DB}" refreshCadence="daily"/>
    </dataLineage>
    <retentionPolicy>2 years per FCC CPNI rules; 7 years for financial records</retentionPolicy>
    <lastReviewed>{EXPORT_DATE.isoformat()}</lastReviewed>
    <tags><tag>telco</tag><tag>network</tag><tag>billing</tag><tag>cpni</tag></tags>
  </governanceMetadata>

  <dataSource name="{DS}" type="relational" vendor="Oracle">
    <connection>
      <contentManagerURL>jdbc:oracle:thin:@//telco-dw-host:1521/{DB}</contentManagerURL>
      <schema>{DB}</schema>
      <catalog>{DB}</catalog>
    </connection>
    <isolationLevel>readCommitted</isolationLevel>
  </dataSource>

  <dataModule name="Telco_Analytics_DataModule"
              contentStorePath="//content/folder[@name='Telco Analytics']/dataModule[@name='Telco_Analytics_DM']">
    <description>CA 12 Data Module wrapping the relational model</description>
  </dataModule>

  <namespace name="Physical Layer">
    <description>Direct mappings to {DB} relational tables</description>
{"".join(phys)}  </namespace>

  <relationships>
{rels}  </relationships>

  <namespace name="Business Layer">
    <description>Business-friendly names, calculated items and governance annotations</description>
{"".join(biz)}
    <parameterMap name="CommonPrompts">
      <parameter name="p_FiscalYear" dataType="integer" defaultValue="2026"/>
      <parameter name="p_Region"     dataType="string"  defaultValue="All" multiSelect="true"/>
      <parameter name="p_Market"     dataType="string"  defaultValue="All" multiSelect="true"/>
    </parameterMap>
  </namespace>

  <namespace name="{FM_PKG}">
    <description>Presentation namespace exposed to report authors.</description>
{folders}  </namespace>

  <security>
    <rowLevelSecurity>
      <securityFilter name="MarketFilter" targetQuerySubject="Business Layer.Location">
        <expression>[Business Layer].[Location].[Market] in (select MARKET from {DB}.USER_MARKET_ACCESS where USERNAME = session_user())</expression>
      </securityFilter>
    </rowLevelSecurity>
    <objectLevelSecurity>
      <securedObject name="Business Layer.Invoice.InvoiceAmount">
        <allowedRoles><role name="Finance_Analysts"/><role name="Billing_Analysts"/><role name="Report_Admins"/></allowedRoles>
      </securedObject>
      <securedObject name="Business Layer.Subscriber.MSISDN">
        <allowedRoles><role name="Care_Supervisors"/><role name="Fraud_Team"/></allowedRoles>
        <masking>
          <maskingRule>
            <maskedValue>XXX-XXX-####</maskedValue>
            <applyToRoles><role name="Report_Viewers"/><role name="Retail_Store_Staff"/></applyToRoles>
          </maskingRule>
        </masking>
      </securedObject>
    </objectLevelSecurity>
    <attributeBasedAccessControl>
      <policy name="CPNIProtectionPolicy">
        <condition>user.cpniTraining = 'expired'</condition>
        <effect>deny</effect>
        <targets>
          <target refObject="Business Layer.Subscriber.MSISDN"/>
          <target refObject="Business Layer.Subscriber.CreditScore"/>
        </targets>
      </policy>
    </attributeBasedAccessControl>
  </security>

  <publishSettings>
    <contentStoreFolder>//content/folder[@name='Telco Analytics']</contentStoreFolder>
    <packageName>{FM_PKG}</packageName>
    <description>Telecommunications data package for Cognos Analytics {CV}</description>
    <includedNamespaces><namespace refName="{FM_PKG}"/></includedNamespaces>
  </publishSettings>

</project>
'''


def cpf_xml() -> str:
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://www.developer.cognos.com/schemas/bmt/60/13" version="13.0" cognosVersion="{CV}"
         created="{EXPORT_DATE.isoformat()}T00:00:00" createdBy="admin">
  <projectName>{FM_PKG}</projectName>
  <description>Telecommunications Framework Manager project: subscribers, usage, billing and network performance.</description>
  <locale>en-us</locale>
  <projectFiles>
    <file type="model" path="model/model.xml"/>
    <file type="datasource" path="datasources/{DS}.ds"/>
    <file type="security" path="security/rowlevelsecurity.xml"/>
    <file type="security" path="security/objectlevelsecurity.xml"/>
    <file type="parametermap" path="parametermaps/CommonPrompts.xml"/>
    <file type="publishsettings" path="publish/publishsettings.xml"/>
    <file type="namespace" path="namespaces/Physical_Layer.ns"/>
    <file type="namespace" path="namespaces/Business_Layer.ns"/>
    <file type="namespace" path="namespaces/{FM_PKG}.ns"/>
  </projectFiles>
  <namespaces>
    <namespace name="Physical Layer" type="physical" file="namespaces/Physical_Layer.ns"/>
    <namespace name="Business Layer" type="business" file="namespaces/Business_Layer.ns"/>
    <namespace name="{FM_PKG}" type="presentation" file="namespaces/{FM_PKG}.ns"/>
  </namespaces>
  <dataSources><dataSource name="{DS}" file="datasources/{DS}.ds"/></dataSources>
</project>
'''


def ns_xml(kind: str) -> str:
    if kind == "physical":
        qss = "".join(f'    <querySubject name="DB_{q}" type="dataSourceQuerySubject" dataSource="{DS}" table="{DB}.{t}" itemCount="{len(c)}"/>\n'
                      for q, (t, c) in PHYS.items())
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<namespace xmlns="http://www.developer.cognos.com/schemas/bmt/namespace/13/" '
                f'name="Physical Layer" type="physical" cognosVersion="{CV}">\n  <querySubjects>\n{qss}  </querySubjects>\n'
                f'  <relationshipCount>{len(RELS)}</relationshipCount>\n</namespace>\n')
    if kind == "business":
        qss = "".join(f'    <querySubject name="{q}" type="modelQuerySubject" sourceNamespace="Physical Layer" itemCount="{len(i)}"/>\n'
                      for q, i in BIZ.items())
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n<namespace xmlns="http://www.developer.cognos.com/schemas/bmt/namespace/13/" '
                f'name="Business Layer" type="business" cognosVersion="{CV}">\n  <querySubjects>\n{qss}  </querySubjects>\n</namespace>\n')
    flds = "".join(f'    <folder name="{f}">\n' + "".join(f'      <item refNamespace="Business Layer" refQuerySubject="{q}"/>\n' for q in qs)
                   + '    </folder>\n' for f, qs in FOLDERS.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<namespace xmlns="http://www.developer.cognos.com/schemas/bmt/namespace/13/" '
            f'name="{FM_PKG}" type="presentation" cognosVersion="{CV}">\n  <folders>\n{flds}  </folders>\n</namespace>\n')


def ds_xml() -> str:
    tables = "".join(f'    <table schema="{DB}" name="{t}"/>\n' for t, _ in PHYS.values()) + f'    <table schema="{DB}" name="USER_MARKET_ACCESS"/>\n'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<dataSourceConnection xmlns="http://www.developer.cognos.com/schemas/bmt/datasource/13/" cognosVersion="{CV}" name="{DS}">
  <description>Oracle 19c data warehouse - telecommunications</description>
  <connectionType>relational</connectionType>
  <vendor>Oracle</vendor>
  <vendorVersion>19c</vendorVersion>
  <jdbcConnection>
    <url>jdbc:oracle:thin:@//telco-dw-host.example.com:1521/{DB}</url>
    <schema>{DB}</schema>
    <catalog>{DB}</catalog>
  </jdbcConnection>
  <tables>
{tables}  </tables>
</dataSourceConnection>
'''


def params_xml() -> str:
    def pl(vals):
        return "    <pickList>\n" + "".join(f'      <item value="{v}" label="{l}"/>\n' for v, l in vals) + "    </pickList>\n"
    p = [("p_FiscalYear", "integer", "false", "true", "2026", "Fiscal Year", pl([(str(y), f"FY{y}") for y in range(2022, 2028)])),
         ("p_Region", "string", "true", "false", "All", "Region(s)", pl([("All", "All Regions")] + [(r, r) for r in ("Northeast", "Southeast", "Central", "Mountain", "Pacific")])),
         ("p_Market", "string", "true", "false", "All", "Market(s)", pl([("All", "All Markets")] + [(m, m) for m in ("New York", "Atlanta", "Chicago", "Denver", "Seattle", "Los Angeles")])),
         ("p_Month", "string", "true", "false", "", "Month(s)", pl([(m, m) for m in ("January", "February", "March", "April", "May", "June", "July",
                                                                                      "August", "September", "October", "November", "December")])),
         ("p_Technology", "string", "true", "false", "All", "Radio technology", pl([("All", "All"), ("4G LTE", "4G LTE"), ("5G NR", "5G NR")])),
         ("p_Segment", "string", "true", "false", "All", "Customer segment", pl([("All", "All"), ("Consumer", "Consumer"), ("Business", "Business"), ("Wholesale", "Wholesale")])),
         ("p_DateFrom", "date", "false", "false", "2026-01-01", "From date", ""),
         ("p_DateTo", "date", "false", "false", "2026-12-31", "To date", "")]
    body = "".join(f'  <parameter name="{n}">\n    <dataType>{t}</dataType>\n    <multiSelect>{ms}</multiSelect>\n    <required>{rq}</required>\n'
                   + (f'    <defaultValue>{dv}</defaultValue>\n' if dv else "") + f'    <promptText>{pt}</promptText>\n{pk}  </parameter>\n'
                   for n, t, ms, rq, dv, pt, pk in p)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<parameterMap xmlns="http://www.developer.cognos.com/schemas/bmt/parametermap/13/" '
            f'name="CommonPrompts" cognosVersion="{CV}">\n  <description>Shared prompts for all telco reports.</description>\n{body}</parameterMap>\n')


def rls_xml() -> str:
    def f(name, qs, expr, applies, exempt, desc):
        return (f'  <securityFilter name="{name}" targetNamespace="Business Layer" targetQuerySubject="{qs}" enabled="true">\n'
                f'    <description>{desc}</description>\n    <expression>{escape(expr)}</expression>\n'
                f'    <appliesTo>{R(applies)}</appliesTo>\n'
                f'    <exemptRoles>{R(exempt)}</exemptRoles>\n  </securityFilter>\n')
    body = (f("MarketFilter", "Location", f"[Business Layer].[Location].[Market] in (select MARKET from {DB}.USER_MARKET_ACCESS where USERNAME = session_user())",
              ["Market_Managers", "Retail_Store_Staff", "Network_Engineers"], ["Report_Admins", "Executive_Viewers"],
              "Market managers and store staff see only their markets.")
            + f("ActiveSubscriberFilter", "Subscriber", "[Business Layer].[Subscriber].[SubscriberStatus] = 'Active'",
                ["Retail_Store_Staff"], ["Report_Admins", "Care_Supervisors"], "Store staff see active subscribers only.")
            + f("CostCenterFilter", "BudgetActual", f"[Business Layer].[BudgetActual].[CostCenter] in (select COST_CENTER from {DB}.USER_COST_CENTER where USERNAME = session_user())",
                ["Finance_Analysts"], ["Finance_Managers", "Report_Admins"], "Finance analysts see their own cost centres.")
            + f("RegulatoryCaseFilter", "ComplianceCase", "[Business Layer].[ComplianceCase].[CaseStatus] <> 'Sealed'",
                ["Compliance_Analysts"], ["Legal_Counsel", "Report_Admins"], "Sealed regulatory cases are visible to legal only."))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<rowLevelSecurity xmlns="http://www.developer.cognos.com/schemas/bmt/security/rls/13/" '
            f'cognosVersion="{CV}">\n{body}</rowLevelSecurity>\n')


def ols_xml() -> str:
    def so(name, qs, item, allowed, denied=()):
        return (f'  <securedObject name="{name}" namespace="Business Layer" querySubject="{qs}" queryItem="{item}">\n'
                f'    <allowedRoles>{R(allowed)}</allowedRoles>\n'
                + (f'    <deniedRoles>{R(denied)}</deniedRoles>\n' if denied else "") + '  </securedObject>\n')

    def cm(name, qs, item, allowed, masked, roles, desc):
        return (f'  <columnMasking name="{name}" namespace="Business Layer" querySubject="{qs}" queryItem="{item}">\n'
                f'    <description>{desc}</description>\n    <allowedRoles>{R(allowed)}</allowedRoles>\n'
                f'    <maskedValue>{masked}</maskedValue>\n    <maskingRoles>{R(roles)}</maskingRoles>\n'
                f'  </columnMasking>\n')
    body = (so("InvoiceAmount", "Invoice", "InvoiceAmount", ["Finance_Analysts", "Finance_Managers", "Billing_Analysts", "Report_Admins"],
               ["Network_Engineers", "Retail_Store_Staff"])
            + so("TotalInvoiceWithTax", "Invoice", "TotalInvoiceWithTax", ["Finance_Analysts", "Finance_Managers", "Report_Admins"])
            + so("PenaltyAmount", "ComplianceCase", "PenaltyAmount", ["Legal_Counsel", "Finance_Managers", "Report_Admins"])
            + cm("MSISDN_Mask", "Subscriber", "MSISDN", ["Care_Supervisors", "Fraud_Team", "Report_Admins"], "XXX-XXX-####",
                 ["Report_Viewers", "Retail_Store_Staff", "Market_Managers"], "Phone numbers are CPNI and masked outside care and fraud teams.")
            + cm("CreditScore_Mask", "Subscriber", "CreditScore", ["Credit_Risk_Team", "Finance_Managers", "Report_Admins"], "*** Restricted ***",
                 ["Retail_Store_Staff", "Market_Managers", "Care_Agents"], "Credit score is masked outside credit risk and finance.")
            + cm("Address_Mask", "Location", "Address", ["Network_Engineers", "Field_Technicians", "Report_Admins"], "[Address Restricted]",
                 ["Report_Viewers", "Finance_Analysts"], "Street address hidden except for field operations."))
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<objectLevelSecurity xmlns="http://www.developer.cognos.com/schemas/bmt/security/ols/13/" '
            f'cognosVersion="{CV}">\n{body}</objectLevelSecurity>\n')


def publish_xml() -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<publishSettings xmlns="http://www.developer.cognos.com/schemas/bmt/publish/13/" cognosVersion="{CV}">\n'
            f"  <contentStoreFolder>//content/folder[@name='Telco Analytics']</contentStoreFolder>\n  <packageName>{FM_PKG}</packageName>\n"
            f'  <includedNamespaces><namespace refName="{FM_PKG}" expose="true"/></includedNamespaces>\n</publishSettings>\n')


# --------------------------------------------------------------------------- workbooks and catalog
def xlsx_bytes(build) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    build(wb)
    for ws in wb.worksheets:
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(48, max(10, *(len(str(c.value or "")) for c in col[:60])))
    buf = io.BytesIO()
    fixed = dt.datetime(2026, 10, 20)
    wb.properties.created = wb.properties.modified = fixed
    wb.save(buf)
    return buf.getvalue()


def main() -> Path:
    rng = random.Random(SEED)
    reports = build_reports(rng)
    usage = usage_for(reports, rng)
    xml_parts, metas = [], []
    by_pkg: dict[str, int] = {}
    for r in reports:
        folders = ["Active"]
        if rng.random() < 0.85:
            folders.append("Archive")
        if rng.random() < 0.7:
            folders.append("Community")
        for folder in folders:
            x, m = report_xml(r, folder, rng)
            xml_parts.append((r["package"], x))
            runs, last, dur = usage[m["report_name"]]
            m.update(runs_per_day=runs, last_run_date=last.strftime("%b %d, %Y 12:00:00 AM"), avg_duration_min=dur)
            metas.append(m)
            by_pkg[r["package"]] = by_pkg.get(r["package"], 0) + 1
    total = len(metas)
    counts = {f: sum(1 for m in metas if m["folder_category"] == f) for f in ("Active", "Archive", "Community")}
    pkg_meta = "".join(f'      <ca:package name="{p}" reports="{n}"/>\n' for p, n in by_pkg.items())
    sections = ""
    for p in PACKAGES:
        sections += f"\n  <!-- PACKAGE: {p} ({by_pkg.get(p, 0)} reports) -->\n" + "".join(x for pk, x in xml_parts if pk == p)
    all_reports = f'''<?xml version="1.0" encoding="UTF-8"?>
<!--
  FILE    : all_reports.xml
  CREATED : {EXPORT_DATE.isoformat()}
  Synthetic Cognos Analytics {CV} content export for a telecommunications operator, generated by
  samples/telco/generate_telco_bundle.py. {counts["Active"]} Active | {counts["Archive"]} Archive | {counts["Community"]} Community.
-->
<contentExport
    xmlns:ca="http://developer.cognos.com/schemas/contentExport/1/"
    cognosVersion="{CV}"
    schemaVersion="report/16"
    exportDate="{EXPORT_DATE.isoformat()}T00:00:00"
    exportedBy="admin"
    totalReports="{total}">

  <ca:metadata>
    <ca:totalReports>{total}</ca:totalReports>
    <ca:activeReports>{counts["Active"]}</ca:activeReports>
    <ca:archiveDuplicates>{counts["Archive"]}</ca:archiveDuplicates>
    <ca:communityDuplicates>{counts["Community"]}</ca:communityDuplicates>
    <ca:packages>
{pkg_meta}    </ca:packages>
  </ca:metadata>
{sections}
</contentExport>
'''
    # FM project zip
    fm = io.BytesIO()
    with zipfile.ZipFile(fm, "w", zipfile.ZIP_DEFLATED) as z:
        for path, content in (("fm_project/package.xml", fm_package_xml()), ("fm_project/model/model.xml", fm_package_xml(drift=True)),
                              (f"fm_project/{FM_PKG}.cpf", cpf_xml()), (f"fm_project/datasources/{DS}.ds", ds_xml()),
                              ("fm_project/namespaces/Physical_Layer.ns", ns_xml("physical")),
                              ("fm_project/namespaces/Business_Layer.ns", ns_xml("business")),
                              (f"fm_project/namespaces/{FM_PKG}.ns", ns_xml("presentation")),
                              ("fm_project/parametermaps/CommonPrompts.xml", params_xml()),
                              ("fm_project/security/rowlevelsecurity.xml", rls_xml()),
                              ("fm_project/security/objectlevelsecurity.xml", ols_xml()),
                              ("fm_project/publish/publishsettings.xml", publish_xml())):
            z.writestr(zipfile.ZipInfo(path, (2026, 10, 20, 0, 0, 0)), content)

    cols = ["report_name", "report_path", "package", "report_type", "folder_category", "duplicate_group_id", "similarity_score",
            "is_duplicate", "query_name", "column_count", "runs_per_day", "last_run_date", "avg_duration_min"]

    def usage_wb(wb):
        ws = wb.active
        ws.title = "Report Usage"
        stated = (total // 50 + 1) * 50                     # the title rounds up, as real audit extracts often do
        ws.append([f"Cognos Analytics {CV} - Telecommunications Report Usage ({stated} reports)"])
        ws.append([f"{counts['Active']} Distinct (Active)  |  {counts['Archive']} Archive Duplicates (97-99% similar)  |  "
                   f"{counts['Community']} Community Duplicates (90-96% similar)  |  Generated: {EXPORT_DATE.isoformat()}"])
        ws.append([])
        ws.append(cols)
        for m in metas:
            ws.append([m[c] for c in cols])

    def mapping_wb(wb):
        ws = wb.active
        ws.title = "Sheet1"
        ws.append(["FM Package/Data Module", "FM Package", "Source Database/System"])
        for p, (_, _, src, _) in PACKAGES.items():
            ws.append([p, p, src])
        for p, (_, _, src, dms) in PACKAGES.items():
            for dm in dms:
                ws.append([dm, p, src])

    cat = io.StringIO()
    w = csv.writer(cat, lineterminator="\n")
    w.writerow(["table_catalog", "table_schema", "table_name", "column_name", "data_type", "row_count"])
    for db, schema, table, cols_, rows in (
            ("NETWORK_PERF_DW", "NETWORK_PERF_DW", "TROUBLE_TICKET", ["TICKET_ID", "TICKET_PRIORITY", "TICKET_STATUS", "TICKET_COUNT", "RESOLUTION_HOURS", "OPENED_DATE"], 4_200_000),
            ("NETWORK_PERF_DW", "NETWORK_PERF_DW", "NETWORK_OUTAGE", ["OUTAGE_ID", "OUTAGE_CAUSE", "SUBSCRIBERS_AFFECTED", "OUTAGE_MINUTES", "IS_REPORTABLE", "START_DATE"], 180_000),
            ("SF_TELCO_CRM", "SF_TELCO_CRM", "CARE_INTERACTION", ["INTERACTION_ID", "CHANNEL", "CONTACT_REASON", "INTERACTION_COUNT", "HANDLE_TIME_MIN", "FIRST_CONTACT_RESOLUTION_PCT"], 65_000_000),
            ("SAP_SD_PROD", "SAP_SD_PROD", "SALES_ORDER", ["ORDER_ID", "ORDER_CHANNEL", "ORDER_STATUS", "UNITS", "ORDER_VALUE", "ORDER_DATE"], 22_000_000)):
        for c in cols_:
            w.writerow([db, schema, table, c, "NUMBER" if c.endswith(("COUNT", "HOURS", "MINUTES", "UNITS", "VALUE", "PCT", "MIN", "AFFECTED")) else "VARCHAR2", rows])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    stamp = (2026, 10, 20, 0, 0, 0)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("FM/telco_fm_package_v12.zip", stamp), fm.getvalue())
        z.writestr(zipfile.ZipInfo("Reports/cognos_content_export_v12/all_reports.xml", stamp), all_reports)
        z.writestr(zipfile.ZipInfo("cognos_report_usage_telco.xlsx", stamp), xlsx_bytes(usage_wb))
        z.writestr(zipfile.ZipInfo("FM_Data_Module_Mapping_Telco.xlsx", stamp), xlsx_bytes(mapping_wb))
        z.writestr(zipfile.ZipInfo("source_catalog_telco.csv", stamp), cat.getvalue())
    print(f"{OUT}: {total} reports ({counts['Active']} active, {counts['Archive']} archive, {counts['Community']} community) "
          f"in {len(PACKAGES)} packages")
    return OUT


if __name__ == "__main__":
    main()
