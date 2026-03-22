from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class EmailType(str, Enum):
    NEW_FORWARD = "new_forward"
    APPROVAL_REPLY = "approval_reply"


class ParsedEmail(BaseModel):
    email_type: EmailType
    sender_email: str
    subject: str
    # Fields for new forwards
    proxyvote_url: str | None = None
    company_name: str | None = None
    auto_vote: bool = False
    # Fields for approval replies
    session_id: str | None = None


class BallotData(BaseModel):
    page_text: str
    document_urls: list[str]
    proxyvote_url: str


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
