"""
LLM client wrapper + token pricing for cost accounting.

The hackathon brief's stack preference is the Anthropic API. This build
uses DeepSeek instead (OpenAI-compatible Chat Completions API) because
that's the key available in this environment -- see README.md's "stack
deviation" note. `LLMResponse`/`_Messages` below present an
Anthropic-Messages-shaped interface (`client.messages.create(...)` ->
`resp.content[0].text`, `resp.usage.input_tokens/output_tokens`) so the
rest of the codebase (baseline.py, orchestrator.py, tools.py) is written
against one interface regardless of provider.
"""
import os

DEFAULT_MODEL = "deepseek-chat"

# USD per million tokens.
PRICING = {
    "deepseek-chat": {"input": 0.28, "output": 0.42},          # cache-miss rates, deepseek.com/pricing
    "deepseek-reasoner": {"input": 0.28, "output": 0.42},
    "claude-sonnet-4-5-20250929": {"input": 3.00, "output": 15.00},
    "claude-opus-4-1-20250805": {"input": 15.00, "output": 75.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
}


class _Content:
    def __init__(self, text):
        self.text = text


class _Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class LLMResponse:
    def __init__(self, text, input_tokens, output_tokens):
        self.content = [_Content(text)]
        self.usage = _Usage(input_tokens, output_tokens)


class _Messages:
    def __init__(self, api_key, base_url):
        self._api_key = api_key
        self._base_url = base_url

    def create(self, model, max_tokens, messages):
        import json
        import urllib.request
        import urllib.error

        body = json.dumps({"model": model, "max_tokens": max_tokens, "messages": messages}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=body,
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"DeepSeek API error {e.code}: {e.read().decode()}") from e
        text = data["choices"][0]["message"]["content"] or ""
        usage = data["usage"]
        return LLMResponse(text, usage["prompt_tokens"], usage["completion_tokens"])


class DeepSeekClient:
    """Anthropic-Messages-shaped wrapper around DeepSeek's OpenAI-compatible API.
    Uses plain HTTP (requests) rather than the openai SDK's httpx client, which
    hits a decompressor incompatibility in this environment."""
    def __init__(self, api_key):
        self.messages = _Messages(api_key, "https://api.deepseek.com")


def get_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if os.environ.get("DEEPSEEK_API_KEY"):
        return DeepSeekClient(os.environ["DEEPSEEK_API_KEY"])
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    raise RuntimeError(
        "Neither DEEPSEEK_API_KEY nor ANTHROPIC_API_KEY is set. Export one of them to "
        "run the baseline or agent (both make live LLM calls, per the hackathon brief's "
        "'must be built and run for real, not simulated' requirement)."
    )


def cost_usd(model, input_tokens, output_tokens):
    rates = PRICING.get(model)
    if not rates:
        return None
    return (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]
