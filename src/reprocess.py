"""Retry corrected original inputs and update dead-letter status. python -m src.reprocess"""
import argparse
import json
from pathlib import Path
from .main import run


def retry(base):
    result=run(base)
    errors=[]
    import csv
    with (base/"reports/processing_errors.csv").open(encoding="utf-8") as handle:
        errors=list(csv.DictReader(handle))
    pending={(e["file"],str(e.get("section") or "")) for e in errors}
    for path in (base/"dead-letter").glob("*.json"):
        data=json.loads(path.read_text())
        key=(data["source_file"],str(data.get("section") if data.get("section") is not None else ""))
        # Do not call deleted/unavailable originals resolved.
        from .configuration import load_config
        config=load_config(base)
        folder=base/config["settings"]["input_folder"]
        if not folder.exists():
            folder=base/"sample-data"
        if key not in pending and (folder/data["source_file"]).exists():
            data.update(status="resolved",resolved_run_id=result["run_id"])
            path.write_text(json.dumps(data,indent=2))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base",type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    raise SystemExit(0 if retry(args.base)["status"]=="PASS" else 1)


if __name__=="__main__":
    main()
