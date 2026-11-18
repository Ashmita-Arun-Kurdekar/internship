"""Declarative clinic adapters: paths and classifier names are data, not Python code."""
from copy import deepcopy
from fnmatch import fnmatch


def get_path(data, path, root=None):
    if path == "$":
        return data
    if path.startswith("$root."):
        data, path = root, path[6:]
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def adapt_source(raw, relative_file, config):
    profiles = config["clinics"]["profiles"]
    matches = [c for c in config["clinics"]["clinics"] if fnmatch(relative_file, c["file_pattern"])]
    if len(matches) > 1:
        raise ValueError("Multiple clinic configurations match source")
    clinic = matches[0] if matches else {}
    candidates = [p for p in profiles if p["id"] == clinic["profile"]] if clinic else [p for p in profiles if get_path(raw, p["detect"]) is not None]
    if len(candidates) != 1:
        raise ValueError("Cannot select a unique clinic schema profile; configure clinics.json")
    profile = candidates[0]
    sections = get_path(raw, profile["sections"])
    if not isinstance(sections, list):
        raise ValueError("Configured sections path must point to an array")
    envelope = {k: get_path(raw, path) for k, path in profile["envelope"].items()}
    trace = envelope.pop("traceId", None)
    normalized = []
    for section in sections:
        if not isinstance(section, dict):
            normalized.append(section)
            continue
        source_kind = get_path(section, profile["classifier"], raw)
        kind = profile["classifiers"].get(source_kind, source_kind)
        payload = get_path(section, profile["payload"], raw)
        if not isinstance(payload, dict):
            normalized.append({"classifier": kind, "data": payload})
            continue
        spec = profile.get("lab" if kind == "lab_report" else "discharge" if kind == "discharge_summary" else "")
        if not spec:
            normalized.append({"classifier": kind, "data": payload})
            continue
        fields = {target: get_path(payload, path, raw) for target, path in spec["fields"].items()}
        children = get_path(payload, spec["children"], raw)
        if children is not None and not isinstance(children, list):
            raise ValueError("Configured child collection must be an array")
        mapped = [{target: get_path(child, path, raw) for target, path in spec["child_fields"].items()} if isinstance(child, dict) else child for child in (children or [])]
        data = {"basic_info": fields, "report_details": mapped} if kind == "lab_report" else {**fields, "dischargeMedications": mapped}
        normalized.append({**section, "classifier": kind, "data": data})
    return {"traceId": trace, "data": {**envelope, "responseDetails": normalized},
            "_original_source": deepcopy(raw), "_clinic_id": clinic.get("clinic_id"),
            "_clinic_label": clinic.get("label"), "_schema_version": profile["id"]}
