"""Real sample integration tests; all inline data below are SYNTHETIC edge cases."""
import json
import shutil
from pathlib import Path
import pandas as pd
import pytest
from openpyxl import load_workbook
from src.ingestion import load_json, load_batch
from src.extraction import extract, extract_lab, extract_discharge, Extracted
from src.standardisation import ClinicalMappings
from src.transformation import load_schema, parse_number, parse_range, parse_date, transform
from src.duplicate_detection import detect_duplicates
from src.validation import validate
from src.export import export_data, verify_exports
from src.main import run

BASE = Path(__file__).resolve().parents[1]

@pytest.fixture(scope="module")
def mappings():
    return ClinicalMappings(BASE / "reference/Clinical_name_standardization.xlsx")

@pytest.fixture(scope="module")
def schema():
    return load_schema(BASE / "reference")

@pytest.fixture(scope="module")
def sample_records():
    result = []
    for path in sorted((BASE / "sample-data").glob("*.json")):
        rows, errors = extract(path, load_json(path))
        assert not errors
        result.extend(rows)
    return result

@pytest.mark.parametrize("number,expected", [(1,18),(2,26),(3,18),(4,208),(5,167)])
def test_real_file_loading_and_extraction(number, expected):
    path = BASE / f"sample-data/Sample_JSON_file{number}.json"
    root = load_json(path)
    records, errors = extract(path, root)
    assert not errors and len(records) == expected
    assert all(r.provenance["source"] == root for r in records)
    expected_children = sum(len(s["data"].get("report_details", s["data"].get("dischargeMedications", []))) for s in root["data"]["responseDetails"])
    assert len(records) == expected_children


def test_real_classifiers_and_raw_fields(sample_records):
    assert {r.values["record_type"] for r in sample_records} == {"lab_report", "discharge_summary"}
    labs = [r for r in sample_records if r.values["record_type"] == "lab_report"]
    meds = [r for r in sample_records if r.values["record_type"] == "discharge_summary"]
    assert len(labs) == 363 and len(meds) == 74
    for r in labs:
        for k in ["test_name", "result", "range", "unit", "page_no", "test_analytics"]:
            assert r.values["report_details_" + k] == str(r.provenance["child"][k])
    for r in meds:
        for k in ["medicine", "dose", "frequency"]:
            assert r.values["discharge_medications_" + k] == r.provenance["child"][k]

@pytest.mark.parametrize("value,expected", [(" 1.25 ",1.25),("-2e3",-2000.0),(0,0.0),(".5",.5),("1,000",None),("98.6 degree F",None),("<5",None),("1-2",None),("NaN",None),("Infinity",None),("1e999",None),(True,None),(None,None),("",None)])
def test_synthetic_numbers(value, expected):
    assert parse_number(value) == expected

@pytest.mark.parametrize("value,expected", [("4.5 - 5.5",(4.5,5.5)),("-5--2",(-5.,-2.)),("<50",(None,None)),("5",(None,None)),("9-2",(None,None)),("1e999-2e999",(None,None))])
def test_synthetic_ranges(value, expected):
    assert parse_range(value) == expected

@pytest.mark.parametrize("value,expected,status", [("2025-10-08","2025-10-08","parsed"),("08/Oct/2025","2025-10-08","parsed"),("13-10-2025","2025-10-13","parsed"),("10-13-2025","2025-10-13","parsed"),("09-10-2025","09-10-2025","ambiguous"),("31-02-2025","31-02-2025","invalid_or_unsupported"),("DD/MM/YYYY","DD/MM/YYYY","invalid_or_unsupported"),(None,None,"missing"),("","","missing")])
def test_synthetic_dates(value, expected, status):
    assert parse_date(value) == (expected, status)

@pytest.mark.parametrize("value,canonical", [("  sodium ","SODIUM"),("Na+","SODIUM"),("TOTAL   WBC count","WHITE BLOOD CELL COUNT"),("ALT (SGPT)","ALANINE AMINOTRANSFERASE")])
def test_reference_matching(mappings, value, canonical):
    match = mappings.match(value)
    assert match.canonical == canonical and match.confidence == 1.


def test_conflicts_and_unknowns(mappings):
    for value in ["Hb", "CREATININE"]:
        assert mappings.match(value).method == "ambiguous"
        assert mappings.match(value).canonical is None
    assert mappings.match("invented test").method == "unknown"
    assert mappings.match(None).method == "missing"
    assert mappings.match("SERUM").canonical is None
    assert len([r for r in mappings.review if r["issue"] == "ambiguous_alias_serialization"]) == 3


def test_synthetic_dynamic_reference(tmp_path):
    path = tmp_path / "mapping.xlsx"
    pd.DataFrame([{"test_name_canonical": "SYNTHETIC CANONICAL", "variation_count": 1, "original_test_names": '["synthetic alias"]'}]).to_excel(path, index=False)
    assert ClinicalMappings(path).match("synthetic alias").canonical == "SYNTHETIC CANONICAL"


def test_synthetic_empty_and_null_children():
    assert len(list(extract_lab({"basic_info": {}, "report_details": []}))) == 1
    assert len(list(extract_discharge({"dischargeMedications": None}))) == 1
    with pytest.raises(ValueError):
        list(extract_lab({"report_details": ["bad"]}))
    rows = list(extract_discharge({"dischargeMedications": [{"medicine": "X", "dose": "", "frequency": None}]}))
    assert rows[0][1]["dose"] == "" and rows[0][1]["frequency"] is None


