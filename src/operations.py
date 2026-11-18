"""Structured observability, dead-letter capture and portable metric exposition."""
import hashlib
import json
import logging
from datetime import datetime,timezone
from pathlib import Path


class JsonFormatter(logging.Formatter):
    def format(self,record):
        payload={"timestamp":datetime.now(timezone.utc).isoformat(),"level":record.levelname,"message":record.getMessage()}
        for key in ["run_id","correlation_id","document_id","record_id","clinic_id","source_file","stage"]:
            payload[key]=getattr(record,key,None)
        if record.exc_info:
            payload["exception"]=self.formatException(record.exc_info)
        return json.dumps(payload,ensure_ascii=False)


def configure_logging(base):
    console=logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logfile=logging.FileHandler(base/"logs/processing.log",encoding="utf-8")
    logfile.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.DEBUG,handlers=[console,logfile],force=True)


def capture_dead_letters(base,input_folder,issues,run_id):
    folder=base/"dead-letter"
    folder.mkdir(exist_ok=True)
    for issue in issues:
        source=input_folder/issue["file"]
        identity=hashlib.sha256((str(source)+json.dumps(issue,sort_keys=True)).encode()).hexdigest()
        data={"run_id":run_id,"source_file":issue["file"],"reason":issue["error"],"section":issue.get("section"),"status":"pending","captured_at":datetime.now(timezone.utc).isoformat()}
        if source.is_file():
            # Bytes, including malformed JSON, retained verbatim; no fabricated source envelope.
            (folder/(identity+".source")).write_bytes(source.read_bytes())
        (folder/(identity+".json")).write_text(json.dumps(data,indent=2),encoding="utf-8")


def metrics_and_alerts(summary,settings,folder):
    monitoring=settings["monitoring"]
    alerts=[]
    for metric,threshold in [("error_rate",monitoring["error_rate_threshold"]),("processing_lag_seconds",monitoring["lag_sla_seconds"])]:
        if summary[metric]>threshold:
            alerts.append({"metric":metric,"value":summary[metric],"threshold":threshold,"severity":"warning"})
    if summary["distinct_variant_coverage"]<monitoring["coverage_target"]:
        alerts.append({"metric":"distinct_variant_coverage","value":summary["distinct_variant_coverage"],"threshold":monitoring["coverage_target"],"severity":"review"})
    lines=[]
    for key in ["input_files_processed","output_rows","database_rows","validation_errors","processing_errors","error_rate","processing_lag_seconds","duration_seconds","records_per_second","distinct_variant_coverage"]:
        lines.append(f"medical_pipeline_{key} {summary.get(key,0)}")
    (folder/"metrics.prom").write_text("\n".join(lines)+"\n")
    (folder/"alerts.json").write_text(json.dumps(alerts,indent=2))
    return alerts
