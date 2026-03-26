from types import SimpleNamespace
from unittest.mock import patch

from proxy_voter.models import UsageStats, VotingDecision
from proxy_voter.notifier import (
    _build_results_html,
    _build_usage_line,
    _vote_class,
    send_confirmation_email,
    send_error_email,
    send_recommendations_email,
)


def _make_metadata() -> dict:
    return {
        "company_name": "TEST CORP",
        "meeting_date": "April 15, 2026",
        "voting_deadline": "April 9, 2026",
        "shares_available": 100,
        "control_number": "1234567890",
        "cusip": "T12345",
    }


def _make_decisions() -> list[VotingDecision]:
    return [
        VotingDecision(
            proposal_number="1",
            proposal_description="Approve financials",
            vote="For",
            reasoning="Standard approval of audited financials.",
            policy_rationale="Routine governance.",
            board_recommendation="For",
            aligned_with_board=True,
        ),
        VotingDecision(
            proposal_number="2",
            proposal_description="Executive compensation",
            vote="Against",
            reasoning="Compensation exceeds peers.",
            policy_rationale="Opposes excessive pay.",
            board_recommendation="For",
            aligned_with_board=False,
        ),
    ]


# ---------------------------------------------------------------------------
# _vote_class (pure function)
# ---------------------------------------------------------------------------


class TestVoteClass:
    def test_for(self):
        assert _vote_class("For") == "vote-for"

    def test_against(self):
        assert _vote_class("Against") == "vote-against"

    def test_abstain(self):
        assert _vote_class("Abstain") == "vote-abstain"

    def test_withhold(self):
        assert _vote_class("Withhold") == "vote-withhold"

    def test_one_year(self):
        assert _vote_class("1 Year") == "vote-1-year"


# ---------------------------------------------------------------------------
# _build_usage_line
# ---------------------------------------------------------------------------


class TestBuildUsageLine:
    def test_with_stats(self):
        u = UsageStats()
        u.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=45230,
                output_tokens=3120,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        result = _build_usage_line(u)
        assert "45,230 input tokens" in result
        assert "3,120 output tokens" in result
        assert "$" in result

    def test_none(self):
        assert _build_usage_line(None) == ""

    def test_empty_stats(self):
        assert _build_usage_line(UsageStats()) == ""


# ---------------------------------------------------------------------------
# _build_results_html
# ---------------------------------------------------------------------------


class TestBuildResultsHtml:
    def test_submitted_true(self):
        html = _build_results_html(
            _make_metadata(), _make_decisions(), submitted=True, session_id="PV-abc123"
        )
        assert "VOTES SUBMITTED" in html
        assert "approved" not in html  # No approval CTA

    def test_submitted_false(self):
        html = _build_results_html(
            _make_metadata(), _make_decisions(), submitted=False, session_id="PV-abc123"
        )
        assert "RECOMMENDATIONS" in html
        assert "approved" in html  # Has approval CTA

    def test_renders_all_proposals(self):
        decisions = _make_decisions()
        html = _build_results_html(
            _make_metadata(), decisions, submitted=True, session_id="PV-abc123"
        )
        assert "Approve financials" in html
        assert "Executive compensation" in html

    def test_aligned_vs_divergent_rows(self):
        decisions = _make_decisions()
        html = _build_results_html(
            _make_metadata(), decisions, submitted=True, session_id="PV-abc123"
        )
        assert 'class="aligned"' in html
        assert 'class="divergent"' in html

    def test_metadata_fields_present(self):
        html = _build_results_html(
            _make_metadata(), _make_decisions(), submitted=True, session_id="PV-abc123"
        )
        assert "TEST CORP" in html
        assert "April 15, 2026" in html
        assert "April 9, 2026" in html
        assert "100" in html
        assert "1234567890" in html
        assert "T12345" in html
        assert "PV-abc123" in html

    def test_usage_in_footer(self):
        u = UsageStats()
        u.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=1000,
                output_tokens=500,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        html = _build_results_html(
            _make_metadata(), _make_decisions(), submitted=True, session_id="PV-x", usage=u
        )
        assert "API usage:" in html
        assert "1,000 input tokens" in html

    def test_no_usage_in_footer(self):
        html = _build_results_html(
            _make_metadata(), _make_decisions(), submitted=True, session_id="PV-x"
        )
        assert "API usage:" not in html


# ---------------------------------------------------------------------------
# send_* functions (mocked Resend)
# ---------------------------------------------------------------------------


class TestSendRecommendationsEmail:
    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_calls_resend(self, mock_send):
        send_recommendations_email(
            "user@example.com", "PV-abc123", _make_metadata(), _make_decisions()
        )
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["to"] == ["user@example.com"]
        assert "[PV-abc123]" in call_args["subject"]
        assert "Recommendations" in call_args["subject"]
        assert "TEST CORP" in call_args["subject"]

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_includes_usage(self, mock_send):
        u = UsageStats()
        u.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=1000,
                output_tokens=500,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        send_recommendations_email(
            "user@example.com", "PV-abc123", _make_metadata(), _make_decisions(), usage=u
        )
        html = mock_send.call_args[0][0]["html"]
        assert "API usage:" in html


class TestSendConfirmationEmail:
    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_calls_resend(self, mock_send):
        send_confirmation_email(
            "user@example.com", "PV-abc123", _make_metadata(), _make_decisions()
        )
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Votes Submitted" in call_args["subject"]
        assert "[PV-abc123]" in call_args["subject"]


class TestSendErrorEmail:
    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_calls_resend(self, mock_send):
        send_error_email("user@example.com", "Something went wrong")
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert call_args["subject"] == "Proxy Vote Error"
        assert "Something went wrong" in call_args["html"]

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_with_context(self, mock_send):
        send_error_email("user@example.com", "Error", "Extra context here")
        html = mock_send.call_args[0][0]["html"]
        assert "Extra context here" in html

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_without_context(self, mock_send):
        send_error_email("user@example.com", "Error", "")
        html = mock_send.call_args[0][0]["html"]
        # No extra context paragraph
        assert "Extra context" not in html

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_with_diagnostic_info(self, mock_send):
        send_error_email(
            "user@example.com",
            "Research failed",
            session_id="PV-abc123",
            company_name="ACME Corp",
            stage="proposal research",
            voting_url="https://www.proxyvote.com/test",
            error_type="ValueError",
        )
        call_args = mock_send.call_args[0][0]
        assert "[PV-abc123]" in call_args["subject"]
        assert "ACME Corp" in call_args["subject"]
        html = call_args["html"]
        assert "PV-abc123" in html
        assert "ACME Corp" in html
        assert "proposal research" in html
        assert "ValueError" in html
        assert "https://www.proxyvote.com/test" in html

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_subject_without_company(self, mock_send):
        send_error_email(
            "user@example.com",
            "Error",
            session_id="PV-abc123",
        )
        subject = mock_send.call_args[0][0]["subject"]
        assert subject == "[PV-abc123] Proxy Vote Error"

    @patch("proxy_voter.notifier.resend.Emails.send")
    def test_subject_with_company_no_session(self, mock_send):
        send_error_email(
            "user@example.com",
            "Error",
            company_name="ACME Corp",
        )
        subject = mock_send.call_args[0][0]["subject"]
        assert "ACME Corp" in subject
