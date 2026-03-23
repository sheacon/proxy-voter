import logging

import resend

from proxy_voter.config import get_settings
from proxy_voter.models import VotingDecision

logger = logging.getLogger(__name__)


def _init_resend() -> None:
    settings = get_settings()
    resend.api_key = settings.resend_api_key


def send_recommendations_email(
    to_email: str,
    session_id: str,
    metadata: dict,
    decisions: list[VotingDecision],
) -> None:
    _init_resend()
    settings = get_settings()

    company = metadata.get("company_name", "Unknown")
    subject = f"[{session_id}] Proxy Vote Recommendations: {company}"
    html = _build_results_html(metadata, decisions, submitted=False, session_id=session_id)

    resend.Emails.send(
        {
            "from": f"Proxy Voter <{settings.from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )
    logger.info("Sent recommendations email to %s for session %s", to_email, session_id)


def send_confirmation_email(
    to_email: str,
    session_id: str,
    metadata: dict,
    decisions: list[VotingDecision],
) -> None:
    _init_resend()
    settings = get_settings()

    company = metadata.get("company_name", "Unknown")
    subject = f"[{session_id}] Votes Submitted: {company}"
    html = _build_results_html(metadata, decisions, submitted=True, session_id=session_id)

    resend.Emails.send(
        {
            "from": f"Proxy Voter <{settings.from_email}>",
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    )
    logger.info("Sent confirmation email to %s for session %s", to_email, session_id)


def send_error_email(to_email: str, error_message: str, context: str = "") -> None:
    _init_resend()
    settings = get_settings()

    html = f"""<!DOCTYPE html>
<html>
<head><style>{_base_styles()}</style></head>
<body>
<div class="container">
    <div class="header" style="background-color: #dc3545;">
        <h1>Proxy Vote Error</h1>
    </div>
    <div class="content">
        <p>{error_message}</p>
        {f'<p style="color: #666; font-size: 14px;">{context}</p>' if context else ""}
        <p>If this is unexpected, please try forwarding the email again or vote manually.</p>
    </div>
</div>
</body>
</html>"""

    resend.Emails.send(
        {
            "from": f"Proxy Voter <{settings.from_email}>",
            "to": [to_email],
            "subject": "Proxy Vote Error",
            "html": html,
        }
    )
    logger.info("Sent error email to %s: %s", to_email, error_message[:100])


def _base_styles() -> str:
    return """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
           margin: 0; padding: 0; background-color: #f5f5f5; }
    .container { max-width: 800px; margin: 20px auto; background: white;
                 border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .header { background-color: #037DAE; color: white; padding: 24px 32px; }
    .header h1 { margin: 0; font-size: 22px; font-weight: 600; }
    .header .meta { font-size: 14px; opacity: 0.9; margin-top: 8px; }
    .content { padding: 24px 32px; }
    .badge { display: inline-block; padding: 4px 12px; border-radius: 12px;
             font-size: 13px; font-weight: 600; }
    .badge-submitted { background-color: #28a745; color: white; }
    .badge-pending { background-color: #ffc107; color: #333; }
    table { width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 14px; }
    th { background-color: #f8f9fa; text-align: left; padding: 10px 12px;
         border-bottom: 2px solid #dee2e6; font-weight: 600; }
    td { padding: 10px 12px; border-bottom: 1px solid #dee2e6; vertical-align: top; }
    tr.aligned td { background-color: #f0fff0; }
    tr.divergent td { background-color: #fff8e1; }
    .vote-for { color: #28a745; font-weight: 600; }
    .vote-against { color: #dc3545; font-weight: 600; }
    .vote-abstain { color: #6c757d; font-weight: 600; }
    .vote-withhold { color: #6c757d; font-weight: 600; }
    .footer { padding: 16px 32px; background-color: #f8f9fa; font-size: 13px; color: #666;
              border-top: 1px solid #dee2e6; }
    .cta { margin: 20px 0; padding: 16px; background-color: #e3f2fd; border-radius: 8px;
           border-left: 4px solid #037DAE; }
    """


def _vote_class(vote: str) -> str:
    return f"vote-{vote.lower().replace(' ', '-')}"


def _build_results_html(
    metadata: dict,
    decisions: list[VotingDecision],
    submitted: bool,
    session_id: str,
) -> str:
    company = metadata.get("company_name", "Unknown")
    meeting_date = metadata.get("meeting_date", "")
    voting_deadline = metadata.get("voting_deadline", "")
    shares = metadata.get("shares_available", "")
    control_number = metadata.get("control_number", "")
    cusip = metadata.get("cusip", "")

    status_badge = (
        '<span class="badge badge-submitted">VOTES SUBMITTED</span>'
        if submitted
        else '<span class="badge badge-pending">RECOMMENDATIONS (NOT YET SUBMITTED)</span>'
    )

    rows = ""
    for d in decisions:
        row_class = "aligned" if d.aligned_with_board else "divergent"
        vote_cls = _vote_class(d.vote)
        rows += f"""<tr class="{row_class}">
            <td><strong>{d.proposal_number}</strong></td>
            <td>{d.proposal_description}</td>
            <td class="{vote_cls}">{d.vote}</td>
            <td>{d.board_recommendation}</td>
            <td>{d.reasoning}</td>
            <td><em>{d.policy_rationale}</em></td>
        </tr>"""

    approval_cta = ""
    if not submitted:
        approval_cta = """<div class="cta">
            <strong>To submit these votes:</strong> Reply to this email with the word
            <strong>"approved"</strong> in the body. Your votes will be cast automatically.
        </div>"""

    return f"""<!DOCTYPE html>
<html>
<head><style>{_base_styles()}</style></head>
<body>
<div class="container">
    <div class="header">
        <h1>{company}</h1>
        <div class="meta">
            Meeting: {meeting_date} &bull;
            Deadline: {voting_deadline} &bull;
            Shares: {shares}
        </div>
    </div>
    <div class="content">
        <p>{status_badge}</p>
        <p>Session: <code>{session_id}</code> &bull;
           Control #: <code>{control_number}</code> &bull;
           CUSIP: <code>{cusip}</code></p>

        {approval_cta}

        <table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>Proposal</th>
                    <th>Vote</th>
                    <th>Board Rec</th>
                    <th>Reasoning</th>
                    <th>Policy Rationale</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    <div class="footer">
        <p>Voting deadline: <strong>{voting_deadline}</strong></p>
        <p>This email was generated by Proxy Voter.</p>
    </div>
</div>
</body>
</html>"""
