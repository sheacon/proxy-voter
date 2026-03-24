import email
import email.policy
import logging
import re
from email.message import EmailMessage
from email.utils import parseaddr

import anthropic

from proxy_voter.config import get_settings
from proxy_voter.models import EmailType, ParsedEmail, UsageStats

logger = logging.getLogger(__name__)

SESSION_ID_PATTERN = re.compile(r"\[PV-([a-z0-9]+)\]")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")

EMAIL_EXTRACTION_PROMPT = """\
You are analyzing a forwarded proxy vote notification email. Your task is to identify:
1. The URL that leads to the online voting platform where the shareholder can cast their votes
2. The company name for which this proxy vote is being held
3. The name of the voting platform

Common voting platforms include ProxyVote.com, Broadridge InvestorVote, ISS VoteNow, and others.

## Email Subject
{subject}

## Email Body
{body_text}

## URLs Found in Email
{urls_text}

CRITICAL: The voting_url you return MUST be one of the URLs listed above. Do not invent or modify \
URLs.

Call the extract_voting_info tool with your findings."""

EMAIL_EXTRACTION_TOOL = {
    "name": "extract_voting_info",
    "description": "Extract the voting platform URL and company name from a proxy vote email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "voting_url": {
                "type": "string",
                "description": "The URL to the online voting platform. "
                "Must be one of the URLs provided in the URL list.",
            },
            "company_name": {
                "type": "string",
                "description": "The company name for which this proxy vote is being held.",
            },
            "platform_name": {
                "type": "string",
                "description": "The name of the voting platform "
                "(e.g., ProxyVote.com, Broadridge InvestorVote, ISS VoteNow).",
            },
        },
        "required": ["voting_url", "company_name"],
    },
}


async def parse_email(raw_bytes: bytes) -> tuple[ParsedEmail, UsageStats]:
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

    sender_email = _extract_sender(msg)
    subject = msg.get("Subject", "")

    # Classify: approval reply or new forward?
    session_match = SESSION_ID_PATTERN.search(subject)
    if session_match:
        parsed = _parse_approval_reply(msg, sender_email, subject, session_match.group(1))
        return parsed, UsageStats()

    return _parse_new_forward(msg, sender_email, subject)


def _extract_sender(msg: EmailMessage) -> str:
    _, addr = parseaddr(msg.get("From", ""))
    return addr.lower()


def _parse_approval_reply(
    msg: EmailMessage, sender_email: str, subject: str, session_id: str
) -> ParsedEmail:
    body_text = _get_text_body(msg).lower()
    if "approved" not in body_text:
        logger.warning("Approval reply from %s missing 'approved' in body", sender_email)

    return ParsedEmail(
        email_type=EmailType.APPROVAL_REPLY,
        sender_email=sender_email,
        subject=subject,
        session_id=f"PV-{session_id}",
    )


def _parse_new_forward(
    msg: EmailMessage, sender_email: str, subject: str
) -> tuple[ParsedEmail, UsageStats]:
    voting_url = None
    company_name = None
    platform_name = None
    usage = UsageStats()

    # Check for message/rfc822 attachment (Gmail "Forward as attachment")
    inner_msg = _find_attached_message(msg)
    source_msg = inner_msg if inner_msg else msg

    # Extract all URLs from the source message
    urls = _extract_all_urls(source_msg)

    # Also try the outer message if inner didn't have URLs
    if not urls and inner_msg:
        urls = _extract_all_urls(msg)

    # Get text content for Claude
    body_text = _get_text_body(source_msg)
    email_subject = source_msg.get("Subject", "") if inner_msg else subject

    if urls:
        voting_url, company_name, platform_name, call_usage = _identify_voting_url_and_company(
            email_subject, body_text, urls
        )
        usage.merge(call_usage)

    # Fall back to outer message if company not found from inner
    if not company_name and inner_msg:
        _, company_name, _, call_usage = _identify_voting_url_and_company(
            subject, _get_text_body(msg), urls
        )
        usage.merge(call_usage)

    # Detect auto-vote flag in the forwarder's own text
    outer_body = _get_text_body(msg)
    auto_vote = bool(re.search(r"\bauto-vote\b", outer_body, re.IGNORECASE))

    if not voting_url:
        logger.warning("No voting URL found in email from %s", sender_email)

    return ParsedEmail(
        email_type=EmailType.NEW_FORWARD,
        sender_email=sender_email,
        subject=subject,
        voting_url=voting_url,
        company_name=company_name,
        platform_name=platform_name,
        auto_vote=auto_vote,
    ), usage


def _find_attached_message(msg: EmailMessage) -> EmailMessage | None:
    for part in msg.walk():
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                return payload[0]
            if isinstance(payload, EmailMessage):
                return payload
    return None


def _extract_all_urls(msg: EmailMessage) -> list[str]:
    """Extract and deduplicate all URLs from an email's HTML and text bodies."""
    urls: list[str] = []
    seen: set[str] = set()

    for body in (_get_html_body(msg), _get_text_body(msg)):
        if body:
            for url in URL_PATTERN.findall(body):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)

    return urls


def _identify_voting_url_and_company(
    subject: str, body_text: str, urls: list[str]
) -> tuple[str | None, str | None, str | None, UsageStats]:
    """Use Claude to identify the voting URL and company from an email.

    Returns (voting_url, company_name, platform_name, usage_stats).
    """
    usage = UsageStats()
    if not urls:
        return None, None, None, usage

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    urls_text = "\n".join(f"- {url}" for url in urls)
    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": EMAIL_EXTRACTION_PROMPT.format(
                    subject=subject, body_text=body_text[:5000], urls_text=urls_text
                ),
            }
        ],
        tools=[EMAIL_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "extract_voting_info"},
    )
    usage.add(settings.claude_model, response.usage)
    logger.info(
        "Email parser API usage: in=%d, out=%d",
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "extract_voting_info":
            voting_url = block.input.get("voting_url")
            company_name = block.input.get("company_name")
            platform_name = block.input.get("platform_name")

            # Validate URL against actual extracted URLs
            if voting_url and voting_url not in urls:
                matched = [u for u in urls if u.startswith(voting_url) or voting_url.startswith(u)]
                if matched:
                    voting_url = matched[0]
                else:
                    logger.warning("Claude returned URL not found in email: %s", voting_url)
                    voting_url = None

            return voting_url, company_name, platform_name, usage

    return None, None, None, usage


def _get_text_body(msg: EmailMessage) -> str:
    try:
        body = msg.get_body(preferencelist=("plain",))
        if body:
            content = body.get_content()
            if isinstance(content, str):
                return content
    except Exception:
        pass

    # Fall back to walking parts
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            try:
                content = part.get_content()
                if isinstance(content, str):
                    return content
            except Exception:
                continue
    return ""


def _get_html_body(msg: EmailMessage) -> str:
    try:
        body = msg.get_body(preferencelist=("html",))
        if body:
            content = body.get_content()
            if isinstance(content, str):
                return content
    except Exception:
        pass

    for part in msg.walk():
        if part.get_content_type() == "text/html":
            try:
                content = part.get_content()
                if isinstance(content, str):
                    return content
            except Exception:
                continue
    return ""


def validate_sender(sender_email: str) -> bool:
    approved = get_settings().load_approved_senders()
    return sender_email.lower() in approved
