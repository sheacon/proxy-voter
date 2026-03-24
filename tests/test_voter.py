from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from proxy_voter.models import VotingDecision
from proxy_voter.voter import (
    _build_button_locator,
    _build_locator,
    _click_submit_fallback,
    _css_escape,
    _dismiss_session_modal,
    cast_votes,
)

# ---------------------------------------------------------------------------
# _css_escape (pure function)
# ---------------------------------------------------------------------------


class TestCssEscape:
    def test_clean_string(self):
        assert _css_escape("hello") == "hello"

    def test_escapes_quotes(self):
        assert _css_escape('a"b') == 'a\\"b'

    def test_escapes_backslashes(self):
        assert _css_escape("a\\b") == "a\\\\b"

    def test_escapes_both(self):
        assert _css_escape('a\\"b') == 'a\\\\\\"b'

    def test_empty(self):
        assert _css_escape("") == ""


# ---------------------------------------------------------------------------
# _build_locator
# ---------------------------------------------------------------------------


class TestBuildLocator:
    def test_by_id(self):
        page = MagicMock()
        _build_locator(page, {"id": "my-radio", "name": "vote", "value": "for"}, "radio")
        page.locator.assert_called_with("#my-radio")

    def test_by_name_and_value(self):
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "vote", "value": "for"}, "radio")
        page.locator.assert_called_with('input[type="radio"][name="vote"][value="for"]')

    def test_by_name_only(self):
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "vote", "value": ""}, "radio")
        page.locator.assert_called_with('input[type="radio"][name="vote"]')

    def test_fallback_radio(self):
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "", "value": ""}, "radio")
        page.locator.assert_called_with('input[type="radio"]')

    def test_select_type(self):
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "sel", "value": ""}, "select")
        page.locator.assert_called_with('select[name="sel"]')

    def test_checkbox_type(self):
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "cb", "value": "yes"}, "checkbox")
        page.locator.assert_called_with('input[type="checkbox"][name="cb"][value="yes"]')

    def test_name_with_brackets(self):
        """Brackets in name should be handled (proxyvote uses proposalVoteOptions[0])."""
        page = MagicMock()
        _build_locator(page, {"id": "", "name": "proposalVoteOptions[0]", "value": "for"}, "radio")
        page.locator.assert_called_with(
            'input[type="radio"][name="proposalVoteOptions[0]"][value="for"]'
        )


# ---------------------------------------------------------------------------
# _build_button_locator
# ---------------------------------------------------------------------------


class TestBuildButtonLocator:
    def test_by_id(self):
        page = MagicMock()
        _build_button_locator(page, {"id": "btn-submit", "text": "Submit", "tag": "button"})
        page.locator.assert_called_with("#btn-submit")

    def test_by_text(self):
        page = MagicMock()
        _build_button_locator(page, {"id": "", "text": "Submit Vote", "tag": "button"})
        page.locator.assert_called_with('button:has-text("Submit Vote")')

    def test_fallback(self):
        page = MagicMock()
        _build_button_locator(page, {"id": "", "text": "", "tag": "button"})
        page.locator.assert_called_with("button")


# ---------------------------------------------------------------------------
# _dismiss_session_modal
# ---------------------------------------------------------------------------


class TestDismissSessionModal:
    async def test_no_modal(self):
        page = MagicMock()
        modal = AsyncMock()
        modal.count = AsyncMock(return_value=0)
        page.locator.return_value = modal
        # Should not raise
        await _dismiss_session_modal(page)

    async def test_clicks_continue_button(self):
        page = MagicMock()
        # Playwright locator() is sync, count()/click() are async
        modal = MagicMock()
        modal.count = AsyncMock(return_value=1)

        first_btn = MagicMock()
        first_btn.click = AsyncMock()

        btn = MagicMock()
        btn.count = AsyncMock(return_value=1)
        btn.first = first_btn

        modal.locator.return_value = btn
        page.locator.return_value = modal
        page.wait_for_timeout = AsyncMock()

        await _dismiss_session_modal(page)
        first_btn.click.assert_awaited_once()


# ---------------------------------------------------------------------------
# _click_submit_fallback
# ---------------------------------------------------------------------------


class TestClickSubmitFallback:
    async def test_finds_submit_button(self):
        page = MagicMock()
        page.locator.return_value = AsyncMock()  # For dismiss_session_modal
        page.locator.return_value.count = AsyncMock(return_value=0)

        element = AsyncMock()
        element.click = AsyncMock()
        page.query_selector = AsyncMock(side_effect=[element])

        await _click_submit_fallback(page)
        element.click.assert_awaited_once()

    async def test_raises_when_none_found(self):
        page = MagicMock()
        page.locator.return_value = AsyncMock()
        page.locator.return_value.count = AsyncMock(return_value=0)
        page.query_selector = AsyncMock(return_value=None)

        with pytest.raises(RuntimeError, match="Submit button not found"):
            await _click_submit_fallback(page)


# ---------------------------------------------------------------------------
# cast_votes (full mocked)
# ---------------------------------------------------------------------------


def _make_decisions(n: int = 1) -> list[VotingDecision]:
    return [
        VotingDecision(
            proposal_number=str(i + 1),
            proposal_description=f"Proposal {i + 1}",
            vote="For",
            reasoning="OK",
            policy_rationale="Aligns",
            board_recommendation="For",
            aligned_with_board=True,
        )
        for i in range(n)
    ]


