"""Cloud LLM factory. The provider and model are chosen with environment variables."""
import os

from app.config import get_settings


class LLMConfigError(RuntimeError):
    """Raised when the configured LLM cannot be created (missing key, unknown provider)."""


DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "groq": "llama-3.3-70b-versatile",
    "anthropic": "claude-haiku-4-5-20251001",
    "openrouter": "openrouter/free",
}
KEY_VARIABLES = {
    "gemini": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def key_configured():
    """True when the selected provider has an API key set (the key itself is never exposed)."""
    variable = KEY_VARIABLES.get(get_settings().llm_provider)
    return bool(variable and os.environ.get(variable, "").strip())


def get_llm():
    settings = get_settings()
    provider = settings.llm_provider
    if provider not in DEFAULT_MODELS:
        raise LLMConfigError(
            f"Unknown LLM_PROVIDER '{provider}'. Use one of: {', '.join(DEFAULT_MODELS)}"
        )

    key_variable = KEY_VARIABLES[provider]
    api_key = os.environ.get(key_variable, "").strip()
    if not api_key:
        raise LLMConfigError(
            f"{key_variable} is not set (LLM_PROVIDER={provider}). "
            f"Put {key_variable}=<your key> in the .env file next to requirements.txt and restart the server."
        )
    model = settings.llm_model or DEFAULT_MODELS[provider]

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, temperature=0.1, google_api_key=api_key)
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, temperature=0.1, api_key=api_key)
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )

    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, temperature=0.1, api_key=api_key, max_tokens=1500)
