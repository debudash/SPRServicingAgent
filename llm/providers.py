"""Provider-agnostic LLM access + cost helper.

get_model(name) returns a LangChain chat model for any benchmarked provider; the
agent and the benchmark both go through here so swapping models is one word and the
comparison stays fair. Imports are lazy so you only need the SDK/key for models you run.
"""
import config

_SUPPORTED = ("gpt-4o", "gemini", "claude")


def model_names():
    return list(_SUPPORTED)


def get_model(name: str, temperature: float = 0.0):
    """temperature=0 for reproducible evals; per-call output cap bounds cost."""
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
        return ChatAnthropic(model=config.ANTHROPIC_MODEL, temperature=temperature,
                             max_tokens=max_tokens, api_key=config.ANTHROPIC_API_KEY)
    raise ValueError(f"Unknown model '{name}'. Supported: {', '.join(_SUPPORTED)}")


def cost_usd(name: str, input_tokens: int, output_tokens: int) -> float:
    """Dollar cost of a call from token usage and the config price table."""
    price_in, price_out = config.PRICING.get(name, (0.0, 0.0))
    return round(input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out, 6)
