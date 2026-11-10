"""PolicySource for Compliance (FR-22): the knowledge index, limited to the policy documents.

Compliance cites operations policy, not product material, so its `get_policy` tool cannot return a
chunk of the FAQ, the fee schedule or the product summary, however the query is worded.
"""

from datetime import date

from contracts.ports import KnowledgeChunk
from data.knowledge_index.index import ChromaKnowledgeSearch

# The PG-06 operations documents in knowledge/ (integrator-owned). A new policy document is added
# here in the same PR that adds it to knowledge/.
POLICY_DOC_IDS = frozenset(
    {"large_withdrawal_policy", "vulnerable_customer_policy", "waiver_review_procedure"}
)


class ChromaPolicySource:
    def __init__(self, index: ChromaKnowledgeSearch) -> None:
        self._index = index

    def get_policy(self, query: str, as_of: date, k: int = 4) -> list[KnowledgeChunk]:
        return self._index.search_documents(query, as_of, k, doc_ids=POLICY_DOC_IDS)
