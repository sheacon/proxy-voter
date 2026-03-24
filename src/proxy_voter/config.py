from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str
    resend_api_key: str
    webhook_secret: str
    from_email: str
    claude_model: str = "claude-sonnet-4-6"
    claude_voter_model: str = "claude-haiku-4-5"
    database_path: str = "data/proxy_voter.db"
    approved_senders: str = ""
    policy_preferences_path: str = "policy-preferences.md"
    test_ballot_url: str = ""

    def load_approved_senders(self) -> set[str]:
        if not self.approved_senders.strip():
            return set()
        return {addr.strip().lower() for addr in self.approved_senders.split(",") if addr.strip()}

    def load_policy_preferences(self) -> str:
        path = Path(self.policy_preferences_path)
        if not path.exists():
            return ""
        return path.read_text().strip()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
