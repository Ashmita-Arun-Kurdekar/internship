"""Exact reference matching; conflicting or malformed aliases never auto-map."""
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import pandas as pd


def normalize(value):
    return " ".join(str(value).split()).casefold()


@dataclass(frozen=True)
class Match:
    canonical: str | None
    method: str
    confidence: float | None


class ClinicalMappings:
    def __init__(self, path: Path):
        frame = pd.read_excel(path, engine="openpyxl", keep_default_na=False)
        required = {"test_name_canonical", "variation_count", "original_test_names"}
        if not required.issubset(frame.columns):
            raise ValueError("Invalid clinical reference columns")
        candidates, approved = defaultdict(set), defaultdict(set)
        self.review = []
        for index, row in frame.iterrows():
            canonical = str(row.test_name_canonical).strip()
            if not canonical:
                raise ValueError("Empty canonical name")
            raw = str(row.original_test_names)
            try:
                aliases = json.loads(raw)
                if not isinstance(aliases, list) or not all(isinstance(x, str) for x in aliases):
                    raise ValueError("Expected string list")
                safe = len(aliases) == int(row.variation_count)
            except (ValueError, TypeError):
                aliases = [x.strip() for x in raw.strip("[]").split(",")]
                safe = raw.startswith("[") and raw.endswith("]") and len(aliases) == int(row.variation_count)
            candidates[normalize(canonical)].add(canonical)
            approved[normalize(canonical)].add(canonical)
            for alias in aliases:
                if alias:
                    candidates[normalize(alias)].add(canonical)
                    if safe:
                        approved[normalize(alias)].add(canonical)
            if not safe:
                self.review.append({"issue": "ambiguous_alias_serialization", "name": canonical,
                                    "candidates": canonical, "reference_row": index + 2,
                                    "raw_aliases": raw, "declared_count": row.variation_count})
        self.conflicts = {k: sorted(v) for k, v in candidates.items() if len(v) > 1}
        for key, values in self.conflicts.items():
            self.review.append({"issue": "conflicting_mapping", "name": key,
                                "candidates": json.dumps(values), "reference_row": None,
                                "raw_aliases": None, "declared_count": None})
        self.mapping = {k: next(iter(v)) for k, v in approved.items() if k not in self.conflicts and len(v) == 1}

    def match(self, value):
        if value is None or not str(value).strip():
            return Match(None, "missing", None)
        key = normalize(value)
        if key in self.conflicts:
            return Match(None, "ambiguous", None)
        if key in self.mapping:
            return Match(self.mapping[key], "exact_normalized_reference", 1.0)
        return Match(None, "unknown", None)
