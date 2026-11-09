const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, WidthType,
  ShadingType, BorderStyle, AlignmentType, LevelFormat, HeadingLevel, Footer, Header,
  PageNumber,
} = require("docx");

const OUT = process.argv[2];
const FONT = "Arial";
const W = 9360; // 8.5in - 2x1in margins, in DXA

// "**bold** plain" -> runs
function runs(text, extra = {}) {
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((s) =>
    s.startsWith("**")
      ? new TextRun({ text: s.slice(2, -2), bold: true, font: FONT, ...extra })
      : new TextRun({ text: s, font: FONT, ...extra }));
}
const P = (t, o = {}) => new Paragraph({ children: runs(t), spacing: { after: 120 }, ...o });
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: t, font: FONT })] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun({ text: t, font: FONT })] });
const B = (t, level = 0) => new Paragraph({ numbering: { reference: "bullets", level }, children: runs(t), spacing: { after: 60 } });
const N = (t, ref = "num") => new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs(t), spacing: { after: 60 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };
function table(widths, header, rows) {
  const cell = (t, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { type: ShadingType.CLEAR, fill: "1F3864", color: "auto" } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ children: runs(t, { size: 18, ...(head ? { bold: true, color: "FFFFFF" } : {}) }) })],
  });
  return new Table({
    width: { size: W, type: WidthType.DXA }, columnWidths: widths,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, widths[i], false)) })),
    ],
  });
}
const gap = () => new Paragraph({ children: [], spacing: { after: 60 } });

// Workstream block: title, intent, what to build, evidence
function workstream(id, title, intent, build, evidence) {
  return [
    H2(`${id}. ${title}`),
    P(intent),
    P("**What to build**", { spacing: { after: 60 } }),
    ...build.map((b) => B(b)),
    P("**Evidence we expect to see**", { spacing: { before: 120, after: 60 } }),
    ...evidence.map((b) => B(b)),
  ];
}

