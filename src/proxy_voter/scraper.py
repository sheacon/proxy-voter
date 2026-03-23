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


async def open_ballot(voting_url: str) -> BallotSession:
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

    logger.info("Navigating to voting page: %s", voting_url[:80])
    await page.goto(voting_url, wait_until="domcontentloaded", timeout=60000)

    # Wait for page to fully load (works for SPAs and static pages)
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        logger.warning("Timed out waiting for networkidle. Current URL: %s", page.url)
    # Additional wait for any JS rendering to settle
    await page.wait_for_timeout(2000)

    # Get full page text for Claude research
    page_text = await page.evaluate("() => document.body.innerText")

    # Extract all links from the page
    document_urls = await page.evaluate("""() => {
        const urls = [];
        for (const link of document.querySelectorAll('a[href]')) {
            const href = link.href;
            if (href && href.startsWith('http')) urls.push(href);
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
        voting_url=voting_url,
    )

    return BallotSession(ballot=ballot, page=page, browser=browser, playwright=pw)
