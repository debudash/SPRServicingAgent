"""Central config for the SPR Financials servicing agent. Reads .env; flat + readable."""
import os
from dotenv import load_dotenv

load_dotenv()

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
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "claude")   # LLM-as-judge

# --- Pricing per 1,000,000 tokens (input, output), USD. ---
# VERIFY against your own account/tier — these are approximate public list prices.
PRICING = {
    "gpt-4o": (2.50, 10.00),
    "gemini": (1.25, 5.00),
    "claude": (3.00, 15.00),
}

# --- Runtime guardrails (loops + cost; enforced by the agent loop) ---
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "6"))
MAX_CONSECUTIVE_FAILURES = int(os.getenv("MAX_CONSECUTIVE_FAILURES", "2"))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))
