import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from proxy_voter.models import (
    BallotData,
    EmailType,
    ParsedEmail,
    SessionStatus,
    UsageStats,
    VotingDecision,
)
from proxy_voter.webhook import (
    _handle_approval_reply,
    _handle_new_forward,
    _log_total_usage,
    _StageError,
)


def _make_parsed_email(**kwargs) -> ParsedEmail:
    defaults = {
        "email_type": EmailType.NEW_FORWARD,
        "sender_email": "user@example.com",
        "subject": "Fwd: Proxy Vote",
        "voting_url": "https://www.proxyvote.com/test",
        "company_name": "TEST CORP",
        "platform_name": "ProxyVote.com",
        "auto_vote": False,
    }
    defaults.update(kwargs)
    return ParsedEmail(**defaults)


def _make_decisions() -> list[VotingDecision]:
    return [
        VotingDecision(
            proposal_number="1",
            proposal_description="Approve financials",
            vote="For",
            reasoning="Standard approval.",
            policy_rationale="Routine governance.",
            board_recommendation="For",
            aligned_with_board=True,
        ),
    ]


def _make_metadata() -> dict:
    return {
        "company_name": "TEST CORP",
        "meeting_date": "April 15, 2026",
        "voting_deadline": "April 9, 2026",
        "shares_available": 100,
        "control_number": "12345",
        "cusip": "T12345",
    }


def _make_ballot_session():
    session = MagicMock()
    session.ballot = BallotData(
        page_text="Proposal 1: Approve\nBoard Recommendation: For",
        document_urls=[],
        voting_url="https://www.proxyvote.com/test",
    )
    session.page = MagicMock()
    session.page.goto = AsyncMock()
    session.page.wait_for_load_state = AsyncMock()
    session.page.wait_for_timeout = AsyncMock()
    session.close = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


class TestReceiveEmail:
    async def test_invalid_secret(self):
        from proxy_voter.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/webhook/email",
                content=b"raw email bytes",
                headers={"x-webhook-secret": "wrong-secret"},
            )
        assert resp.status_code == 401

    async def test_valid_secret_returns_200(self):
        from proxy_voter.main import app

        with patch("proxy_voter.webhook._process_email", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/webhook/email",
                    content=b"raw email bytes",
                    headers={"x-webhook-secret": "test-secret"},
                )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# _handle_new_forward
# ---------------------------------------------------------------------------


class TestHandleNewForward:
    async def test_no_voting_url_sends_error(self):
        parsed = _make_parsed_email(voting_url=None)
        with patch("proxy_voter.webhook.send_error_email") as mock_err:
            await _handle_new_forward(parsed, UsageStats())
        mock_err.assert_called_once()
        assert "No voting platform link" in mock_err.call_args[0][1]

    async def test_empty_page_text_sends_error(self):
        parsed = _make_parsed_email()
        session = _make_ballot_session()
        session.ballot.page_text = "   "

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch("proxy_voter.webhook.send_error_email") as mock_err,
        ):
            await _handle_new_forward(parsed, UsageStats())

        mock_err.assert_called_once()
        assert "empty" in mock_err.call_args[0][1].lower()
        session.close.assert_awaited_once()

    async def test_recommendation_flow(self):
        parsed = _make_parsed_email(auto_vote=False)
        session = _make_ballot_session()

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch(
                "proxy_voter.webhook.research_proposals",
                new_callable=AsyncMock,
                return_value=(_make_metadata(), _make_decisions(), UsageStats()),
            ),
            patch(
                "proxy_voter.webhook.create_session",
                new_callable=AsyncMock,
                return_value="PV-abc123",
            ),
            patch("proxy_voter.webhook.send_recommendations_email") as mock_send,
        ):
            await _handle_new_forward(parsed, UsageStats())

        mock_send.assert_called_once()
        assert mock_send.call_args[0][1] == "PV-abc123"
        session.close.assert_awaited_once()

    async def test_auto_vote_flow(self):
        parsed = _make_parsed_email(auto_vote=True)
        session = _make_ballot_session()

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch(
                "proxy_voter.webhook.research_proposals",
                new_callable=AsyncMock,
                return_value=(_make_metadata(), _make_decisions(), UsageStats()),
            ),
            patch(
                "proxy_voter.webhook.cast_votes",
                new_callable=AsyncMock,
                return_value=("Confirmed", UsageStats()),
            ) as mock_cast,
            patch(
                "proxy_voter.webhook.create_session",
                new_callable=AsyncMock,
                return_value="PV-abc123",
            ),
            patch(
                "proxy_voter.webhook.update_session_status",
                new_callable=AsyncMock,
            ) as mock_update,
            patch("proxy_voter.webhook.send_confirmation_email") as mock_confirm,
        ):
            await _handle_new_forward(parsed, UsageStats())

        mock_cast.assert_awaited_once()
        mock_update.assert_awaited_once_with("PV-abc123", SessionStatus.VOTES_SUBMITTED)
        mock_confirm.assert_called_once()
        session.close.assert_awaited_once()

    async def test_auto_vote_reloads_page(self):
        parsed = _make_parsed_email(auto_vote=True)
        session = _make_ballot_session()

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch(
                "proxy_voter.webhook.research_proposals",
                new_callable=AsyncMock,
                return_value=(_make_metadata(), _make_decisions(), UsageStats()),
            ),
            patch(
                "proxy_voter.webhook.cast_votes",
                new_callable=AsyncMock,
                return_value=("Confirmed", UsageStats()),
            ),
            patch(
                "proxy_voter.webhook.create_session",
                new_callable=AsyncMock,
                return_value="PV-x",
            ),
            patch("proxy_voter.webhook.update_session_status", new_callable=AsyncMock),
            patch("proxy_voter.webhook.send_confirmation_email"),
        ):
            await _handle_new_forward(parsed, UsageStats())

        session.page.goto.assert_awaited_once_with(
            "https://www.proxyvote.com/test",
            wait_until="domcontentloaded",
            timeout=60000,
        )

    async def test_closes_session_on_error(self):
        parsed = _make_parsed_email()
        session = _make_ballot_session()

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch(
                "proxy_voter.webhook.research_proposals",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API error"),
            ),
            pytest.raises(_StageError, match="proposal research"),
        ):
            await _handle_new_forward(parsed, UsageStats())

        session.close.assert_awaited_once()

    async def test_stage_error_has_context(self):
        parsed = _make_parsed_email()
        session = _make_ballot_session()

        with (
            patch("proxy_voter.webhook.open_ballot", new_callable=AsyncMock, return_value=session),
            patch(
                "proxy_voter.webhook.research_proposals",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API error"),
            ),
            pytest.raises(_StageError) as exc_info,
        ):
            await _handle_new_forward(parsed, UsageStats())

        assert exc_info.value.stage == "proposal research"
        assert exc_info.value.company_name == "TEST CORP"
        assert exc_info.value.voting_url == "https://www.proxyvote.com/test"
        assert isinstance(exc_info.value.__cause__, RuntimeError)


