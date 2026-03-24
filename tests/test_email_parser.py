import email
import email.policy
from pathlib import Path
from unittest.mock import patch

import pytest

from proxy_voter.email_parser import (
    _extract_all_urls,
    parse_email,
    validate_sender,
)
from proxy_voter.models import EmailType, UsageStats

FIXTURES_DIR = Path(__file__).parent.parent / "example-files"
_has_fixtures = FIXTURES_DIR.is_dir() and any(FIXTURES_DIR.glob("*.eml"))
requires_fixtures = pytest.mark.skipif(not _has_fixtures, reason="example-files/ not present")


def _load_eml(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


def _mock_identify(voting_url: str, company_name: str, platform_name: str = "ProxyVote.com"):
    """Return a patch context manager that mocks _identify_voting_url_and_company."""
    return patch(
        "proxy_voter.email_parser._identify_voting_url_and_company",
        return_value=(voting_url, company_name, platform_name, UsageStats()),
    )


class TestExtractAllUrls:
    def test_extracts_urls_from_html(self) -> None:
        msg = email.message.EmailMessage()
        msg["From"] = "test@example.com"
        msg["Subject"] = "Test"
        msg.set_content("plain text")
        msg.add_alternative(
            '<a href="https://www.proxyvote.com/abc123">Vote</a> '
            '<a href="https://example.com/doc">Doc</a>',
            subtype="html",
        )
        urls = _extract_all_urls(msg)
        assert "https://www.proxyvote.com/abc123" in urls
        assert "https://example.com/doc" in urls

    def test_extracts_urls_from_text(self) -> None:
        msg = email.message.EmailMessage()
        msg["From"] = "test@example.com"
        msg.set_content("Visit https://investorvote.com/ballot/123 to vote")
        urls = _extract_all_urls(msg)
        assert "https://investorvote.com/ballot/123" in urls

    def test_deduplicates_urls(self) -> None:
        msg = email.message.EmailMessage()
        msg["From"] = "test@example.com"
        msg.set_content("https://example.com/a https://example.com/a")
        urls = _extract_all_urls(msg)
        assert urls.count("https://example.com/a") == 1

    def test_empty_message(self) -> None:
        msg = email.message.EmailMessage()
        msg["From"] = "test@example.com"
        msg.set_content("")
        urls = _extract_all_urls(msg)
        assert urls == []


@requires_fixtures
class TestParseDirectEmail:
    """Test parsing the raw proxy emails (not forwarded yet)."""

    async def test_parse_ubs_email(self) -> None:
        raw = _load_eml("example-proxy-email.eml")
        with _mock_identify("https://www.proxyvote.com/0abc", "UBS GROUP AG", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.email_type == EmailType.NEW_FORWARD
        assert parsed.sender_email == "id@proxyvote.com"
        assert parsed.voting_url == "https://www.proxyvote.com/0abc"
        assert parsed.company_name == "UBS GROUP AG"
        assert parsed.auto_vote is False

    async def test_parse_enbridge_email(self) -> None:
        raw = _load_eml("example-proxy-email-1.eml")
        with _mock_identify("https://www.proxyvote.com/0def", "ENBRIDGE INC.", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.company_name == "ENBRIDGE INC."
        assert parsed.voting_url is not None

    async def test_parse_nestle_email(self) -> None:
        raw = _load_eml("example-proxy-email-2.eml")
        with _mock_identify("https://www.proxyvote.com/0ghi", "NESTLE S.A.", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.company_name == "NESTLE S.A."
        assert parsed.voting_url is not None

    async def test_parse_ups_email(self) -> None:
        raw = _load_eml("example-proxy-email-3.eml")
        with _mock_identify(
            "https://www.proxyvote.com/0jkl",
            "UNITED PARCEL SERVICE, INC.",
            "ProxyVote.com",
        ):
            parsed, _ = await parse_email(raw)
        assert parsed.company_name == "UNITED PARCEL SERVICE, INC."
        assert parsed.voting_url is not None

    async def test_parse_ge_email(self) -> None:
        raw = _load_eml("example-proxy-email-4.eml")
        with _mock_identify("https://www.proxyvote.com/0mno", "GE AEROSPACE", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.company_name == "GE AEROSPACE"
        assert parsed.voting_url is not None


@requires_fixtures
class TestParseForwardedEmail:
    """Test parsing simulated Gmail-forwarded emails."""

    def _make_inline_forward(
        self,
        from_addr: str = "user@example.com",
        inner_eml_name: str = "example-proxy-email.eml",
        user_text: str = "",
    ) -> bytes:
        """Simulate Gmail inline forward."""
        inner_raw = _load_eml(inner_eml_name)
        inner_msg = email.message_from_bytes(inner_raw, policy=email.policy.default)
        inner_subject = inner_msg.get("Subject", "")
        inner_from = inner_msg.get("From", "")

        # Get original HTML body
        html_body = ""
        for part in inner_msg.walk():
            if part.get_content_type() == "text/html":
                html_body = part.get_content()
                break

        forwarded_html = f"""<div>{user_text}</div>
<br>
<div>---------- Forwarded message ----------</div>
<div>From: {inner_from}</div>
<div>Subject: {inner_subject}</div>
<br>
{html_body}"""

        outer = email.message.EmailMessage()
        outer["From"] = from_addr
        outer["To"] = "proxy-voter@example.com"
        outer["Subject"] = f"Fwd: {inner_subject}"
        outer.set_content(user_text or "See forwarded email below.")
        outer.add_alternative(forwarded_html, subtype="html")
        return outer.as_bytes()

    async def test_inline_forward_extracts_url(self) -> None:
        raw = self._make_inline_forward()
        with _mock_identify("https://www.proxyvote.com/0abc", "UBS GROUP AG", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.email_type == EmailType.NEW_FORWARD
        assert parsed.sender_email == "user@example.com"
        assert parsed.voting_url is not None
        assert parsed.company_name == "UBS GROUP AG"

    async def test_inline_forward_auto_vote(self) -> None:
        raw = self._make_inline_forward(user_text="auto-vote")
        with _mock_identify("https://www.proxyvote.com/0abc", "UBS GROUP AG", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.auto_vote is True

    async def test_inline_forward_auto_vote_case_insensitive(self) -> None:
        raw = self._make_inline_forward(user_text="Please Auto-Vote this one")
        with _mock_identify("https://www.proxyvote.com/0abc", "UBS GROUP AG", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.auto_vote is True

    async def test_inline_forward_no_flag(self) -> None:
        raw = self._make_inline_forward(user_text="Please handle this proxy vote")
        with _mock_identify("https://www.proxyvote.com/0abc", "UBS GROUP AG", "ProxyVote.com"):
            parsed, _ = await parse_email(raw)
        assert parsed.auto_vote is False

    async def test_inline_forward_different_emails(self) -> None:
        cases = [
            ("example-proxy-email-1.eml", "ENBRIDGE INC."),
            ("example-proxy-email-2.eml", "NESTLE S.A."),
            ("example-proxy-email-3.eml", "UNITED PARCEL SERVICE, INC."),
            ("example-proxy-email-4.eml", "GE AEROSPACE"),
        ]
        for eml_name, expected_company in cases:
            raw = self._make_inline_forward(inner_eml_name=eml_name)
            with _mock_identify(
                "https://www.proxyvote.com/0test", expected_company, "ProxyVote.com"
            ):
                parsed, _ = await parse_email(raw)
            assert parsed.voting_url is not None, f"No URL for {eml_name}"
            assert parsed.company_name == expected_company, f"Bad company for {eml_name}"


class TestParseApprovalReply:
    def _make_approval_reply(
        self,
        session_id: str = "PV-abc123",
        body: str = "approved",
        from_addr: str = "user@example.com",
    ) -> bytes:
        msg = email.message.EmailMessage()
        msg["From"] = from_addr
        msg["To"] = "proxy-voter@example.com"
        msg["Subject"] = f"Re: [{session_id}] Proxy Vote Recommendations: UBS GROUP AG"
        msg.set_content(body)
        return msg.as_bytes()

    async def test_approval_reply(self) -> None:
        raw = self._make_approval_reply()
        parsed, _ = await parse_email(raw)
        assert parsed.email_type == EmailType.APPROVAL_REPLY
        assert parsed.session_id == "PV-abc123"
        assert parsed.sender_email == "user@example.com"

    async def test_approval_with_extra_text(self) -> None:
        raw = self._make_approval_reply(body="Looks good, approved!\n\nThanks")
        parsed, _ = await parse_email(raw)
        assert parsed.email_type == EmailType.APPROVAL_REPLY
        assert parsed.session_id == "PV-abc123"

    async def test_different_session_id(self) -> None:
        raw = self._make_approval_reply(session_id="PV-xyz789")
        parsed, _ = await parse_email(raw)
        assert parsed.session_id == "PV-xyz789"


class TestValidateSender:
    def test_approved_sender(self) -> None:
        assert validate_sender("user@example.com") is True

    def test_approved_sender_case_insensitive(self) -> None:
        assert validate_sender("USER@EXAMPLE.COM") is True

    def test_unapproved_sender(self) -> None:
        assert validate_sender("hacker@evil.com") is False

    def test_other_approved_sender(self) -> None:
        assert validate_sender("user2@example.com") is True
