import asyncio
import logging

import anthropic
from playwright.async_api import Page

from proxy_voter.config import get_settings
from proxy_voter.models import VotingDecision

logger = logging.getLogger(__name__)

VOTING_PROMPT = """You are a form automation assistant. Given numbered form elements \
on a proxy voting ballot and a list of voting decisions, return the index of the form element \
to interact with for each vote.

## Voting Decisions

{decisions_text}

## Ballot Page Text (for context)

{page_text}

## Form Elements (numbered)

Each line is a form element on the ballot page, prefixed with its index number.

{form_data}

## Buttons / Submit Elements (numbered)

{button_data}

## Instructions

For each voting decision, identify which form element to interact with by its INDEX NUMBER.

Key observations:
- For radio buttons: buttons are grouped by their `name` attribute — same name = same proposal
- For select dropdowns: each `<select>` element typically corresponds to one proposal
- Match proposals to form elements by correlating page text with proposal descriptions
- The order of form elements on the page typically matches the order of proposals
- Look at the `label` field to determine which value maps to For/Against/Abstain/Withhold

For each vote action, specify:
- `element_index`: the index number of the form element to interact with (from the list above)
- `action_type`: "check_radio", "select_option", or "check_checkbox"
- `value`: for select_option only, the option value to select

Also identify the submit/vote button by its index from the buttons list.

Call the `submit_vote_actions` tool with your results."""

VOTE_ACTION_TOOL = {
    "name": "submit_vote_actions",
    "description": "Submit the element index for each vote and the submit button index.",
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
                        "element_index": {
                            "type": "integer",
                            "description": "Index of the form element from the numbered list",
                        },
                        "value": {
                            "type": "string",
                            "description": "For select_option: the option value to select",
                        },
                        "matched": {"type": "boolean"},
                    },
                    "required": [
                        "proposal_number",
                        "action_type",
                        "element_index",
                        "matched",
                    ],
                },
            },
            "submit_button_index": {
                "type": "integer",
                "description": "Index of the submit/vote button from the numbered buttons list.",
            },
        },
        "required": ["actions", "submit_button_index"],
    },
}


async def _dismiss_session_modal(page: Page) -> None:
    """Dismiss any session-about-to-expire modal that may block interactions."""
    try:
        modal = page.locator("#session_aboutTo_expire_modal.show")
        if await modal.count() > 0:
            logger.info("Dismissing session expiration modal")
            # Try clicking the continue/OK button inside the modal
            for btn_text in ["Continue", "OK", "Stay Logged In", "Extend"]:
                btn = modal.locator(f'button:has-text("{btn_text}")')
                if await btn.count() > 0:
                    await btn.first.click(timeout=3000)
                    await page.wait_for_timeout(500)
                    return
            # Fallback: click any primary/action button in the modal
            btn = modal.locator("button.btn-primary, button.btn-action").first
            if await btn.count() > 0:
                await btn.click(timeout=3000)
                await page.wait_for_timeout(500)
                return
            # Last resort: try to hide the modal via JS
            await page.evaluate("""() => {
                const modal = document.getElementById('session_aboutTo_expire_modal');
                if (modal) {
                    modal.classList.remove('show');
                    modal.style.display = 'none';
                    const backdrop = document.querySelector('.modal-backdrop');
                    if (backdrop) backdrop.remove();
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = '';
                }
            }""")
            await page.wait_for_timeout(500)
            logger.info("Dismissed modal via JS fallback")
    except Exception:
        logger.debug("No session modal to dismiss")


