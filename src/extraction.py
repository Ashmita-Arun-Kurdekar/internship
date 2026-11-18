"""Separate lab and discharge extractors with complete source provenance."""
import hashlib
import json
import logging
from dataclasses import dataclass


def text(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


@dataclass
class Extracted:
    values: dict
    provenance: dict


DISCHARGE_FIELDS = {
    "admissionDate": "admission_date", "dischargeDate": "discharge_date",
    "patientName": "patient_name", "age": "age", "gender": "gender",
    "doctorName": "doctor_name", "hospitalName": "hospital_name",
    "hospitalAddress": "hospital_address", "diagnosis": "diagnosis",
    "briefHistory": "brief_history", "generalExaminations": "general_examinations",
    "recommendations": "recommendations", "ward": "ward",
    "postDischargeAdvice": "post_discharge_advice",
    "medicineInjectionsInvestigation": "medicine_injections_investigation",
    "courseDuringHospitalisation": "course_during_hospitalisation",
}


def extract_lab(data):
    basic = data.get("basic_info") or {}
    if not isinstance(basic, dict):
        raise ValueError("basic_info must be an object")
    shared = {k: text(v) for k, v in basic.items()}
    shared["hospital_name"] = text(basic.get("lab_or_hospital_name"))
    shared["basic_info_age"] = text(basic.get("age"))
    shared["basic_info_bill_date"] = text(basic.get("bill_date"))
    children = data.get("report_details")
    if children is None:
        children = []
    if not isinstance(children, list) or not all(isinstance(c, dict) for c in children):
        raise ValueError("report_details must contain objects")
    for i, child in enumerate(children or [{}]):
        row = dict(shared)
        for k in ["page_no", "range", "result", "test_analytics", "test_name", "unit"]:
            row["report_details_" + k] = text(child.get(k))
            row[k] = text(child.get(k))
        yield i, row, child, bool(children)


def extract_discharge(data):
    shared = {target: text(data.get(source)) for source, target in DISCHARGE_FIELDS.items()}
    children = data.get("dischargeMedications")
    if children is None:
        children = []
    if not isinstance(children, list) or not all(isinstance(c, dict) for c in children):
        raise ValueError("dischargeMedications must contain objects")
    for i, child in enumerate(children or [{}]):
        row = dict(shared)
        for k in ["medicine", "dose", "frequency"]:
            row[k] = text(child.get(k))
            row["discharge_medications_" + k] = text(child.get(k))
        row["medicine_type"] = text(child.get("type"))
        yield i, row, child, bool(children)


def extract(path, root):
    result, errors = [], []
    envelope = root["data"]
    meta = envelope.get("metaDetails")
    pairs = {x.get("key"): x.get("value") for x in meta if isinstance(x, dict)} if isinstance(meta, list) else meta if isinstance(meta, dict) else {}
    metadata = {"document_id": text(envelope.get("documentId")),
                "correlation_id": text(envelope.get("correlationId")),
                "trace_id": text(root.get("traceId")), "metadetails": text(meta)}
    for source, target in {"DestinationIdentifier": "destination_identifier", "ConsumerClientId": "consumer_client_id",
                           "source_system": "source_system", "claim_no": "claim_no", "nt_code": "nt_code",
                           "file_gcs_path": "file_gcs_path"}.items():
        metadata[target] = text(pairs.get(source, envelope.get(source)))
    for section_index, section in enumerate(envelope["responseDetails"]):
        try:
            if not isinstance(section, dict) or not isinstance(section.get("data"), dict):
                raise ValueError("Section and section.data must be objects")
            classifier = section.get("classifier")
            logging.info("%s section %s: %s", path.name, section_index, classifier)
            data = section["data"]
            if classifier == "lab_report":
                children = list(extract_lab(data))
            elif classifier == "discharge_summary":
                children = list(extract_discharge(data))
            else:
                errors.append({"file": path.name, "section": section_index, "error": "Unsupported classifier preserved in provenance"})
                children = [(0, {}, data, False)]
            for child_index, row, child, has_child in children:
                identifier = hashlib.sha256(f"{path.name}:{section_index}:{child_index}".encode()).hexdigest()
                row.update(metadata)
                row.update(id=identifier, record_type=text(classifier))
                provenance = {"id": identifier, "file": path.name, "section": section_index,
                              "child_index": child_index, "has_child": has_child, "child": child,
                              "section_data": data, "source": root.get("_original_source", root),
                              "clinic_id": root.get("_clinic_id"), "clinic_label": root.get("_clinic_label"),
                              "schema_version": root.get("_schema_version", "legacy_v1")}
                result.append(Extracted(row, provenance))
        except (ValueError, TypeError) as exc:
            errors.append({"file": path.name, "section": section_index, "error": str(exc)})
    return result, errors
