"""Claude via the official Anthropic SDK, using structured outputs."""
from __future__ import annotations

from .base import LLMError, LLMProvider, LLMResult

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str | None, model: str = DEFAULT_MODEL, timeout: float = 300.0):
        if not api_key:
            raise LLMError("Anthropic API key is not configured. Add it on the Settings page.")
        import anthropic
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.model = model or DEFAULT_MODEL

    def structured(self, system, user, schema, max_tokens=16000) -> LLMResult:
        a = self._anthropic
        try:
            resp = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": "high"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError:
            raise LLMError("The Anthropic API rejected the key (authentication failed). Check Settings.") from None
        except a.PermissionDeniedError:
            raise LLMError("The Anthropic API key lacks permission for this request.") from None
        except a.NotFoundError:
            raise LLMError(f"Model '{self.model}' was not found for this API key.") from None
        except a.RateLimitError:
            raise LLMError("Anthropic API rate limit reached after retries. Try again later.") from None
        except a.BadRequestError as e:
            raise LLMError(f"Anthropic API rejected the request: {e.message}") from None
        except a.APIStatusError as e:
            raise LLMError(f"Anthropic API error {e.status_code}. Try again later.") from None
        except a.APIConnectionError:
            raise LLMError("Could not reach the Anthropic API (network error).") from None
        if resp.stop_reason == "refusal":
            raise LLMError("The model declined this research request.")
        if resp.stop_reason == "max_tokens":
            raise LLMError("The research response was cut off (max_tokens). Use fewer or shorter sources.")
        if resp.parsed_output is None:
            raise LLMError("The model returned no structured output.")
        return LLMResult(output=resp.parsed_output, input_tokens=resp.usage.input_tokens,
                         output_tokens=resp.usage.output_tokens, model=resp.model)
