"""Assignment extensions: real idempotency and explicitly synthetic clinical/clinic edges."""
import copy
import json
import shutil
import sqlite3
from pathlib import Path
import pandas as pd
import pytest
from src.configuration import load_config
from src.adapters import adapt_source
from src.clinical import demographics,parse_mixed,unit_rule,clinical_classification,enrich,add_config_aliases,mask_values
from src.standardisation import ClinicalMappings
from src.extraction import extract
from src.transformation import load_schema,transform
from src.database import deduplication_links,review,review_states
from src.main import run
from src.operations import capture_dead_letters,metrics_and_alerts
from src.reprocess import retry
from src.webapp import load_snapshot

BASE=Path(__file__).resolve().parents[1]

@pytest.fixture
def config():
    return load_config(BASE)

@pytest.fixture
def mappings():
    return ClinicalMappings(BASE/"reference/Clinical_name_standardization.xlsx")

@pytest.mark.parametrize("age,gender,expected,sex",[("33Y11M265D","M",{"years":33,"months":11,"days":265},"Male"),("22","female",{"years":22,"months":None,"days":None},"Female"),("[AGE REDACTED]","[GENDER REDACTED]",{"years":None,"months":None,"days":None},None)])
def test_synthetic_demographics(age,gender,expected,sex):
    result=demographics(age,gender)
    assert result["age"]==expected and result["gender"]==sex

@pytest.mark.parametrize("raw,unit,test,value,issue",[("120000 cells/cu.mm","cells/cu.mm","Platelet Count",120000.,None),("2.5 g/L","g/L","HAEMOGLOBIN",2.5,None),("120 mg/dL","g/dL","HAEMOGLOBIN",None,"non_numeric_or_missing"),("13 g/L","g/dL","HAEMOGLOBIN",None,"contradictory_or_unknown_unit"),("12 / 14","g/dL","HAEMOGLOBIN",None,"multiple_or_complex_values"),("NEGATIVE","","HAEMOGLOBIN",None,"non_numeric_or_missing")])
def test_synthetic_mixed_numeric(config,raw,unit,test,value,issue):
    result=parse_mixed(raw,unit,test,config)
    assert result["value"]==value and result["issue"]==issue

@pytest.mark.parametrize("unit,factor",[("mil/cu.mm",1),("mil/cu.cm",.001)])
def test_synthetic_dimensional_conversion(config,unit,factor):
    rule=unit_rule("Red Blood Cell Count (RBC)",unit,config)
    assert rule["factor"]==factor and rule["canonical"]=="10^12/L"

@pytest.mark.parametrize("value,expected",[(15,"Within Range"),(10,"Below Range"),(20,"Above Range"),(.1,"Outlier"),(999,"Outlier"),(None,"Invalid")])
def test_synthetic_medical_reference_classifications(config,value,expected):
    result=clinical_classification(value,"HAEMOGLOBIN","g/dL",(None,None),demographics("35","M"),config)
    assert result[0]==expected
    if value is not None and expected not in {"Outlier"}:
        assert result[1]=="reference_dictionary"


def test_synthetic_missing_context_is_not_normal(config):
    assert clinical_classification(15,"HAEMOGLOBIN","g/dL",(None,None),demographics(None,None),config)[0]=="Invalid"
    assert clinical_classification(15,"HAEMOGLOBIN","g/dL",(12,17),demographics(None,None),config)[1]=="source_document_range_not_independently_verified"
    assert clinical_classification(50,"ALANINE AMINOTRANSFERASE","U/L",(None,50),demographics(None,None),config,"<")[0]=="Above Range"


def synthetic_root(name="SODIUN",value="140",unit="mmol/L"):
    return {"traceId":"synthetic-trace","data":{"documentId":"synthetic-doc","responseDetails":[{"classifier":"lab_report","data":{"basic_info":{"age":"35","gender":"M"},"report_details":[{"test_name":name,"result":value,"unit":unit,"range":"135-145"}]}}]}}


def test_synthetic_fuzzy_assignment_opt_in_and_conflict_block(config,mappings):
    config["settings"]["fuzzy"].update(auto_assign=True,threshold=.8,margin=.01)
    rows,_=extract(Path("synthetic.json"),synthetic_root())
    schema=load_schema(BASE/"reference")
    frame,_,_=transform(rows,schema,mappings,"2026-11-17T00:00:00Z")
    result,audits,flags,suggestions=enrich(frame,rows,mappings,config)
    assert result.loc[0,"test_name_canonical"]=="SODIUM"
    assert result.loc[0,"normalization_method"]=="configured_fuzzy_reference"
    assert suggestions[0]["auto_assigned"]
    rows,_=extract(Path("synthetic.json"),synthetic_root("Hb","15","g/dL"))
    frame,_,_=transform(rows,schema,mappings,"2026-11-17T00:00:00Z")
    result,_,_,suggestions=enrich(frame,rows,mappings,config)
    assert pd.isna(result.loc[0,"test_name_canonical"]) and not suggestions


def test_synthetic_alias_cannot_override_conflict(config,mappings):
    config["test_aliases"]["aliases"]=[{"name":"Hb","canonical":"HAEMOGLOBIN","approved":True}]
    with pytest.raises(ValueError,match="conflicts"):
        add_config_aliases(mappings,config)


