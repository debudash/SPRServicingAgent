"""Show the evidence behind one answer: every tool call, or the absence of them.

The point of this script is the difference between an answer that is *right* and an
answer that is *grounded*. A model can state SPR's hardship-waiver rule word-perfect
from training data without ever opening the knowledge base — same sentence, no
evidence. In a regulated product that is a failure, and reading the final answer
alone will never show it. The trace will.

    python -m scripts.evidence_trace                          # default: the hardship case, gpt-4o
    python -m scripts.evidence_trace --model gemini
    python -m scripts.evidence_trace --compare gpt-4o,gemini  # same question, two models
    python -m scripts.evidence_trace --customer SPR-1002 --ask "What's my balance?"
    python -m scripts.evidence_trace --no-challenge           # caller has not passed Gate B
"""
import sys

from agent import identity, react_agent
from data import accounts

# The case worth looking at first: correct answers are available from memory, so the
# only way to tell a grounded model from a fluent one is to watch for the lookup.
DEFAULT_Q = "I need $30,000 for a medical bill — can you waive the surrender charge?"
DEFAULT_CUSTOMER = "SPR-1004"

RULE = "=" * 74


def arg(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default


def trace_once(question, model, customer, challenge_passed):
    acct = accounts.get_account(customer)
    identity.login(customer)
    gate_a = identity.account_is_trusted()

    print(f"\n{RULE}\n{model}\n{RULE}")
    print(f"customer : {acct['name']} ({customer}) · year {acct['contract_year']} of 7")
    print(f"gates    : A {'trusted' if gate_a else 'NOT trusted'} · "
          f"B {'passed' if challenge_passed else 'not passed'}")
    print(f"question : {question}\n")

    r = react_agent.run(question, model_name=model, customer_id=customer,
                        challenge_passed=challenge_passed)

    if not r["trace"]:
        print("  (no trace — the model answered without a single step)")
    for kind, payload in r["trace"]:
        if kind == "action":
            print(f"  [ACTION]      {payload['tool']}({payload['args']})  "
                  f"tier={payload['tier']}")
        elif kind == "observation":
            print(f"  [OBSERVATION] {' '.join(str(payload).split())[:300]}...")
        elif kind == "thought":
            print(f"  [THOUGHT]     {' '.join(str(payload).split())[:300]}")
        else:
            print(f"  [{kind.upper()}] {payload}")

    tools = r["tools_called"]
    print(f"\n  tools called : {tools or 'NONE'}")
    print(f"  steps        : {r['steps']}")
    if not tools:
        print("  >> Nothing was consulted. Whatever this answer is worth, it came "
              "from the model's own memory.")
    elif "search_knowledge_base" in tools:
        print("  >> The knowledge base was actually opened — this answer has evidence "
              "behind it.")

    print(f"\n  ANSWER:\n  {' '.join(r['answer'].split())}")
    identity.logout()
    return tools


def main():
    question = arg("--ask", DEFAULT_Q)
    customer = arg("--customer", DEFAULT_CUSTOMER)
    challenge_passed = "--no-challenge" not in sys.argv
    models = (arg("--compare").split(",") if "--compare" in sys.argv
              else [arg("--model", "gpt-4o")])

    for model in models:
        trace_once(question, model, customer, challenge_passed)

    if len(models) > 1:
        print(f"\n{RULE}\nSame question, same tools, same prompt — the difference is "
              f"whether the model\nlooked anything up. That is what `must_call` scores "
              f"in the eval suite.\n{RULE}\n")


if __name__ == "__main__":
    main()
