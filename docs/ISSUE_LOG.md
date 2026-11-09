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
