from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from pydantic import BaseModel

# Pricing per million tokens (as of 2025)
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5": {
        "input": 0.80,
        "output": 4.0,
        "cache_write": 1.0,
        "cache_read": 0.08,
    },
}

# Fallback to Sonnet pricing for unknown models
_DEFAULT_PRICING = _MODEL_PRICING["claude-sonnet-4-6"]


@dataclass
class _CallRecord:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


@dataclass
class UsageStats:
    """Accumulates API usage across multiple calls with per-model cost tracking."""

    calls: list[_CallRecord] = field(default_factory=list)

    def add(self, model: str, usage: object) -> None:
        """Accumulate from an anthropic response.usage object."""
        self.calls.append(
            _CallRecord(
                model=model,
                input_tokens=getattr(usage, "input_tokens", 0),
                output_tokens=getattr(usage, "output_tokens", 0),
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )
        )

    def merge(self, other: UsageStats) -> None:
        """Merge another UsageStats into this one."""
        self.calls.extend(other.calls)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def estimated_cost(self) -> float:
        """Calculate estimated cost in USD based on per-model pricing.

        Anthropic's API returns input_tokens as non-cached input only,
        so each token category is billed independently at its own rate.
        """
        total = 0.0
        for c in self.calls:
            pricing = _MODEL_PRICING.get(c.model, _DEFAULT_PRICING)
            total += c.input_tokens * pricing["input"] / 1_000_000
            total += c.output_tokens * pricing["output"] / 1_000_000
            total += c.cache_creation_tokens * pricing["cache_write"] / 1_000_000
            total += c.cache_read_tokens * pricing["cache_read"] / 1_000_000
        return total


class EmailType(str, Enum):
    NEW_FORWARD = "new_forward"
    APPROVAL_REPLY = "approval_reply"


class ParsedEmail(BaseModel):
    email_type: EmailType
    sender_email: str
    subject: str
    # Fields for new forwards
    voting_url: str | None = None
    company_name: str | None = None
    platform_name: str | None = None
    auto_vote: bool = False
    # Fields for approval replies
    session_id: str | None = None


class BallotData(BaseModel):
    page_text: str
    document_urls: list[str]
    voting_url: str


class VotingDecision(BaseModel):
    proposal_number: str
    proposal_description: str
    vote: str  # "For", "Against", "Abstain", "Withhold", etc. — whatever the ballot offers
    reasoning: str
    policy_rationale: str
    board_recommendation: str
    aligned_with_board: bool
    # Derived from the ballot by Claude
    company_name: str = ""
    meeting_date: str = ""
    voting_deadline: str = ""


class SessionStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    VOTES_SUBMITTED = "votes_submitted"
    EXPIRED = "expired"
