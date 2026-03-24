from types import SimpleNamespace

from proxy_voter.models import (
    BallotData,
    EmailType,
    ParsedEmail,
    SessionStatus,
    UsageStats,
    VotingDecision,
)


class TestUsageStats:
    def test_empty(self):
        u = UsageStats()
        assert u.total_input_tokens == 0
        assert u.total_output_tokens == 0
        assert u.estimated_cost == 0.0

    def test_add_single_call(self):
        u = UsageStats()
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        u.add("claude-sonnet-4-6", usage)
        assert u.total_input_tokens == 1000
        assert u.total_output_tokens == 500

    def test_add_multiple_calls(self):
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
        u.add(
            "claude-haiku-4-5",
            SimpleNamespace(
                input_tokens=2000,
                output_tokens=300,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        assert u.total_input_tokens == 3000
        assert u.total_output_tokens == 800

    def test_merge(self):
        a = UsageStats()
        a.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=100,
                output_tokens=50,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        b = UsageStats()
        b.add(
            "claude-haiku-4-5",
            SimpleNamespace(
                input_tokens=200,
                output_tokens=30,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        a.merge(b)
        assert len(a.calls) == 2
        assert a.total_input_tokens == 300
        assert a.total_output_tokens == 80

    def test_estimated_cost_sonnet(self):
        u = UsageStats()
        u.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        # input: 1M * $3/M = $3, output: 1M * $15/M = $15
        assert u.estimated_cost == 18.0

    def test_estimated_cost_haiku(self):
        u = UsageStats()
        u.add(
            "claude-haiku-4-5",
            SimpleNamespace(
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        # input: 1M * $0.80/M = $0.80, output: 1M * $4/M = $4
        assert u.estimated_cost == 4.80

    def test_estimated_cost_unknown_model_uses_sonnet_pricing(self):
        u = UsageStats()
        u.add(
            "claude-unknown-99",
            SimpleNamespace(
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        assert u.estimated_cost == 18.0

    def test_estimated_cost_with_cache_tokens(self):
        u = UsageStats()
        u.add(
            "claude-sonnet-4-6",
            SimpleNamespace(
                input_tokens=1000,
                output_tokens=500,
                cache_read_input_tokens=200,
                cache_creation_input_tokens=100,
            ),
        )
        # non_cached_input = 1000 - 200 - 100 = 700
        # cost = 700*3/1M + 500*15/1M + 100*3.75/1M + 200*0.30/1M
        expected = (700 * 3.0 + 500 * 15.0 + 100 * 3.75 + 200 * 0.30) / 1_000_000
        assert abs(u.estimated_cost - expected) < 1e-10

    def test_cache_tokens_none_handling(self):
        """API may return None for cache token fields."""
        u = UsageStats()
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
        )
        u.add("claude-sonnet-4-6", usage)
        # Should not raise — None is treated as 0
        assert u.estimated_cost >= 0

    def test_missing_cache_attributes(self):
        """Some API objects may not have cache attributes at all."""
        u = UsageStats()
        usage = SimpleNamespace(input_tokens=100, output_tokens=50)
        u.add("claude-sonnet-4-6", usage)
        assert u.total_input_tokens == 100


class TestEnums:
    def test_email_type_values(self):
        assert EmailType.NEW_FORWARD == "new_forward"
        assert EmailType.APPROVAL_REPLY == "approval_reply"

    def test_session_status_values(self):
        assert SessionStatus.PENDING_APPROVAL == "pending_approval"
        assert SessionStatus.VOTES_SUBMITTED == "votes_submitted"
        assert SessionStatus.EXPIRED == "expired"


class TestPydanticModels:
    def test_parsed_email_defaults(self):
        p = ParsedEmail(
            email_type=EmailType.NEW_FORWARD,
            sender_email="test@example.com",
            subject="Test",
        )
        assert p.voting_url is None
        assert p.auto_vote is False
        assert p.session_id is None
        assert p.company_name is None

    def test_voting_decision_defaults(self):
        d = VotingDecision(
            proposal_number="1",
            proposal_description="Approve",
            vote="For",
            reasoning="OK",
            policy_rationale="Aligns",
            board_recommendation="For",
            aligned_with_board=True,
        )
        assert d.company_name == ""
        assert d.meeting_date == ""
        assert d.voting_deadline == ""

    def test_ballot_data_roundtrip(self):
        b = BallotData(
            page_text="text",
            document_urls=["https://example.com"],
            voting_url="https://vote.com/123",
        )
        dumped = b.model_dump_json()
        restored = BallotData.model_validate_json(dumped)
        assert restored.page_text == "text"
        assert restored.document_urls == ["https://example.com"]
        assert restored.voting_url == "https://vote.com/123"
