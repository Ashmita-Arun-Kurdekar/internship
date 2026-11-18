"""Dashboard API integration tests using real artifacts and synthetic HTTP requests."""
import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
import pytest
from src.webapp import BASE, DashboardState, load_snapshot, make_handler


def test_real_dashboard_totals_and_lineage():
    data = load_snapshot(BASE)
    assert len(data["records"]) == data["summary"]["output_rows"] == 437
    assert sum(g["rows"] for g in data["groups"]) == 437
    assert data["summary"]["standardised_test_names"] == 61
    assert {k:data["flag_counts"][k] for k in ["mapping","date","duplicate"]} == {"mapping":302,"date":468,"duplicate":93}
    assert data["flag_counts"]["clinical"] > 0
    assert data["flagged_rows"] == len({r["id"] for r in data["records"] if r["flags"]})
    row = data["records"][0]
    assert row["values"]["file_gcs_path"] is None
    assert row["file"] == "Sample_JSON_file1.json"
    assert row["section"] == 0 and row["child_index"] == 0
    assert row["values"]["medication_dose"] == ""


def test_synthetic_no_run_yet(tmp_path):
    data = load_snapshot(tmp_path)
    assert data["records"] == [] and data["summary"] == {}
    assert data["groups"] == [] and data["updated_at"] is None


@pytest.fixture
def server():
    state = DashboardState(BASE)
    http = ThreadingHTTPServer(("127.0.0.1",0), make_handler(state))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{http.server_port}", state
    http.shutdown()
    http.server_close()
    thread.join()


def read(url, headers=None, method="GET"):
    return urlopen(Request(url, headers=headers or {}, method=method), timeout=20)


def test_static_pages_and_headers(server):
    url, _ = server
    for path, expected in [("/","Record explorer"),("/app.js","async function inspect"),("/style.css","@media")]:
        with read(url+path) as response:
            assert response.status == 200
            assert expected in response.read().decode()
            assert response.headers["Cache-Control"] == "no-store"
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_real_api_and_inspector(server):
    url, _ = server
    with read(url+"/api/data") as response:
        data=json.load(response)
    identifier=data["records"][0]["id"]
    with read(url+"/api/record?id="+identifier) as response:
        record=json.load(response)
    assert record["record"]["id"] == record["provenance"]["id"]
    assert record["provenance"]["child"]["medicine"] == record["record"]["values"]["medication_name"]
    assert "traceId" in record["provenance"]["source"]
    assert len(record["record"]["values"]) == 78
    with pytest.raises(HTTPError) as exc:
        read(url+"/api/record?id=nonexistent")
    assert exc.value.code == 404


def test_download_matches_generated_file(server):
    url, _ = server
    for key,filename in [("csv","standardised_medical_data.csv"),("excel","standardised_medical_data.xlsx")]:
        with read(url+"/download/"+key) as response:
            assert response.read() == (BASE/"output"/filename).read_bytes()
            assert filename in response.headers["Content-Disposition"]


@pytest.mark.parametrize("path",["/../input/Sample_JSON_file1.json","/download/../../input/Sample_JSON_file1.json","/src/main.py"])
def test_no_arbitrary_file_serving(server,path):
    url, _ = server
    with pytest.raises(HTTPError) as exc:
        read(url+path)
    assert exc.value.code == 404


def test_run_requires_same_origin_token(server):
    url, state=server
    with pytest.raises(HTTPError) as exc:
        read(url+"/api/run",method="POST")
    assert exc.value.code == 403
    with pytest.raises(HTTPError) as exc:
        read(url+"/api/run",headers={"X-Dashboard-Token":state.token,"Origin":"http://other.example"},method="POST")
    assert exc.value.code == 403
    with pytest.raises(HTTPError) as exc:
        read(url+"/api/data",headers={"Host":"untrusted.example"})
    assert exc.value.code == 403


def test_run_endpoint_and_busy_exports(server,monkeypatch):
    url,state=server
    monkeypatch.setattr(state,"_process",lambda: None)
    with read(url+"/api/session") as response:
        token=json.load(response)["token"]
    with read(url+"/api/run",headers={"X-Dashboard-Token":token},method="POST") as response:
        assert response.status==202 and json.load(response)["started"]
    assert state.running
    with pytest.raises(HTTPError) as exc:
        read(url+"/api/run",headers={"X-Dashboard-Token":token},method="POST")
    assert exc.value.code==409
    with pytest.raises(HTTPError) as exc:
        read(url+"/download/csv")
    assert exc.value.code==409
    with read(url+"/api/data") as response:
        assert json.load(response)["running"] is True
    state.running=False


def test_synthetic_failed_run_visible(monkeypatch,tmp_path):
    state=DashboardState(tmp_path)
    class Result:
        returncode=1
        stdout=""
        stderr="SYNTHETIC processing failure"
    monkeypatch.setattr("src.webapp.subprocess.run",lambda *args,**kwargs: Result())
    state.last_run={"started_at":"synthetic"}
    state.running=True
    state._process()
    assert not state.running
    assert state.last_run["exit_code"]==1
    assert "SYNTHETIC" in state.last_run["log"]
