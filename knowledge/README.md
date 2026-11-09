# Knowledge documents (integrator-owned)

The documents the desk answers from. Agent PRs that touch this folder are rejected by the pipeline:
product facts and policies change only through a human PR.

Every document starts with front matter that ingestion copies onto each chunk (ARCHITECTURE.md §2.3):

```yaml
---
doc_id: fee_schedule          # stable ID used in citations
version: 1                    # bump on any change; old versions stay, with superseded_by
effective_date: 2020-01-01    # retrieval uses the version in force at the as-of date
superseded_by: 2              # optional
synthetic: false              # true for anything not from the starter kit
source: ...                   # where it came from
---
```

Chunks are split by `###` section, and the heading text is the citation's section. The FAQ has no
`###` sections: it is split by question, one chunk per `**Q: ...**` block, and the question text is the
section.

| doc_id | Version | Synthetic | What it is |
|---|---|---|---|
| `product_summary` | 1 | no | Starter kit, unchanged below the front matter |
| `fee_schedule` | 1 | no | Starter kit, unchanged below the front matter |
| `faq` | 1 | no | Starter kit, unchanged below the front matter |
| `large_withdrawal_policy` | 1 | yes | Which withdrawals a person reviews (D-01, D-02) |
| `vulnerable_customer_policy` | 1 | yes | Hold signals and third-party contact (D-07, D-09) |
| `waiver_review_procedure` | 1 | yes | How waiver requests are reviewed; documents for the terminal illness waiver (D-03, FR-13) |

The superseded fee-schedule version used by the versioning case (BH-B4-02) is added in B4.
The synthetic documents add process rules only; none contradicts a starter-kit product fact.
