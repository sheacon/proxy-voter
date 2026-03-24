#!/usr/bin/env python3
"""Send a test proxy vote email for end-to-end pipeline testing.

Usage:
    uv run python scripts/send_test_email.py --to user@example.com

The recipient then forwards the email to the proxy-voter inbound address.
The email links to the fake ballot page configured via TEST_BALLOT_URL.
"""

import argparse

import resend

from proxy_voter.config import get_settings


def build_email_html(ballot_url: str) -> str:
    proxy_statement_url = f"{ballot_url}/proxy-statement"
    annual_report_url = f"{ballot_url}/annual-report"

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="font-family: -apple-system, sans-serif; margin: 0; padding: 0; background: #f5f5f5;">
<div style="max-width: 600px; margin: 20px auto; background: white; border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden;">

  <div style="background: #037DAE; color: white; padding: 24px 32px;">
    <h1 style="margin: 0; font-size: 20px;">CHARLES SCHWAB &amp; CO., INC.</h1>
    <p style="margin: 8px 0 0; opacity: 0.9;">Proxy Vote Notification</p>
  </div>

  <div style="padding: 24px 32px;">
    <h2 style="color: #333; font-size: 18px;">Vote now! MOODY'S CORPORATION Annual Meeting</h2>

    <p>Dear Shareholder,</p>

    <p>You are receiving this notification because you hold shares of
    <strong>MOODY'S CORPORATION</strong> (CUSIP: 615369105) in your
    Charles Schwab brokerage account.</p>

    <table style="width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px;">
      <tr>
        <td style="padding: 6px 0; font-weight: 600; color: #555;">Meeting Date:</td>
        <td style="padding: 6px 0;">April 22, 2026</td>
      </tr>
      <tr>
        <td style="padding: 6px 0; font-weight: 600; color: #555;">Voting Deadline:</td>
        <td style="padding: 6px 0;">April 21, 2026, 11:59 PM ET</td>
      </tr>
      <tr>
        <td style="padding: 6px 0; font-weight: 600; color: #555;">Control Number:</td>
        <td style="padding: 6px 0;">999999999999</td>
      </tr>
      <tr>
        <td style="padding: 6px 0; font-weight: 600; color: #555;">Shares:</td>
        <td style="padding: 6px 0;">150</td>
      </tr>
    </table>

    <div style="text-align: center; margin: 24px 0;">
      <a href="{ballot_url}"
         style="display: inline-block; background: #037DAE; color: white; padding: 14px 48px;
                text-decoration: none; border-radius: 6px; font-size: 16px; font-weight: 600;">
        VOTE NOW
      </a>
    </div>

    <p style="font-size: 14px; color: #555;">
      Review the
      <a href="{proxy_statement_url}" style="color: #037DAE;">Proxy Statement</a> and
      <a href="{annual_report_url}" style="color: #037DAE;">2025 Annual Report</a>
      before casting your vote.
    </p>
  </div>

  <div style="padding: 16px 32px; background: #f8f9fa; font-size: 12px; color: #666;
              border-top: 1px solid #dee2e6;">
    <p>This is a test email for Proxy Voter end-to-end testing.</p>
  </div>
</div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test proxy vote email")
    parser.add_argument("--to", required=True, help="Recipient email address")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.test_ballot_url:
        print("Error: TEST_BALLOT_URL is not set in .env")
        print("Set it to the URL of your fake ballot page (e.g. https://ballot.example.com)")
        raise SystemExit(1)

    resend.api_key = settings.resend_api_key

    result = resend.Emails.send(
        {
            "from": f"CHARLES SCHWAB & CO., INC. <{settings.from_email}>",
            "to": [args.to],
            "subject": "Vote now! MOODY'S CORPORATION Annual Meeting",
            "html": build_email_html(settings.test_ballot_url),
        }
    )
    print(f"Test email sent to {args.to} (id: {result.get('id', 'unknown')})")
    print("Forward it to your proxy-voter inbound address to test the pipeline.")
    print("Add 'auto-vote' in the forwarding body to skip the approval step.")


if __name__ == "__main__":
    main()
