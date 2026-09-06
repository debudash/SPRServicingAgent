# SPR Financials — Agent Starter Kit

This folder contains the data and knowledge base for building the SPR Financials servicing agent.

---

## Structure

```
spr_starter_kit/
├── knowledge_base/
│   ├── product_summary.md       # What the SecureGrowth Fixed Annuity is
│   ├── fee_schedule.md          # Surrender charges by contract year + examples
│   └── faq.md                   # Common customer questions and correct answers
│
└── data/
    └── accounts.json            # Mock customer accounts (4 accounts)
```

---

## Accounts Overview

| Customer ID | Name              | Contract Year | Balance      | Identity Verified |
|-------------|-------------------|---------------|--------------|-------------------|
| SPR-1001    | Margaret Holloway | 3             | $87,450.62   | Yes               |
| SPR-1002    | Raymond Okafor    | 2             | $42,100.00   | No                |
| SPR-1003    | Linda Chu         | 4             | $11,200.00   | Yes               |
| SPR-1004    | Thomas Brennan    | 5             | $210,000.00  | Yes               |

---

## Surrender Charge Schedule

| Contract Year | Rate |
|---------------|------|
| Year 1        | 8%   |
| Year 2        | 7%   |
| Year 3        | 6%   |
| Year 4        | 5%   |
| Year 5        | 3%   |
| Year 6        | 1%   |
| Year 7        | 0%   |

Free withdrawal allowance: **10% of account balance per contract year**, no charge applied.

---

## Notes

- The knowledge base is the ground truth for all product facts. Your agent's answers should be grounded in these documents or in tool output — never from model memory.
- The accounts data backs whatever tools you build. Tool design, signatures, and error handling are yours to decide.
- Think carefully about what data your tools should and should not expose to the agent.
