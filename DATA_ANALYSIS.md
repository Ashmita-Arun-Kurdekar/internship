# Data analysis and mapping decisions

All five supplied JSON files and both XLSX workbooks were inspected before implementation. The schema CSV and workbook contain 78 identical ordered definitions: 71 STRING, 5 FLOAT64 and 2 TIMESTAMP; all nullable. The XLSX is authoritative; disagreement with the CSV is fatal.

## Input inventory

|File|Sections|Lab tests|Medications|Rows|
|---|---:|---:|---:|---:|
|Sample_JSON_file1.json|1|0|18|18|
|Sample_JSON_file2.json|2|23|3|26|
|Sample_JSON_file3.json|1|0|18|18|
|Sample_JSON_file4.json|2|193|15|208|
|Sample_JSON_file5.json|3|147|20|167|

## Row strategy and preservation

One row per report_details element (record_type lab_report), or dischargeMedications element (record_type discharge_summary). Keep a document row when its child array is empty. Never cross join tests and medications. Child order and every occurrence are retained. IDs are deterministic SHA-256 hashes of source filename, section index and child index, and are explicitly generated technical identifiers. Timestamps record processing and ingestion UTC times, not clinical events. Envelope documentId identifies the source document; section index and fileId stay in provenance.

Exact same section content in file 5 is retained. Files 1 and 3 contain identical discharge clinical payloads with different document identifiers; these are cross-document similarities, not grounds for deletion. Repeated names with different results are separately classified. Duplicate reports retain source positions.

Original files are copied byte-for-byte to input and never modified. reports/provenance.jsonl stores each entire source envelope, source path, section/child indices and output ID. This preserves empty versus null, envelope statuses, fileId, extra fields and original dates without adding columns. Lists in schema STRING fields are JSON encoded. No redaction token, N/A, header-like lab row, questionable OCR medication, or inconsistent clinical value is repaired or discarded.

## Safe conversion and mapping rules

Clinical matching only collapses whitespace and case, with exact dictionary lookup. Confidence 1.0 means exact reference match, not clinical certainty. Unknown/ambiguous names have null canonical and confidence, with an explicit method. No fuzzy matching. Conflicts remain blocked, including canonical spellings when the same normalized key conflicts.

The workbook uses bracketed unquoted lists. Serum Creatinine (declared 3, comma split 4), ALBUMIN (2 versus 3) and URIC ACID (2 versus 3) cannot be tokenized reliably because names include commas. Their alias lists are disabled pending review; canonical self-names remain usable unless conflicted. Tentative split tokens participate in conflict detection so CREATININE is blocked rather than silently assigned. Hb also conflicts. The raw cell and declared counts are reported. No alias override is approved.

Numeric parsing accepts only a complete signed decimal/exponent string, rejects booleans and nonfinite values. Complex results such as 98.6 degree F, 100/60 mmHg and result ranges stay as text. Reference bounds are extracted only from a complete two-number low-high expression with low <= high; inequalities and single numbers stay as text. All originals are duplicated into raw schema fields.

Dates: ISO YYYY-MM-DD, named-month DD/Mon/YYYY and DD-Mon-YYYY, and numeric day/month or month/day only if there is exactly one valid calendar interpretation (or both coincide). Otherwise retain original string and report ambiguity/invalidity. DD/MM/YYYY placeholders and LAB10945 are not parsed. Output successful dates use YYYY-MM-DD. No age inference or unit normalization/conversion; unit_canonical stays null.

## Findings

Lab data uses basic_info and report_details; discharge data uses camelCase fields and dischargeMedications. Metadata is data.metaDetails key/value array; traceId is at the root, documentId and correlationId under data. No file_gcs_path is supplied. case_id in file 5 is preserved in metadetails. All medicine type entries are null; initial medications in files 1/3 have empty doses/frequencies. courseDuringHospitalisation is an empty list. File 2 contains truncated test names and bill_date LAB10945. File 5 contains placeholder lab headings, dates, composite values and visibly corrupted medication strings. Preserve all for source review.

