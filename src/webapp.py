"""Local dashboard. Run: python -m src.webapp (binds only to loopback)."""
import argparse
import base64
import csv
import json
import logging
import os
import secrets
import subprocess
import sys
import threading
from collections import Counter, defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from fnmatch import fnmatch
from .configuration import load_config
from .clinical import mask_values
from .database import history,review_states,review,connect

BASE = Path(__file__).resolve().parents[1]
DOWNLOADS = {
    "wide": ("output/medical_tests_wide.csv", "text/csv; charset=utf-8"),
    "clinical": ("reports/clinical_flags.csv", "text/csv; charset=utf-8"),
    "csv": ("output/standardised_medical_data.csv", "text/csv; charset=utf-8"),
    "excel": ("output/standardised_medical_data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "validation": ("reports/validation_report.txt", "application/json"),
    "unknown": ("reports/unknown_test_names.csv", "text/csv; charset=utf-8"),
    "duplicates": ("reports/duplicate_records.csv", "text/csv; charset=utf-8"),
    "dates": ("reports/date_review.csv", "text/csv; charset=utf-8"),
    "mappings": ("reports/ambiguous_mappings.csv", "text/csv; charset=utf-8"),
}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_jsonl(path):
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)


def load_snapshot(base):
    report_path = base / "reports/validation_report.txt"
    summary = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    config=load_config(base)
    db_path=base/config["settings"]["database"]
    reviews=review_states(db_path)
    privacy=config["settings"]["privacy"]
    flags = defaultdict(list)
    for filename, category in [("unknown_test_names.csv", "mapping"), ("date_review.csv", "date"), ("duplicate_records.csv", "duplicate"), ("clinical_flags.csv", "clinical")]:
        for row in read_csv(base / "reports" / filename):
            if row.get("id"):
                flags[row["id"]].append({"type": category, "details": row})
    provenance = {}
    for entry in read_jsonl(base / "reports/provenance.jsonl"):
        provenance[entry["id"]] = {k: entry[k] for k in ["file", "section", "child_index", "child", "has_child", "clinic_id", "clinic_label", "schema_version"]}
    records, groups = [], {}
    for row in read_csv(base / "output/standardised_medical_data.csv"):
        values = {k: None if v == r"\N" else v for k, v in row.items()}
        identifier = values["id"]
        source = provenance.get(identifier, {})
        values=mask_values(values,privacy)
        group_key = (source.get("clinic_label") or source.get("clinic_id") or "Clinic unavailable", values.get("source_system") or "Source unavailable")
        item = {"id": identifier, "values": values, "file": source.get("file", "Unknown source"),
                "section": source.get("section"), "child_index": source.get("child_index"),
                "flags": flags[identifier], "source_group": " / ".join(group_key), "clinic_id":source.get("clinic_id"), "schema_version":source.get("schema_version"),
                "review":reviews.get(identifier,{"status":"open","note":""})}
        records.append(item)
        group = groups.setdefault(group_key, {"hospital": group_key[0], "source_system": group_key[1], "rows": 0,
                                             "flagged": 0, "duplicates": 0, "missing_patient": 0, "clinical_flags":0, "errors":0, "missing_cells":0, "checked_cells":0, "files": set()})
        group["rows"] += 1
        group["files"].add(item["file"])
        group["flagged"] += bool(item["flags"])
        group["duplicates"] += any(f["type"] == "duplicate" for f in item["flags"])
        group["missing_patient"] += values.get("patient_name") in (None, "")
        group["clinical_flags"] += any(f["type"]=="clinical" for f in item["flags"])
        important=["patient_name","age","gender","document_id"] + (["test_name_original","result_text","unit_original"] if values["record_type"]=="lab_report" else ["medication_name","medication_dose","medication_frequency"])
        group["missing_cells"]+=sum(values.get(key) in (None,"") for key in important)
        group["checked_cells"]+=len(important)
        group["missing_field_rate"] = group["missing_cells"]/max(1,group["checked_cells"])
    processing_errors=read_csv(base/"reports/processing_errors.csv")
    for issue in processing_errors:
        matches=[c for c in config["clinics"]["clinics"] if fnmatch(issue["file"],c["file_pattern"])]
        label=matches[0].get("label",matches[0]["clinic_id"]) if matches else "Clinic unavailable"
        group=next((g for g in groups.values() if g["hospital"]==label),None)
        if group is None:
            group={"hospital":label,"source_system":"Source unavailable","rows":0,"flagged":0,"duplicates":0,"missing_patient":0,"clinical_flags":0,"missing_cells":0,"checked_cells":0,"missing_field_rate":0,"errors":0,"files":set()}
            groups[(label,"Source unavailable")]=group
        group["errors"]+=1
        group["files"].add(issue["file"])
    for group in groups.values():
        group["files"] = sorted(group["files"])
        group["error_rate"]=group["errors"]/max(1,len(group["files"]))
    return {
        "summary": summary, "records": records, "groups": list(groups.values()),
        "run_history":history(db_path), "privacy_masked":privacy["mask_dashboard"],
        "alerts":json.loads((base/"reports/alerts.json").read_text()) if (base/"reports/alerts.json").exists() else [],
        "mapping_review": read_csv(base / "reports/ambiguous_mappings.csv"),
        "processing_errors": processing_errors,
        "flagged_rows": sum(bool(r["flags"]) for r in records),
        "flag_counts": dict(Counter(f["type"] for r in records for f in r["flags"])),
        "updated_at": datetime.fromtimestamp(report_path.stat().st_mtime, timezone.utc).isoformat() if report_path.exists() else None,
    }


