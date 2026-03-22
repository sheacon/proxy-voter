import logging
from dataclasses import dataclass

from playwright.async_api import Browser, Page, Playwright, async_playwright

from proxy_voter.models import BallotData

logger = logging.getLogger(__name__)


@dataclass
class BallotSession:
    """Holds the ballot data and the live browser session for voting."""

    ballot: BallotData
    page: Page
    browser: Browser
    playwright: Playwright

    async def close(self) -> None:
        await self.browser.close()
        await self.playwright.stop()


async def open_ballot(proxyvote_url: str) -> BallotSession:
    """Open a ballot page and extract its content.

    Returns a BallotSession with the page still open for voting.
    Caller must call session.close() when done.
    """
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=True)
    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
    )
    page = await context.new_page()

    logger.info("Navigating to ProxyVote page: %s", proxyvote_url[:80])
    await page.goto(proxyvote_url, wait_until="domcontentloaded", timeout=60000)

    # Wait for ballot content to render (JS-rendered SPA)
    try:
        await page.wait_for_selector("text=Submit Vote", timeout=30000)
    except Exception:
        logger.warning("Submit Vote button not found. Current URL: %s", page.url)

    # Get full page text for Claude research
    page_text = await page.evaluate("() => document.body.innerText")

    # Extract document URLs from dropdowns and links
    document_urls = await page.evaluate("""() => {
        const urls = [];
        const sel = 'a[href*="materials"], a[href*="document"]';
        for (const link of document.querySelectorAll(sel)) {
            if (link.href && link.href.startsWith('http')) urls.push(link.href);
        }
        for (const select of document.querySelectorAll('select')) {
            for (const option of select.options) {
                if (option.value && option.value.startsWith('http')) {
                    urls.push(option.value);
                }
            }
        }
        return [...new Set(urls)];
    }""")

    logger.info("Scraped ballot page (%d chars, %d doc URLs)", len(page_text), len(document_urls))

    ballot = BallotData(
        page_text=page_text,
        document_urls=document_urls,
        proxyvote_url=proxyvote_url,
    )

    return BallotSession(ballot=ballot, page=page, browser=browser, playwright=pw)
