"""Provider-agnostic LLM access + cost helper.

get_model(name) returns a LangChain chat model for any benchmarked provider; the
agent and the benchmark both go through here so swapping models is one word and the
comparison stays fair. Imports are lazy so you only need the SDK/key for models you run.
"""
import config

# The contestants, and the judge — deliberately disjoint. A judge that is also being
# benchmarked grades its own answers, and self-preference bias is well documented.
_BENCHMARKED = ("gpt-4o", "gemini", "claude")
_JUDGE_ONLY = ("openrouter",)
_SUPPORTED = _BENCHMARKED + _JUDGE_ONLY


def model_names():
    """The benchmarked contestants. Excludes judge-only models on purpose."""
    return list(_BENCHMARKED)


def get_model(name: str, temperature: float = 0.0):
    """temperature=0 for reproducible evals (except claude, which doesn't support
    overriding it); per-call output cap bounds cost."""
    max_tokens = config.MAX_OUTPUT_TOKENS
    if name == "gpt-4o":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=config.OPENAI_MODEL, temperature=temperature,
                          max_tokens=max_tokens, api_key=config.OPENAI_API_KEY)
    if name == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, temperature=temperature,
                                      max_output_tokens=max_tokens,
                                      google_api_key=config.GOOGLE_API_KEY)
    if name == "claude":
        from langchain_anthropic import ChatAnthropic
        # claude-sonnet-5 doesn't support overriding temperature (400s on any value) —
        # omit it and let the model use its own default.
        return ChatAnthropic(model=config.ANTHROPIC_MODEL,
                             max_tokens=max_tokens, api_key=config.ANTHROPIC_API_KEY)
    if name == "openrouter":
        # The neutral judge. OpenRouter is OpenAI-API-compatible, so this needs no new
        # SDK — same ChatOpenAI class, different base_url. Being a fourth party (and not
        # a contestant) is the point: it has no stake in the models it grades, and unlike
        # claude-sonnet-5 it accepts temperature=0, so grading is reproducible.
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=config.OPENROUTER_MODEL, temperature=temperature,
                          max_tokens=max_tokens, api_key=config.OPENROUTER_API_KEY,
                          base_url="https://openrouter.ai/api/v1")
    raise ValueError(f"Unknown model '{name}'. Supported: {', '.join(_SUPPORTED)}")


def cost_usd(name: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of a call from token usage and the config price table."""
    price_in, price_out = config.PRICING.get(name, (0.0, 0.0))
    return round(input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out, 6)
