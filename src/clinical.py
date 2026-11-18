"""Auditable, rule-driven numeric, unit, demographic and clinical enrichment."""
import hashlib
import hmac
import json
import math
import os
import re
from difflib import SequenceMatcher
from collections import defaultdict
import pandas as pd
from .transformation import NUMBER, parse_number, parse_range
from .standardisation import normalize


def demographics(age, gender):
    text = str(age or "").strip()
    match = re.fullmatch(r"(?:(\d+)\s*[Yy])?\s*(?:(\d+)\s*[Mm])?\s*(?:(\d+)\s*[Dd])?", text)
    parts = {"years": None, "months": None, "days": None}
    if match and any(x is not None for x in match.groups()):
        parts = {k: int(v) if v is not None else None for k, v in zip(parts, match.groups())}
    elif re.fullmatch(r"\d{1,3}", text):
        parts["years"] = int(text)
    sex = {"m":"Male", "male":"Male", "f":"Female", "female":"Female", "other":"Other"}.get(str(gender or "").strip().casefold())
    return {"age": parts, "gender": sex}


def unit_rule(test, unit, config):
    if test is None or unit is None:
        return None
    matches = [r for r in config["units"]["rules"] if normalize(r["test"]) == normalize(test) and str(unit).strip() in r["aliases"]]
    return matches[0] if matches else None


def parse_mixed(raw, declared_unit, test, config):
    direct = parse_number(raw)
    if direct is not None:
        return {"value": direct, "unit": declared_unit, "method": "numeric", "issue": None}
    match = re.fullmatch(rf"\s*({NUMBER})\s+(.+?)\s*", str(raw))
    if match:
        value, suffix = parse_number(match[1]), match[2]
        rule = unit_rule(test, suffix, config)
        declared = unit_rule(test, declared_unit, config) if declared_unit else None
        # Embedded suffix must be configured, and must agree with any explicit unit.
        if value is not None and rule and (not declared_unit or declared and all(rule[k] == declared[k] for k in ["canonical", "factor", "offset"])):
            return {"value": value, "unit": suffix, "method": "numeric_with_verified_unit", "issue": None}
        if rule and declared_unit:
            return {"value": None, "unit": declared_unit, "method": "text", "issue": "contradictory_or_unknown_unit"}
    issue = "multiple_or_complex_values" if len(re.findall(NUMBER, str(raw))) > 1 else "non_numeric_or_missing"
    return {"value": None, "unit": declared_unit, "method": "text", "issue": issue}


def mapping_suggestions(original, mappings, config):
    if not original or normalize(original) in mappings.conflicts:
        return []
    scores = defaultdict(float)
    for alias, canonical in mappings.mapping.items():
        scores[canonical] = max(scores[canonical], SequenceMatcher(None, normalize(original), alias).ratio())
    return [{"canonical": key, "confidence": round(score, 6)} for key, score in sorted(scores.items(), key=lambda kv:(-kv[1],kv[0]))[:3]]


def add_config_aliases(mappings, config):
    known = set(mappings.mapping.values())
    for alias in config["test_aliases"]["aliases"]:
        if not alias.get("approved"):
            continue
        key, canonical = normalize(alias["name"]), alias["canonical"]
        if canonical not in known or key in mappings.conflicts or key in mappings.mapping and mappings.mapping[key] != canonical:
            raise ValueError("Alias conflicts with authoritative workbook: " + alias["name"])
        mappings.mapping[key] = canonical


def clinical_classification(value, test, unit, source_range, demo, config, source_operator=None):
    if value is None:
        return "Invalid", "non_numeric_or_conflicting_result", None
    rules = [r for r in config["clinical_ranges"]["rules"] if normalize(r["test"]) == normalize(test) and r["unit"] == unit] if test else []
    # Broad, explicitly labelled plausibility screens can operate without demographics.
    for rule in rules:
        if value < rule["plausible_low"] or value > rule["plausible_high"]:
            return "Outlier", rule["outlier_basis"], rule["id"]
    applicable = [r for r in rules if demo["age"]["years"] is not None and demo["age"]["years"] >= r.get("age_min",0) and (not r.get("gender") or demo["gender"] == r["gender"])]
    if applicable:
        bounds = {(r["low"],r["high"]) for r in applicable}
        if len(bounds) != 1:
            return "Invalid", "conflicting_reference_rules", None
        low, high = bounds.pop()
        return ("Below Range" if value < low else "Above Range" if value > high else "Within Range"), "reference_dictionary", applicable[0]["id"]
    low, high = source_range
    if config["settings"]["allow_document_ranges"] and source_operator:
        bound=high if source_operator.startswith("<") else low
        if bound is not None:
            outside = value>=bound if source_operator=="<" else value>bound if source_operator=="<=" else value<=bound if source_operator==">" else value<bound
            return ("Above Range" if source_operator.startswith("<") else "Below Range") if outside else "Within Range", "source_document_inequality_not_independently_verified", None
    if config["settings"]["allow_document_ranges"] and low is not None and high is not None:
        return ("Below Range" if value < low else "Above Range" if value > high else "Within Range"), "source_document_range_not_independently_verified", None
    return "Invalid", "not_assessable_without_applicable_reference_or_context", None


