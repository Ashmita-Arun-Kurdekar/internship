# Reference register

Verified 17 November 2026. Values are summarized; source text is not copied wholesale. External source availability does not constitute organizational clinical approval.

| Reference | Use and limitations |
|---|---|
| [Provided ideal schema](../reference/Ourput-table-ideal-schema.xlsx) | Authoritative 78 ordered columns/types/nullability; cross-checked with CSV. |
| [Provided clinical dictionary](../reference/Clinical_name_standardization.xlsx) | Authoritative canonical names/aliases; conflicts and malformed lists remain unresolved. |
| [MedlinePlus / National Library of Medicine: Hemoglobin](https://medlineplus.gov/ency/article/003645.htm) | General adult intervals: male 13.8?17.2, female 12.1?15.1 g/dL. Context-dependent; source explicitly notes laboratory differences. Applied only to known adult age/sex. |
| [ASHP: Basic Skills in Interpreting Laboratory Data, chapter 12](https://www.ashp.org/-/media/store-files/p5488-sample-chapter-12.pdf) | Sodium adult interval 135?145 mmol/L/mEq/L; age-context matters. |
| [Indian Railways: Micro Labs product list](https://rb.indianrailways.gov.in/public/ourOrganization/public/pdf/Micro%20Labs%20Ltd_f6c76dd6_1761620046441.pdf) | Product table identifies Dolo-650 with paracetamol 650 mg. Used only for exact curated Dolo-650 aliases. Not a general OCR brand resolver. |
| [BIPM SI Brochure](https://www.bipm.org/en/publications/si-brochure) | SI dimensional relationships behind explicit concentration factors. 1 mm cubed is 1 microlitre; RBC mil unit interpretation is declared in config rather than inferred from the SI source. |
| [SQLite transactions](https://www.sqlite.org/lang_transaction.html) | Local transactional persistence; current snapshots/history and uniqueness constraints. |
| [Cloud Run Pub/Sub tutorial](https://cloud.google.com/run/docs/tutorials/pubsub) | Production asynchronous worker design; not a deployed local integration. |
| [Eventarc Cloud Storage triggers](https://cloud.google.com/run/docs/triggering/storage-triggers) | Production arrival-event integration. |
| [Prometheus alerting](https://prometheus.io/docs/alerting/latest/overview/) | Metrics exposition and alert rule examples; local files expose alert state, external receivers remain to be configured. |

Prototype hemoglobin [1,30] g/dL and sodium [50,250] mmol/L plausibility envelopes are explicit engineering review heuristics. They are not sourced physiological or clinical critical thresholds and must not be presented as such. They deliberately distinguish gross-review outliers from ordinary reference-range deviations in synthetic tests.
