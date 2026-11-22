"""Run the public dashboard with a fresh, entirely synthetic dataset."""
import json
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from .main import run
from .webapp import BASE, main as serve


def prepare_demo(base):
    for folder in ("config", "reference"):
        shutil.copytree(BASE / folder, base / folder)
    inputs = base / "input"
    inputs.mkdir()

    for number, sodium in enumerate(("140", "128", "155", "2500", "unreadable"), 1):
        patient = f"Synthetic Patient {number}"
        lab = {
            "classifier": "lab_report",
            "data": {
                "basic_info": {"patient_name": patient, "age": f"{30 + number}Y", "gender": "M"},
                "report_details": [
                    {"test_name": "SODIUM", "result": sodium, "range": "135-145", "unit": "mmol/L"},
                    {"test_name": "aemoglobin", "result": "14.5", "range": "13.8-17.2", "unit": "g/dL"},
                ],
            },
        }
        discharge = {
            "classifier": "discharge_summary",
            "data": {
                "patientName": patient,
                "dischargeMedications": [{"medicine": "Dolo-650", "dose": "650 mg"}],
            },
        }
        report = {
            "traceId": f"demo-trace-{number}",
            "data": {"documentId": f"demo-report-{number}", "responseDetails": [lab, discharge]},
        }
        (inputs / f"Sample_JSON_file{number}.json").write_text(json.dumps(report), encoding="utf-8")


if __name__ == "__main__":
    with TemporaryDirectory(prefix="veritas-public-") as directory:
        base = Path(directory)
        prepare_demo(base)
        if run(base)["status"] != "PASS":
            raise SystemExit("Could not initialise the public demo")
        serve(["--base", str(base)], hosted_demo=True)