def enrich(frame, records, mappings, config):
    result = frame.copy()
    audits, flags, suggestions = [], [], []
    for index, record in enumerate(records):
        v, p = record.values, record.provenance
        demo = demographics(v.get("age"), v.get("gender"))
        audit = {"id":v["id"], "clinic_id":p.get("clinic_id"), "schema_version":p.get("schema_version"), "demographics":demo,
                 "config_hash":config["hash"], "source_analytics":v.get("test_analytics")}
        if demo["age"]["years"] is not None:
            result.at[index,"age_years"] = str(demo["age"]["years"])
        if demo["gender"]:
            result.at[index,"gender"] = demo["gender"]
        if v.get("record_type") == "lab_report":
            test = None if pd.isna(result.at[index,"test_name_canonical"]) else result.at[index,"test_name_canonical"]
            candidates = mapping_suggestions(v.get("test_name"), mappings, config) if not test and config["settings"]["fuzzy"]["suggest"] else []
            if candidates:
                suggestions.append({"id":v["id"], "original":v.get("test_name"), "suggestions":json.dumps(candidates), "auto_assigned":False})
                fuzzy = config["settings"]["fuzzy"]
                if fuzzy["auto_assign"] and candidates[0]["confidence"] >= fuzzy["threshold"] and (len(candidates)<2 or candidates[0]["confidence"]-candidates[1]["confidence"]>=fuzzy["margin"]):
                    test = candidates[0]["canonical"]
                    result.at[index,"test_name_canonical"] = test
                    result.at[index,"normalization_method"] = "configured_fuzzy_reference"
                    result.at[index,"normalization_confidence"] = candidates[0]["confidence"]
                    suggestions[-1]["auto_assigned"] = True
            parsed = parse_mixed(v.get("result"), v.get("unit"), test, config)
            rule = unit_rule(test, parsed["unit"], config)
            value = parsed["value"]
            low, high = parse_range(v.get("range"))
            source_operator=None
            inequality=re.fullmatch(rf"\s*([<>]=?)\s*({NUMBER})\s*",str(v.get("range")))
            if inequality:
                source_operator=inequality[1]
                bound=parse_number(inequality[2])
                if source_operator.startswith("<"):
                    high=bound
                else:
                    low=bound
            unit = parsed["unit"]
            if rule:
                unit = rule["canonical"]
                result.at[index,"unit_canonical"] = unit
                value = value*rule["factor"]+rule.get("offset",0) if value is not None else None
                low,high=(x*rule["factor"]+rule.get("offset",0) if x is not None else None for x in [low,high])
                result.at[index,"range_low"],result.at[index,"range_high"] = low,high
            if value is not None and not math.isfinite(value):
                value=None
                parsed["issue"]="numeric_overflow"
            result.at[index,"result_value"] = value
            classification, reason, reference = clinical_classification(value,test,unit,(low,high),demo,config,source_operator)
            result.at[index,"test_analytics"] = classification
            audit.update(parse_method=parsed["method"],parse_issue=parsed["issue"],unit_rule=rule,analytics=classification,analytics_reason=reason,reference_rule=reference)
            if classification != "Within Range":
                flags.append({"id":v["id"],"category":classification,"reason":reason,"test":v.get("test_name"),"result":v.get("result"),"canonical_value":value,"unit":unit,"reference_rule":reference})
        elif v.get("record_type") == "discharge_summary":
            matches=[r for r in config["medicines"]["rules"] if normalize(v.get("medicine")) in {normalize(a) for a in r["aliases"]}]
            generics={r["generic"] for r in matches}
            if len(generics)==1:
                result.at[index,"medication_name"] = next(iter(generics))
                audit["medicine_mapping"] = matches[0]
            elif len(generics)>1:
                audit["medicine_mapping_issue"]="ambiguous"
        audits.append(audit)
    return result,audits,flags,suggestions


def validate_enrichment(frame, baseline, records, mappings, config):
    expected, _, _, _ = enrich(baseline,records,mappings,config)
    errors=[]
    if list(frame.columns)!=list(baseline.columns):
        return ["Enriched schema/order mismatch"]
    for field in frame.columns:
        # Timestamps may be retained from a previous idempotent database ingestion.
        if field not in {"processed_at","ingested_at"} and not frame[field].equals(expected[field]):
            errors.append("Unsupported enrichment change: "+field)
    return errors


def mask_values(values, settings):
    if not settings["mask_dashboard"]:
        return values
    salt=os.environ.get(settings["salt_env"])
    if not salt:
        raise ValueError("PII masking enabled but salt environment variable is missing")
    result=dict(values)
    for key in settings["token_fields"]:
        if result.get(key) not in (None,""):
            result[key]="token:"+hmac.new(salt.encode(),str(result[key]).encode(),hashlib.sha256).hexdigest()[:24]
    return result
