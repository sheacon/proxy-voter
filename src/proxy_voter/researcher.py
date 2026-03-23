import asyncio
import logging

import anthropic

from proxy_voter.config import get_settings
from proxy_voter.models import BallotData, VotingDecision

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


async def research_proposals(ballot: BallotData) -> tuple[dict, list[VotingDecision]]:
    """Research proposals and return (ballot_metadata, decisions).

    ballot_metadata contains company_name, meeting_date, voting_deadline, etc.
    extracted by Claude from the raw page text.
    """
    settings = get_settings()
    policy_preferences = settings.load_policy_preferences()

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    doc_urls_text = ""
    if ballot.document_urls:
        doc_urls_text = "\n\nLinked documents available for review:\n" + "\n".join(
            f"- {url}" for url in ballot.document_urls
        )

    user_message = f"""Below is the raw text content scraped from a proxy voting ballot page. \
Please identify all proposals, research them, and submit your voting recommendations.

## Raw Ballot Page Text

{ballot.page_text}
{doc_urls_text}

## Instructions

1. First, identify the company, meeting date, voting deadline, shares, and all proposals from \
the ballot text above
2. Search for the company's investor relations page for proxy materials and context
3. Research each proposal and recommend a vote
4. Submit your decisions using the submit_voting_decisions tool

Important: Only include actual voting proposals in your decisions. Skip non-proposal content \
like requests for printed materials, attendance preferences, etc."""

    logger.info("Sending ballot to research agent (%d chars of page text)", len(ballot.page_text))

    system = SYSTEM_PROMPT.format(policy_preferences=policy_preferences)
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 10},
        VOTING_DECISIONS_TOOL,
    ]

    response = await _create_with_retry(
        client,
        model=settings.claude_model,
        system=system,
        tools=tools,
        messages=[{"role": "user", "content": user_message}],
    )

    messages = [
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": response.content},
    ]

    max_turns = 15
    for _ in range(max_turns):
        # Check if the submit_voting_decisions tool was called
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_voting_decisions":
                return _parse_results(block.input)

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason != "tool_use":
            break

        # Web search is server-side — continue the conversation
        response = await _create_with_retry(
            client,
            model=settings.claude_model,
            system=system,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

    # Final check
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_voting_decisions":
            return _parse_results(block.input)

    raise RuntimeError("Research agent did not submit voting decisions")


async def _create_with_retry(client, **kwargs) -> anthropic.types.Message:
    """Call messages.create with retry on rate limit errors."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            return client.messages.create(
                max_tokens=8192,
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


def _parse_results(tool_input: dict) -> tuple[dict, list[VotingDecision]]:
    metadata = {
        "company_name": tool_input.get("company_name", "Unknown"),
        "meeting_date": tool_input.get("meeting_date", ""),
        "voting_deadline": tool_input.get("voting_deadline", ""),
        "shares_available": tool_input.get("shares_available", 0),
        "control_number": tool_input.get("control_number", ""),
        "cusip": tool_input.get("cusip", ""),
    }

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
