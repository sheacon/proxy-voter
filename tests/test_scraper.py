from unittest.mock import AsyncMock, MagicMock, patch

from proxy_voter.scraper import BallotSession, open_ballot


def _mock_playwright_chain():
    """Build a full mock playwright -> browser -> context -> page chain."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.add_init_script = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.url = "https://central.proxyvote.com/ballot"
    page.evaluate = AsyncMock(
        side_effect=[
            "Proposal 1: Approve financials\nBoard Recommendation: For",
            ["https://example.com/proxy.pdf"],
        ]
    )

    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()

    pw = MagicMock()
    pw.chromium = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()

    return pw, browser, context, page


class TestOpenBallot:
    async def test_returns_ballot_session(self):
        pw, browser, context, page = _mock_playwright_chain()
        mock_start = AsyncMock(return_value=pw)

        with patch("proxy_voter.scraper.async_playwright") as mock_apw:
            mock_apw.return_value.start = mock_start
            session = await open_ballot("https://www.proxyvote.com/test")

        assert isinstance(session, BallotSession)
        assert session.ballot.voting_url == "https://www.proxyvote.com/test"
        assert "Proposal 1" in session.ballot.page_text
        assert "https://example.com/proxy.pdf" in session.ballot.document_urls
        assert session.browser is browser
        assert session.playwright is pw

    async def test_navigates_to_url(self):
        pw, browser, context, page = _mock_playwright_chain()
        mock_start = AsyncMock(return_value=pw)

        with patch("proxy_voter.scraper.async_playwright") as mock_apw:
            mock_apw.return_value.start = mock_start
            await open_ballot("https://www.proxyvote.com/test")

        page.goto.assert_awaited_once_with(
            "https://www.proxyvote.com/test",
            wait_until="domcontentloaded",
            timeout=60000,
        )

    async def test_sets_user_agent(self):
        pw, browser, context, page = _mock_playwright_chain()
        mock_start = AsyncMock(return_value=pw)

        with patch("proxy_voter.scraper.async_playwright") as mock_apw:
            mock_apw.return_value.start = mock_start
            await open_ballot("https://www.proxyvote.com/test")

        call_kwargs = browser.new_context.call_args.kwargs
        assert "Chrome" in call_kwargs["user_agent"]

    async def test_handles_networkidle_timeout(self):
        pw, browser, context, page = _mock_playwright_chain()
        page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("networkidle timeout"))
        mock_start = AsyncMock(return_value=pw)

        with patch("proxy_voter.scraper.async_playwright") as mock_apw:
            mock_apw.return_value.start = mock_start
            session = await open_ballot("https://www.proxyvote.com/test")

        # Should still return a session despite timeout
        assert session.ballot.page_text is not None


class TestBallotSessionClose:
    async def test_closes_browser_and_playwright(self):
        pw = MagicMock()
        pw.stop = AsyncMock()
        browser = MagicMock()
        browser.close = AsyncMock()
        page = MagicMock()

        from proxy_voter.models import BallotData

        session = BallotSession(
            ballot=BallotData(page_text="", document_urls=[], voting_url=""),
            page=page,
            browser=browser,
            playwright=pw,
        )
        await session.close()

        browser.close.assert_awaited_once()
        pw.stop.assert_awaited_once()
