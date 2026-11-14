"""Application settings with Pydantic."""

from pathlib import Path
from typing import Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os


class GmailAccountSettings(BaseSettings):
    """Single Gmail account configuration."""

    email: str
    # Credentials loaded from secrets manager
    credentials_path: Optional[Path] = None
    token_path: Optional[Path] = None

    model_config = SettingsConfigDict(extra="ignore")


class GoogleCloudSettings(BaseSettings):
    """Google Cloud OAuth settings (shared across accounts)."""

    client_id: str
    client_secret: str
    project_id: str
    redirect_uris: list[str] = ["http://localhost:8080/oauth2callback"]

    model_config = SettingsConfigDict(extra="ignore")


class GitHubSettings(BaseSettings):
    """GitHub integration settings."""

    token: str = ""  # From secrets
    default_org: Optional[str] = None
    auto_commit: bool = True
    auto_push: bool = True

    model_config = SettingsConfigDict(extra="ignore")


class FinanceSettings(BaseSettings):
    """Finance management settings."""

    # Plaid (optional)
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"  # sandbox, development, production
    # Manual tracking
    default_currency: str = "USD"
    budget_alerts: bool = True

    model_config = SettingsConfigDict(extra="ignore")


class VoiceSettings(BaseSettings):
    """Voice interaction settings (for later)."""

    stt_model: str = "base"  # tiny, base, small, medium, large
    tts_voice: str = "default"
    wake_word: str = "jarvis"
    language: str = "en"

    model_config = SettingsConfigDict(extra="ignore")


class AppControlSettings(BaseSettings):
    """macOS app control settings."""

    accessibility_enabled: bool = True
    screen_recording_enabled: bool = False
    allowed_apps: list[str] = Field(default_factory=lambda: [
        "Finder", "Safari", "Chrome", "Terminal", "VSCode", "Cursor",
        "Notes", "Mail", "Calendar", "Reminders", "Messages"
    ])

    model_config = SettingsConfigDict(extra="ignore")


class MCPServerSettings(BaseSettings):
    """MCP server configuration."""

    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class Settings(BaseSettings):
    """Main Jarvis settings."""

    # Paths
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".jarvis")
    logs_dir: Path = Field(default_factory=lambda: Path.home() / ".jarvis" / "logs")
    plugins_dir: Path = Field(default_factory=lambda: Path.home() / ".jarvis" / "plugins")

    # Core
    debug: bool = False
    log_level: str = "INFO"
    timezone: str = "America/New_York"

    # Integrations
    gmail_accounts: list[GmailAccountSettings] = Field(default_factory=list)
    google_cloud: Optional[GoogleCloudSettings] = None
    github: GitHubSettings = Field(default_factory=GitHubSettings)
    finance: FinanceSettings = Field(default_factory=FinanceSettings)
    voice: VoiceSettings = Field(default_factory=VoiceSettings)
    app_control: AppControlSettings = Field(default_factory=AppControlSettings)

    # MCP Servers
    mcp_servers: list[MCPServerSettings] = Field(default_factory=list)

    # Agent behavior
    max_concurrent_tasks: int = 5
    default_timeout: int = 300
    auto_approve_safe_ops: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @field_validator("data_dir", "logs_dir", "plugins_dir", mode="before")
    @classmethod
    def expand_path(cls, v: str | Path) -> Path:
        return Path(v).expanduser().resolve()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Load .env explicitly to get flat vars into os.environ
        load_dotenv(override=True)
        # Build google_cloud from flat env vars if not set via nested
        if self.google_cloud is None:
            client_id = os.getenv("GOOGLE_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
            project_id = os.getenv("GOOGLE_PROJECT_ID")
            if client_id and client_secret and project_id:
                self.google_cloud = GoogleCloudSettings(
                    client_id=client_id,
                    client_secret=client_secret,
                    project_id=project_id,
                )
        # Ensure directories exist
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)


# Singleton instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reload_settings() -> Settings:
    """Force reload settings from environment."""
    global _settings
    _settings = Settings()
    return _settings