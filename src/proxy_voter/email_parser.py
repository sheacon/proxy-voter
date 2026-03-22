import email
import email.policy
import logging
import re
from email.message import EmailMessage
from email.utils import parseaddr

from proxy_voter.config import get_settings
from proxy_voter.models import EmailType, ParsedEmail

logger = logging.getLogger(__name__)

PROXYVOTE_URL_PATTERN = re.compile(r"https://www\.proxyvote\.com/[A-Za-z0-9_\-]+")
SESSION_ID_PATTERN = re.compile(r"\[PV-([a-z0-9]+)\]")
COMPANY_FROM_SUBJECT = re.compile(r"Vote now!\s+(.+?)\s+Annual Meeting", re.IGNORECASE)


def parse_email(raw_bytes: bytes) -> ParsedEmail:
    msg = email.message_from_bytes(raw_bytes, policy=email.policy.default)

    sender_email = _extract_sender(msg)
    subject = msg.get("Subject", "")

    # Classify: approval reply or new forward?
    session_match = SESSION_ID_PATTERN.search(subject)
    if session_match:
        return _parse_approval_reply(msg, sender_email, subject, session_match.group(1))

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


def _parse_new_forward(msg: EmailMessage, sender_email: str, subject: str) -> ParsedEmail:
    # Try to find the original proxy email — either as attachment or inline
    proxyvote_url = None
    company_name = None

    # Check for message/rfc822 attachment (Gmail "Forward as attachment")
    inner_msg = _find_attached_message(msg)
    if inner_msg:
        proxyvote_url = _extract_proxyvote_url(inner_msg)
        company_name = _extract_company_name(inner_msg.get("Subject", ""))

    # Fall back to searching the body of the outer message (Gmail inline forward)
    if not proxyvote_url:
        proxyvote_url = _extract_proxyvote_url(msg)

    if not company_name:
        company_name = _extract_company_name(subject)

    # Detect auto-vote flag in the forwarder's own text
    outer_body = _get_text_body(msg)
    auto_vote = bool(re.search(r"\bauto-vote\b", outer_body, re.IGNORECASE))

    if not proxyvote_url:
        logger.warning("No ProxyVote URL found in email from %s", sender_email)

    return ParsedEmail(
        email_type=EmailType.NEW_FORWARD,
        sender_email=sender_email,
        subject=subject,
        proxyvote_url=proxyvote_url,
        company_name=company_name,
        auto_vote=auto_vote,
    )


def _find_attached_message(msg: EmailMessage) -> EmailMessage | None:
    for part in msg.walk():
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                return payload[0]
            if isinstance(payload, EmailMessage):
                return payload
    return None


def _extract_proxyvote_url(msg: EmailMessage) -> str | None:
    html_body = _get_html_body(msg)
    if html_body:
        urls = PROXYVOTE_URL_PATTERN.findall(html_body)
        if urls:
            return urls[0]

    text_body = _get_text_body(msg)
    if text_body:
        urls = PROXYVOTE_URL_PATTERN.findall(text_body)
        if urls:
            return urls[0]

    return None


def _extract_company_name(subject: str) -> str | None:
    match = COMPANY_FROM_SUBJECT.search(subject)
    if match:
        return match.group(1).strip()
    return None


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