def test_synthetic_invalid_json_isolated(tmp_path):
    (tmp_path / "invalid.json").write_text("{")
    shutil.copy(BASE / "sample-data/Sample_JSON_file1.json", tmp_path / "valid.json")
    sources, errors = load_batch(tmp_path)
    assert len(sources) == 1 and len(errors) == 1
    with pytest.raises(ValueError):
        load_json(tmp_path / "invalid.json")


def test_synthetic_unknown_classifier_and_invalid_section(tmp_path):
    source = {"data": {"responseDetails": [{"classifier": "synthetic_other", "data": {"extra": 1}}, {"data": []}]}}
    rows, issues = extract(tmp_path / "synthetic.json", source)
    assert len(rows) == 1 and len(issues) == 2
    assert rows[0].provenance["source"] == source


def test_real_duplicates_preserved(sample_records):
    before = len(sample_records)
    report = detect_duplicates(sample_records)
    assert len(sample_records) == before
    counts = pd.Series([r["category"] for r in report]).value_counts().to_dict()
    assert counts == {"repeated_name_different_result": 62, "similar_content_different_document": 18, "exact_source_repeat": 13}


def test_real_schema_and_preservation(sample_records, schema, mappings):
    frame, dates, unknown = transform(sample_records, schema, mappings, "2026-11-17T00:00:00+00:00")
    assert frame.shape == (437,78)
    assert not validate(frame, schema, sample_records, mappings)
    assert frame.test_name_canonical.notna().sum() == 60
    assert len(unknown) == 303 and dates
    assert frame.file_gcs_path.isna().all() and frame.unit_canonical.isna().all()
    assert frame.medication_dose.eq("").sum() == 6
    for r, (_, row) in zip(sample_records, frame.iterrows()):
        if r.values["record_type"] == "discharge_summary":
            assert row.medication_name == r.provenance["child"]["medicine"]
    modified = frame.copy()
    modified.loc[0,"medication_name"] = "fabricated"
    assert validate(modified, schema, sample_records, mappings)
    assert validate(frame[list(reversed(frame.columns))], schema, sample_records, mappings)


def test_synthetic_required_and_datatype_validation(schema, mappings):
    record = Extracted({"id":"synthetic", "record_type":"other"}, {})
    frame, _, _ = transform([record], schema, mappings, "2026-11-17T00:00:00Z")
    altered = [dict(c, is_nullable="NO") if c["column_name"] == "patient_name" else c for c in schema]
    assert validate(frame, altered, [record], mappings)
    frame["result_value"] = ["invalid"]
    assert validate(frame, schema, [record], mappings)


def test_synthetic_schema_disagreement(tmp_path):
    shutil.copytree(BASE / "reference", tmp_path / "reference")
    path = tmp_path / "reference/Ourput-table-ideal-schema.csv"
    path.write_text(path.read_text().replace("id,STRING,YES", "wrong,STRING,YES", 1))
    with pytest.raises(ValueError, match="disagree"):
        load_schema(path.parent)


def test_synthetic_csv_excel_export(tmp_path, schema, mappings):
    record = Extracted({"id":"synthetic", "record_type":"other", "patient_name":"=1+1", "age":"", "gender":None}, {})
    frame, _, _ = transform([record], schema, mappings, "2026-11-17T00:00:00Z")
    paths = export_data(frame, tmp_path)
    verify_exports(frame, paths)
    csv = pd.read_csv(paths[0], keep_default_na=False, dtype=str)
    assert csv.loc[0,"age"] == "" and csv.loc[0,"gender"] == r"\N"
    cell = load_workbook(paths[1]).active.cell(2,12)
    assert cell.value == "=1+1" and cell.data_type == "s"


def test_real_pipeline_end_to_end(tmp_path):
    shutil.copytree(BASE / "sample-data", tmp_path / "input")
    shutil.copytree(BASE / "reference", tmp_path / "reference")
    report = run(tmp_path)
    assert report["status"] == "PASS" and report["validation_errors"] == 0
    assert report["output_rows"] == 437
    assert len((tmp_path / "reports/provenance.jsonl").read_text(encoding="utf-8").splitlines()) == 437
    assert len((tmp_path / "reports/source_archive.jsonl").read_text(encoding="utf-8").splitlines()) == 5
    for filename in ["validation_report.txt", "unknown_test_names.csv", "ambiguous_mappings.csv", "duplicate_records.csv"]:
        assert (tmp_path / "reports" / filename).exists()


def test_synthetic_date_tampering_detected(sample_records, schema, mappings):
    frame, _, _ = transform(sample_records, schema, mappings, "2026-11-17T00:00:00Z")
    frame.loc[0, "admission_date"] = "2025-09-10"
    assert any("unsafe date conversion" in e for e in validate(frame, schema, sample_records, mappings))


def test_synthetic_excel_length_refuses_truncation(tmp_path, schema, mappings):
    record = Extracted({"id":"synthetic", "record_type":"other", "patient_name":"X" * 32768}, {})
    frame, _, _ = transform([record], schema, mappings, "2026-11-17T00:00:00Z")
    with pytest.raises(ValueError, match="refusing truncation"):
        export_data(frame, tmp_path)
