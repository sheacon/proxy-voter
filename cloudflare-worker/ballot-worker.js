/**
 * Fake proxy voting ballot page for end-to-end testing.
 * Serves a realistic Moody's Corporation ballot at ballot.example.org.
 *
 * Routes:
 *   GET  /                 — Ballot page with radio buttons and submit
 *   POST /                 — Confirmation page after vote submission
 *   GET  /proxy-statement  — Placeholder proxy statement
 *   GET  /annual-report    — Placeholder annual report
 */

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (url.pathname === "/proxy-statement") {
      return new Response(proxyStatementPage(), {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    if (url.pathname === "/annual-report") {
      return new Response(annualReportPage(), {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    if (url.pathname === "/" || url.pathname === "") {
      if (request.method === "POST") {
        return new Response(confirmationPage(), {
          headers: { "Content-Type": "text/html; charset=utf-8" },
        });
      }
      return new Response(ballotPage(), {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    return new Response("Not Found", { status: 404 });
  },
};

function ballotPage() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Proxy Voting Ballot - Moody's Corporation</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 0; background: #f5f5f5; color: #333; }
  .container { max-width: 900px; margin: 20px auto; background: white;
               border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow: hidden; }
  .header { background: #037DAE; color: white; padding: 24px 32px; }
  .header h1 { margin: 0 0 8px; font-size: 24px; }
  .header .meta { font-size: 14px; opacity: 0.9; }
  .content { padding: 24px 32px; }
  .info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px;
               margin: 16px 0 24px; font-size: 14px; }
  .info-grid dt { font-weight: 600; color: #555; }
  .info-grid dd { margin: 0; }
  .proposal { margin: 24px 0; padding: 16px; border: 1px solid #dee2e6; border-radius: 6px; }
  .proposal h3 { margin: 0 0 4px; font-size: 16px; }
  .proposal .description { color: #555; font-size: 14px; margin: 0 0 12px; }
  .proposal .board-rec { font-size: 13px; color: #037DAE; font-weight: 600; margin-bottom: 8px; }
  .vote-options { display: flex; gap: 20px; flex-wrap: wrap; }
  .vote-option { display: flex; align-items: center; gap: 6px; }
  .vote-option label { cursor: pointer; font-size: 14px; }
  .nominee-row { display: flex; align-items: center; justify-content: space-between;
                 padding: 8px 0; border-bottom: 1px solid #f0f0f0; }
  .nominee-name { font-size: 14px; min-width: 200px; }
  .docs { margin: 24px 0; padding: 16px; background: #f8f9fa; border-radius: 6px; }
  .docs h3 { margin: 0 0 8px; font-size: 15px; }
  .docs a { color: #037DAE; text-decoration: none; margin-right: 16px; }
  .docs a:hover { text-decoration: underline; }
  .submit-section { text-align: center; padding: 24px; border-top: 1px solid #dee2e6; }
  #submit-vote { background: #037DAE; color: white; border: none; padding: 12px 48px;
                 font-size: 16px; border-radius: 6px; cursor: pointer; font-weight: 600; }
  #submit-vote:hover { background: #025f88; }
  .footer { padding: 16px 32px; background: #f8f9fa; font-size: 13px; color: #666;
            border-top: 1px solid #dee2e6; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Moody's Corporation</h1>
    <div class="meta">Annual Meeting of Shareholders &bull; Proxy Voting Ballot</div>
  </div>

  <div class="content">
    <dl class="info-grid">
      <dt>Meeting Date</dt>
      <dd>April 22, 2026</dd>
      <dt>Voting Deadline</dt>
      <dd>April 21, 2026, 11:59 PM ET</dd>
      <dt>Control Number</dt>
      <dd>999999999999</dd>
      <dt>CUSIP</dt>
      <dd>615369105</dd>
      <dt>Shares Available to Vote</dt>
      <dd>150</dd>
      <dt>Record Date</dt>
      <dd>February 28, 2026</dd>
    </dl>

    <div class="docs">
      <h3>Proxy Materials</h3>
      <a href="/proxy-statement">Proxy Statement</a>
      <a href="/annual-report">2025 Annual Report</a>
    </div>

    <form method="POST" action="/">

      <div class="proposal">
        <h3>Proposal 1 &mdash; Election of Directors</h3>
        <p class="description">The Board of Directors recommends a vote FOR each of the following nominees for a one-year term expiring at the 2027 Annual Meeting.</p>
        <p class="board-rec">Board Recommendation: FOR each nominee</p>

        <div class="nominee-row">
          <span class="nominee-name">1a. Basil L. Anderson</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1a" value="for" id="p1a_for">
              <label for="p1a_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1a" value="withhold" id="p1a_withhold">
              <label for="p1a_withhold">Withhold</label>
            </div>
          </div>
        </div>

        <div class="nominee-row">
          <span class="nominee-name">1b. Jorge A. Bermudez</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1b" value="for" id="p1b_for">
              <label for="p1b_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1b" value="withhold" id="p1b_withhold">
              <label for="p1b_withhold">Withhold</label>
            </div>
          </div>
        </div>

        <div class="nominee-row">
          <span class="nominee-name">1c. Therese M. Esperdy</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1c" value="for" id="p1c_for">
              <label for="p1c_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1c" value="withhold" id="p1c_withhold">
              <label for="p1c_withhold">Withhold</label>
            </div>
          </div>
        </div>

        <div class="nominee-row">
          <span class="nominee-name">1d. Vincent A. Forlenza</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1d" value="for" id="p1d_for">
              <label for="p1d_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1d" value="withhold" id="p1d_withhold">
              <label for="p1d_withhold">Withhold</label>
            </div>
          </div>
        </div>

        <div class="nominee-row">
          <span class="nominee-name">1e. Kathryn M. Hill</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1e" value="for" id="p1e_for">
              <label for="p1e_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1e" value="withhold" id="p1e_withhold">
              <label for="p1e_withhold">Withhold</label>
            </div>
          </div>
        </div>

        <div class="nominee-row">
          <span class="nominee-name">1f. Robert Fauber</span>
          <div class="vote-options">
            <div class="vote-option">
              <input type="radio" name="proposal_1f" value="for" id="p1f_for">
              <label for="p1f_for">For</label>
            </div>
            <div class="vote-option">
              <input type="radio" name="proposal_1f" value="withhold" id="p1f_withhold">
              <label for="p1f_withhold">Withhold</label>
            </div>
          </div>
        </div>
      </div>

      <div class="proposal">
        <h3>Proposal 2 &mdash; Ratification of Independent Registered Public Accounting Firm</h3>
        <p class="description">Ratify the appointment of PricewaterhouseCoopers LLP as Moody's independent registered public accounting firm for fiscal year 2026.</p>
        <p class="board-rec">Board Recommendation: FOR</p>
        <div class="vote-options">
          <div class="vote-option">
            <input type="radio" name="proposal_2" value="for" id="p2_for">
            <label for="p2_for">For</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_2" value="against" id="p2_against">
            <label for="p2_against">Against</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_2" value="abstain" id="p2_abstain">
            <label for="p2_abstain">Abstain</label>
          </div>
        </div>
      </div>

      <div class="proposal">
        <h3>Proposal 3 &mdash; Advisory Vote on Executive Compensation (Say-on-Pay)</h3>
        <p class="description">Approve, on a non-binding advisory basis, the compensation of Moody's named executive officers as disclosed in the proxy statement.</p>
        <p class="board-rec">Board Recommendation: FOR</p>
        <div class="vote-options">
          <div class="vote-option">
            <input type="radio" name="proposal_3" value="for" id="p3_for">
            <label for="p3_for">For</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_3" value="against" id="p3_against">
            <label for="p3_against">Against</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_3" value="abstain" id="p3_abstain">
            <label for="p3_abstain">Abstain</label>
          </div>
        </div>
      </div>

      <div class="proposal">
        <h3>Proposal 4 &mdash; Shareholder Proposal: Report on Lobbying Expenditures</h3>
        <p class="description">A shareholder proposal requesting the Board to prepare and publish annually a report disclosing Moody's lobbying policies, procedures, payments, and expenditures.</p>
        <p class="board-rec">Board Recommendation: AGAINST</p>
        <div class="vote-options">
          <div class="vote-option">
            <input type="radio" name="proposal_4" value="for" id="p4_for">
            <label for="p4_for">For</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_4" value="against" id="p4_against">
            <label for="p4_against">Against</label>
          </div>
          <div class="vote-option">
            <input type="radio" name="proposal_4" value="abstain" id="p4_abstain">
            <label for="p4_abstain">Abstain</label>
          </div>
        </div>
      </div>

      <div class="submit-section">
        <button type="submit" id="submit-vote">Submit Vote</button>
      </div>

    </form>
  </div>

  <div class="footer">
    <p>This is a test ballot page for Proxy Voter end-to-end testing.</p>
    <p>Control Number: 999999999999 &bull; CUSIP: 615369105</p>
  </div>
</div>
</body>
</html>`;
}

function confirmationPage() {
  const now = new Date().toISOString();
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Vote Confirmation - Moody's Corporation</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         margin: 0; padding: 0; background: #f5f5f5; color: #333; }
  .container { max-width: 600px; margin: 40px auto; background: white;
               border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
               padding: 32px; text-align: center; }
  .checkmark { font-size: 48px; margin-bottom: 16px; }
  h1 { color: #28a745; font-size: 22px; }
  .details { text-align: left; margin: 24px 0; padding: 16px; background: #f8f9fa;
             border-radius: 6px; font-size: 14px; }
  .details dt { font-weight: 600; color: #555; margin-top: 8px; }
  .details dd { margin: 2px 0 0 0; }
</style>
</head>
<body>
<div class="container">
  <div class="checkmark">&#10003;</div>
  <h1>Your vote has been successfully submitted.</h1>
  <p>Thank you for voting your shares of Moody's Corporation.</p>
  <dl class="details">
    <dt>Confirmation Number</dt>
    <dd>TEST-2026-MCO-001</dd>
    <dt>Company</dt>
    <dd>Moody's Corporation</dd>
    <dt>Control Number</dt>
    <dd>999999999999</dd>
    <dt>Date Submitted</dt>
    <dd>${now}</dd>
    <dt>Shares Voted</dt>
    <dd>150</dd>
  </dl>
  <p>A confirmation email will be sent to the address on file.</p>
</div>
</body>
</html>`;
}

function proxyStatementPage() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Proxy Statement - Moody's Corporation</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
</style>
</head>
<body>
<h1>Moody's Corporation - 2026 Proxy Statement</h1>
<p>This is a placeholder proxy statement for end-to-end testing of Proxy Voter.</p>
<h2>Annual Meeting of Shareholders</h2>
<p>Date: April 22, 2026</p>
<p>Location: 7 World Trade Center, New York, NY 10007</p>
<h2>Proposals</h2>
<ol>
  <li>Election of six directors for a one-year term</li>
  <li>Ratification of PricewaterhouseCoopers LLP as independent auditor</li>
  <li>Advisory vote on executive compensation</li>
  <li>Shareholder proposal regarding lobbying expenditure disclosure</li>
</ol>
</body>
</html>`;
}

function annualReportPage() {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Annual Report - Moody's Corporation</title>
<style>
  body { font-family: -apple-system, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; }
</style>
</head>
<body>
<h1>Moody's Corporation - 2025 Annual Report</h1>
<p>This is a placeholder annual report for end-to-end testing of Proxy Voter.</p>
<h2>Financial Highlights</h2>
<p>Revenue: $7.1 billion (2025)</p>
<p>Moody's Corporation (NYSE: MCO) is a global integrated risk assessment firm.</p>
</body>
</html>`;
}
