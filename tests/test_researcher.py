from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from proxy_voter.models import BallotData
from proxy_voter.researcher import (
    _clean_ballot_text,
    _format_usage,
    _parse_results,
    research_proposals,
)

# ---------------------------------------------------------------------------
# _clean_ballot_text (pure function)
# ---------------------------------------------------------------------------


class TestCleanBallotText:
    def test_removes_cookie_boilerplate(self):
        text = "Proposal 1: Approve\nCookie Policy\nProposal 2: Elect"
        result = _clean_ballot_text(text)
        assert "Cookie Policy" not in result
        assert "Proposal 1" in result
        assert "Proposal 2" in result

    def test_removes_privacy_lines(self):
        text = "Vote For\nPrivacy Policy | Terms of Use\nVote Against"
        result = _clean_ballot_text(text)
        assert "Privacy Policy" not in result

    def test_removes_copyright(self):
        text = "Proposals\nCopyright © 2025 ProxyVote Inc.\nEnd"
        result = _clean_ballot_text(text)
        assert "Copyright" not in result

    def test_removes_all_rights_reserved(self):
        text = "Proposal 1\nAll Rights Reserved\nProposal 2"
        result = _clean_ballot_text(text)
        assert "All Rights Reserved" not in result

    def test_removes_powered_by(self):
        text = "Proposals\nPowered by Broadridge\nEnd"
        result = _clean_ballot_text(text)
        assert "Powered by" not in result

    def test_removes_accept_reject_buttons(self):
        text = "Proposals\nAccept\nReject All\nManage Cookies\nVote For"
        result = _clean_ballot_text(text)
        assert "Accept" not in result
        assert "Reject All" not in result
        assert "Manage Cookies" not in result
        assert "Vote For" in result

    def test_removes_separator_lines(self):
        text = "Section 1\n----\n====\n****\nSection 2"
        result = _clean_ballot_text(text)
        assert "----" not in result
        assert "====" not in result

    def test_removes_bare_urls(self):
        text = "See details\nhttps://example.com/doc.pdf\nProposal 1"
        result = _clean_ballot_text(text)
        assert "https://example.com" not in result
        assert "Proposal 1" in result

    def test_collapses_blank_lines(self):
        text = "A\n\n\n\n\nB"
        result = _clean_ballot_text(text)
        assert "\n\n\n" not in result
        assert "A" in result
        assert "B" in result

    def test_preserves_proposal_content(self):
        text = (
            "Proposal 1: Election of Directors\n"
            "Board Recommendation: FOR\n"
            "Proposal 2: Ratification of Auditor\n"
            "Board Recommendation: FOR"
        )
        result = _clean_ballot_text(text)
        assert result == text

    def test_empty_input(self):
        assert _clean_ballot_text("") == ""

    def test_case_insensitive(self):
        text = "Proposals\ncookie preferences\nPRIVACY NOTICE\nEnd"
        result = _clean_ballot_text(text)
        assert "cookie" not in result.lower()
        assert "privacy" not in result.lower()


# ---------------------------------------------------------------------------
# _parse_results (pure function)
# ---------------------------------------------------------------------------


class TestParseResults:
    def test_full_input(self):
        tool_input = {
            "company_name": "TEST CORP",
            "meeting_date": "April 15, 2026",
            "voting_deadline": "April 9, 2026",
            "shares_available": 100,
            "control_number": "12345",
            "cusip": "T12345",
            "decisions": [
                {
                    "proposal_number": "1",
                    "proposal_description": "Elect directors",
                    "vote": "For",
                    "reasoning": "Standard election",
                    "policy_rationale": "Aligns with governance",
                    "board_recommendation": "For",
                    "aligned_with_board": True,
                },
            ],
        }
        metadata, decisions = _parse_results(tool_input)
        assert metadata["company_name"] == "TEST CORP"
        assert metadata["shares_available"] == 100
        assert len(decisions) == 1
        assert decisions[0].vote == "For"
        assert decisions[0].proposal_number == "1"

    def test_missing_optional_fields(self):
        tool_input = {
            "decisions": [
                {
                    "proposal_number": "1",
                    "proposal_description": "Approve",
                    "vote": "For",
                    "reasoning": "OK",
                    "policy_rationale": "OK",
                    "board_recommendation": "For",
                    "aligned_with_board": True,
                },
            ],
        }
        metadata, decisions = _parse_results(tool_input)
        assert metadata["company_name"] == "Unknown"
        assert metadata["meeting_date"] == ""
        assert metadata["shares_available"] == 0
        assert metadata["control_number"] == ""

    def test_multiple_decisions(self):
        tool_input = {
            "decisions": [
                {
                    "proposal_number": str(i),
                    "proposal_description": f"Proposal {i}",
                    "vote": "For",
                    "reasoning": "OK",
                    "policy_rationale": "OK",
                    "board_recommendation": "For",
                    "aligned_with_board": True,
                }
                for i in range(5)
            ],
        }
        _, decisions = _parse_results(tool_input)
        assert len(decisions) == 5
        assert [d.proposal_number for d in decisions] == ["0", "1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# _format_usage
# ---------------------------------------------------------------------------


class TestFormatUsage:
    def test_basic(self):
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        result = _format_usage(usage)
        assert "in=100" in result
        assert "out=50" in result

    def test_with_cache(self):
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=200,
            cache_creation_input_tokens=300,
        )
        result = _format_usage(usage)
        assert "cache_read=200" in result
        assert "cache_write=300" in result

    def test_no_cache_attributes(self):
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        result = _format_usage(usage)
        assert "in=100" in result
        assert "cache" not in result


