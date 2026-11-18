"""Derived five-column-per-test view. Aligned arrays preserve repeated tests."""
import json
import re
from collections import defaultdict
import pandas as pd
from .database import connect,quote


def build_wide(frame,records,tests,db_path,folder):
    names={t:re.sub(r"[^A-Za-z0-9]+","_",t).strip("_") for t in tests}
    if len(set(names.values()))!=len(names):
        raise ValueError("Wide test names collide after identifier normalization")
    columns=[names[t]+suffix for t in tests for suffix in ["","_Result","_Range","_Unit","_Analytics"]]
    groups=defaultdict(list)
    for (_,row),record in zip(frame.iterrows(),records):
        if row.record_type=="lab_report":
            groups[(record.provenance.get("source_key",record.provenance["file"]),record.provenance["section"])].append(row)
    rows,index=[],[]
    for (file,section),items in groups.items():
        output={c:None for c in columns}
        for test in tests:
            matched=[r for r in items if pd.notna(r.test_name_canonical) and r.test_name_canonical==test]
            if not matched:
                continue
            for suffix,field in [("","test_name_canonical"),("_Result","result_value"),("_Range","range_text"),("_Unit","unit_canonical"),("_Analytics","test_analytics")]:
                values=[]
                for r in matched:
                    value=r[field]
                    if suffix=="_Result" and pd.isna(value):
                        value=r.result_text
                    if suffix=="_Unit" and pd.isna(value):
                        value=r.unit_original
                    values.append(None if pd.isna(value) else value)
                output[names[test]+suffix]=json.dumps(values,ensure_ascii=False)
        index.append({"row_index":len(rows),"file":file,"section":section})
        rows.append(output)
    wide=pd.DataFrame(rows,columns=columns)
    wide.to_csv(folder/"medical_tests_wide.csv",index=False)
    pd.DataFrame(index,columns=["row_index","file","section"]).to_csv(folder/"medical_tests_wide_index.csv",index=False)
    with connect(db_path) as db:
        db.execute("DROP TABLE IF EXISTS medical_tests_wide")
        db.execute("CREATE TABLE medical_tests_wide ("+", ".join(quote(c)+" TEXT" for c in columns)+")")
        if rows:
            db.executemany("INSERT INTO medical_tests_wide VALUES ("+", ".join("?" for c in columns)+")",[tuple(row[c] for c in columns) for row in rows])
        db.commit()
    return len(rows),len(columns)