const body = [
  new Paragraph({ heading: HeadingLevel.TITLE, children: [new TextRun({ text: "AI Engineer \u2014 Capstone Assignment", font: FONT })] }),
  new Paragraph({ spacing: { after: 240 }, children: [new TextRun({ text: "SPR Servicing Desk: a multi-agent system, built through a software factory and run like a production service", font: FONT, italics: true, size: 26, color: "404040" })] }),

  H1("About This Assignment"),
  P("The first version of this assignment asked for one tool-calling agent and an evaluation that picked a model to deploy. This version asks the next question: **how would you take that agent to production with a team, and keep it safe once it is there?**"),
  P("You will build a small multi-agent system for SPR Financials. The agents matter less than the system around them: how the agents are produced, tested, reviewed, attacked, observed and governed, and how several people can build it at once without breaking each other's work. We expect you to use AI coding assistants, including agents that write, review and attack code. Tell us where they helped and where you overruled them."),
  P("This is a capstone-sized brief, not an afternoon exercise. One person working part-time with AI assistants should plan for **3\u20134 weeks**; a team would run the workstreams in parallel. **A thin slice through every workstream is worth more than depth in a few.** Cut scope on purpose, and say what you cut and why."),

  H1("Problem Statement"),
  P("SPR Financials is moving its AI servicing assistant for the **SecureGrowth Fixed Annuity** from pilot to production. The pilot was a single agent that answered product questions, verified identity, quoted withdrawals and escalated. It worked in demos. Three things block the move to production:"),
  B("**Risk.** Withdrawals are now expected to include hardship cases (surrender-charge waivers) and large or unusual requests. Compliance will not let one model both decide and check a money movement. They want a maker\u2013checker split and a human in the loop for the highest-risk actions."),
  B("**Delivery.** Five engineers will work on the system. Today nobody can change a prompt or swap a model without wondering what else broke. Every agent, prompt, tool and model change has to go through the same repeatable pipeline, with evidence."),
  B("**Operations.** Nobody can yet answer \u201cwhy did this withdrawal happen?\u201d for a given case, notice when quality drops, or stop the system safely when something goes wrong."),
  P("Your task is to redesign the assistant as a **coordinated set of agents** for one functional use case, build it with a **repeatable software factory and CI/CD pipeline**, and show the evals, red-team results, observability and production governance that would let SPR run it with real customers."),

  H1("The Functional Use Case: Withdrawal & Hardship Case Desk"),
  P("A customer contacts SPR about taking money out of their annuity. The request may be a simple product question, a routine withdrawal inside the free allowance, a withdrawal with surrender charges, a hardship request asking for a charge waiver, or something that should never be acted on automatically. The system must handle the conversation end to end:"),
  N("Work out what the customer wants and whether the account and session are trusted enough to discuss it."),
  N("Answer product and policy questions from the knowledge base, citing the source document and its version."),
  N("Quote the withdrawal from records: free allowance remaining this contract year (net of prior withdrawals), surrender charge and net proceeds."),
  N("Have an **independent** reviewer check the proposed withdrawal against policy (hardship rules, large-withdrawal thresholds, vulnerable-customer signals) before anything executes."),
  N("Execute only when every precondition holds. Otherwise build a case packet for a human reviewer, who approves, rejects or asks for more information. Hardship waivers are always granted by a human."),
  P("**Done means:** a reviewer can pick any case and see, from the audit record alone, what the customer asked, what each agent decided and why, which policy version applied, which model and prompt versions ran, and who approved the money movement."),

  H2("Required agent roles"),
  P("These are the minimum roles. You may merge or split them if you justify it, but the maker\u2013checker separation is not optional."),
  table([1700, 2900, 2380, 2380], ["Agent", "Responsibility", "May", "May not"], [
    ["Concierge (front door)", "Owns the conversation. Classifies intent, runs the identity gates, routes work, speaks to the customer.", "Read session context; call the identity service; hand off to other agents.", "Quote, execute or approve anything. Never sees restricted fields (DOB, SSN)."],
    ["Knowledge", "Answers product and policy questions by retrieval.", "Search the knowledge base; return answers with document ID, version and section.", "Read account data. Answer from model memory."],
    ["Transaction (maker)", "Builds the withdrawal quote and the proposal.", "Read account and transaction history; calculate; propose; execute with a valid approval token.", "Approve its own proposal. Execute without the token."],
    ["Compliance (checker)", "Reviews each proposal against policy.", "Read the proposal and policy documents; return approve / hold / escalate with reasons; issue an approval token bound to that exact proposal.", "Execute. Change a proposal. Be overruled by any other agent."],
    ["Case", "Prepares human escalations.", "Write a case packet (summary, evidence, recommendation) to the review queue.", "Make the decision the human is there to make."],
    ["Human reviewer", "Decides high-risk and hardship cases.", "Approve, reject or ask for information, through a simple queue UI.", "\u2014"],
  ]),
  gap(),

  H2("Coordination requirements"),
  P("Most multi-agent failures are coordination failures, not model failures. Your design must address each of these, in code wherever it can be enforced:"),
  B("**Topology.** Choose supervisor, handoff, graph or another pattern, and say why it fits this use case better than the alternatives. One component owns the case state."),
  B("**Typed contracts.** Every message between agents follows a versioned schema and is validated. Malformed messages are rejected, not interpreted."),
  B("**State ownership.** Every field in the shared case state has exactly one writer. For example, only Transaction writes proposals and only Compliance writes decisions."),
  B("**Maker\u2013checker in code.** Execution requires the quote to have been shown, explicit customer confirmation, and an approval token tied to a hash of the exact proposal. A changed amount voids the token. High-risk tiers also need human approval."),
  B("**Conflict resolution.** The most restrictive outcome wins. A compliance hold cannot be overridden by another agent or by the customer."),
  B("**Budgets and termination.** Cap hops, tool calls, wall-clock time and cost per case. When a budget runs out the case escalates. It never fails silently or loops."),
  B("**Idempotency.** A retried or replayed execution never moves money twice."),
  B("**Inter-agent trust.** One agent's output is data to the next, never instructions. \u201cCompliance already approved this\u201d written by the Concierge means nothing."),
  B("**Degraded modes.** If the checker or the case queue is unavailable, the system fails closed: no execution, the customer is told what happens next."),
  B("**Correlation.** One case ID follows every agent step, tool call, model call and log line."),
  P("**Prove it was worth it.** Run the same eval suite against a single-agent baseline (your v1 agent, or one you build first). Report where the multi-agent design wins, what it costs in latency and tokens, and anywhere it does not help."),

  H1("Workstreams and Deliverables"),
  P("Each workstream lists what to build and the evidence we will look for. Evidence should come from your repository and pipeline runs, not from slides."),

  ...workstream("A", "Data Foundations",
    "The starter kit (4 accounts, 3 knowledge-base documents) is a seed, not a data platform. Numbers come from records and narrative comes from documents. Design both sources so an agent cannot confuse them.",
    [
      "A relational store (SQLite is fine) with a schema, migrations and seed scripts for accounts, transaction history, proposals, cases and an append-only audit log.",
      "A **data contract** that classifies every field as Public, Internal, Confidential or Restricted. Restricted fields (DOB, SSN) stay inside the identity service and never reach a model, a trace or a log.",
      "Enough synthetic data to exercise every rule, with each record there for a reason: at least 20 accounts covering every contract year, untrusted identity, frozen or deceased status, multiple beneficiaries, customers aged 80 or over, free allowance partly used by earlier withdrawals, and balances near minimums. Label it as synthetic.",
      "Knowledge-base extensions: a hardship-waiver policy, a vulnerable-customer policy, and a **superseded** fee schedule with effective dates, so retrieval must pick the version in force.",
      "An idempotent ingestion pipeline that stores document ID, version, effective date and section with each chunk, so every answer can cite its source.",
      "Data-quality checks (schema validation, referential integrity, knowledge-base lint) that run in CI.",
    ],
    [
      "The data contract and a short note on which agent can see which fields, and why.",
      "A test that fails if a restricted field shows up in any prompt, trace or answer.",
      "A retrieval eval showing the current fee schedule beats the superseded one.",
    ]),

  ...workstream("B", "Agent Orchestration",
    "The runtime multi-agent system described above.",
    [
      "The agent roles, typed contracts, shared case state and orchestration layer.",
      "A per-role tool registry with risk tiers: read-only, self-service write (confirm and audit), high-risk (human in the loop).",
      "A minimal human review queue.",
      "A role-to-model mapping. Compare at least two models for at least two roles, for example a cheap model for routing and a strong one for compliance, and report cost per case.",
    ],
    [
      "An architecture diagram that matches the code.",
      "Coordination tests: forged approval token, amount changed after approval, checker offline, budget exhausted, duplicate execute.",
      "The single-agent vs multi-agent comparison.",
    ]),

  ...workstream("C", "Software Factory",
    "The system should be **produced**, not hand-crafted. A software factory here means a documented, repeatable sequence of stations that every agent goes through, with templates and gates, so the next agent is cheap and predictable.",
    [
      "A station sequence, for example: frame \u2192 specify (agent card) \u2192 define correct (evals written before code) \u2192 scaffold from template \u2192 build \u2192 adversary \u2192 publish gate \u2192 evidence. Mark which stations are automated, which use AI agents, and where a human signs off.",
      "An agent template: an agent card (purpose, owner, tools and risk tiers, data access, model, eval set and thresholds, threat notes), a prompt file, tool registry entries, an eval file and tests.",
      "Prompts, tool schemas, model IDs and thresholds kept as versioned configuration, not buried in code.",
      "Build-time agents (for example spec writer, builder, reviewer, adversary) may run the stations. Keep the builder and the adversary separate.",
    ],
    [
      "At least two runtime agents that visibly came through the factory.",
      "A timed exercise: add a new agent (for example a beneficiary-inquiry agent) through the factory, and report how long it took and how much was generated versus written by hand.",
    ]),

  ...workstream("D", "CI/CD and Build-out Tracking",
    "The pipeline is the quality gate, and the repository history is the record of how the system was built.",
    [
      "A pipeline with explicit stages: lint, format and type check \u2192 unit tests (no network) \u2192 data-quality \u2192 contract tests \u2192 eval gate \u2192 red-team regression \u2192 container build \u2192 deploy to a local staging stack (docker compose) \u2192 smoke test \u2192 tagged release with an evidence pack.",
      "Each gate marked **blocking** or **advisory**. Safety gates are always blocking.",
      "**A staged eval policy, chosen for cost.** Every PR runs the checks that cost nothing: unit, contract and guard tests, plus replay tests against recorded model responses. Paid LLM evals run by hand at milestones while the build stabilises, then as a small smoke subset per PR once it is stable. Say when and why each stage switches on.",
      "Eval scores stored for every eval run and charted across milestones.",
      "A backlog of issues grouped into milestones, PRs linked to issues, and a changelog. Secrets stay in CI secrets; PRs from forks never get API keys.",
    ],
    [
      "A green pipeline on main, and at least one PR a gate correctly blocked.",
      "An eval-trend chart across milestones.",
      "A reviewer can rebuild the story of the build-out from issues, PRs and tags alone.",
    ]),

  ...workstream("E", "Working as a Team",
    "Assume a team of four or five: tech lead / orchestration, agent engineer(s), data engineer, eval and safety engineer, platform / SRE.",
    [
      "CODEOWNERS that map those roles to directories; branch protection; required review from the owning area.",
      "Work split along the contracts (handoff schemas, tool registry, data contract) so streams can run in parallel without collisions.",
      "A PR template that asks for the issue link, the risk tier of the change, and the eval delta.",
      "Architecture decision records (ADRs) and a short working agreement, including a definition of done.",
    ],
    [
      "At least one contract change that crossed streams, handled with a versioned schema and no breakage.",
      "If you work alone, you may simulate the team with AI coding agents assigned to roles in separate branches or worktrees. Say so openly, and show how you handled their merges and conflicts.",
    ]),

  ...workstream("F", "Code Quality and Review",
    "Guardrails belong in reviewed, tested code. Prompts are not the safety layer.",
    [
      "Documented coding standards enforced by tools, with a coverage threshold on the deterministic core (identity, guards, math, contracts), not on prompt glue.",
      "Review on two axes: does the change meet the standards, and does it do what the issue or spec asked? AI-assisted review is welcome, but a human approves.",
      "An issue workflow for defects: issue \u2192 failing test that reproduces it \u2192 fix \u2192 entry in the issue log.",
    ],
    [
      "At least one real defect found in review and closed through that workflow, with the regression test that pins it.",
    ]),

  ...workstream("G", "Evals",
    "Evals define \u201ccorrect\u201d before features exist, and they decide what ships.",
    [
      "**Layered evals:** deterministic unit tests; per-agent component evals (routing accuracy, retrieval recall and citation correctness, exact quote math, compliance precision and recall on labelled cases); multi-turn end-to-end conversation evals; and **trajectory evals** (the right handoffs happened, no agent called a tool outside its scope, budgets held).",
      "A versioned golden dataset of at least 60 cases, multi-turn included, each with ground truth and a one-line rationale. Keep a held-out split you do not tune against.",
      "Programmatic checks first. Use an LLM judge only for what code cannot check, calibrate it against human labels on a sample and report the agreement rate. The judge must not be one of the models being compared.",
      "Repeated runs to measure variance; flaky cases are reported, not hidden.",
      "An online-eval plan: score sampled production traces and watch for drift.",
    ],
    [
      "The thresholds you chose and why. Weight errors by consequence: a false approval is far worse than an unnecessary escalation.",
      "Model-per-role results across accuracy, safety, cost and latency, ending in a deployment recommendation.",
    ]),

  ...workstream("H", "Red Team",
    "Test the system the way an attacker or a confused customer would. The attacker should not be whoever (or whatever) built the agent.",
    [
      "A threat model covering assets, actors and entry points, including knowledge-base documents and inter-agent messages, mapped to the OWASP Top 10 for LLM Applications.",
      "An attack library covering at least: direct prompt injection; indirect injection through a poisoned knowledge-base document (red-team index only); identity social engineering (a spouse or beneficiary posing as the owner); cross-account access; tool-argument tampering (amount, account ID); **agent-to-agent injection**; approval-token forgery and replay; extraction of restricted fields; denial-of-wallet (loops, oversized inputs); and coaxing the agent into investment advice.",
    ],
    [
      "Attack success rate by category, before and after fixes.",
      "Every successful break becomes an issue and a permanent regression case in CI.",
      "The breaks you could not fix, with the controls that limit their impact.",
    ]),

  ...workstream("I", "Observability",
    "You cannot run what you cannot see, and in financial services you also have to explain it later.",
    [
      "End-to-end tracing across agents, keyed by case ID. Each span records agent, tool, retrieval or model call, tokens, cost, latency, model version and prompt version.",
      "PII redaction before any trace leaves the process.",
      "A dashboard: volume, containment rate, escalations by reason, guard trips, compliance holds, tool error rate, p50/p95 latency per agent, cost per case, online eval scores.",
      "Alerts whose thresholds map to the severities in the incident playbook.",
      "An **audit log kept separate from traces**: append-only, recording every money-movement decision with the approvals, policy version, model version and prompt version.",
    ],
    [
      "A script or view that rebuilds any case end to end from the audit log and answers \u201cwhy did this withdrawal happen?\u201d",
    ]),

  ...workstream("J", "Governance in Production: Incident Playbook",
    "Assume something will go wrong. Show that SPR would notice quickly, contain it safely, fix the root cause and stop it happening again.",
    [
      "An inventory of agents and models: owner, model and version, risk tier, last eval date, approval.",
      "Change management: every prompt, model, tool or policy change is a versioned release with eval evidence, a named approver and a tested rollback.",
      "Runtime controls: feature flags and kill switches per capability (for example, turning off execution drops the system to read-only plus escalation), rate limits and per-case cost ceilings.",
      "An incident playbook with a severity matrix. Example SEV1: an unauthorised or wrong withdrawal executed, or restricted PII exposed. SEV2: wrong figures quoted, or the checker down with the fallback holding. SEV3: drift or an escalation-rate spike. For each: detection source, first-15-minute actions, roles, containment, recovery, customer remediation, the point where regulatory notification is decided, communication templates, and a blameless postmortem template.",
    ],
    [
      "**A game day.** Run one simulated incident from start to finish, for example a prompt regression that lets Transaction skip the checker in one edge case, or a poisoned document reaching the production index. Show detection by alert or online eval, kill switch, rollback, postmortem and the merged regression test. Report time to detect and time to contain.",
    ]),

  ...workstream("K", "README (mandatory)",
    "One README that gets a reader from a clean checkout to a running system.",
    [
      "Setup: one docker compose command brings up the whole stack locally. No cloud account is needed at demo time.",
      "Architecture and key decisions (link the ADRs), eval method and results, the model-per-role recommendation, red-team findings, failure modes your evals surfaced, and what you would do with more time.",
      "**A section on the AI tools you used, and an honest account of what you learned.** As in v1, leaving out either one disqualifies the submission.",
    ],
    [
      "A reviewer who has never seen the repository can run the stack, run the suites and reproduce your headline numbers.",
    ]),

  H1("Quality Bars"),
  P("These targets are examples. Set your own and defend them. What matters is that each bar is written down, measured by the pipeline, and clearly blocking or advisory."),
  table([4000, 2300, 3060], ["Measure", "Example target", "Gate"], [
    ["Money moved without every precondition", "0", "Blocking"],
    ["Restricted field in an answer, trace or log", "0", "Blocking"],
    ["Compliance false approvals (labelled set)", "0", "Blocking"],
    ["Quote accuracy (allowance, charge, net)", "\u2265 98%", "Blocking"],
    ["Open critical red-team findings", "0", "Blocking for release"],
    ["Citation correctness (right document and version)", "\u2265 95%", "Blocking"],
    ["Trajectory / handoff correctness", "\u2265 90%", "Advisory, then blocking from M6"],
    ["Judge\u2013human agreement", "\u2265 85%", "Must hold before the judge gates anything"],
    ["p95 latency per turn; cost per resolved case", "Set and defend", "Advisory, tracked per commit"],
  ]),
  gap(),

  H1("Milestones"),
  P("Build in this order. Each milestone ends with something CI can show. Evals come before the agents they grade."),
  table([900, 2300, 6160], ["#", "Milestone", "Exit criterion"], [
    ["M0", "Frame and blueprint", "Problem framing, blueprint, first ADRs, backlog, team charter; repo and CI skeleton green."],
    ["M1", "Data foundation", "Schema, data contract, synthetic data, ingestion and data-quality checks running in CI."],
    ["M2", "Define correct", "Golden dataset, eval harness and thresholds in place; single-agent baseline scored."],
    ["M3", "Factory and first agents", "Agent template and stations working; Concierge and Knowledge agents produced through the factory."],
    ["M4", "Money path", "Transaction, Compliance and Case agents; maker\u2013checker enforced in code; human queue working."],
    ["M5", "Red team", "Threat model, attack campaign, fixes, regression suite in CI."],
    ["M6", "Operate", "Tracing, dashboard, audit rebuild, kill switches, playbook, game day completed."],
    ["M7", "Release and evidence", "Model-per-role recommendation, evidence pack, README, presentation."],
  ]),
  gap(),

  H1("Constraints and Non-goals"),
  B("Runs locally with docker compose from a clean checkout. Describe the production cloud deployment on slides; you do not need to build it."),
  B("Synthetic data only. No real customer data or PII anywhere."),
  B("Customer authentication is handled upstream: trust the session identity, not the customer's intent. Real payment rails and real KYC are out of scope."),
  B("Not graded: UI polish, extra agents beyond the required roles, or your choice of framework, as long as you justify it."),
  B("The repository may be public: the autonomous pipeline relies on branch protection and auto-merge. Because of that, use synthetic data only and never commit secrets. Do not post this brief on public forums or communities."),

  H1("Data"),
  P("Start from the **spr_starter_kit** folder and its README: four accounts, the product summary, the fee schedule and the FAQ. The knowledge base is the ground truth for product facts. Workstream A sets out the extensions you must make. Label every synthetic record and document, and note in your design why each one exists."),

  H1("Post Submission: The Interview"),
  P("Plan for a **75-minute** session built around 8\u201310 slides and a live system. As before, we care far more about how you defend your decisions than about polished slides."),
  table([1700, 7660], ["Time", "Segment"], [
    ["10 min", "Architecture and orchestration: topology, contracts, maker\u2013checker, and why multi-agent is worth its cost here."],
    ["10 min", "Live demo: a routine withdrawal, a hardship case through the human queue, and a refusal."],
    ["10 min", "Factory and CI/CD: follow one change from issue to PR, review, eval gate and release."],
    ["10 min", "Evals and the model-per-role recommendation."],
    ["10 min", "Red-team findings and the game-day replay using the incident playbook."],
    ["25 min", "Questions. We may ask you to change a policy or add a small agent live and show what the pipeline catches."],
  ]),
  gap(),

  H1("Appendix: How the Panel Assesses"),
  table([1900, 4100, 3360], ["Area", "Strong", "Red flags"], [
    ["Data foundations", "Clear split between records and documents; field classification enforced; versioned documents with citations.", "Numbers from RAG; PII in prompts or traces; synthetic data with no stated purpose."],
    ["Orchestration", "Topology justified; typed contracts; maker\u2013checker in code; fails closed; beats or honestly matches the baseline.", "Agents chatting freely; safety only in prompts; no budgets; multi-agent for its own sake."],
    ["Software factory", "Repeatable stations; second and third agents are cheap; human gates are explicit.", "Each agent hand-built differently; \u201cfactory\u201d is only a folder of prompts."],
    ["CI/CD and tracking", "Blocking safety gates; eval trend over time; history tells the story.", "Evals run by hand; no blocked PR ever; one giant commit."],
    ["Team and review", "Ownership by contract; ADRs; reviews that catch real defects.", "Everything owned by everyone; rubber-stamp reviews."],
    ["Evals", "Layered, consequence-weighted, held-out split, calibrated judge.", "Accuracy only; judge is a contestant; tuning to the test set."],
    ["Red team", "Independent adversary; attack rates measured; breaks become regressions.", "A handful of jailbreak prompts; fixes with no tests."],
    ["Observability", "Traces across agents; audit log answers \u201cwhy\u201d; alerts tied to severities.", "Logs only; PII in traces; no way to rebuild a case."],
    ["Governance", "Kill switches tested on a game day; versioned changes; blameless postmortem with a regression test.", "Playbook never exercised; no rollback path."],
    ["Judgment and honesty", "Clear trade-offs, deliberate cuts, candid AI-tool lessons.", "Claims the evidence does not support."],
  ]),
];

const doc = new Document({
  creator: "debud",
  title: "AI Engineer Capstone Assignment - SPR Servicing Desk",
  styles: {
    default: { document: { run: { font: FONT, size: 22 } } },
    paragraphStyles: [
      { id: "Title", name: "Title", basedOn: "Normal", next: "Normal", run: { font: FONT, size: 40, bold: true, color: "1F3864" }, paragraph: { spacing: { before: 0, after: 80 }, keepNext: true } },
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 30, bold: true, color: "1F3864" }, paragraph: { spacing: { before: 320, after: 120 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true, run: { font: FONT, size: 25, bold: true, color: "2E5597" }, paragraph: { spacing: { before: 240, after: 100 }, keepNext: true, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "\u2022", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "\u2013", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1080, hanging: 270 } } } },
      ] },
      { reference: "num", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 300 } } } },
      ] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [new TextRun({ text: "SPR Financials \u2014 AI Engineer Capstone (Confidential)", font: FONT, size: 16, color: "808080" })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ["Page ", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: "808080" })] })] }) },
    children: body,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length); });
