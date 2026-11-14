"""Integration plugins for external services."""

from .gmail import GmailPlugin
from .calendar import CalendarPlugin
from .files import FilesPlugin
from .github import GitHubPlugin
from .finance import FinancePlugin
from .app_control import AppControlPlugin
from .reminders import RemindersPlugin
from .llm import LLMManager, LLMProvider, OpenAIProvider, AnthropicProvider, OllamaProvider, JARVIS_TOOLS, create_llm_manager

__all__ = [
    "GmailPlugin",
    "CalendarPlugin",
    "FilesPlugin",
    "GitHubPlugin",
    "FinancePlugin",
    "AppControlPlugin",
    "RemindersPlugin",
    "LLMManager",
    "LLMProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "JARVIS_TOOLS",
    "create_llm_manager",
]