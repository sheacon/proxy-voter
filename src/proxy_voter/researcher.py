import logging
import re

import anthropic

from proxy_voter.api_client import create_with_retry
from proxy_voter.config import get_settings
from proxy_voter.models import BallotData, UsageStats, VotingDecision

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a proxy voting research analyst. Your job is to analyze corporate proxy \
voting proposals and recommend votes based on the shareholder's policy preferences.

## Shareholder Policy Preferences

{policy_preferences}

## Your Task

You will receive the raw text content of a proxy voting ballot page. Your job is to:
1. Identify the company name, meeting date, voting deadline, and all proposals
2. Research the company and proposal context using web search
3. Specifically search for the company's investor relations page and any linked proxy materials
4. Analyze each proposal against the shareholder's policy preferences
5. Recommend a vote for each proposal, using only the vote options available for that proposal

## Guidelines

- Be efficient with web searches. Focus on the company's latest proxy statement and any major \
controversies. Avoid redundant searches.
- For compensation-related proposals: the shareholder is generally opposed to management-backed \
compensation proposals. Research whether the compensation is reasonable relative to peers and \
tied to long-term performance before recommending.
- For director elections: briefly research each nominee's background and any controversies.
- For routine matters (financial statement approval, auditor election): generally vote For unless \
there are specific red flags.
- For all proposals: prioritize long-term shareholder value above all other considerations.
- Use exactly the vote options shown on the ballot for each proposal (e.g., some proposals may \
only offer "For" and "Against", others may include "Abstain" or "Withhold").

When you have completed your research and analysis, call the `submit_voting_decisions` tool with \
your recommendations."""

VOTING_DECISIONS_TOOL = {
    "name": "submit_voting_decisions",
    "description": "Submit the final voting decisions for all proposals on the ballot.",
    "input_schema": {
        "type": "object",
        "properties": {
            "company_name": {
                "type": "string",
                "description": "The company name as shown on the ballot",
            },
            "meeting_date": {
                "type": "string",
                "description": "The meeting date as shown on the ballot",
            },
            "voting_deadline": {
                "type": "string",
                "description": "The voting deadline as shown on the ballot",
            },
            "shares_available": {
                "type": "integer",
                "description": "Number of shares available to vote",
            },
            "control_number": {
                "type": "string",
                "description": "The control number shown on the ballot",
            },
            "cusip": {
                "type": "string",
                "description": "The CUSIP identifier shown on the ballot",
            },
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "proposal_number": {
                            "type": "string",
                            "description": "Proposal number exactly as shown on ballot",
                        },
                        "proposal_description": {
                            "type": "string",
                            "description": "Brief description of the proposal",
                        },
                        "vote": {
                            "type": "string",
                            "description": "Your recommended vote using the exact options "
                            "available on the ballot (For, Against, Abstain, Withhold, etc.)",
                        },
                        "reasoning": {
                            "type": "string",
                            "description": "Factual research summary (2-3 sentences)",
                        },
                        "policy_rationale": {
                            "type": "string",
                            "description": "How this vote adheres to the shareholder's "
                            "policy preferences",
                        },
                        "board_recommendation": {
                            "type": "string",
                            "description": "The board/vote recommendation as shown on ballot",
                        },
                        "aligned_with_board": {"type": "boolean"},
                    },
                    "required": [
                        "proposal_number",
                        "proposal_description",
                        "vote",
                        "reasoning",
                        "policy_rationale",
                        "board_recommendation",
                        "aligned_with_board",
                    ],
                },
            },
        },
        "required": [
            "company_name",
            "meeting_date",
            "voting_deadline",
            "shares_available",
            "control_number",
            "cusip",
            "decisions",
        ],
    },
}


# Patterns to strip from ballot page text (case-insensitive)
_BOILERPLATE_PATTERNS = [
    r"^.*cookie\s*(policy|preferences|settings|consent).*$",
    r"^.*privacy\s*(policy|notice|statement).*$",
    r"^.*terms\s*(of\s*use|of\s*service|&\s*conditions).*$",
    r"^.*copyright\s*©?\s*\d{4}.*$",
    r"^.*all\s*rights\s*reserved.*$",
    r"^.*powered\s*by\s+.*$",
    r"^accept(\s+all)?\s*$",
    r"^reject(\s+all)?\s*$",
    r"^(manage|customize)\s*cookies?\s*$",
]
_BOILERPLATE_RE = re.compile("|".join(_BOILERPLATE_PATTERNS), re.MULTILINE | re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^[\s\-=*_]{4,}$", re.MULTILINE)
_BLANK_LINES_RE = re.compile(r"\n{3,}")
_BARE_URL_RE = re.compile(r"^https?://\S+$", re.MULTILINE)


def _clean_ballot_text(text: str) -> str:
    """Remove boilerplate noise from ballot page text. No truncation."""
    text = _BOILERPLATE_RE.sub("", text)
    text = _SEPARATOR_RE.sub("", text)
    text = _BARE_URL_RE.sub("", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


async def research_proposals(
    ballot: BallotData,
) -> tuple[dict, list[VotingDecision], UsageStats]:
    """Research proposals and return (ballot_metadata, decisions, usage_stats).

    ballot_metadata contains company_name, meeting_date, voting_deadline, etc.
    extracted by Claude from the raw page text.
    """
    settings = get_settings()
    policy_preferences = settings.load_policy_preferences()
    usage = UsageStats()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    doc_urls_text = ""
    if ballot.document_urls:
        doc_urls_text = "\n\nLinked documents available for review:\n" + "\n".join(
            f"- {url}" for url in ballot.document_urls
        )

    cleaned_text = _clean_ballot_text(ballot.page_text)
    logger.info(
        "Cleaned ballot text: %d -> %d chars (%.0f%% reduction)",
        len(ballot.page_text),
        len(cleaned_text),
        (1 - len(cleaned_text) / len(ballot.page_text)) * 100 if ballot.page_text else 0,
    )

    user_message = f"""## Raw Ballot Page Text