## Complete observed nested paths and types

|Path|Types/counts|
|---|---|
|$|{'dict': 5}|
|$.data|{'dict': 5}|
|$.data.correlationId|{'str': 5}|
|$.data.documentId|{'str': 5}|
|$.data.message|{'NoneType': 5}|
|$.data.metaDetails|{'list': 5}|
|$.data.metaDetails[]|{'dict': 26}|
|$.data.metaDetails[].key|{'str': 26}|
|$.data.metaDetails[].value|{'str': 26}|
|$.data.responseDetails|{'list': 5}|
|$.data.responseDetails[]|{'dict': 9}|
|$.data.responseDetails[].classifier|{'str': 9}|
|$.data.responseDetails[].data|{'dict': 9}|
|$.data.responseDetails[].data.admissionDate|{'str': 6}|
|$.data.responseDetails[].data.age|{'str': 6}|
|$.data.responseDetails[].data.basic_info|{'dict': 3}|
|$.data.responseDetails[].data.basic_info.age|{'str': 3}|
|$.data.responseDetails[].data.basic_info.bill_date|{'str': 3}|
|$.data.responseDetails[].data.basic_info.gender|{'str': 3}|
|$.data.responseDetails[].data.basic_info.lab_or_hospital_name|{'str': 3}|
|$.data.responseDetails[].data.basic_info.patient_name|{'str': 3}|
|$.data.responseDetails[].data.basic_info.reports_date|{'str': 3}|
|$.data.responseDetails[].data.basic_info.uhid|{'str': 3}|
|$.data.responseDetails[].data.briefHistory|{'str': 6}|
|$.data.responseDetails[].data.courseDuringHospitalisation|{'list': 6}|
|$.data.responseDetails[].data.diagnosis|{'str': 6}|
|$.data.responseDetails[].data.dischargeDate|{'str': 6}|
|$.data.responseDetails[].data.dischargeMedications|{'list': 6}|
|$.data.responseDetails[].data.dischargeMedications[]|{'dict': 74}|
|$.data.responseDetails[].data.dischargeMedications[].dose|{'str': 74}|
|$.data.responseDetails[].data.dischargeMedications[].frequency|{'str': 74}|
|$.data.responseDetails[].data.dischargeMedications[].medicine|{'str': 74}|
|$.data.responseDetails[].data.dischargeMedications[].type|{'NoneType': 74}|
|$.data.responseDetails[].data.doctorName|{'str': 6}|
|$.data.responseDetails[].data.gender|{'str': 6}|
|$.data.responseDetails[].data.generalExaminations|{'str': 6}|
|$.data.responseDetails[].data.hospitalAddress|{'str': 6}|
|$.data.responseDetails[].data.hospitalName|{'str': 6}|
|$.data.responseDetails[].data.medicineInjectionsInvestigation|{'list': 6}|
|$.data.responseDetails[].data.medicineInjectionsInvestigation[]|{'str': 32}|
|$.data.responseDetails[].data.patientName|{'str': 6}|
|$.data.responseDetails[].data.postDischargeAdvice|{'NoneType': 6}|
|$.data.responseDetails[].data.recommendations|{'str': 6}|
|$.data.responseDetails[].data.report_details|{'list': 3}|
|$.data.responseDetails[].data.report_details[]|{'dict': 363}|
|$.data.responseDetails[].data.report_details[].page_no|{'int': 363}|
|$.data.responseDetails[].data.report_details[].range|{'str': 363}|
|$.data.responseDetails[].data.report_details[].result|{'str': 363}|
|$.data.responseDetails[].data.report_details[].test_analytics|{'str': 363}|
|$.data.responseDetails[].data.report_details[].test_name|{'str': 363}|
|$.data.responseDetails[].data.report_details[].unit|{'str': 363}|
|$.data.responseDetails[].data.ward|{'str': 6}|
|$.data.responseDetails[].errorMessage|{'NoneType': 9}|
|$.data.responseDetails[].fileId|{'NoneType': 9}|
|$.data.responseDetails[].status|{'str': 9}|
|$.data.status|{'bool': 5}|
|$.message|{'list': 5}|
|$.message[]|{'str': 5}|
|$.statusCode|{'int': 5}|
|$.traceId|{'str': 5}|

