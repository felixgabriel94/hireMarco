"""Prices for the Meta Model API, read from dev.meta.ai/docs/pricing-rate-limits
on 2026-10-26. USD per million tokens: (cached input, input, output).
Update this table when the page changes; the job log records the price used.
"""

from __future__ import annotations

PRICES_PER_MILLION: dict[str, tuple[float, float, float]] = {
    "muse-wonder-1.0": (0.20, 4.00, 20.00),
    "muse-spark-1.3": (0.15, 1.25, 4.25),
    "muse-spark-1.2": (0.15, 1.25, 4.25),
    "muse-spark-1.1": (0.15, 1.25, 4.25),
    "muse-spark-1.3-contributor": (0.002, 0.10, 0.20),
    "muse-spark-1.2-contributor": (0.002, 0.10, 0.20),
}

PRICES_READ_ON = "2026-10-26"


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int = 0) -> float:
    """Cost of one call. Cached tokens are a subset of prompt tokens.

    Raises KeyError for a model not in the table, so an unpriced call is a
    defect to report rather than a silent zero.
    """
    cached_price, input_price, output_price = PRICES_PER_MILLION[model]
    cached = min(cached_tokens, prompt_tokens)
    fresh = prompt_tokens - cached
    cost = (cached * cached_price + fresh * input_price + completion_tokens * output_price) / 1_000_000
    return round(cost, 8)


# Speech to text is priced by audio time, USD per hour (read 2026-10-26).
PRICES_PER_HOUR: dict[str, float] = {
    "muse-voice-transcribe-1.0": 0.18,
}


def audio_cost_usd(model: str, milliseconds: int) -> float:
    """Raises KeyError for an unpriced model, like ``cost_usd``."""
    return round(PRICES_PER_HOUR[model] * milliseconds / 3_600_000, 8)


# Text to speech is priced by characters, USD per 1,000. ElevenLabs is not a
# Meta model; it is Marco's voice. These are estimates from third-party
# summaries (2026-10-28); replace them with the rate on the Owner's own plan.
PRICES_PER_THOUSAND_CHARS: dict[str, float] = {
    "eleven_flash_v2_5": 0.05,
}


def speech_cost_usd(model: str, characters: int) -> float:
    """Raises KeyError for an unpriced model, like ``cost_usd``."""
    return round(PRICES_PER_THOUSAND_CHARS[model] * characters / 1000, 8)


# Segmentation is priced per image (pricing page, read 2026-10-28): 2.50 USD
# per 1,000 images for SAM 3.1.
PRICES_PER_IMAGE: dict[str, float] = {
    "sam-3.1": 2.50 / 1000,
}
