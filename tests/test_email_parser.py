import email
import email.policy
from pathlib import Path

import pytest

from proxy_voter.email_parser import (
    _extract_company_name,
    _extract_proxyvote_url,
    parse_email,
    validate_sender,
)
from proxy_voter.models import EmailType

FIXTURES_DIR = Path(__file__).parent.parent / "example-files"
_has_fixtures = FIXTURES_DIR.is_dir() and any(FIXTURES_DIR.glob("*.eml"))
requires_fixtures = pytest.mark.skipif(not _has_fixtures, reason="example-files/ not present")


def _load_eml(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


class TestExtractCompanyName:
    def test_standard_subject(self) -> None:
        assert _extract_company_name("Vote now! UBS GROUP AG Annual Meeting") == "UBS GROUP AG"

    def test_enbridge(self) -> None:
        assert _extract_company_name("Vote now! ENBRIDGE INC. Annual Meeting") == "ENBRIDGE INC."

    def test_ge_aerospace(self) -> None:
        assert _extract_company_name("Vote now! GE AEROSPACE Annual Meeting") == "GE AEROSPACE"

    def test_no_match(self) -> None:
        assert _extract_company_name("Some other subject") is None

    def test_forwarded_subject(self) -> None:
        assert _extract_company_name("Fwd: Vote now! NESTLE S.A. Annual Meeting") == "NESTLE S.A."


@requires_fixtures
class TestExtractProxyVoteUrl:
    def test_example_email(self) -> None:
        raw = _load_eml("example-proxy-email.eml")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        url = _extract_proxyvote_url(msg)
        assert url is not None
        assert url.startswith("https://www.proxyvote.com/0")

    def test_all_example_emails(self) -> None:
        for name in [
            "example-proxy-email.eml",
            "example-proxy-email-1.eml",
            "example-proxy-email-2.eml",
            "example-proxy-email-3.eml",
            "example-proxy-email-4.eml",
        ]:
            raw = _load_eml(name)
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            url = _extract_proxyvote_url(msg)
            assert url is not None, f"No URL found in {name}"
            assert url.startswith("https://www.proxyvote.com/"), f"Bad URL in {name}: {url}"


@requires_fixtures
class TestParseDirectEmail:
    """Test parsing the raw proxy emails (not forwarded yet)."""

    def test_parse_ubs_email(self) -> None:
        raw = _load_eml("example-proxy-email.eml")
        parsed = parse_email(raw)
        assert parsed.email_type == EmailType.NEW_FORWARD
        assert parsed.sender_email == "id@proxyvote.com"
        assert parsed.proxyvote_url is not None
        assert parsed.proxyvote_url.startswith("https://www.proxyvote.com/0")
        assert parsed.company_name == "UBS GROUP AG"
        assert parsed.auto_vote is False

    def test_parse_enbridge_email(self) -> None:
        raw = _load_eml("example-proxy-email-1.eml")
        parsed = parse_email(raw)
        assert parsed.company_name == "ENBRIDGE INC."
        assert parsed.proxyvote_url is not None

    def test_parse_nestle_email(self) -> None:
        raw = _load_eml("example-proxy-email-2.eml")
        parsed = parse_email(raw)
        assert parsed.company_name == "NESTLE S.A."
        assert parsed.proxyvote_url is not None

    def test_parse_ups_email(self) -> None:
        raw = _load_eml("example-proxy-email-3.eml")
        parsed = parse_email(raw)
        assert parsed.company_name == "UNITED PARCEL SERVICE, INC."
        assert parsed.proxyvote_url is not None

    def test_parse_ge_email(self) -> None:
        raw = _load_eml("example-proxy-email-4.eml")
        parsed = parse_email(raw)
        assert parsed.company_name == "GE AEROSPACE"
        assert parsed.proxyvote_url is not None


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

    def test_inline_forward_extracts_url(self) -> None:
        raw = self._make_inline_forward()
        parsed = parse_email(raw)
        assert parsed.email_type == EmailType.NEW_FORWARD
        assert parsed.sender_email == "user@example.com"
        assert parsed.proxyvote_url is not None
        assert parsed.proxyvote_url.startswith("https://www.proxyvote.com/")
        assert parsed.company_name == "UBS GROUP AG"

    def test_inline_forward_auto_vote(self) -> None:
        raw = self._make_inline_forward(user_text="auto-vote")
        parsed = parse_email(raw)
        assert parsed.auto_vote is True

    def test_inline_forward_auto_vote_case_insensitive(self) -> None:
        raw = self._make_inline_forward(user_text="Please Auto-Vote this one")
        parsed = parse_email(raw)
        assert parsed.auto_vote is True

    def test_inline_forward_no_flag(self) -> None:
        raw = self._make_inline_forward(user_text="Please handle this proxy vote")
        parsed = parse_email(raw)
        assert parsed.auto_vote is False

    def test_inline_forward_different_emails(self) -> None:
        for eml_name, expected_company in [
            ("example-proxy-email-1.eml", "ENBRIDGE INC."),
            ("example-proxy-email-2.eml", "NESTLE S.A."),
            ("example-proxy-email-3.eml", "UNITED PARCEL SERVICE, INC."),
            ("example-proxy-email-4.eml", "GE AEROSPACE"),
        ]:
            raw = self._make_inline_forward(inner_eml_name=eml_name)
            parsed = parse_email(raw)
            assert parsed.proxyvote_url is not None, f"No URL for {eml_name}"
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

    def test_approval_reply(self) -> None:
        raw = self._make_approval_reply()
        parsed = parse_email(raw)
        assert parsed.email_type == EmailType.APPROVAL_REPLY
        assert parsed.session_id == "PV-abc123"
        assert parsed.sender_email == "user@example.com"

    def test_approval_with_extra_text(self) -> None:
        raw = self._make_approval_reply(body="Looks good, approved!\n\nThanks")
        parsed = parse_email(raw)
        assert parsed.email_type == EmailType.APPROVAL_REPLY
        assert parsed.session_id == "PV-abc123"

    def test_different_session_id(self) -> None:
        raw = self._make_approval_reply(session_id="PV-xyz789")
        parsed = parse_email(raw)
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
