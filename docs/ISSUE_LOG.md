# Issue log

One row per fixed defect. The commit carries the full Issue / Root cause / Fix / Test write-up.
"Found by" names the source, for example `eval G-B3-01`, `red team`, `review on PR #n`, `manual run`.
Defects found in review are the evidence for workstream F (ADR 0002), so they always get a row.

| ID | Date | Symptom (one line) | Found by | Fix commit |
|----|------|--------------------|----------|------------|
| #21 | 2026-11-09 | Approval accepted a token on a hold/escalate decision and any approver string | review on PR #20 (both axes) | 035ea16 |
| #22 | 2026-11-09 | Quote validated a wrong surrender charge | review on PR #20 (standards) | 78a2bd1 |
| #23 | 2026-11-09 | Intake could replace the whole session, resetting the identity lockout | review on PR #20 (standards) | e3f6042 |
| #24 | 2026-11-09 | Large-withdrawal policy sent inactive accounts to a reviewer, contradicting FR-07 | review on PR #20 (spec) | 89a5d84 |
| #25 | 2026-11-09 | Contract tests could pass on a regression (float rounding, vacuous globs, shallow checks) | review on PR #20 (standards) | 8975acd |
| #30 | 2026-11-09 | Identity back-door test missed keyword-only parameters | review on PR #29 (standards) | b028ab5 |
| #31 | 2026-11-09 | AuditRecord accepted any string as its timestamp | review on PR #29 (both axes) | 894941e |
| #32 | 2026-11-09 | AuditLog.append accepted values AuditRecord would refuse | review on PR #29 (standards) | f1704ea |
| #62 | 2026-11-09 | ConversationState accepted gate results the session contradicts | review on PR #61 (both axes) | 0d736c4 |
| #65 | 2026-11-09 | A malformed stored date of birth would be quoted in an exception message | review on PR #63 (standards) | da20f31 |
| #66 | 2026-11-09 | Identity-table isolation test missed SQL that reads the dob column | review on PR #63 (spec) | 8a60eb5 |
| #67 | 2026-11-09 | A credential sent in its own turn reached the model unmasked | review on PR #64 (standards) | e078bcb |
| #68 | 2026-11-09 | Common credential forms (no-keyword SSN, 2-digit-year, dotted, compact dates, spaced digits) reached the model raw | review on PR #64 (both axes) | 19fedf2 |
| #69 | 2026-11-09 | Ordinary turns were captured as credentials and would count as failed challenges | review on PR #64 (spec) | 8c73262 |
| #70 | 2026-11-09 | Credentials values were exposable through asdict, equality and pickling | review on PR #64 (standards) | 25ea5c2 |
