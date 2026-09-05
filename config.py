"""Central config for the SPR Financials servicing agent. Reads .env; flat + readable."""
import os
from dotenv import load_dotenv

load_dotenv(override=True)  # .env wins over stray OS-level env vars (e.g. a stale OPENAI_API_KEY from setx)

# --- Provided data (SPR starter kit) ---
ACCOUNTS_PATH = os.getenv("ACCOUNTS_PATH", "data/accounts.json")
KB_DIR = os.getenv("KB_DIR", "knowledge_base")

# --- RAG (knowledge base grounding) ---
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
CHROMA_COLLECTION = "spr_knowledge_base"

# --- The three benchmarked models (same agent runs on each) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude")   # LLM-as-judge

# --- The neutral judge: OpenRouter (free-tier gateway), NOT a benchmarked model ---
# OpenAI-API-compatible, so it needs zero new SDK — just point ChatOpenAI at a
# different base_url. Kept out of the contestant list so the judge has no stake in
# what it grades (see llm/providers.py).
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

# --- Pricing per 1,000,000 tokens (input, output), USD. ---
# VERIFY against your own account/tier — these are approximate public list prices.
PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gemini": (1.25, 5.00),
    "claude": (3.00, 15.00),
    "openrouter": (0.0, 0.0),  # judge only, and $0 while pointed at a :free model
}

# --- Runtime guardrails (loops + cost; enforced by the agent loop) ---
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "8"))
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "2"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))