# ---------------------------------------------------------------------------
# _create_with_retry
# ---------------------------------------------------------------------------


def _make_response(
    tool_name: str | None = None,
    tool_input: dict | None = None,
    stop_reason: str = "end_turn",
):
    """Build a mock anthropic response."""
    content = []
    if tool_name:
        block = MagicMock()
        block.type = "tool_use"
        block.name = tool_name
        block.input = tool_input or {}
        content.append(block)
    else:
        block = MagicMock()
        block.type = "text"
        block.text = "Some text"
        content.append(block)

    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return resp


class TestCreateWithRetry:
    async def test_success_first_attempt(self):
        from proxy_voter.api_client import create_with_retry

        client = MagicMock()
        expected = _make_response()
        client.messages.create.return_value = expected

        result = await create_with_retry(client, model="test", messages=[])
        assert result is expected
        assert client.messages.create.call_count == 1

    async def test_retries_on_rate_limit(self):
        from proxy_voter.api_client import create_with_retry

        client = MagicMock()
        expected = _make_response()
        client.messages.create.side_effect = [
            anthropic.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429, headers={}),
                body=None,
            ),
            expected,
        ]

        with patch("proxy_voter.api_client.asyncio.sleep", new_callable=AsyncMock):
            result = await create_with_retry(client, model="test", messages=[])

        assert result is expected
        assert client.messages.create.call_count == 2

    async def test_exhausts_retries(self):
        from proxy_voter.api_client import create_with_retry

        client = MagicMock()
        rate_err = anthropic.RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        client.messages.create.side_effect = rate_err

        with patch("proxy_voter.api_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(anthropic.RateLimitError):
                await create_with_retry(client, model="test", messages=[])

        assert client.messages.create.call_count == 5


# ---------------------------------------------------------------------------
# research_proposals (integration with mocked API)
# ---------------------------------------------------------------------------


def _make_submit_response(decisions_count: int = 1):
    """Build a response that calls submit_voting_decisions."""
    return _make_response(
        tool_name="submit_voting_decisions",
        tool_input={
            "company_name": "TEST CORP",
            "meeting_date": "2026-04-15",
            "voting_deadline": "2026-04-09",
            "shares_available": 100,
            "control_number": "12345",
            "cusip": "T12345",
            "decisions": [
                {
                    "proposal_number": str(i + 1),
                    "proposal_description": f"Proposal {i + 1}",
                    "vote": "For",
                    "reasoning": "Standard",
                    "policy_rationale": "Aligns",
                    "board_recommendation": "For",
                    "aligned_with_board": True,
                }
                for i in range(decisions_count)
            ],
        },
        stop_reason="tool_use",
    )


def _make_ballot() -> BallotData:
    return BallotData(
        page_text="Proposal 1: Approve financials\nBoard Recommendation: For",
        document_urls=[],
        voting_url="https://www.proxyvote.com/test",
    )


class TestResearchProposals:
    async def test_submits_on_first_turn(self):
        resp = _make_submit_response(2)
        with patch("proxy_voter.researcher.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = resp
            metadata, decisions, usage = await research_proposals(_make_ballot())

        assert metadata["company_name"] == "TEST CORP"
        assert len(decisions) == 2
        assert usage.total_input_tokens > 0

    async def test_continues_on_web_search(self):
        """Researcher loops when Claude does web searches before submitting."""
        web_search_resp = _make_response(stop_reason="tool_use")
        # Make the web search response look like it has a server-side tool use (not submit)
        web_search_resp.content[0].type = "text"
        submit_resp = _make_submit_response()

        with patch("proxy_voter.researcher.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.side_effect = [
                web_search_resp,
                submit_resp,
            ]
            metadata, decisions, usage = await research_proposals(_make_ballot())

        assert metadata["company_name"] == "TEST CORP"
        assert len(decisions) == 1
        # Two API calls made
        assert len(usage.calls) == 2

    async def test_raises_on_no_submission(self):
        """Raises RuntimeError if Claude never calls submit_voting_decisions."""
        end_resp = _make_response(stop_reason="end_turn")

        with patch("proxy_voter.researcher.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = end_resp
            with pytest.raises(RuntimeError, match="did not submit voting decisions"):
                await research_proposals(_make_ballot())

    async def test_includes_doc_urls_in_prompt(self):
        ballot = BallotData(
            page_text="Proposal 1",
            document_urls=["https://example.com/proxy.pdf"],
            voting_url="https://vote.com",
        )
        resp = _make_submit_response()

        with patch("proxy_voter.researcher.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = resp
            await research_proposals(ballot)

        call_args = mock_cls.return_value.messages.create.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        assert "Linked documents available" in user_msg
        assert "https://example.com/proxy.pdf" in user_msg

    async def test_no_doc_urls_section_when_empty(self):
        ballot = BallotData(
            page_text="Proposal 1",
            document_urls=[],
            voting_url="https://vote.com",
        )
        resp = _make_submit_response()

        with patch("proxy_voter.researcher.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value.messages.create.return_value = resp
            await research_proposals(ballot)

        call_args = mock_cls.return_value.messages.create.call_args
        user_msg = call_args.kwargs["messages"][0]["content"]
        assert "Linked documents" not in user_msg