# ---------------------------------------------------------------------------
# _handle_approval_reply
# ---------------------------------------------------------------------------


class TestHandleApprovalReply:
    async def test_no_session_id(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id=None)
        with patch("proxy_voter.webhook.send_error_email") as mock_err:
            await _handle_approval_reply(parsed)
        assert "identify" in mock_err.call_args[0][1].lower()

    async def test_session_not_found(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id="PV-notreal")
        with (
            patch("proxy_voter.webhook.get_session", new_callable=AsyncMock, return_value=None),
            patch("proxy_voter.webhook.send_error_email") as mock_err,
        ):
            await _handle_approval_reply(parsed)
        assert "not found" in mock_err.call_args[0][1].lower()

    async def test_already_submitted(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id="PV-abc123")
        db_session = {"status": SessionStatus.VOTES_SUBMITTED.value}
        with (
            patch(
                "proxy_voter.webhook.get_session",
                new_callable=AsyncMock,
                return_value=db_session,
            ),
            patch("proxy_voter.webhook.send_error_email") as mock_err,
        ):
            await _handle_approval_reply(parsed)
        assert "already been submitted" in mock_err.call_args[0][1].lower()

    async def test_expired_session(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id="PV-abc123")
        db_session = {"status": SessionStatus.EXPIRED.value}
        with (
            patch(
                "proxy_voter.webhook.get_session",
                new_callable=AsyncMock,
                return_value=db_session,
            ),
            patch("proxy_voter.webhook.send_error_email") as mock_err,
        ):
            await _handle_approval_reply(parsed)
        assert "expired" in mock_err.call_args[0][1].lower()

    async def test_success(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id="PV-abc123")
        db_session = {
            "status": SessionStatus.PENDING_APPROVAL.value,
            "voting_url": "https://www.proxyvote.com/test",
            "voting_decisions": json.dumps([d.model_dump() for d in _make_decisions()]),
            "metadata": json.dumps(_make_metadata()),
        }

        ballot_session = _make_ballot_session()

        with (
            patch(
                "proxy_voter.webhook.get_session",
                new_callable=AsyncMock,
                return_value=db_session,
            ),
            patch(
                "proxy_voter.webhook.open_ballot",
                new_callable=AsyncMock,
                return_value=ballot_session,
            ),
            patch(
                "proxy_voter.webhook.cast_votes",
                new_callable=AsyncMock,
                return_value=("Confirmed", UsageStats()),
            ),
            patch(
                "proxy_voter.webhook.update_session_status",
                new_callable=AsyncMock,
            ) as mock_update,
            patch("proxy_voter.webhook.send_confirmation_email") as mock_confirm,
        ):
            await _handle_approval_reply(parsed)

        mock_update.assert_awaited_once_with("PV-abc123", SessionStatus.VOTES_SUBMITTED)
        mock_confirm.assert_called_once()
        ballot_session.close.assert_awaited_once()

    async def test_closes_session_on_error(self):
        parsed = _make_parsed_email(email_type=EmailType.APPROVAL_REPLY, session_id="PV-abc123")
        db_session = {
            "status": SessionStatus.PENDING_APPROVAL.value,
            "voting_url": "https://www.proxyvote.com/test",
            "voting_decisions": json.dumps([d.model_dump() for d in _make_decisions()]),
            "metadata": json.dumps(_make_metadata()),
        }
        ballot_session = _make_ballot_session()

        with (
            patch(
                "proxy_voter.webhook.get_session",
                new_callable=AsyncMock,
                return_value=db_session,
            ),
            patch(
                "proxy_voter.webhook.open_ballot",
                new_callable=AsyncMock,
                return_value=ballot_session,
            ),
            patch(
                "proxy_voter.webhook.cast_votes",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Vote failed"),
            ),
            pytest.raises(_StageError, match="vote casting"),
        ):
            await _handle_approval_reply(parsed)

        ballot_session.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# _log_total_usage
# ---------------------------------------------------------------------------


class TestLogTotalUsage:
    def test_logs_without_error(self):
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
        # Should not raise
        _log_total_usage(u)

    def test_empty_usage(self):
        _log_total_usage(UsageStats())