def test_synthetic_new_clinic_without_code_changes(config):
    # A completely different field layout is handled by a JSON profile edit only.
    profile=copy.deepcopy(config["clinics"]["profiles"][1])
    profile.update(id="synthetic-clinic-v2",detect="visits",sections="visits")
    profile["lab"]["fields"]["patient_name"]="$root.person.full_name"
    config["clinics"]["profiles"].append(profile)
    config["clinics"]["clinics"].append({"file_pattern":"clinic-v2/*.json","clinic_id":"SYNTHETIC-CLINIC","profile":profile["id"]})
    raw={"document_id":"synthetic-document","person":{"full_name":"SYNTHETIC PATIENT"},"visits":[{"kind":"laboratory","observations":[{"name":"SODIUM","value":"140","units":"mmol/L"}]}]}
    normalized=adapt_source(raw,"clinic-v2/test.json",config)
    rows,errors=extract(Path("test.json"),normalized)
    assert not errors and rows[0].values["patient_name"]=="SYNTHETIC PATIENT"
    assert rows[0].provenance["clinic_id"]=="SYNTHETIC-CLINIC"
    assert rows[0].provenance["source"]==raw


def test_synthetic_suppression_config_keeps_raw(config):
    rows,_=extract(Path("synthetic.json"),{"data":{"documentId":"X","responseDetails":[{"classifier":"lab_report","data":{"report_details":[{"test_name":"X","result":"1"},{"test_name":"X","result":"1"},{"test_name":"X","result":"2"}]}}]}})
    assert len(set(deduplication_links(rows,"none").values()))==3
    assert len(set(deduplication_links(rows,"exact_within_document").values()))==2
    assert len(rows)==3


def test_synthetic_unit_config_conflict_rejected(tmp_path,config):
    shutil.copytree(BASE/"config",tmp_path/"config")
    path=tmp_path/"config/units.json"
    units=json.loads(path.read_text());duplicate=dict(units["rules"][0]);duplicate["factor"]=10;units["rules"].append(duplicate);path.write_text(json.dumps(units))
    with pytest.raises(ValueError,match="Conflicting unit"):
        load_config(tmp_path)


def test_synthetic_pii_tokenization(config,monkeypatch):
    privacy=config["settings"]["privacy"]
    privacy["mask_dashboard"]=True
    monkeypatch.setenv("MEDICAL_PII_SALT","SYNTHETIC_TEST_SECRET")
    raw={"patient_name":"SYNTHETIC NAME","result":"14"}
    first=mask_values(raw,privacy)
    assert first["patient_name"].startswith("token:") and first["result"]=="14"
    assert mask_values(raw,privacy)==first and raw["patient_name"]=="SYNTHETIC NAME"
    monkeypatch.delenv("MEDICAL_PII_SALT")
    with pytest.raises(ValueError):
        mask_values(raw,privacy)


def test_synthetic_alert_thresholds(tmp_path,config):
    summary={"error_rate":.02,"processing_lag_seconds":901,"distinct_variant_coverage":.5}
    alerts=metrics_and_alerts(summary,config["settings"],tmp_path)
    assert {a["metric"] for a in alerts}=={"error_rate","processing_lag_seconds","distinct_variant_coverage"}
    assert "medical_pipeline_error_rate 0.02" in (tmp_path/"metrics.prom").read_text()


def test_synthetic_deadletter_retains_bad_bytes(tmp_path):
    folder=tmp_path/"input";folder.mkdir();(folder/"bad.json").write_bytes(b'{bad-json')
    capture_dead_letters(tmp_path,folder,[{"file":"bad.json","error":"SYNTHETIC parse error"}],"synthetic-run")
    assert next((tmp_path/"dead-letter").glob("*.source")).read_bytes()==b'{bad-json'
    assert json.loads(next((tmp_path/"dead-letter").glob("*.json")).read_text())["status"]=="pending"


def test_real_database_rerun_and_exact_schema(tmp_path):
    for folder in ["sample-data","reference","config"]:
        shutil.copytree(BASE/folder,tmp_path/folder)
    first=run(tmp_path)
    csv_before=(tmp_path/"output/standardised_medical_data.csv").read_bytes()
    second=run(tmp_path)
    assert first["status"]==second["status"]=="PASS"
    assert second["database_rows"]==424 and second["suppressed_duplicates"]==13
    assert csv_before==(tmp_path/"output/standardised_medical_data.csv").read_bytes()
    with sqlite3.connect(tmp_path/"data/medical_data.sqlite3") as db:
        assert db.execute("SELECT count(*) FROM raw_records").fetchone()[0]==437
        assert db.execute("SELECT count(*) FROM medical_records").fetchone()[0]==424
        assert db.execute("SELECT count(*) FROM runs").fetchone()[0]==2
        assert len(db.execute("PRAGMA table_info(medical_records)").fetchall())==78
        assert len(db.execute("PRAGMA table_info(medical_tests_wide)").fetchall())==60
        identifier=db.execute("SELECT id FROM raw_records LIMIT 1").fetchone()[0]
    review(tmp_path/"data/medical_data.sqlite3",identifier,"reviewed","SYNTHETIC REVIEW NOTE","2026-11-17T00:00:00Z")
    assert review_states(tmp_path/"data/medical_data.sqlite3")[identifier]["status"]=="reviewed"
    snapshot=load_snapshot(tmp_path)
    assert len(snapshot["groups"])==5 and len(snapshot["run_history"])==2
    assert snapshot["summary"]["medicine_names_mapped"]==3
    assert snapshot["flag_counts"]["clinical"]>0
