"""Load and validate editable configuration; fail early on unsafe or broken rules."""
import hashlib
import json
import math
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config"


def load_config(base):
    folder = base / "config" if (base / "config").exists() else DEFAULT_CONFIG
    result = {}
    digest = hashlib.sha256()
    for name in ["settings", "clinics", "units", "clinical_ranges", "medicines", "test_aliases"]:
        raw = (folder / (name + ".json")).read_bytes()
        digest.update(raw)
        result[name] = json.loads(raw)
    result["hash"] = digest.hexdigest()
    settings = result["settings"]
    if settings["deduplication"]["mode"] not in {"none", "exact_within_document"}:
        raise ValueError("Unsupported deduplication mode; cross-document suppression requires verified patient identity")
    for profile in result["clinics"]["profiles"]:
        if not profile.get("id") or not profile.get("sections"):
            raise ValueError("Clinic profile requires id and sections path")
    seen = {}
    for rule in result["units"]["rules"]:
        if not all(math.isfinite(rule.get(k, 0)) for k in ["factor", "offset"]) or rule["factor"] <= 0:
            raise ValueError("Unit rules must use finite positive factors")
        for alias in rule["aliases"]:
            # Units are case-sensitive: do not equate mL and ML by case folding.
            key = (rule["test"].casefold(), alias.strip())
            signature = (rule["canonical"], rule["factor"], rule.get("offset", 0))
            if key in seen and seen[key] != signature:
                raise ValueError("Conflicting unit rule: " + str(key))
            seen[key] = signature
    for rule in result["clinical_ranges"]["rules"]:
        if rule["low"] > rule["high"] or rule["plausible_low"] > rule["plausible_high"]:
            raise ValueError("Invalid clinical range rule")
        if not rule.get("source"):
            raise ValueError("Clinical rules require a source")
    return result
