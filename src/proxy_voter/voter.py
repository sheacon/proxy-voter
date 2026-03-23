import asyncio
import logging

import anthropic
from playwright.async_api import Page

from proxy_voter.config import get_settings
from proxy_voter.models import VotingDecision

logger = logging.getLogger(__name__)

VOTING_PROMPT = """You are a form automation assistant. Given structured data about form elements \
on a proxy voting ballot and a list of voting decisions, return the exact actions to perform \
for each vote.

## Voting Decisions

{decisions_text}

## Ballot Page Text (for context)

{page_text}

## Form Element Data

Each entry below is a form element on the ballot page with its type and attributes.

{form_data}

## Buttons / Submit Elements

{button_data}

## Instructions

For each voting decision, identify which form element to interact with and how. The ballot may \
use radio buttons, dropdown selects, checkboxes, or other form elements.

Key observations:
- For radio buttons: buttons are grouped by their `name` attribute — same name = same proposal
- For select dropdowns: each `<select>` element typically corresponds to one proposal
- Match proposals to form elements by correlating page text with proposal descriptions
- The order of form elements on the page typically matches the order of proposals
- Look at the `label` field to determine which value maps to For/Against/Abstain/Withhold

For each vote action, specify:
- `action_type`: "check_radio", "select_option", or "check_checkbox"
- `selector`: CSS selector for the element (use `#theId` when an id is available, otherwise use \
`input[name="theName"][value="theValue"]` for radios/checkboxes or `select[name="theName"]` \
for dropdowns)
- `value`: for select_option only, the option value to select

CRITICAL: Only use selectors constructed from the ACTUAL `name`, `value`, and `id` fields \
shown in the form data above. NEVER invent or guess element IDs.

Also identify the submit/vote button. Look for buttons or inputs with text like "Submit Vote", \
"Submit", "Vote Now", "Cast Votes", etc. Return its CSS selector in the `submit_selector` field.

Call the `submit_vote_actions` tool with your results."""

VOTE_ACTION_TOOL = {
    "name": "submit_vote_actions",
    "description": "Submit the actions to cast each vote and the submit button selector.",
    "input_schema": {
        "type": "object",
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "proposal_number": {"type": "string"},
                        "action_type": {
                            "type": "string",
                            "enum": ["check_radio", "select_option", "check_checkbox"],
                        },
                        "selector": {"type": "string"},
                        "value": {
                            "type": "string",
                            "description": "For select_option: the option value to select",
                        },
                        "matched": {"type": "boolean"},
                    },
                    "required": ["proposal_number", "action_type", "selector", "matched"],
                },
            },
            "submit_selector": {
                "type": "string",
                "description": "CSS selector for the submit/vote button on the form.",
            },
        },
        "required": ["actions", "submit_selector"],
    },
}


