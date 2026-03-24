import asyncio
import json
import logging

from fastapi import APIRouter, Header, Request, Response

from proxy_voter.config import get_settings
from proxy_voter.email_parser import parse_email, validate_sender
from proxy_voter.models import EmailType, SessionStatus, UsageStats, VotingDecision
from proxy_voter.notifier import (
    send_confirmation_email,
    send_error_email,
    send_recommendations_email,
)
from proxy_voter.researcher import research_proposals
from proxy_voter.scraper import open_ballot
from proxy_voter.storage import create_session, get_session, update_session_status
from proxy_voter.voter import cast_votes

logger = logging.getLogger(__name__)

router = APIRouter()

# Serialize processing to avoid API rate limits
_lock = asyncio.Lock()


@router.post("/webhook/email")
async def receive_email(
    request: Request,
    x_webhook_secret: str = Header(...),
) -> Response:
    settings = get_settings()
    if x_webhook_secret != settings.webhook_secret:
        logger.warning("Invalid webhook secret")
        return Response(status_code=401, content="Unauthorized")

    raw_bytes = await request.body()
    logger.info("Received email webhook (%d bytes)", len(raw_bytes))

    try:
        async with _lock:
            await _process_email(raw_bytes)
    except Exception:
        logger.exception("Unhandled error in webhook")

    return Response(status_code=200, content="Processed")


async def _process_email(raw_bytes: bytes) -> None:
    parsed = None
    try:
        parsed, parse_usage = await parse_email(raw_bytes)
        logger.info(
            "Parsed email: type=%s sender=%s",
            parsed.email_type,
            parsed.sender_email,
        )

        if not validate_sender(parsed.sender_email):
            logger.warning("Rejected email from unapproved sender: %s", parsed.sender_email)
            send_error_email(
                parsed.sender_email,
                "Your email address is not authorized to use this service.",
                "Contact the administrator to add your email to the approved senders list.",
            )
            return

        if parsed.email_type == EmailType.NEW_FORWARD:
            await _handle_new_forward(parsed, parse_usage)
        elif parsed.email_type == EmailType.APPROVAL_REPLY:
            await _handle_approval_reply(parsed)

    except Exception:
        logger.exception("Error processing email")
        if parsed and parsed.sender_email:
            try:
                send_error_email(
                    parsed.sender_email,
                    "An unexpected error occurred while processing your proxy vote email.",
                    "Please try forwarding the email again. If the problem persists, "
                    "you may need to vote manually via the voting link in the original email.",
                )
            except Exception:
                logger.exception("Failed to send error email")


async def _handle_new_forward(parsed, parse_usage: UsageStats) -> None:
    usage = UsageStats()
    usage.merge(parse_usage)

    if not parsed.voting_url:
        send_error_email(
            parsed.sender_email,
            "No voting platform link was found in the forwarded email.",
            "Make sure you're forwarding a proxy vote notification email from your broker.",
        )
        return

    logger.info("Opening ballot from %s", parsed.voting_url[:80])
    session = await open_ballot(parsed.voting_url)

    try:
        if not session.ballot.page_text.strip():
            send_error_email(
                parsed.sender_email,
                "The voting page appears to be empty. The link may have expired.",
                f"Company: {parsed.company_name or 'Unknown'}",
            )
            return

        logger.info("Researching proposals...")
        metadata, decisions, research_usage = await research_proposals(session.ballot)
        usage.merge(research_usage)
        company_name = metadata.get("company_name", parsed.company_name or "Unknown")

        logger.info("Research complete: %s — %d decisions", company_name, len(decisions))

        if parsed.auto_vote:
            logger.info("Auto-vote enabled, casting votes immediately")
            # Reload the ballot page — the voting session likely expired
            # during the research phase (can take several minutes)
            await session.page.goto(parsed.voting_url, wait_until="domcontentloaded", timeout=60000)
            try:
                await session.page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                logger.warning("Timed out waiting for page reload")
            await session.page.wait_for_timeout(2000)
            _, voter_usage = await cast_votes(session.page, decisions)
            usage.merge(voter_usage)

            session_id = await create_session(
                sender_email=parsed.sender_email,
                company_name=company_name,
                voting_url=parsed.voting_url,
                ballot_data=session.ballot,
                voting_decisions=decisions,
                metadata=metadata,
            )
            await update_session_status(session_id, SessionStatus.VOTES_SUBMITTED)

            _log_total_usage(usage)
            send_confirmation_email(parsed.sender_email, session_id, metadata, decisions, usage)
        else:
            session_id = await create_session(
                sender_email=parsed.sender_email,
                company_name=company_name,
                voting_url=parsed.voting_url,
                ballot_data=session.ballot,
                voting_decisions=decisions,
                metadata=metadata,
            )

            _log_total_usage(usage)
            send_recommendations_email(parsed.sender_email, session_id, metadata, decisions, usage)
            logger.info("Sent recommendations for session %s, awaiting approval", session_id)
    finally:
        await session.close()


async def _handle_approval_reply(parsed) -> None:
    usage = UsageStats()

    if not parsed.session_id:
        send_error_email(
            parsed.sender_email,
            "Could not identify which voting session to approve.",
            "Please reply to the original recommendations email.",
        )
        return

    db_session = await get_session(parsed.session_id)
    if not db_session:
        send_error_email(
            parsed.sender_email,
            f"Voting session {parsed.session_id} was not found.",
            "The session may have expired or been deleted.",
        )
        return

    status = db_session["status"]
    if status == SessionStatus.VOTES_SUBMITTED.value:
        send_error_email(
            parsed.sender_email,
            f"Votes for session {parsed.session_id} have already been submitted.",
        )
        return

    if status == SessionStatus.EXPIRED.value:
        send_error_email(
            parsed.sender_email,
            f"Session {parsed.session_id} has expired. The voting deadline may have passed.",
        )
        return

    decisions = [
        VotingDecision.model_validate(d) for d in json.loads(db_session["voting_decisions"])
    ]
    metadata = json.loads(db_session["metadata"])

    # Open a fresh browser session to the ballot page for voting
    logger.info("Approval received for session %s, opening ballot to cast votes", parsed.session_id)
    ballot_session = await open_ballot(db_session["voting_url"])

    try:
        _, voter_usage = await cast_votes(ballot_session.page, decisions)
        usage.merge(voter_usage)
        await update_session_status(parsed.session_id, SessionStatus.VOTES_SUBMITTED)

        _log_total_usage(usage)
        send_confirmation_email(parsed.sender_email, parsed.session_id, metadata, decisions, usage)
        logger.info("Votes submitted for session %s", parsed.session_id)
    finally:
        await ballot_session.close()


def _log_total_usage(usage: UsageStats) -> None:
    logger.info(
        "Pipeline total: %d input tokens, %d output tokens, est. cost $%.4f",
        usage.total_input_tokens,
        usage.total_output_tokens,
        usage.estimated_cost,
    )
