import asyncio
import logging

import anthropic

logger = logging.getLogger(__name__)


async def create_with_retry(
    client: anthropic.Anthropic, *, max_tokens: int = 4096, **kwargs
) -> anthropic.types.Message:
    """Call messages.create with retry on rate limit errors."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return client.messages.create(max_tokens=max_tokens, **kwargs)
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 30 * (attempt + 1)
            logger.warning(
                "Rate limited, retrying in %ds (attempt %d/%d)",
                wait,
                attempt + 1,
                max_retries,
            )
            await asyncio.sleep(wait)
