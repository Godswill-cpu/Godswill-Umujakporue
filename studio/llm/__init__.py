"""Provider-agnostic LLM access with structured (pydantic-validated) outputs."""
from __future__ import annotations


def select_llm(settings):
    """Return the configured LLM provider, or None when AI research is switched off."""
    if not settings.llm_configured:
        return None
    from .anthropic_provider import AnthropicProvider
    return AnthropicProvider(settings.anthropic_api_key.get_secret_value(), settings.llm_model)
