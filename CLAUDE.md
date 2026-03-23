# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync --dev

# Run the server locally
uv run uvicorn proxy_voter.main:app --port 8080

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/test_email_parser.py::TestParseDirectEmail::test_parse_ubs_email

# Lint / format
uv run ruff check .
uv run ruff format .

# Deploy
fly deploy

# Playwright (required for scraper)
uv run playwright install --with-deps chromium
```

## Architecture

Proxy Voter is an automated proxy voting system for corporate shareholder ballots. Users forward proxy vote notification emails from any brokerage (Charles Schwab, Fidelity, Vanguard, E*TRADE, etc.) to a configured inbound email address, and the system researches proposals, recommends votes, and optionally casts them. The system uses Claude to dynamically interpret emails and voting platform pages, so it is not tied to any specific brokerage or voting platform.

### Email flow

1. **Cloudflare Email Worker** (`cloudflare-worker/email-worker.js`) — receives inbound email and forwards raw RFC 822 bytes to the Fly.io webhook.

2. **Webhook** (`webhook.py`) — FastAPI endpoint at `/webhook/email`. Validates the shared secret, parses the email, and orchestrates the pipeline. Processing is serialized via an asyncio lock to avoid API rate limits.

3. **Email Parser** (`email_parser.py`) — classifies incoming emails as either a **new forward** (contains a voting platform URL) or an **approval reply** (subject contains `[PV-xxxx]`). Uses Claude to extract the voting URL, company name, and platform name from any brokerage email format. Also detects the optional `auto-vote` flag from the forwarded body.

4. **Scraper** (`scraper.py`) — opens the voting URL in headless Chromium (Playwright), waits for the ballot to render, extracts page text and document URLs. Returns a `BallotSession` that keeps the browser open for later voting.

5. **Researcher** (`researcher.py`) — sends ballot text to Claude with web search enabled. Claude identifies proposals, researches the company, and returns structured `VotingDecision` objects via tool use (`submit_voting_decisions`).

6. **Voter** (`voter.py`) — extracts form element data (radio buttons, dropdowns, checkboxes) from the live ballot page and sends it to Claude, which maps voting decisions to form actions via tool use (`submit_vote_actions`). Executes the actions and submits the form.

7. **Notifier** (`notifier.py`) — sends HTML emails via Resend: recommendation emails (pending approval), confirmation emails (votes submitted), or error emails.

8. **Storage** (`storage.py`) — SQLite via aiosqlite. Stores voting sessions with status tracking (`pending_approval` → `votes_submitted` | `expired`).

### Two-phase voting

By default, new forwards trigger a **recommendation email** — the user must reply with "approved" to cast votes. If the user includes `auto-vote` in their forwarded email body, votes are cast immediately and only a confirmation is sent.

### Key models

- `ParsedEmail` — classified email with type, sender, voting URL, platform name, session ID
- `BallotData` — scraped page text, document URLs, voting URL
- `VotingDecision` — per-proposal vote with reasoning and policy rationale
- `BallotSession` — holds live Playwright page + browser for the ballot

### Configuration

Settings are loaded via `pydantic-settings` from `.env`. Key settings include `CLAUDE_MODEL` (defaults to `claude-sonnet-4-6`), `APPROVED_SENDERS` (comma-separated emails), and `POLICY_PREFERENCES_PATH` (plain text file that controls how votes are decided).

### Tests

Tests use `.eml` fixture files in `example-files/`. `conftest.py` sets dummy env vars so tests don't require real API keys. Claude API calls in the email parser are mocked in tests. `asyncio_mode = "auto"` is configured in pyproject.toml.
