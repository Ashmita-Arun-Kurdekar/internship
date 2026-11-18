"""Transactional SQLite snapshot, deduplicated analytics, provenance and run history."""
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
import pandas as pd


def quote(name):
    return '"' + name.replace('"','""') + '"'


def connect(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    return db


def setup(db,schema):
    definitions=", ".join(quote(c["column_name"])+(" REAL" if c["data_type"]=="FLOAT64" else " TEXT")+(" PRIMARY KEY" if c["column_name"]=="id" else "") for c in schema)
    for name in ["medical_records","raw_records"]:
        db.execute(f"CREATE TABLE IF NOT EXISTS {name} ({definitions})")
        actual=[r[1] for r in db.execute(f"PRAGMA table_info({name})")]
        if actual!=[c["column_name"] for c in schema]:
            raise ValueError("Existing database schema differs from reference")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS source_versions(source_key TEXT, source_hash TEXT, raw_json TEXT NOT NULL, PRIMARY KEY(source_key,source_hash));
    CREATE TABLE IF NOT EXISTS lineage(id TEXT PRIMARY KEY, source_key TEXT, source_hash TEXT, clinic_id TEXT, schema_version TEXT, section_index INTEGER, child_index INTEGER, canonical_id TEXT, suppressed INTEGER, first_ingested TEXT, config_hash TEXT);
    CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, decision_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, finished_at TEXT, summary_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS review_status(id TEXT PRIMARY KEY, status TEXT NOT NULL, note TEXT, updated_at TEXT);
    CREATE TABLE IF NOT EXISTS occurrence_history(id TEXT, source_hash TEXT, config_hash TEXT, record_json TEXT NOT NULL, PRIMARY KEY(id,source_hash,config_hash));
    """)
    db.commit()


def stable_timestamps(frame,records,path,schema,config_hash=None):
    with connect(path) as db:
        setup(db,schema)
        old={row[0]:row[1:] for row in db.execute("SELECT id,source_hash,first_ingested,config_hash FROM lineage")}
        for i,record in enumerate(records):
            previous=old.get(record.values["id"])
            if previous and previous[0]==record.provenance["source_hash"]:
                stamp=pd.Timestamp(previous[1])
                frame.at[i,"ingested_at"]=stamp
                if config_hash is None or previous[2]==config_hash:
                    frame.at[i,"processed_at"]=stamp
    return frame


def deduplication_links(records,mode):
    seen,links={},{}
    for record in records:
        v,p=record.values,record.provenance
        # Anonymous/redacted identities cannot be safely deduplicated across documents.
        key=json.dumps({"source":p.get("source_key",p["file"]),"document":v.get("document_id"),"type":v.get("record_type"),"section":p["section_data"],"child":p["child"]},sort_keys=True,ensure_ascii=False)
        canonical=seen.setdefault(key,v["id"]) if mode=="exact_within_document" else v["id"]
        links[v["id"]]=canonical
    return links


def serialize(value):
    if pd.isna(value):
        return None
    return value.isoformat() if isinstance(value,pd.Timestamp) else float(value) if isinstance(value,(float,int)) else value


def load_database(path,frame,records,audits,schema,summary,config):
    links=deduplication_links(records,config["settings"]["deduplication"]["mode"])
    columns=list(frame.columns)
    insert="("+", ".join(quote(c) for c in columns)+") VALUES ("+", ".join("?" for _ in columns)+")"
    with connect(path) as db:
        setup(db,schema)
        # Replace the current snapshot atomically; history remains append-only by version.
        db.execute("DELETE FROM medical_records")
        db.execute("DELETE FROM raw_records")
        for (_,row),record,audit in zip(frame.iterrows(),records,audits):
            values=tuple(serialize(v) for v in row)
            identifier=record.values["id"]
            p=record.provenance
            db.execute("INSERT INTO raw_records "+insert,values)
            if links[identifier]==identifier:
                db.execute("INSERT INTO medical_records "+insert,values)
            db.execute("INSERT OR IGNORE INTO source_versions VALUES (?,?,?)",(p["source_key"],p["source_hash"],json.dumps(p["source"],ensure_ascii=False)))
            db.execute("INSERT OR REPLACE INTO lineage VALUES (?,?,?,?,?,?,?,?,?,?,?)",(identifier,p["source_key"],p["source_hash"],p.get("clinic_id"),p.get("schema_version"),p["section"],p["child_index"],links[identifier],int(links[identifier]!=identifier),serialize(row.ingested_at),config["hash"]))
            db.execute("INSERT OR REPLACE INTO decisions VALUES (?,?)",(identifier,json.dumps(audit,ensure_ascii=False)))
            db.execute("INSERT OR IGNORE INTO occurrence_history VALUES (?,?,?,?)",(identifier,p["source_hash"],config["hash"],json.dumps(dict(zip(columns,values)),ensure_ascii=False)))
        active=int(db.execute("SELECT count(*) FROM medical_records").fetchone()[0])
        summary.update(database_rows=active,suppressed_duplicates=len(frame)-active,database=str(path))
        db.execute("INSERT INTO runs VALUES (?,?,?)",(summary["run_id"],summary["finished_at"],json.dumps(summary)))
        db.commit()
    return links


def history(path):
    if not path.exists():
        return []
    with connect(path) as db:
        try:
            return [json.loads(row[0]) for row in db.execute("SELECT summary_json FROM runs ORDER BY finished_at DESC LIMIT 30")]
        except sqlite3.OperationalError:
            return []


def review(path,identifier,status,note,timestamp):
    if status not in {"open","reviewed","resolved"} or len(note)>2000:
        raise ValueError("Invalid review status or note length")
    with connect(path) as db:
        if not db.execute("SELECT 1 FROM raw_records WHERE id=?",(identifier,)).fetchone():
            raise ValueError("Unknown record")
        db.execute("INSERT OR REPLACE INTO review_status VALUES (?,?,?,?)",(identifier,status,note,timestamp))
        db.commit()


def review_states(path):
    if not path.exists():
        return {}
    with connect(path) as db:
        try:
            return {r[0]:{"status":r[1],"note":r[2],"updated_at":r[3]} for r in db.execute("SELECT id,status,note,updated_at FROM review_status")}
        except sqlite3.OperationalError:
            return {}
