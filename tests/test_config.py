import proxy_voter.config
from proxy_voter.config import get_settings


class TestSettings:
    def test_defaults(self):
        s = get_settings()
        assert s.claude_model == "claude-sonnet-4-6"
        assert s.database_path == "test_data/proxy_voter.db"  # from conftest env
        assert s.policy_preferences_path == "policy-preferences.md"

    def test_loads_from_env(self):
        s = get_settings()
        assert s.anthropic_api_key == "test-key"
        assert s.resend_api_key == "test-key"
        assert s.webhook_secret == "test-secret"
        assert s.from_email == "proxy-voter@example.com"


class TestLoadApprovedSenders:
    def test_multiple(self, monkeypatch):
        monkeypatch.setenv("APPROVED_SENDERS", "a@b.com, C@D.com")
        proxy_voter.config._settings = None
        result = get_settings().load_approved_senders()
        assert result == {"a@b.com", "c@d.com"}

    def test_empty(self, monkeypatch):
        monkeypatch.setenv("APPROVED_SENDERS", "")
        proxy_voter.config._settings = None
        assert get_settings().load_approved_senders() == set()

    def test_whitespace_only(self, monkeypatch):
        monkeypatch.setenv("APPROVED_SENDERS", "  ,  , ")
        proxy_voter.config._settings = None
        assert get_settings().load_approved_senders() == set()

    def test_single(self, monkeypatch):
        monkeypatch.setenv("APPROVED_SENDERS", "one@test.com")
        proxy_voter.config._settings = None
        assert get_settings().load_approved_senders() == {"one@test.com"}


class TestLoadPolicyPreferences:
    def test_existing_file(self, tmp_path, monkeypatch):
        pf = tmp_path / "policy.md"
        pf.write_text("  Vote for shareholder value.  \n")
        monkeypatch.setenv("POLICY_PREFERENCES_PATH", str(pf))
        proxy_voter.config._settings = None
        assert get_settings().load_policy_preferences() == "Vote for shareholder value."

    def test_missing_file(self, monkeypatch):
        monkeypatch.setenv("POLICY_PREFERENCES_PATH", "/nonexistent/policy.md")
        proxy_voter.config._settings = None
        assert get_settings().load_policy_preferences() == ""


class TestGetSettings:
    def test_caches_singleton(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_resets_after_clear(self):
        s1 = get_settings()
        proxy_voter.config._settings = None
        s2 = get_settings()
        assert s1 is not s2
