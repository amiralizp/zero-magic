"""Token and cost estimation.

We do not ship a tokenizer dependency: the point of the exercise is to see the
order of magnitude. Latin text is estimated at ~4 characters per token, Persian
at ~3 (Arabic-script letters are often split more finely). The estimate is
labelled as an estimate everywhere it is shown.
"""

from __future__ import annotations

import math

# Example list prices in USD per million tokens. Verify before trusting a bill.
PRICES: dict[str, tuple[float, float]] = {
    "mock-strong": (0.0, 0.0),
    "mock-fast": (0.0, 0.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "anthropic/claude-3.5-haiku": (0.80, 4.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
}


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    persian = sum(1 for char in text if "\u0600" <= char <= "\u06ff")
    ratio = 3.0 if persian > len(text) * 0.3 else 4.0
    return max(1, math.ceil(len(text) / ratio))


def price_for(model: str) -> tuple[float, float]:
    return PRICES.get(model, (0.0, 0.0))


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    input_price, output_price = price_for(model)
    return round(
        (input_tokens / 1_000_000) * input_price
        + (output_tokens / 1_000_000) * output_price,
        8,
    )
