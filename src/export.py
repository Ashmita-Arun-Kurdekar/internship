r"""Exact column exports. CSV null is explicit \N; Excel null is a blank cell."""
from pathlib import Path
import pandas as pd
from openpyxl import Workbook, load_workbook


def export_data(frame, folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "standardised_medical_data.csv"
    excel_path = folder / "standardised_medical_data.xlsx"
    # Explicit null token distinguishes an empty source string from missing in CSV.
    if frame.astype("string").eq(r"\N").any().any():
        raise ValueError(r"Source contains reserved CSV null token \N")
    for column in frame.columns:
        if frame[column].map(lambda v: isinstance(v, str) and len(v) > 32767).any():
            raise ValueError(f"Excel cell length limit exceeded in {column}; refusing truncation")
    frame.to_csv(csv_path, index=False, encoding="utf-8", na_rep=r"\N")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "medical_data"
    sheet.append(list(frame.columns))
    for row in frame.itertuples(index=False, name=None):
        sheet.append([None if pd.isna(v) else v.isoformat() if isinstance(v, pd.Timestamp) else v for v in row])
        # Force text cells: source strings beginning '=' must not become Excel formulas.
        for cell, value in zip(sheet[sheet.max_row], row):
            if isinstance(value, str):
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    workbook.save(excel_path)
    return csv_path, excel_path


def verify_exports(frame, paths):
    loaded = pd.read_csv(paths[0], dtype=str, keep_default_na=False)
    expected = frame.copy()
    for c in expected.columns:
        expected[c] = expected[c].map(lambda v: r"\N" if pd.isna(v) else str(v))
    if list(loaded.columns) != list(frame.columns) or loaded.values.tolist() != expected.values.tolist():
        raise ValueError("CSV read-back failed")
    workbook = load_workbook(paths[1], data_only=False)
    rows = list(workbook.active.values)
    if list(rows[0]) != list(frame.columns) or len(rows) - 1 != len(frame):
        raise ValueError("Excel shape/header read-back failed")
    for actual, original in zip(rows[1:], frame.itertuples(index=False, name=None)):
        for a, v in zip(actual, original):
            expected_value = None if pd.isna(v) or v == "" else v.isoformat() if isinstance(v, pd.Timestamp) else v
            if isinstance(expected_value, float) and isinstance(a, (float, int)):
                if not __import__('math').isclose(a, expected_value, rel_tol=1e-14):
                    raise ValueError("Excel numeric read-back failed")
            elif a != expected_value:
                raise ValueError(f"Excel value read-back failed: {a!r} != {expected_value!r}")