{cleaned_text}
{doc_urls_text}

Only include actual voting proposals in your decisions. Skip non-proposal content like \
requests for printed materials, attendance preferences, etc."""

    logger.info("Sending ballot to research agent (%d chars of page text)", len(cleaned_text))

    system = SYSTEM_PROMPT.format(policy_preferences=policy_preferences)
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 5},
        VOTING_DECISIONS_TOOL,
    ]

    response = await create_with_retry(
        client,
        model=settings.claude_model,
        system=system,
        tools=tools,
        messages=[{"role": "user", "content": user_message}],
        cache_control={"type": "ephemeral"},
    )
    usage.add(settings.claude_model, response.usage)
    logger.info("Research turn 1: %s", _format_usage(response.usage))

    messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response.content},
    ]

    max_turns = 8
    for turn in range(max_turns):
        # Check if the submit_voting_decisions tool was called
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_voting_decisions":
                return *_parse_results(block.input), usage

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            break

        # Web search is server-side — continue the conversation
        response = await create_with_retry(
            client,
            model=settings.claude_model,
            system=system,
            tools=tools,
            messages=messages,
            cache_control={"type": "ephemeral"},
        )
        usage.add(settings.claude_model, response.usage)
        logger.info("Research turn %d: %s", turn + 2, _format_usage(response.usage))
        messages.append({"role": "assistant", "content": response.content})

    # Final check
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_voting_decisions":
            return *_parse_results(block.input), usage

    raise RuntimeError("Research agent did not submit voting decisions")


def _format_usage(usage: object) -> str:
    """Format an anthropic usage object for logging."""
    parts = [
        f"in={getattr(usage, 'input_tokens', 0)}",
        f"out={getattr(usage, 'output_tokens', 0)}",
    ]
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    if cache_read:
        parts.append(f"cache_read={cache_read}")
    if cache_write:
        parts.append(f"cache_write={cache_write}")
    return ", ".join(parts)


def _parse_results(tool_input: dict) -> tuple[dict, list[VotingDecision]]:
    metadata = {
        "company_name": tool_input.get("company_name", "Unknown"),
        "meeting_date": tool_input.get("meeting_date", ""),
        "voting_deadline": tool_input.get("voting_deadline", ""),
        "shares_available": tool_input.get("shares_available", 0),
        "control_number": tool_input.get("control_number", ""),
        "cusip": tool_input.get("cusip", ""),
    }

    if "decisions" not in tool_input:
        logger.error(
            "Research agent tool response missing 'decisions' key. Keys received: %s",
            list(tool_input.keys()),
        )
        raise ValueError(
            f"Research agent returned malformed response (missing 'decisions' key, "
            f"got keys: {list(tool_input.keys())})"
        )

    decisions = []
    for d in tool_input["decisions"]:
        decisions.append(
            VotingDecision(
                proposal_number=d["proposal_number"],
                proposal_description=d["proposal_description"],
                vote=d["vote"],
                reasoning=d["reasoning"],
                policy_rationale=d["policy_rationale"],
                board_recommendation=d["board_recommendation"],
                aligned_with_board=d["aligned_with_board"],
            )
        )

    logger.info(
        "Research agent returned %d voting decisions for %s",
        len(decisions),
        metadata["company_name"],
    )
    return metadata, decisions