async def cast_votes(page: Page, decisions: list[VotingDecision]) -> str:
    """Cast votes by having Claude interpret the form structure and return actions."""
    logger.info("Casting %d votes via Claude-assisted form submission", len(decisions))

    # Extract all form elements from the page
    form_data = await page.evaluate("""() => {
        const results = [];

        // Radio buttons
        for (const radio of document.querySelectorAll('input[type="radio"]')) {
            const name = radio.name || '';
            const value = radio.value || '';
            const id = radio.id || '';
            let label = '';

            if (radio.labels && radio.labels.length > 0) {
                label = radio.labels[0].innerText.trim();
            }
            if (!label) {
                label = radio.getAttribute('aria-label') || '';
            }
            if (!label && radio.parentElement) {
                const parent = radio.parentElement;
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
            if (!label && id) {
                const lbl = document.querySelector('label[for="' + CSS.escape(id) + '"]');
                if (lbl) label = lbl.innerText.trim();
            }

            results.push({ type: 'radio', name, value, id, label });
        }

        // Select dropdowns
        for (const select of document.querySelectorAll('select')) {
            const name = select.name || '';
            const id = select.id || '';
            const options = [];
            for (const opt of select.options) {
                options.push({ value: opt.value, text: opt.textContent.trim() });
            }
            let label = '';
            if (select.labels && select.labels.length > 0) {
                label = select.labels[0].innerText.trim();
            }
            if (!label && id) {
                const lbl = document.querySelector('label[for="' + CSS.escape(id) + '"]');
                if (lbl) label = lbl.innerText.trim();
            }
            results.push({ type: 'select', name, id, label, options });
        }

        // Checkboxes
        for (const cb of document.querySelectorAll('input[type="checkbox"]')) {
            const name = cb.name || '';
            const value = cb.value || '';
            const id = cb.id || '';
            let label = '';
            if (cb.labels && cb.labels.length > 0) {
                label = cb.labels[0].innerText.trim();
            }
            if (!label && id) {
                const lbl = document.querySelector('label[for="' + CSS.escape(id) + '"]');
                if (lbl) label = lbl.innerText.trim();
            }
            results.push({ type: 'checkbox', name, value, id, label });
        }

        return results;
    }""")

    # Extract button/submit element candidates
    button_data = await page.evaluate("""() => {
        const results = [];
        const buttons = document.querySelectorAll(
            'button, input[type="submit"], a.btn, [role="button"]'
        );
        for (const btn of buttons) {
            const text = btn.innerText?.trim() || btn.value || '';
            if (!text) continue;
            const tag = btn.tagName.toLowerCase();
            const id = btn.id || '';
            const type = btn.type || '';
            const classes = btn.className || '';
            results.push({ tag, text, id, type, classes });
        }
        return results;
    }""")

    logger.info("Found %d form elements and %d buttons on ballot", len(form_data), len(button_data))

    # Log first few form entries for debugging
    for f in form_data[:5]:
        logger.info(
            "  Form element: type=%s name=%s label=%s",
            f["type"],
            f.get("name"),
            f.get("label"),
        )

    if not form_data:
        raise RuntimeError("No form elements found on ballot page")

    # Format form data for Claude
    form_text_lines = []
    for f in form_data:
        if f["type"] == "radio":
            form_text_lines.append(
                f'  [radio] name={f["name"]} value={f["value"]} id={f["id"]} label="{f["label"]}"'
            )
        elif f["type"] == "select":
            opts = ", ".join(f'{o["value"]}="{o["text"]}"' for o in f.get("options", []))
            form_text_lines.append(
                f'  [select] name={f["name"]} id={f["id"]} label="{f["label"]}" options=[{opts}]'
            )
        elif f["type"] == "checkbox":
            form_text_lines.append(
                f"  [checkbox] name={f['name']} value={f['value']}"
                f' id={f["id"]} label="{f["label"]}"'
            )
    form_text = "\n".join(form_text_lines)

    # Format button data for Claude
    button_text = "\n".join(
        f'  [{b["tag"]}] text="{b["text"]}" id={b["id"]} type={b["type"]} class={b["classes"]}'
        for b in button_data
    )

    # Get page text for context (truncated)
    page_text = await page.evaluate("() => document.body.innerText")
    page_text_truncated = page_text[:3000]

    decisions_text = "\n".join(
        f"- Proposal {d.proposal_number}: Vote **{d.vote}**" for d in decisions
    )

    # Ask Claude to map decisions to form actions
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    response = await _create_with_retry(
        client,
        model=settings.claude_model,
        messages=[
            {
                "role": "user",
                "content": VOTING_PROMPT.format(
                    decisions_text=decisions_text,
                    page_text=page_text_truncated,
                    form_data=form_text,
                    button_data=button_text,
                ),
            }
        ],
        tools=[VOTE_ACTION_TOOL],
        tool_choice={"type": "tool", "name": "submit_vote_actions"},
    )

    # Extract actions and submit selector from the tool call
    actions = []
    submit_selector = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_vote_actions":
            actions = block.input.get("actions", [])
            submit_selector = block.input.get("submit_selector")
            break

    if not actions:
        raise RuntimeError("Claude did not return any vote actions")

    logger.info("Claude returned %d vote actions", len(actions))

    # Execute each action
    voted = 0
    for action in actions:
        if not action.get("matched"):
            logger.warning(
                "Proposal %s: no match found by Claude",
                action.get("proposal_number"),
            )
            continue

        selector = action["selector"]
        action_type = action["action_type"]
        try:
            if action_type == "check_radio":
                try:
                    await page.locator(selector).check(timeout=5000)
                except Exception:
                    await page.locator(selector).check(force=True, timeout=5000)
            elif action_type == "select_option":
                await page.locator(selector).select_option(action.get("value", ""), timeout=5000)
            elif action_type == "check_checkbox":
                try:
                    await page.locator(selector).check(timeout=5000)
                except Exception:
                    await page.locator(selector).check(force=True, timeout=5000)
            voted += 1
            logger.info(
                "Voted on proposal %s (%s: %s)",
                action["proposal_number"],
                action_type,
                selector,
            )
        except Exception:
            logger.warning(
                "Failed to execute action for proposal %s: %s %s",
                action["proposal_number"],
                action_type,
                selector,
            )

    logger.info("Executed votes for %d/%d proposals", voted, len(decisions))

    if voted == 0:
        raise RuntimeError("Failed to execute any vote actions")

    # Click submit button
    if submit_selector:
        logger.info("Clicking submit button: %s", submit_selector)
        try:
            await page.locator(submit_selector).click(timeout=10000)
        except Exception:
            logger.warning("Claude's submit selector failed, trying generic fallback")
            await _click_submit_fallback(page)
    else:
        await _click_submit_fallback(page)

    # Wait for confirmation
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    confirmation = await page.evaluate("() => document.body.innerText")
    logger.info("Post-submission page preview: %.200s", confirmation)

    return confirmation[:1000]


async def _click_submit_fallback(page: Page) -> None:
    """Try common submit button patterns as a fallback."""
    candidates = [
        'button:has-text("Submit")',
        'input[type="submit"]',
        'button:has-text("Vote")',
        'a:has-text("Submit")',
    ]
    for selector in candidates:
        try:
            element = await page.query_selector(selector)
            if element:
                await element.click()
                return
        except Exception:
            continue
    raise RuntimeError("Submit button not found")


async def _create_with_retry(client, **kwargs) -> anthropic.types.Message:
    """Call messages.create with retry on rate limit errors."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return client.messages.create(
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