class DashboardState:
    def __init__(self, base):
        self.base = base.resolve()
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.running = False
        self.last_run = None
        self.snapshot = None

    def data(self):
        with self.lock:
            if not self.running or self.snapshot is None:
                self.snapshot = load_snapshot(self.base)
            return {**self.snapshot, "running": self.running, "last_run": self.last_run}

    def start(self):
        with self.lock:
            if self.running:
                return False
            self.snapshot = load_snapshot(self.base)
            self.running = True
            self.last_run = {"started_at": datetime.now(timezone.utc).isoformat(), "exit_code": None}
            threading.Thread(target=self._process, daemon=True).start()
            return True

    def _process(self):
        try:
            result = subprocess.run([sys.executable, "-m", "src.main", "--base", str(self.base)],
                                    cwd=BASE, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
            outcome = {"exit_code": result.returncode, "log": (result.stdout + result.stderr)[-12000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            outcome = {"exit_code": -1, "log": str(exc)}
        with self.lock:
            self.last_run.update(outcome, finished_at=datetime.now(timezone.utc).isoformat())
            self.running = False

    def record(self, identifier):
        with self.lock:
            data = self.data()
            record = next((r for r in data["records"] if r["id"] == identifier), None)
            if record is None:
                return None
            # Use cached original while a pipeline run replaces the reports.
            if self.running:
                return {"record": record, "raw_unavailable": True}
            if data["privacy_masked"]:
                return {"record":record,"raw_unavailable":True,"privacy_masked":True}
            decisions=None
            config=load_config(self.base)
            db_path=self.base/config["settings"]["database"]
            if db_path.exists():
                with connect(db_path) as db:
                    decision=db.execute("SELECT decision_json FROM decisions WHERE id=?",(identifier,)).fetchone()
                    decisions=json.loads(decision[0]) if decision else None
            provenance = next((p for p in read_jsonl(self.base / "reports/provenance.jsonl") if p["id"] == identifier), None)
            return {"record": record, "provenance": provenance,"decisions":decisions}


def make_handler(state, external_url=None, demo_password=None):
    external_host = urlsplit(external_url).netloc if external_url else None
    demo_auth = (
        "Basic " + base64.b64encode(f"reviewer:{demo_password}".encode()).decode()
        if demo_password else None
    )

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="application/json; charset=utf-8", filename=None):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
                if filename:
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.end_headers()
                self.wfile.write(body)
            except ConnectionError:
                # A tab closed or navigated away before the response completed.
                return


        def allowed_host(self):
            if external_host:
                return self.headers.get("Host", "").lower() == external_host.lower()
            host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            return host in {"localhost", "127.0.0.1"}

        def authorized(self):
            if demo_auth is None or secrets.compare_digest(
                self.headers.get("Authorization", "").encode(), demo_auth.encode()
            ):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Veritas Claims Demo"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def do_GET(self):
            if not self.allowed_host():
                return self.send(403, {"error": "Unexpected dashboard host"})
            if not self.authorized():
                return
            parsed = urlsplit(self.path)
            try:
                if parsed.path == "/api/session":
                    return self.send(200, {"token": state.token})
                if parsed.path == "/metrics":
                    path=state.base/"reports/metrics.prom"
                    return self.send(200,path.read_bytes() if path.exists() else b"", "text/plain; version=0.0.4")
                if parsed.path == "/api/data":
                    return self.send(200, state.data())
                if parsed.path == "/api/record":
                    result = state.record(parse_qs(parsed.query).get("id", [""])[0])
                    return self.send(200 if result else 404, result or {"error": "Record not found"})
                if parsed.path.startswith("/download/"):
                    key = parsed.path.removeprefix("/download/")
                    if key not in DOWNLOADS:
                        return self.send(404, {"error": "Unknown export"})
                    with state.lock:
                        if load_config(state.base)["settings"]["privacy"]["mask_dashboard"]:
                            return self.send(403,{"error":"Raw exports are disabled while dashboard PII masking is enabled"})
                        if state.running:
                            return self.send(409, {"error": "Exports are being refreshed. Try after the run finishes."})
                        name, kind = DOWNLOADS[key]
                        path = state.base / name
                        return self.send(200, path.read_bytes(), kind, path.name)
                static = {"/": ("index.html", "text/html; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/style.css": ("style.css", "text/css; charset=utf-8")}
                if parsed.path in static:
                    name, kind = static[parsed.path]
                    return self.send(200, (BASE / "web" / name).read_bytes(), kind)
                return self.send(404, {"error": "Not found"})
            except FileNotFoundError:
                return self.send(404, {"error": "Artifact not available. Run the pipeline first."})
            except (ValueError, KeyError, OSError):
                logging.exception("Dashboard artifact read failed")
                return self.send(500, {"error": "Could not read pipeline artifacts. Check the terminal log."})

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected_origin = external_url or "http://" + self.headers.get("Host", "")
            if self.allowed_host() and not self.authorized():
                return
            if not self.allowed_host() or (origin and origin != expected_origin) or not secrets.compare_digest(self.headers.get("X-Dashboard-Token", ""), state.token):
                return self.send(403, {"error": "Refresh the dashboard before running the pipeline"})
            if self.path == "/api/review":
                try:
                    length=int(self.headers.get("Content-Length","0"))
                    if not 0<length<=8192:
                        return self.send(400,{"error":"Invalid review payload size"})
                    body=json.loads(self.rfile.read(length))
                    with state.lock:
                        if state.running:
                            return self.send(409,{"error":"Wait for the current pipeline run"})
                        config=load_config(state.base)
                        review(state.base/config["settings"]["database"],body["id"],body["status"],body.get("note",""),datetime.now(timezone.utc).isoformat())
                    return self.send(200,{"saved":True})
                except (ValueError,KeyError,TypeError):
                    return self.send(400,{"error":"Invalid review request"})
            if self.path != "/api/run":
                return self.send(404, {"error": "Not found"})
            try:
                started = state.start()
                return self.send(202 if started else 409, {"started": started})
            except (ValueError, OSError):
                logging.exception("Could not start pipeline")
                return self.send(500, {"error": "Could not start the pipeline. Check the terminal log."})
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=BASE)
    external_url = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    demo_password = os.environ.get("DASHBOARD_DEMO_PASSWORD")
    if external_url and (urlsplit(external_url).scheme != "https" or not demo_password):
        parser.error("Hosted mode requires an HTTPS URL and DASHBOARD_DEMO_PASSWORD")
    parser.add_argument("--port", type=int, default=os.environ.get("PORT", "8000") if external_url else 8000)
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    bind_host = "0.0.0.0" if external_url else "127.0.0.1"
    handler = make_handler(DashboardState(args.base), external_url or None, demo_password if external_url else None)
    server = ThreadingHTTPServer((bind_host, args.port), handler)
    dashboard_url = external_url or f"http://localhost:{server.server_port}"
    print(f"Medical data dashboard: {dashboard_url}", flush=True)
    print("Press Ctrl+C to stop.", flush=True)
    if args.open_browser:
        import webbrowser
        threading.Timer(0.5, lambda: webbrowser.open(dashboard_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