def _mock_page(form_data: list[dict] | None = None, button_data: list[dict] | None = None):
    """Create a mock Playwright page with form data."""
    if form_data is None:
        form_data = [
            {"type": "radio", "name": "vote[0]", "value": "for", "id": "", "label": "For"},
            {"type": "radio", "name": "vote[0]", "value": "against", "id": "", "label": "Against"},
        ]
    if button_data is None:
        button_data = [
            {
                "tag": "button",
                "text": "Submit",
                "id": "submit-btn",
                "type": "submit",
                "classes": "",
            },
        ]

    page = MagicMock()
    # evaluate calls: combined extraction (dict), then confirmation text
    page.evaluate = AsyncMock(
        side_effect=[
            {"formElements": form_data, "buttons": button_data, "pageText": "Page text..."},
            "Confirmation",
        ]
    )
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()

    # Modal dismiss
    modal = AsyncMock()
    modal.count = AsyncMock(return_value=0)
    page.locator.return_value = modal

    # Locator for form interaction
    locator = AsyncMock()
    locator.check = AsyncMock()
    locator.click = AsyncMock()
    page.locator.return_value = locator
    # For .first
    locator.first = locator

    return page


def _mock_claude_response(actions: list[dict], submit_button_index: int = 0):
    """Build a mock Claude response for vote actions."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_vote_actions"
    block.input = {"actions": actions, "submit_button_index": submit_button_index}

    resp = MagicMock()
    resp.content = [block]
    resp.usage = SimpleNamespace(
        input_tokens=100,
        output_tokens=50,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
    )
    return resp


class TestCastVotes:
    async def test_no_form_elements(self):
        page = _mock_page(form_data=[])
        with pytest.raises(RuntimeError, match="No form elements found"):
            await cast_votes(page, _make_decisions())

    async def test_no_actions_from_claude(self):
        page = _mock_page()
        resp = _mock_claude_response(actions=[])

        with patch(
            "proxy_voter.voter.create_with_retry",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="did not return any vote actions"):
                await cast_votes(page, _make_decisions())

    async def test_all_unmatched_actions(self):
        page = _mock_page()
        resp = _mock_claude_response(
            actions=[
                {
                    "proposal_number": "1",
                    "action_type": "check_radio",
                    "element_index": 0,
                    "matched": False,
                }
            ]
        )

        with patch(
            "proxy_voter.voter.create_with_retry",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="Failed to execute any vote actions"):
                await cast_votes(page, _make_decisions())

    async def test_invalid_element_index(self):
        page = _mock_page()
        resp = _mock_claude_response(
            actions=[
                {
                    "proposal_number": "1",
                    "action_type": "check_radio",
                    "element_index": 999,
                    "matched": True,
                }
            ]
        )

        with patch(
            "proxy_voter.voter.create_with_retry",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            with pytest.raises(RuntimeError, match="Failed to execute any vote actions"):
                await cast_votes(page, _make_decisions())

    async def test_happy_path_radio(self):
        page = _mock_page()

        resp = _mock_claude_response(
            actions=[
                {
                    "proposal_number": "1",
                    "action_type": "check_radio",
                    "element_index": 0,
                    "matched": True,
                }
            ],
            submit_button_index=0,
        )

        with patch(
            "proxy_voter.voter.create_with_retry",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            confirmation, usage = await cast_votes(page, _make_decisions())

        assert isinstance(confirmation, str)
        assert usage.total_input_tokens > 0

    async def test_submit_button_fallback(self):
        page = _mock_page()

        resp = _mock_claude_response(
            actions=[
                {
                    "proposal_number": "1",
                    "action_type": "check_radio",
                    "element_index": 0,
                    "matched": True,
                }
            ],
            submit_button_index=None,
        )

        with (
            patch(
                "proxy_voter.voter.create_with_retry",
                new_callable=AsyncMock,
                return_value=resp,
            ),
            patch(
                "proxy_voter.voter._click_submit_fallback",
                new_callable=AsyncMock,
            ) as mock_fallback,
        ):
            await cast_votes(page, _make_decisions())
            mock_fallback.assert_awaited_once()

    async def test_force_check_on_radio_failure(self):
        """When locator.check() fails, retries with force=True."""
        form_data = [
            {"type": "radio", "name": "vote[0]", "value": "for", "id": "r1", "label": "For"},
        ]
        button_data = [
            {
                "tag": "button",
                "text": "Submit",
                "id": "submit-btn",
                "type": "submit",
                "classes": "",
            },
        ]

        page = MagicMock()
        page.evaluate = AsyncMock(
            side_effect=[
                {"formElements": form_data, "buttons": button_data, "pageText": "Page text"},
                "Confirmation",
            ]
        )
        page.wait_for_timeout = AsyncMock()
        page.wait_for_load_state = AsyncMock()

        # Modal dismiss
        modal = AsyncMock()
        modal.count = AsyncMock(return_value=0)

        # The locator: first .check() fails, force=True succeeds
        locator = AsyncMock()
        locator.check = AsyncMock(side_effect=[Exception("not clickable"), None])
        locator.click = AsyncMock()

        page.locator.return_value = modal
        # We need different behavior for different calls to page.locator
        # - first for modal dismiss
        # - then for form element
        # - then for submit button
        call_count = {"n": 0}

        def locator_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:  # Modal dismiss calls
                return modal
            return locator

        page.locator.side_effect = locator_side_effect

        resp = _mock_claude_response(
            actions=[
                {
                    "proposal_number": "1",
                    "action_type": "check_radio",
                    "element_index": 0,
                    "matched": True,
                }
            ],
            submit_button_index=0,
        )

        with patch(
            "proxy_voter.voter.create_with_retry",
            new_callable=AsyncMock,
            return_value=resp,
        ):
            confirmation, _ = await cast_votes(page, _make_decisions())

        # check() should have been called twice (once normal, once with force=True)
        assert locator.check.call_count == 2
