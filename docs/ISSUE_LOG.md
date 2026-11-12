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
| #73 | 2026-11-09 | Lockout was lost (and the next try could pass) when the lock case could not be opened | review on PR #72 (spec) | 7ed5009 |
| #74 | 2026-11-09 | Credentials in a turn swallowed the customer's actual request | review on PR #72 (spec) | de2a399 |
| #75 | 2026-11-09 | Spaced or spelled SSN digits reached the model once no challenge was open | red team (#60) | c7d9632 |
| #84 | 2026-11-09 | The first-turn notice for an untrusted account was lost if turn 1 failed | review on PR #83 (spec) | 7582091 |
| #93 | 2026-11-09 | Approval token was bound to the proposal hash only, so identical proposals shared a token | review on PR #92 (spec) | 5bd6dc5 |
| #94 | 2026-11-09 | Proposal status machine could not escalate from quoted or approved | review on PR #92 (spec) | ec7186d |
| #97 | 2026-11-09 | Executed withdrawals never lowered the balance, so money could move past it | review on PR #96 (spec) | 33836e9 |
| #98 | 2026-11-09 | A human approval executed a proposal the customer never confirmed | review on PR #96 (spec) | 186971f |
| #99 | 2026-11-09 | ProposalStore.move could set confirmed, approved or executed around their real paths | review on PR #96 (spec) | 99dad4b |
| #107 | 2026-11-10 | A logged-in but locked session could hold an account view | review on PR #106 (spec) | 7da37b5 |
| #108 | 2026-11-10 | The contract allowed a passed step-up on a locked session | review on PR #106 (spec) | bd585d8 |
| #111 | 2026-11-10 | The restricted-table isolation scans missed quoted, prefixed, joined and DDL forms | review on PR #109 (both axes) | 275fea2 |
| #112 | 2026-11-10 | check_password raised on a corrupt login row instead of refusing | review on PR #109 (spec) | 88a3c07 |
| #114 | 2026-11-10 | Withdrawal amounts were masked as SSN digits for every logged-in customer | review on PR #113 (spec) | 569ee41 |
| #115 | 2026-11-10 | A refused step-up kept the previous turn's gate, account view and case | review on PR #113 (spec) | e78bf27 |
| #116 | 2026-11-10 | A malformed step-up counted as a failed identity attempt | review on PR #113 (both axes) | 426a42f |
| #118 | 2026-11-10 | The rule-pinning self-test counted retired and pending golden cases | review on PR #117 (spec) | c697921 |
| #120 | 2026-11-10 | The eval harness crashed the whole run when the desk asked a guest for a step-up | review on PR #119 (spec) | 4969e59 |
| #121 | 2026-11-10 | Wrong step-up values scripted by an eval case were neither caught nor redacted | review on PR #119 (spec) | 0a3cf00 |
| #126 | 2026-11-10 | The live desk answered as of today, not the as-of date (D-04) | review on PR #125 (spec) | f55ad32 |
| #130 | 2026-11-10 | A refused new amount left the old quote live, and a bare yes then confirmed it | review on PR #129 (spec) | ae1e175 |
| #131 | 2026-11-10 | The step-up could be pending for a voided proposal after a turn failed partway | review on PR #129 (spec) | c1ec70a |
| #136 | 2026-11-10 | A withdrawal held for a person could be asked for again and executed in the same session | review on PR #135 (spec) | e016db7 |
| #137 | 2026-11-10 | Flagged proposals skipped the Compliance review (FR-11, BH-B4-01) | review on PR #135 (spec) | 9ccb4a4 |
| #140 | 2026-11-10 | A repeated yes after an execution re-quoted, and a bare yes then executed a second withdrawal | money-path red team (#90) | eb384ed |
| #144 | 2026-11-10 | The case store dropped the packet's proposal_id, so a reviewer could not bind to it | building B4 | ff34882 |
| #147 | 2026-11-11 | A harness test failed on dates whose run ID contains 1111 | make check | 997a318 |
| #151 | 2026-11-10 | A reject could be recorded on a withdrawal already approved or executed | review on PR #150 (spec) | d2fb6e7 |
| #152 | 2026-11-10 | Every hardship was treated as a waiver request, implying a waiver (FR-14, NG-01) | review on PR #150 (spec) | 9a02250 |
| #153 | 2026-11-10 | A refused reviewer approval left no audit row; the row followed the execution | review on PR #150 (spec) | 4ff5a55 |
| #154 | 2026-11-10 | A reviewer's approval was not checked against the case's customer | review on PR #150 (spec) | 69d260e |
| #155 | 2026-11-10 | A reviewer ID outside the approver pattern crashed reject and request info | review on PR #150 (spec) | 4b52305 |
| #159 | 2026-11-11 | The identity tests' restricted-value checks failed by chance on timestamps and random IDs | CI on PR #157 | 85d1e49 |
| #161 | 2026-11-11 | The desk page failed in Docker with "No module named 'agents'" | manual run (owner opened the page) | 0951718 |
| #165 | 2026-11-11 | The page smoke skipped a page whose button was missing and still printed PASS | review on PR #163 (spec) | 8535316 |
| #166 | 2026-11-11 | The page smoke did not load the page on Streamlit's import path, so it could not catch #161 | review on PR #163 (spec) | 672135b |
| #175 | 2026-11-11 | Two dollar amounts in a chat reply rendered as a LaTeX formula | manual run (owner, local desk) | addd3f5 |
| #176 | 2026-11-11 | The desk could not say when the contract started (issue date) | manual run (owner, local desk) | bb05b23 |
| #177 | 2026-11-11 | A greeting got a NOT_PERMITTED refusal | manual run (owner, local desk) | 68f9b84 |
| #182 | 2026-11-11 | Every live Compliance call failed: Sonnet 5.5 at high effort refuses a forced tool choice | manual run (owner, local desk) | c37c25c |
| #187 | 2026-11-11 | An amount given in answer to "How much would you like to withdraw?" was read as small talk | manual run (owner, local desk) | f3c0ffd |
| #191 | 2026-11-11 | The Concierge changed the customer's amount ("5000" quoted as $4,500) | checking #187 live; review on PR #192 (both axes) | 24aa241 |
