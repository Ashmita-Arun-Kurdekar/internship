# Medical Data Standardisation

This take-home prototype turns clinic JSON reports into standardised tables. It retains source evidence for review, classifies results using configured rules, and loads records into SQLite. The dashboard uses plain HTML, CSS and JavaScript with Python's built-in HTTP server.

## Run on Windows

Open Command Prompt in the project folder. Use Python 3.10 or newer.

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
python -m pip install -r requirements.txt
python -m src.main
python -m pytest -q
python -m src.webapp
```

Open http://localhost:8000. Press Ctrl+C to stop the server. Use `python -m src.webapp --port 8001` if port 8000 is occupied. After setup, `Start-dashboard.cmd` can also launch the dashboard.

The pipeline uses `sample-data/` when `input/` is absent. To test your own file, create `input/`, copy the JSON there, and run `python -m src.main` or click **Run pipeline** in the dashboard. The pipeline uses only `input/` when that folder exists. Restore the five-file batch before running the dashboard tests, which use the sample outputs.

## Pipeline and dashboard

| Area | Implementation |
|---|---|
| Ingestion | Local batch CLI, dashboard trigger, and folder watcher (`python -m src.scheduler`). Use `--once` to run the watcher once. |
| Configuration | Editable clinic/schema paths, aliases, units, medicine mapping, range rules, and duplicate policy in `config/`. The supplied schema and clinical dictionary are in `reference/`. |
| Standardisation | Canonical test names, reviewed aliases, fuzzy suggestions, numeric parsing, unit conversion, demographic parsing, and exact medicine mappings. |
| Validation | Range, plausibility, and invalid-result flags with their decision basis recorded for review. |
| Persistence | Transactional SQLite loads, stable source identities, run history, configurable duplicate suppression, and raw lineage. |
| Dashboard | Run summary and history, searchable records, raw/transformed inspector, flags and review states, clinic/source quality, and downloads. Sample clinic labels are simulated. |
| Operations | Structured logs, /metrics, alert state, and dead-letter records. Correct a failed source and run `python -m src.reprocess` to retry. |

## Generated files

- `output/standardised_medical_data.csv` and `.xlsx` contain the 78-column reference layout, one row per extracted item.
- `output/medical_tests_wide.csv` contains five columns per configured test. The companion index links each wide row to its source. Repeated results use aligned JSON arrays.
- `data/medical_data.sqlite3` holds analytical records, raw records, lineage, and run history.
- `reports/` contains validation and processing errors, unmapped names, fuzzy suggestions, clinical flags, and metrics.

## Design decisions and limitations

The long-format export preserves extracted occurrences. The analytical database can suppress exact duplicates within a report, while the derived wide output satisfies the five-column-per-test requirement. CSV uses the literal token `\N` for missing data and retains source empty strings. Excel displays both as blank.

The configured alias `aemoglobin` comes from the assignment. The workbook takes precedence on conflicts, including the attempted `Hemoglobin` override. Uncertain OCR variants remain in review. The distinct-variant coverage metric in `reports/metrics.prom` is below the 98% target. Fuzzy assignment is disabled by default. Reference intervals depend on units and applicable demographics. The configured clinical rules demonstrate classification and require clinical review before use in adjudication.

See the [architecture](docs/ARCHITECTURE.md), [non-functional notes](docs/NFR_NOTES.md), [assumptions](docs/ASSUMPTIONS.md), and [reference register](docs/REFERENCES.md). The cloud architecture describes how production ingestion, scale, and alerts would work. The runnable submission uses local files and SQLite. Share the supplied sample JSON and reference files only with authorized reviewers, and keep your own inputs and generated artifacts out of Git.
