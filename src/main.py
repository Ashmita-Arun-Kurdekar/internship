"""Batch entry point: python -m src.main."""
import argparse
import json
import logging
import hashlib
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .ingestion import load_batch
from .extraction import extract
from .standardisation import ClinicalMappings
from .transformation import load_schema, transform
from .duplicate_detection import detect_duplicates
from .validation import validate
from .export import export_data, verify_exports
from .configuration import load_config
from .clinical import enrich, add_config_aliases, validate_enrichment
from .database import load_database, stable_timestamps
from .wide_export import build_wide
from .operations import configure_logging, capture_dead_letters, metrics_and_alerts


def run(base: Path):
    base = base.resolve()
    started = time.monotonic()
    run_id = uuid.uuid4().hex
    for folder in ["output", "reports", "logs", "data", "dead-letter"]:
        (base / folder).mkdir(parents=True, exist_ok=True)
    configure_logging(base)
    config = load_config(base)
    database_path = base / config["settings"]["database"]
    input_folder = base / config["settings"]["input_folder"]
    if not input_folder.exists():
        input_folder = base / "sample-data"
    schema = load_schema(base / "reference")
    mappings = ClinicalMappings(base / "reference/Clinical_name_standardization.xlsx")
    add_config_aliases(mappings, config)
    sources, issues = load_batch(input_folder, config)
    records = []
    per_file = {}
    for path, root in sources:
        extracted, errors = extract(path, root)
        source_key = path.relative_to(input_folder).as_posix()
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        for record in extracted:
            old_id = record.values["id"]
            identifier = hashlib.sha256(f"{source_key}:{record.provenance['section']}:{record.provenance['child_index']}".encode()).hexdigest()
            record.values["id"] = identifier
            record.provenance.update(id=identifier, file=source_key, source_key=source_key, source_hash=source_hash)
            logging.debug("Record extracted", extra={"run_id":run_id,"correlation_id":record.values.get("correlation_id"),"document_id":record.values.get("document_id"),"record_id":identifier,"clinic_id":record.provenance.get("clinic_id"),"source_file":source_key,"stage":"extraction"})
        records.extend(extracted)
        issues.extend(errors)
        per_file[path.relative_to(input_folder).as_posix()] = len(extracted)
        logging.info("%s: extracted %s rows", path.name, len(extracted))
    timestamp = datetime.now(timezone.utc).isoformat()
    frame, date_review, unknown = transform(records, schema, mappings, timestamp)
    duplicates = detect_duplicates(records)
    errors = validate(frame, schema, records, mappings)
    baseline = frame.copy()
    frame, audits, clinical_flags, fuzzy_suggestions = enrich(frame, records, mappings, config)
    errors.extend(validate_enrichment(frame, baseline, records, mappings, config))
    frame = stable_timestamps(frame, records, database_path, schema,config["hash"])
    capture_dead_letters(base,input_folder,issues,run_id)
    # Preserve even unsupported/malformed sections independently of tabular extraction.
    with (base / "reports/source_archive.jsonl").open("w", encoding="utf-8") as handle:
        for path, source in sources:
            handle.write(json.dumps({"file": path.relative_to(input_folder).as_posix(), "source": source.get("_original_source", source)}, ensure_ascii=False) + "\n")
    with (base / "reports/provenance.jsonl").open("w", encoding="utf-8") as handle:
        for r in records:
            handle.write(json.dumps(r.provenance, ensure_ascii=False) + "\n")
    with (base / "reports/normalization_audit.jsonl").open("w",encoding="utf-8") as handle:
        for audit in audits:
            handle.write(json.dumps(audit,ensure_ascii=False)+"\n")
    for name, data, columns in [
        ("clinical_flags.csv",clinical_flags,["id","category","reason","test","result","canonical_value","unit","reference_rule"]),
        ("fuzzy_suggestions.csv",fuzzy_suggestions,["id","original","suggestions","auto_assigned"]),
        ("unknown_test_names.csv", unknown, ["id", "file", "test_name_original", "reason"]),
        ("ambiguous_mappings.csv", mappings.review, ["issue", "name", "candidates", "reference_row", "raw_aliases", "declared_count"]),
        ("duplicate_records.csv", duplicates, ["id", "related_id", "category", "file", "section", "child_index"]),
        ("date_review.csv", date_review, ["id", "field", "original", "status"]),
        ("processing_errors.csv", issues, ["file", "section", "error"]),
    ]:
        pd.DataFrame(data, columns=columns).to_csv(base / "reports" / name, index=False)
    total_variants = {" ".join(str(r.values.get("test_name")).split()).casefold() for r in records if r.values.get("record_type")=="lab_report" and r.values.get("test_name")}
    matched_variants = {" ".join(str(row.test_name_original).split()).casefold() for _,row in frame[frame.test_name_canonical.notna()].iterrows()}
    file_errors = len({issue["file"] for issue in issues})
    summary = {
        "run_id":run_id, "finished_at":datetime.now(timezone.utc).isoformat(), "config_hash":config["hash"],
        "distinct_variants":len(total_variants), "distinct_variants_mapped":len(matched_variants),
        "distinct_variant_coverage":len(matched_variants)/len(total_variants) if total_variants else 1.0,
        "clinical_classifications":dict(Counter(a["analytics"] for a in audits if "analytics" in a)),
        "medicine_names_mapped":sum("medicine_mapping" in a for a in audits),
        "clinical_flag_records":len(clinical_flags), "input_files_failed":file_errors,
        "error_rate":file_errors/max(1,len(list(input_folder.rglob("*.json")))),
        "processing_lag_seconds":max([max(0,time.time()-p.stat().st_mtime) for p,_ in sources] or [0]),
        "input_files_discovered": len(list(input_folder.rglob("*.json"))),
        "input_files_processed": len(sources), "documents_processed": sum(len(s[1]["data"]["responseDetails"]) for s in sources),
        "lab_test_records": sum(r.values["record_type"] == "lab_report" and r.provenance["has_child"] for r in records),
        "medication_records": sum(r.values["record_type"] == "discharge_summary" and r.provenance["has_child"] for r in records),
        "output_rows": len(frame), "standardised_test_names": int(frame.test_name_canonical.notna().sum()),
        "unknown_test_names": sum(x["reason"] == "unknown" for x in unknown),
        "ambiguous_mapping_records": sum(x["reason"] == "ambiguous" for x in unknown),
        "reference_mapping_conflicts": len(mappings.conflicts), "unsafe_alias_lists": sum(x["issue"] == "ambiguous_alias_serialization" for x in mappings.review),
        "duplicate_records": len({x["id"] for x in duplicates}), "duplicate_categories": dict(Counter(x["category"] for x in duplicates)),
        "validation_errors": len(errors), "processing_errors": len(issues), "date_review_entries": len(date_review),
        "records_per_file": per_file,
        "missing_values": {k: int(frame[k].isna().sum()) for k in ["document_id", "patient_name", "age", "gender", "test_name_original", "test_name_canonical", "result_value", "unit_original", "medication_name", "medication_dose", "admission_date", "file_gcs_path"]},
        "empty_strings": {k: int(frame[k].eq("").sum()) for k in ["medication_dose", "medication_frequency", "result_text", "unit_original"]},
        "errors": errors,
    }
    summary["status"] = "PASS" if not errors and not issues else "FAILED_OR_PARTIAL"
    summary["duration_seconds"] = round(time.monotonic()-started,6)
    summary["records_per_second"] = len(frame)/max(summary["duration_seconds"],0.000001)
    if not errors:
        links = load_database(database_path,frame,records,audits,schema,summary,config)
        wide_rows, wide_columns = build_wide(frame,records,config["settings"]["wide_tests"],database_path,base/"output")
        summary.update(wide_rows=wide_rows,wide_columns=wide_columns)
        paths = export_data(frame, base / "output")
        verify_exports(frame, paths)
        logging.info("Verified CSV and Excel: %s", paths)
    summary["duration_seconds"] = round(time.monotonic()-started,6)
    summary["records_per_second"] = len(frame)/max(summary["duration_seconds"],0.000001)
    summary["alerts"] = metrics_and_alerts(summary,config["settings"],base/"reports")
    if not errors:
        from .database import connect
        with connect(database_path) as db:
            db.execute("UPDATE runs SET summary_json=? WHERE run_id=?",(json.dumps(summary),run_id))
            db.commit()
    (base / "reports/validation_report.txt").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logging.info("Standardised %s test names; validation %s", summary["standardised_test_names"], summary["status"])
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        result = run(args.base)
        return 0 if result["status"] == "PASS" else 1
    except Exception:
        logging.exception("Processing failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
