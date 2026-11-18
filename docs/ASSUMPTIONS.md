# Assumptions

## Business assumptions

- This is a take-home operational prototype, not a production claims adjudicator. Flags initiate review; they do not establish diagnosis, fraud or coverage eligibility.
- Local folders simulate clinic/date object storage. Real cloud credentials, notification recipients and reviewer repository access have not been supplied.
- Redacted source identifiers cannot establish patient identity across documents. Sample-source-1 through sample-source-5 are explicitly simulated clinic identities for demonstrating routing/metrics.
- The 98% target is a measured governance objective, not permission to invent aliases. Current coverage remains below it.

## Technical assumptions

- Python 3.10+, pandas/openpyxl, standard-library SQLite/HTTP server and browser HTML/CSS/JS keep setup simple. Verified locally with Python 3.12; dependencies are pinned.
- SQLite is a transactional single-machine prototype. `medical_records` has exactly the reference 78 columns, while separate tables store raw occurrences, source versions, decisions, reviews and run history.
- The full 78-column CSV/Excel is the source-audit output. The five-columns-per-test requirement is a separate wide view. Repeated tests become aligned JSON arrays in the five cells; the index file maps source rows. Unmapped tests remain in the long table and review reports.
- IDs use source relative path and occurrence position. An unchanged source and config retain ingestion/processing timestamps and do not add DB records; rename/reorder is a new identity unless a future upstream stable event key is supplied.
- The local pipeline is serial. Production architecture explains event-driven parallel workers rather than claiming this in-memory prototype meets cloud volume/uptime guarantees.

## Data assumptions

- The supplied schema XLSX and CSV must agree exactly. The original clinical workbook remains authoritative. Existing ambiguous names such as Hb/CREATININE remain blocked.
- Fuzzy candidates are suggestions by default. Auto-assignment is opt-in with threshold/margin; it cannot resolve blocked reference conflicts. Curated aliases require an approved flag and an existing canonical dictionary target.
- Mixed strings become numeric only when the complete suffix is an explicitly registered test/unit rule and agrees with any separate unit. Combined/conflicting fields remain raw with an Invalid review finding.
- Dimensional rules convert values and range bounds together. mil denotes million cells only in configured RBC aliases. There is no global case-insensitive unit equivalence.
- Adult/sex reference intervals require known age/sex. Source ranges are separately labelled unverified source evidence; redacted demographics remain redacted. Source pages may themselves contain OCR errors.
- Dolo-650 generic mapping is an exact curated product lookup with a source reference; its strength is recorded as reference metadata rather than inserted into a missing prescription dose. Unknown medicines are retained.
- Dates are normalized only when unambiguous. Structured age components are preserved without pretending months/days were normalized or inferring a birth date. Gender normalization supports known explicit aliases.
- Within-document exact suppression is enabled in the analytical database, while all 437 source occurrences stay in the audit export/raw table. Different-result tests and different-document similarities are not silently discarded.
- Blank versus null remains distinguishable in CSV and source audit; Excel cannot retain that distinction. Prototype PII masking changes only web views; raw disk/database access still requires OS controls.

## Scope exclusions and release gates

- Actual GCS/Eventarc/Cloud Run/managed database deployment and real paging/email notifications need cloud accounts, credentials and recipient configuration. Local ingestion, watcher, database, metrics and alert-state generation work without those services.
- Clinical sign-off is not supplied. Bundled references and explicit plausibility heuristics demonstrate the engine; production policies require qualified owner approval and validation.
- 98% mapping coverage cannot be responsibly achieved with this incomplete/conflicting workbook alone. The missing dictionary decisions remain review items; reporting them is deliberate.
- Production authentication, encryption key lifecycle, legal compliance certification, audited availability and large-scale load tests are not claimed.
- GitHub publication/reviewer access needs an authorized account/repository destination. The project structure and submission material are prepared locally; no source data is uploaded automatically.

## Requirements conflict decisions

Retain the earlier exact schema and no-source-deletion commitments. Add an independent wide view and configurable downstream suppression. Keep current XLSX mappings authoritative; JSON clinic/unit/reference/medicine policies add capabilities without silently approving disputed aliases. These choices are reversible and documented.
