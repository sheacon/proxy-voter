import asyncio
import logging

import anthropic
from playwright.async_api import Page

from proxy_voter.config import get_settings
from proxy_voter.models import VotingDecision

logger = logging.getLogger(__name__)

SELECTOR_PROMPT = """You are a form automation assistant. Given structured data about \
radio buttons on a proxy voting ballot and a list of voting decisions, return the \
exact CSS selector to click for each vote.

## Voting Decisions

{decisions_text}

## Ballot Page Text (for context)

{page_text}

## Radio Button Data

Each entry below is a radio button on the form with its name, value, id, and the visible label \
text near it.

{radio_data}

## Instructions

For each voting decision, identify which radio button to click. Return the CSS selector \
(use the `id`-based selector like `#theId` when available, otherwise use \
`input[name="theName"][value="theValue"]`).

Key observations:
- Radio groups are typically named `proposalVoteOptions[N]` where N is the index
- The Nth group corresponds to the Nth proposal on the page
- Values are often numeric (0=first option, 1=second option, etc.)
- Look at the `label` field to determine which value maps to For/Against/Abstain/Withhold

CRITICAL: Only use selectors constructed from the ACTUAL `name`, `value`, and `id` fields \
shown in the radio data above. NEVER invent or guess element IDs. If a radio has no `id`, \
use the `input[name="..."][value="..."]` format instead. The name and value fields are always \
populated — use them.

Call the `submit_selectors` tool with your results."""

SELECTOR_TOOL = {
    "name": "submit_selectors",
    "description": "Submit the CSS selectors for each vote.",
    "input_schema": {
        "type": "object",
        "properties": {
            "selectors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "proposal_number": {"type": "string"},
                        "selector": {"type": "string"},
                        "matched": {"type": "boolean"},
                    },
                    "required": ["proposal_number", "selector", "matched"],
                },
            }
        },
        "required": ["selectors"],
    },
}


async def cast_votes(page: Page, decisions: list[VotingDecision]) -> str:
    """Cast votes by having Claude interpret the form structure and return selectors."""
    logger.info("Casting %d votes via Claude-assisted form submission", len(decisions))

    # Extract structured radio button data — much more useful than raw HTML
    radio_data = await page.evaluate("""() => {
        const results = [];
        const radios = document.querySelectorAll('input[type="radio"]');

        for (const radio of radios) {
            const name = radio.name || '';
            const value = radio.value || '';
            const id = radio.id || '';

            // Get the visible label text for this radio
            let label = '';

            // Method 1: explicit label element
            if (radio.labels && radio.labels.length > 0) {
                label = radio.labels[0].innerText.trim();
            }

            // Method 2: aria-label
            if (!label) {
                label = radio.getAttribute('aria-label') || '';
            }

            // Method 3: look at nearby sibling text nodes
            if (!label && radio.parentElement) {
                const parent = radio.parentElement;
                // Check for adjacent text or span
                for (const child of parent.childNodes) {
                    if (child.nodeType === 3 && child.textContent.trim()) {
                        label = child.textContent.trim();
                        break;
                    }
                    if (child.nodeType === 1 && child !== radio) {
                        const t = child.innerText?.trim();
                        if (t && t.length < 20) {
                            label = t;
                            break;
                        }
                    }
                }
            }

            // Method 4: for-attribute label
            if (!label && id) {
                const lbl = document.querySelector('label[for="' + CSS.escape(id) + '"]');
                if (lbl) label = lbl.innerText.trim();
            }

            results.push({ name, value, id, label });
        }

        return results;
    }""")

    logger.info("Found %d radio inputs on ballot", len(radio_data))

    # Log first few radio entries for debugging
    for r in radio_data[:5]:
        logger.info(
            "  Radio: name=%s value=%s id=%s label=%s",
            r["name"],
            r["value"],
            r["id"],
            r["label"],
        )

    if not radio_data:
        raise RuntimeError("No radio inputs found on ballot page")

    # Format radio data for Claude
    radio_text = "\n".join(
        f'  name={r["name"]} value={r["value"]} id={r["id"]} label="{r["label"]}"'
        for r in radio_data
    )

    # Get page text for context (truncated)
    page_text = await page.evaluate("() => document.body.innerText")
    page_text_truncated = page_text[:3000]

    decisions_text = "\n".join(
        f"- Proposal {d.proposal_number}: Vote **{d.vote}**" for d in decisions
    )

    # Ask Claude to map decisions to selectors
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = await _create_with_retry(
        client,
        messages=[
            {
                "role": "user",
                "content": SELECTOR_PROMPT.format(
                    decisions_text=decisions_text,
                    page_text=page_text_truncated,
                    radio_data=radio_text,
                ),
            }
        ],
        tools=[SELECTOR_TOOL],
        tool_choice={"type": "tool", "name": "submit_selectors"},
    )

    # Extract the selectors from the tool call
    selectors = []
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_selectors":
            selectors = block.input.get("selectors", [])
            break

    if not selectors:
        raise RuntimeError("Claude did not return any selectors")

    logger.info("Claude returned %d selectors", len(selectors))

    # Click each selector with a short timeout
    voted = 0
    for sel in selectors:
        if not sel.get("matched"):
            logger.warning(
                "Proposal %s: no match found by Claude",
                sel.get("proposal_number"),
            )
            continue

        selector = sel["selector"]
        try:
            await page.click(selector, timeout=5000)
            voted += 1
            logger.info(
                "Voted on proposal %s (selector: %s)",
                sel["proposal_number"],
                selector,
            )
        except Exception:
            logger.warning(
                "Failed to click selector for proposal %s: %s",
                sel["proposal_number"],
                selector,
            )

    logger.info("Selected votes for %d/%d proposals", voted, len(decisions))

    if voted == 0:
        raise RuntimeError("Failed to click any vote selectors")

    # Click Submit Vote
    logger.info("Clicking Submit Vote")
    submit = await page.query_selector('button:has-text("Submit Vote"), input[value="Submit Vote"]')
    if not submit:
        submit = await page.query_selector("text=Submit Vote")
    if not submit:
        raise RuntimeError("Submit Vote button not found")

    await submit.click()

    # Wait for confirmation
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    confirmation = await page.evaluate("() => document.body.innerText")
    logger.info("Post-submission page preview: %.200s", confirmation)

    return confirmation[:1000]


async def _create_with_retry(client, **kwargs) -> anthropic.types.Message:
    """Call messages.create with retry on rate limit errors."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                **kwargs,
            )
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