## All 78 target columns and source mapping

Every missing source value remains null; explicit empty strings and list values are retained. Safe date normalization applies to bill_date, reports_date, report_date, admission_date and discharge_date; originals remain in raw columns or provenance. Aliases intentionally duplicate source values to satisfy the provided schema.

|Order|Target|Type|Source / rule|
|---:|---|---|---|
|1|id|STRING|Generated SHA-256(filename, section index, child index); technical identifier|
|2|document_id|STRING|data.documentId|
|3|record_type|STRING|data.responseDetails[].classifier|
|4|file_gcs_path|STRING|metaDetails[file_gcs_path] or explicit data.file_gcs_path; absent in samples|
|5|trace_id|STRING|root.traceId|
|6|correlation_id|STRING|data.correlationId|
|7|source_system|STRING|data.metaDetails key source_system|
|8|claim_no|STRING|data.metaDetails key claim_no|
|9|nt_code|STRING|data.metaDetails key nt_code|
|10|consumer_client_id|STRING|data.metaDetails key ConsumerClientId|
|11|destination_identifier|STRING|data.metaDetails key DestinationIdentifier|
|12|patient_name|STRING|Lab basic_info.patient_name or Discharge data.patientName|
|13|age|STRING|Lab basic_info.age or Discharge data.age|
|14|gender|STRING|Lab basic_info.gender or Discharge data.gender|
|15|uhid|STRING|Lab basic_info.uhid|
|16|hospital_name|STRING|Discharge data.hospitalName or lab basic_info.lab_or_hospital_name|
|17|doctor_name|STRING|Lab basic_info.doctor_name or Discharge data.doctorName|
|18|bill_date|STRING|Lab basic_info.bill_date|
|19|reports_date|STRING|Lab basic_info.reports_date|
|20|test_name_canonical|STRING|Unique approved clinical reference match only|
|21|test_name_original|STRING|Lab report_details[].test_name verbatim|
|22|result_value|FLOAT64|report_details[].result parsed only as complete finite numeric string|
|23|result_text|STRING|Lab report_details[].result verbatim|
|24|unit_canonical|STRING|Null; no approved unit normalization rule|
|25|unit_original|STRING|Lab report_details[].unit verbatim|
|26|range_low|FLOAT64|report_details[].range complete two-number low-high expression only|
|27|range_high|FLOAT64|report_details[].range complete two-number low-high expression only|
|28|range_text|STRING|Lab report_details[].range verbatim|
|29|test_analytics|STRING|Lab report_details[].test_analytics verbatim|
|30|normalization_method|STRING|exact_normalized_reference / unknown / ambiguous / missing|
|31|normalization_confidence|FLOAT64|1.0 for exact reference lookup; null otherwise|
|32|admission_date|STRING|Discharge data.admissionDate|
|33|discharge_date|STRING|Discharge data.dischargeDate|
|34|diagnosis|STRING|Discharge data.diagnosis|
|35|brief_history|STRING|Discharge data.briefHistory|
|36|general_examinations|STRING|Discharge data.generalExaminations|
|37|recommendations|STRING|Discharge data.recommendations|
|38|hospital_address|STRING|Discharge data.hospitalAddress|
|39|ward|STRING|Discharge data.ward|
|40|post_discharge_advice|STRING|Discharge data.postDischargeAdvice|
|41|medicine|STRING|Discharge dischargeMedications[].medicine verbatim|
|42|dose|STRING|Discharge dischargeMedications[].dose verbatim|
|43|frequency|STRING|Discharge dischargeMedications[].frequency verbatim|
|44|medicine_type|STRING|Discharge dischargeMedications[].type verbatim|
|45|processed_at|TIMESTAMP|Generated actual processing UTC timestamp|
|46|ingested_at|TIMESTAMP|Generated batch load UTC timestamp|
|47|basic_info_age|STRING|Lab basic_info.age (age_text also discharge age)|
|48|basic_info_bill_date|STRING|Lab basic_info.bill_date (age_text also discharge age)|
|49|medicine_injections_investigation|STRING|Discharge data.medicineInjectionsInvestigation|
|50|discharge_medications_dose|STRING|Discharge dischargeMedications[].dose verbatim|
|51|metadetails|STRING|data.metaDetails serialized as JSON, including unrecognized keys|
|52|discharge_medications_frequency|STRING|Discharge dischargeMedications[].frequency verbatim|
|53|discharge_medications_medicine|STRING|Discharge dischargeMedications[].medicine verbatim|
|54|lab_or_hospital_name|STRING|Lab basic_info.lab_or_hospital_name|
|55|report_details_page_no|STRING|Lab report_details[].page_no verbatim (page number serialized to STRING)|
|56|report_details_range|STRING|Lab report_details[].range verbatim (page number serialized to STRING)|
|57|report_details_result|STRING|Lab report_details[].result verbatim (page number serialized to STRING)|
|58|report_details_test_analytics|STRING|Lab report_details[].test_analytics verbatim (page number serialized to STRING)|
|59|report_details_test_name|STRING|Lab report_details[].test_name verbatim (page number serialized to STRING)|
|60|report_details_unit|STRING|Lab report_details[].unit verbatim (page number serialized to STRING)|
|61|age_text|STRING|Lab basic_info.age (age_text also discharge age)|
|62|other_med_inj_investigations|STRING|Alias of discharge data.medicineInjectionsInvestigation; JSON for lists|
|63|report_date|STRING|Lab basic_info.reports_date (age_text also discharge age)|
|64|course_during_hospitalisation|STRING|Discharge data.courseDuringHospitalisation|
|65|page_number|STRING|Lab report_details[].page_no verbatim|
|66|range_text_original|STRING|Lab report_details[].range verbatim|
|67|medication_dose|STRING|Discharge dischargeMedications[].dose verbatim|
|68|result_text_original|STRING|Lab report_details[].result verbatim|
|69|medication_frequency|STRING|Discharge dischargeMedications[].frequency verbatim|
|70|course_during_hospitalization|STRING|Alias of discharge data.courseDuringHospitalisation; JSON for lists|
|71|medication_name|STRING|Discharge dischargeMedications[].medicine verbatim|
|72|page_no|STRING|Lab report_details[].page_no verbatim|
|73|test_name|STRING|Lab report_details[].test_name verbatim|
|74|medication_medicine|STRING|Discharge dischargeMedications[].medicine verbatim|
|75|result|STRING|Lab report_details[].result verbatim|
|76|unit|STRING|Lab report_details[].unit verbatim|
|77|age_years|STRING|Null; no inferred age from redactions or text|
|78|range|STRING|Lab report_details[].range verbatim|

## Execution findings

Verified sample execution produced 437 rows (363 tests and 74 medications), with 60 exact standardized occurrences and 303 unknown occurrences. There were no ambiguous input matches. Reference review includes Hb and CREATININE conflicts plus the unsafe tentative token SERUM, which is an artifact of malformed comma serialization. There are 3 unsafe alias lists. There were 13 exact repeated row occurrences, 18 similar rows under different source document IDs and 62 repeated-name/different-result occurrences. All 93 flagged rows were retained. Schema/source validation found zero errors. Date review has 468 entries counted per output row and target date field; repeated document context and aliases produce multiple review entries for the same original date.