async def cast_votes(page: Page, decisions: list[VotingDecision]) -> str:
    """Cast votes by having Claude interpret the form structure and return actions."""
    logger.info("Casting %d votes via Claude-assisted form submission", len(decisions))

    # Dismiss any session modal before interacting with the page
    await _dismiss_session_modal(page)

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

    # Format form data for Claude with index numbers
    form_text_lines = []
    for i, f in enumerate(form_data):
        if f["type"] == "radio":
            form_text_lines.append(
                f'  [{i}] radio name="{f["name"]}" value="{f["value"]}" label="{f["label"]}"'
            )
        elif f["type"] == "select":
            opts = ", ".join(f'{o["value"]}="{o["text"]}"' for o in f.get("options", []))
            form_text_lines.append(
                f'  [{i}] select name="{f["name"]}" label="{f["label"]}" options=[{opts}]'
            )
        elif f["type"] == "checkbox":
            form_text_lines.append(
                f'  [{i}] checkbox name="{f["name"]}" value="{f["value"]}" label="{f["label"]}"'
            )
    form_text = "\n".join(form_text_lines)

    # Format button data for Claude with index numbers
    button_text = "\n".join(
        f'  [{i}] {b["tag"]} text="{b["text"]}" id="{b["id"]}"'
        for i, b in enumerate(button_data)
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

    # Extract actions and submit button index from the tool call
    actions = []
    submit_button_index = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_vote_actions":
            actions = block.input.get("actions", [])
            submit_button_index = block.input.get("submit_button_index")
            break

    if not actions:
        raise RuntimeError("Claude did not return any vote actions")

    logger.info("Claude returned %d vote actions", len(actions))

    # Dismiss modal again in case it appeared during the Claude API call
    await _dismiss_session_modal(page)

    # Execute each action using element indices
    voted = 0
    for action in actions:
        if not action.get("matched"):
            logger.warning(
                "Proposal %s: no match found by Claude",
                action.get("proposal_number"),
            )
            continue

        element_index = action.get("element_index")
        action_type = action["action_type"]

        if element_index is None or element_index < 0 or element_index >= len(form_data):
            logger.warning(
                "Proposal %s: invalid element_index %s (form has %d elements)",
                action.get("proposal_number"),
                element_index,
                len(form_data),
            )
            continue

        element_info = form_data[element_index]
        try:
            if action_type == "check_radio":
                locator = _build_locator(page, element_info, "radio")
                try:
                    await locator.check(timeout=5000)
                except Exception:
                    await locator.check(force=True, timeout=5000)
            elif action_type == "select_option":
                locator = _build_locator(page, element_info, "select")
                await locator.select_option(action.get("value", ""), timeout=5000)
            elif action_type == "check_checkbox":
                locator = _build_locator(page, element_info, "checkbox")
                try:
                    await locator.check(timeout=5000)
                except Exception:
                    await locator.check(force=True, timeout=5000)
            voted += 1
            logger.info(
                "Voted on proposal %s (index %d: %s name=%s label=%s)",
                action["proposal_number"],
                element_index,
                action_type,
                element_info.get("name"),
                element_info.get("label"),
            )
        except Exception:
            logger.warning(
                "Failed to execute action for proposal %s: index %d %s name=%s",
                action["proposal_number"],
                element_index,
                action_type,
                element_info.get("name"),
            )

    logger.info("Executed votes for %d/%d proposals", voted, len(decisions))

    if voted == 0:
        raise RuntimeError("Failed to execute any vote actions")

    # Dismiss modal before submit
    await _dismiss_session_modal(page)

    # Click submit button by index or fallback
    if submit_button_index is not None and 0 <= submit_button_index < len(button_data):
        btn = button_data[submit_button_index]
        logger.info("Clicking submit button index %d: %s", submit_button_index, btn.get("text"))
        try:
            locator = _build_button_locator(page, btn)
            await locator.click(timeout=10000)
        except Exception:
            logger.warning("Button index %d failed, trying generic fallback", submit_button_index)
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


def _css_escape(s: str) -> str:
    """Escape a string for use in a CSS attribute selector value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _build_locator(page: Page, element_info: dict, element_type: str):
    """Build a Playwright locator from extracted form element data."""
    eid = element_info.get("id", "")
    name = _css_escape(element_info.get("name", ""))
    value = _css_escape(element_info.get("value", ""))

    if eid:
        return page.locator(f"#{_css_escape(eid)}")

    tag_map = {"radio": "input", "checkbox": "input", "select": "select"}
    tag = tag_map.get(element_type, "input")
    type_attr = f'[type="{element_type}"]' if tag == "input" else ""

    if name and value:
        return page.locator(f'{tag}{type_attr}[name="{name}"][value="{value}"]')
    if name:
        return page.locator(f'{tag}{type_attr}[name="{name}"]').first

    return page.locator(f"{tag}{type_attr}").first


def _build_button_locator(page: Page, button_info: dict):
    """Build a Playwright locator for a button from extracted data."""
    bid = button_info.get("id", "")
    text = button_info.get("text", "")

    if bid:
        return page.locator(f"#{bid}")
    if text:
        tag = button_info.get("tag", "button")
        return page.locator(f'{tag}:has-text("{text}")').first
    return page.locator("button").first


async def _click_submit_fallback(page: Page) -> None:
    """Try common submit button patterns as a fallback."""
    await _dismiss_session_modal(page)
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
