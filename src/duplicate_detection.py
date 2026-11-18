"""Report repetitions using source payload and document identity; never remove rows."""
import json
from collections import defaultdict


def detect_duplicates(records):
    seen, names = {}, defaultdict(list)
    report = []
    for record in records:
        p, v = record.provenance, record.values
        payload = json.dumps({"kind": v.get("record_type"), "data": p["section_data"], "child": p["child"]}, sort_keys=True, ensure_ascii=False)
        if payload in seen:
            first = seen[payload]
            same = first.values.get("document_id") == v.get("document_id")
            # Distinct children in the same section are exact only when their full raw payloads agree.
            report.append({"id": v["id"], "related_id": first.values["id"],
                           "category": "exact_source_repeat" if same else "similar_content_different_document",
                           "file": p["file"], "section": p["section"], "child_index": p["child_index"]})
        else:
            seen[payload] = record
        if v.get("record_type") == "lab_report":
            key = (v.get("document_id"), v.get("test_name"))
            previous = names[key]
            differing = next((x for x in previous if x.values.get("result") != v.get("result")), None)
            if differing:
                report.append({"id": v["id"], "related_id": differing.values["id"], "category": "repeated_name_different_result",
                               "file": p["file"], "section": p["section"], "child_index": p["child_index"]})
            previous.append(record)
    return report
