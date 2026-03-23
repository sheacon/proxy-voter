# Proxy Voter

Automated proxy voting for corporate shareholder ballots. Forward a proxy vote email, get research-backed voting recommendations, and optionally cast votes automatically.

## How it works

1. You receive a proxy vote notification email from your broker (e.g. Charles Schwab, Fidelity, Vanguard, E*TRADE)
2. Forward it to your configured Proxy Voter email address
3. Claude researches each proposal using web search, analyzes it against your policy preferences, and recommends votes
4. You receive an email with recommendations and reasoning for each proposal
5. Reply "approved" to cast your votes, or include "auto-vote" in the original forward to skip approval

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────────┐
│ Forward email │────▶│ Cloudflare Worker │────▶│ FastAPI (Fly.io) │
└──────────────┘     └───────────────────┘     └────────┬─────────┘
                                                        │
                     ┌──────────────────────────────────┐│
                     │ 1. Parse email, extract ballot URL││
                     │ 2. Scrape ballot (Playwright)     ││
                     │ 3. Research proposals (Claude)     ││
                     │ 4. Send recommendations (Resend)   ││
                     │ 5. On approval → cast votes        │▼
                     └──────────────────────────────────┘
```

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- A [Cloudflare](https://cloudflare.com) account with Email Routing
- A [Fly.io](https://fly.io) account
- API keys for [Anthropic](https://console.anthropic.com) and [Resend](https://resend.com)

### Installation

```bash
git clone https://github.com/sheacon/proxy-voter.git
cd proxy-voter
uv sync --dev
uv run playwright install --with-deps chromium
```

### Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude |
| `RESEND_API_KEY` | Resend API key for sending emails |
| `WEBHOOK_SECRET` | Shared secret between Cloudflare Worker and webhook |
| `FROM_EMAIL` | Sender address for outbound emails |
| `CLAUDE_MODEL` | Claude model to use (default: `claude-sonnet-4-6`) |
| `APPROVED_SENDERS` | Comma-separated list of email addresses allowed to use the service |
| `POLICY_PREFERENCES_PATH` | Path to your voting policy file (default: `policy-preferences.md`) |

Edit `policy-preferences.md` to describe your voting philosophy. This is included in the Claude prompt that analyzes each proposal.

### Deploy

**Fly.io:**

```bash
fly launch
fly secrets set ANTHROPIC_API_KEY=... RESEND_API_KEY=... WEBHOOK_SECRET=... FROM_EMAIL=... APPROVED_SENDERS=...
fly deploy
```

**Cloudflare Email Worker:**

```bash
cd cloudflare-worker
wrangler secret put WEBHOOK_URL   # https://your-app.fly.dev/webhook/email
wrangler secret put WEBHOOK_SECRET
wrangler deploy
```

Then configure [Cloudflare Email Routing](https://developers.cloudflare.com/email-routing/) to route your inbound address to the worker.

### Run locally

```bash
uv run uvicorn proxy_voter.main:app --port 8080
```

## Architecture

| Component | File | Role |
|---|---|---|
| Email Worker | `cloudflare-worker/email-worker.js` | Receives inbound email, forwards raw RFC 822 to webhook |
| Webhook | `src/proxy_voter/webhook.py` | Orchestrates the full pipeline |
| Email Parser | `src/proxy_voter/email_parser.py` | Classifies emails, uses Claude to extract voting URLs |
| Scraper | `src/proxy_voter/scraper.py` | Opens ballots in headless Chromium |
| Researcher | `src/proxy_voter/researcher.py` | Claude analyzes proposals with web search |
| Voter | `src/proxy_voter/voter.py` | Claude maps votes to form elements, submits |
| Notifier | `src/proxy_voter/notifier.py` | Sends recommendation/confirmation/error emails via Resend |
| Storage | `src/proxy_voter/storage.py` | SQLite session persistence |

## Testing

```bash
uv run pytest
```

Some tests require `.eml` fixture files in `example-files/` and will be skipped if not present.
