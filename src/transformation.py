"""Conservative numeric and date parsing and exact-schema projection."""
import math
import re
from datetime import datetime
from pathlib import Path
import pandas as pd

NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def parse_number(value):
    if value is None or isinstance(value, bool):
        return None
    raw = str(value).strip()
    if not re.fullmatch(NUMBER, raw):
        return None
    result = float(raw)
    return result if math.isfinite(result) else None


def parse_range(value):
    match = re.fullmatch(rf"\s*({NUMBER})\s*-\s*({NUMBER})\s*", str(value))
    if match:
        low, high = map(parse_number, match.groups())
        if low is not None and high is not None and low <= high:
            return low, high
    return None, None


def parse_date(value):
    if value is None or not str(value).strip():
        return value, "missing"
    raw = str(value).strip()
    formats = ["%Y-%m-%d", "%d/%b/%Y", "%d-%b-%Y", "%d/%B/%Y", "%d-%B-%Y"]
    if re.fullmatch(r"[0-9]{2}[-/][0-9]{2}[-/][0-9]{4}", raw):
        sep = "/" if "/" in raw else "-"
        formats = [f"%d{sep}%m{sep}%Y", f"%m{sep}%d{sep}%Y"]
    dates = set()
    for fmt in formats:
        try:
            dates.add(datetime.strptime(raw, fmt).date().isoformat())
        except ValueError:
            pass
    if len(dates) == 1:
        return dates.pop(), "parsed"
    return value, "ambiguous" if dates else "invalid_or_unsupported"


def load_schema(folder: Path):
    xlsx = pd.read_excel(folder / "Ourput-table-ideal-schema.xlsx", engine="openpyxl", dtype=str)
    csv = pd.read_csv(folder / "Ourput-table-ideal-schema.csv", dtype=str)
    if not xlsx.equals(csv):
        raise ValueError("Schema XLSX and CSV disagree")
    if list(xlsx.columns) != ["column_name", "data_type", "is_nullable"] or len(xlsx) != 78 or xlsx.column_name.duplicated().any():
        raise ValueError("Expected exactly 78 distinct schema columns")
    if not set(xlsx.data_type).issubset({"STRING", "FLOAT64", "TIMESTAMP"}):
        raise ValueError("Unsupported schema type")
    return xlsx.to_dict("records")


def transform(records, schema, mappings, timestamp):
    columns = [c["column_name"] for c in schema]
    rows, date_review, unknown = [], [], []
    for record in records:
        v = dict(record.values)
        kind = v.get("record_type")
        v.update(processed_at=timestamp, ingested_at=timestamp)
        v["age_text"] = v.get("age")
        if kind == "lab_report":
            original = v.get("report_details_test_name")
            match = mappings.match(original)
            v.update(test_name_original=original, test_name_canonical=match.canonical,
                     normalization_method=match.method, normalization_confidence=match.confidence)
            if match.method in {"unknown", "ambiguous"}:
                unknown.append({"id": v["id"], "file": record.provenance["file"], "test_name_original": original, "reason": match.method})
            raw = v.get("report_details_result")
            v.update(result_value=parse_number(raw), result_text=raw, result_text_original=raw,
                     unit_original=v.get("report_details_unit"), unit_canonical=None,
                     range_text=v.get("report_details_range"), range_text_original=v.get("report_details_range"))
            v["range_low"], v["range_high"] = parse_range(v.get("range_text"))
            for field in ["page_number", "page_no"]:
                v[field] = v.get("report_details_page_no")
            v["report_date"] = v.get("reports_date")
        elif kind == "discharge_summary":
            for field in ["medication_name", "medication_medicine"]:
                v[field] = v.get("medicine")
            v["medication_dose"] = v.get("dose")
            v["medication_frequency"] = v.get("frequency")
            v["other_med_inj_investigations"] = v.get("medicine_injections_investigation")
            v["course_during_hospitalization"] = v.get("course_during_hospitalisation")
        for field in ["bill_date", "reports_date", "report_date", "admission_date", "discharge_date"]:
            if field in v:
                v[field], status = parse_date(v[field])
                if status not in {"parsed", "missing"}:
                    date_review.append({"id": v["id"], "field": field, "original": record.values.get(field, record.values.get("reports_date")), "status": status})
        rows.append({column: v.get(column) for column in columns})
    frame = pd.DataFrame(rows, columns=columns)
    for c in schema:
        name = c["column_name"]
        if c["data_type"] == "FLOAT64":
            frame[name] = pd.array(frame[name], dtype="Float64")
        elif c["data_type"] == "STRING":
            frame[name] = pd.array(frame[name], dtype="string")
        else:
            frame[name] = pd.to_datetime(frame[name], utc=True)
    return frame, date_review, unknown
