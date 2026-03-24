"""Smoke tests that every module imports without crashing.

Catches syntax errors, bad regex patterns, missing constants, and circular imports
at the module level — like the (?i) regex crash in researcher.py that took down prod.
"""


def test_import_config():
    from proxy_voter.config import Settings, get_settings  # noqa: F401


def test_import_models():
    from proxy_voter.models import (  # noqa: F401
        BallotData,
        EmailType,
        ParsedEmail,
        SessionStatus,
        UsageStats,
        VotingDecision,
    )


def test_import_email_parser():
    from proxy_voter.email_parser import SESSION_ID_PATTERN, URL_PATTERN  # noqa: F401

    # Verify regexes compiled
    assert SESSION_ID_PATTERN.pattern
    assert URL_PATTERN.pattern


def test_import_researcher():
    # Verify all regexes compiled successfully
    import re

    from proxy_voter.researcher import (  # noqa: F401
        _BARE_URL_RE,
        _BLANK_LINES_RE,
        _BOILERPLATE_RE,
        _SEPARATOR_RE,
        VOTING_DECISIONS_TOOL,
    )

    for obj in (_BOILERPLATE_RE, _SEPARATOR_RE, _BLANK_LINES_RE, _BARE_URL_RE):
        assert isinstance(obj, re.Pattern)


def test_import_voter():
    from proxy_voter.voter import VOTE_ACTION_TOOL, VOTING_PROMPT  # noqa: F401

    assert isinstance(VOTING_PROMPT, str)
    assert isinstance(VOTE_ACTION_TOOL, dict)


def test_import_notifier():
    import proxy_voter.notifier  # noqa: F401


def test_import_scraper():
    from proxy_voter.scraper import BallotSession  # noqa: F401


def test_import_storage():
    from proxy_voter.storage import _CREATE_TABLE  # noqa: F401

    assert "CREATE TABLE" in _CREATE_TABLE


def test_import_webhook():
    from fastapi import APIRouter

    from proxy_voter.webhook import router  # noqa: F401

    assert isinstance(router, APIRouter)


def test_import_main():
    from fastapi import FastAPI

    from proxy_voter.main import app  # noqa: F401

    assert isinstance(app, FastAPI)
