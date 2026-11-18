"""Schema checks plus source-to-output preservation and mapping invariants."""
import math
import pandas as pd
from .transformation import parse_number, parse_range, parse_date


def validate(frame, schema, records, mappings):
    errors = []
    if list(frame.columns) != [c["column_name"] for c in schema]:
        return ["Output columns/order differ from reference"]
    if len(frame) != len(records):
        errors.append("Extracted/output row count mismatch")
    for c in schema:
        name, dtype = c["column_name"], c["data_type"]
        series = frame[name]
        if c["is_nullable"] != "YES" and series.isna().any():
            errors.append(f"{name}: prohibited null")
        for value in series.dropna():
            if dtype == "STRING" and not isinstance(value, str):
                errors.append(f"{name}: expected STRING")
            elif dtype == "FLOAT64" and (isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value)):
                errors.append(f"{name}: invalid FLOAT64")
            elif dtype == "TIMESTAMP" and not isinstance(value, pd.Timestamp):
                errors.append(f"{name}: invalid TIMESTAMP")
    for (_, row), record in zip(frame.iterrows(), records):
        def equal(a, b):
            return (pd.isna(a) and b is None) or (not pd.isna(a) and a == b)
        for field in ["document_id", "trace_id", "correlation_id", "patient_name", "age", "gender", "metadetails",
                      "diagnosis", "brief_history", "general_examinations", "hospital_address", "doctor_name",
                      "post_discharge_advice", "recommendations", "ward", "medicine_injections_investigation",
                      "course_during_hospitalisation"]:
            if not equal(row[field], record.values.get(field)):
                errors.append(f"{row.id}: lost source {field}")
        for field in ["bill_date", "reports_date", "report_date", "admission_date", "discharge_date"]:
            original = record.values.get(field)
            if field == "report_date" and row.record_type == "lab_report":
                original = record.values.get("reports_date")
            expected_date, date_status = parse_date(original)
            if not equal(row[field], expected_date):
                errors.append(f"{row.id}: unsafe date conversion {field}")
            if date_status == "parsed":
                try:
                    __import__("datetime").date.fromisoformat(row[field])
                except (ValueError, TypeError):
                    errors.append(f"{row.id}: invalid parsed date {field}")
        if row.record_type == "lab_report":
            for raw, target in [("test_name", "test_name_original"), ("result", "result_text_original"), ("unit", "unit_original"), ("range", "range_text_original"), ("page_no", "report_details_page_no")]:
                if not equal(row[target], record.values.get(raw)):
                    errors.append(f"{row.id}: lost lab {target}")
            expected = mappings.match(record.values.get("test_name"))
            if not equal(row.test_name_canonical, expected.canonical) or row.normalization_method != expected.method:
                errors.append(f"{row.id}: mapping mismatch")
            if not equal(row.result_value, parse_number(record.values.get("result"))):
                errors.append(f"{row.id}: unsupported numeric result")
            low, high = parse_range(record.values.get("range"))
            if not equal(row.range_low, low) or not equal(row.range_high, high):
                errors.append(f"{row.id}: unsupported range conversion")
            if pd.notna(row.unit_canonical):
                errors.append(f"{row.id}: unsupported canonical unit")
        if row.record_type == "discharge_summary":
            for source, target in [("medicine", "medication_name"), ("dose", "medication_dose"), ("frequency", "medication_frequency"), ("medicine_type", "medicine_type")]:
                if not equal(row[target], record.values.get(source)):
                    errors.append(f"{row.id}: lost medication {target}")
    return errors
