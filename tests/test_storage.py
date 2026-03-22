import pytest

from proxy_voter.models import BallotData, SessionStatus, VotingDecision
from proxy_voter.storage import create_session, get_session, init_db, update_session_status


def _make_ballot() -> BallotData:
    return BallotData(
        page_text="1. Approve financials\nBoard Recommendation: For",
        document_urls=[],
        proxyvote_url="https://www.proxyvote.com/test-token",
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
            policy_rationale="Routine governance — aligns with shareholder value.",
            board_recommendation="For",
            aligned_with_board=True,
        ),
    ]


@pytest.fixture(autouse=True)
async def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    import proxy_voter.config

    proxy_voter.config._settings = None
    await init_db()
    yield
    proxy_voter.config._settings = None


async def test_create_and_get_session():
    ballot = _make_ballot()
    decisions = _make_decisions()

    session_id = await create_session(
        sender_email="test@example.com",
        company_name="TEST CORP",
        proxyvote_url="https://www.proxyvote.com/test-token",
        ballot_data=ballot,
        voting_decisions=decisions,
        metadata=_make_metadata(),
    )

    assert session_id.startswith("PV-")
    assert len(session_id) == 9  # PV- + 6 chars

    session = await get_session(session_id)
    assert session is not None
    assert session["sender_email"] == "test@example.com"
    assert session["company_name"] == "TEST CORP"
    assert session["status"] == "pending_approval"


async def test_get_nonexistent_session():
    session = await get_session("PV-notreal")
    assert session is None


async def test_update_session_status():
    ballot = _make_ballot()
    decisions = _make_decisions()

    session_id = await create_session(
        sender_email="test@example.com",
        company_name="TEST CORP",
        proxyvote_url="https://www.proxyvote.com/test-token",
        ballot_data=ballot,
        voting_decisions=decisions,
        metadata=_make_metadata(),
    )

    await update_session_status(session_id, SessionStatus.VOTES_SUBMITTED)

    session = await get_session(session_id)
    assert session["status"] == "votes_submitted"
