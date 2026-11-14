"""LLM integration for natural language understanding."""

import asyncio
import json
import os
from abc import ABC, abstractmethod
from typing import Any, Optional
from dataclasses import dataclass
from loguru import logger


@dataclass
class LLMMessage:
    """A message in the conversation."""
    role: str  # system, user, assistant, tool
    content: str
    tool_calls: list[dict] = None
    tool_call_id: str = None


@dataclass
class LLMResponse:
    """Response from LLM."""
    content: str
    tool_calls: list[dict] = None
    usage: dict = None


class LLMProvider(ABC):
    """Abstract LLM provider."""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> LLMResponse:
        """Send chat completion request."""
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get model identifier."""
        pass


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    def __init__(self, api_key: str = None, model: str = "gpt-4o", base_url: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model
        self.base_url = base_url or "https://api.openai.com/v1"
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import openai
                self._client = openai.AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except ImportError:
                raise RuntimeError("openai package not installed. Run: pip install openai")
        return self._client

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> LLMResponse:
        client = self._get_client()

        formatted = [{"role": m.role, "content": m.content} for m in messages]
        for m in messages:
            if m.tool_calls:
                formatted[-1]["tool_calls"] = m.tool_calls
            if m.tool_call_id:
                formatted[-1]["tool_call_id"] = m.tool_call_id

        response = await client.chat.completions.create(
            model=self.model,
            messages=formatted,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        msg = response.choices[0].message
        return LLMResponse(
            content=msg.content or "",
            tool_calls=msg.tool_calls,
            usage=response.usage.model_dump() if response.usage else None,
        )

    def get_model_name(self) -> str:
        return f"openai/{self.model}"


class AnthropicProvider(LLMProvider):
    """Anthropic API provider."""

    def __init__(self, api_key: str = None, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model = model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError:
                raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> LLMResponse:
        client = self._get_client()

        # Convert to Anthropic format
        system = ""
        formatted = []
        for m in messages:
            if m.role == "system":
                system = m.content
            elif m.role == "tool":
                formatted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_call_id,
                            "content": m.content,
                        }
                    ]
                })
            else:
                formatted.append({"role": m.role, "content": m.content})

        # Convert tools
        anthropic_tools = None
        if tools:
            anthropic_tools = []
            for t in tools:
                fn = t.get("function", {})
                anthropic_tools.append({
                    "name": fn.get("name"),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                })

        response = await client.messages.create(
            model=self.model,
            system=system,
            messages=formatted,
            tools=anthropic_tools,
            tool_choice={"type": "auto"} if tool_choice == "auto" else tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input),
                    }
                })

        return LLMResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage={"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens},
        )

    def get_model_name(self) -> str:
        return f"anthropic/{self.model}"


class OllamaProvider(LLMProvider):
    """Local Ollama provider."""

    def __init__(self, model: str = "llama3.1", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
        self._session = None

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the aiohttp session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] = None,
        tool_choice: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> LLMResponse:
        session = await self._get_session()

        # Convert messages to Ollama format
        formatted = []
        for m in messages:
            if m.role == "system":
                formatted.append({"role": "system", "content": m.content})
            elif m.role == "tool":
                formatted.append({"role": "tool", "content": m.content, "tool_call_id": m.tool_call_id})
            elif m.role == "assistant" and m.tool_calls:
                # Assistant message with tool calls - convert to Ollama format
                ollama_tool_calls = []
                for tc in m.tool_calls:
                    func = tc.get("function", {})
                    if func.get("name"):
                        # Parse arguments from JSON string to object
                        args = func.get("arguments", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except:
                                args = {}
                        ollama_tool_calls.append({
                            "function": {
                                "name": func["name"],
                                "arguments": args,
                            }
                        })
                formatted.append({
                    "role": "assistant",
                    "content": m.content or "",
                    "tool_calls": ollama_tool_calls if ollama_tool_calls else None
                })
            else:
                formatted.append({"role": m.role, "content": m.content})

        # Convert tools to Ollama format
        ollama_tools = None
        if tools:
            ollama_tools = []
            for t in tools:
                fn = t.get("function", {})
                # Ensure parameters is a proper JSON schema
                params = fn.get("parameters", {})
                if not params:
                    params = {"type": "object", "properties": {}}
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": fn.get("name"),
                        "description": fn.get("description", ""),
                        "parameters": params,
                    }
                })

        payload = {
            "model": self.model,
            "messages": formatted,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        if ollama_tools:
            payload["tools"] = ollama_tools
            # Force tool use when tools are available
            payload["tool_choice"] = "auto" if tool_choice == "auto" else tool_choice

        # Debug: print payload size
            import sys
            # Log payload for debugging
            logger.debug(f"Ollama payload: {len(str(payload))} chars, tools: {len(ollama_tools) if ollama_tools else 0}")

            async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                if resp.status == 404:
                    # Model not found
                    error_text = await resp.text()
                    raise RuntimeError(f"Ollama model '{self.model}' not found. Run: ollama pull {self.model}")
                elif resp.status != 200:
                    error_text = await resp.text()
                    logger.error(f"Ollama error response: {error_text}")
                    raise RuntimeError(f"Ollama error ({resp.status}): {error_text}")

                data = await resp.json()

            # Check for error in response
            if "error" in data:
                raise RuntimeError(f"Ollama error: {data['error']}")

            message = data.get("message", {})
            content = message.get("content", "")

            # Parse tool calls from Ollama response
            tool_calls = []
            if "tool_calls" in message:
                for tc in message["tool_calls"]:
                    # Ollama format: {id, function: {name, arguments}}
                    # No "type" field, arguments is already a dict
                    try:
                        func = tc.get("function", {})
                        if func.get("name"):
                            args = func.get("arguments", {})
                            # Ensure arguments is a JSON string
                            if isinstance(args, dict):
                                args = json.dumps(args)
                            tool_calls.append({
                                "id": tc.get("id", f"call_{len(tool_calls)}"),
                                "type": "function",
                                "function": {
                                    "name": func["name"],
                                    "arguments": args,
                                }
                            })
                    except Exception as e:
                        logger.warning(f"Failed to parse tool call: {e}")
                        continue

        return LLMResponse(content=content, tool_calls=tool_calls if tool_calls else None)

    def get_model_name(self) -> str:
        return f"ollama/{self.model}"


class LLMManager:
    """Manages LLM providers and conversations."""

    def __init__(self):
        self.providers: dict[str, LLMProvider] = {}
        self.default_provider: Optional[str] = None
        self.conversation_history: list[LLMMessage] = []

    def add_provider(self, name: str, provider: LLMProvider, default: bool = False):
        """Add an LLM provider."""
        self.providers[name] = provider
        if default or self.default_provider is None:
            self.default_provider = name

    async def close(self):
        """Close all provider sessions."""
        for provider in self.providers.values():
            if hasattr(provider, 'close'):
                await provider.close()

    def get_provider(self, name: str = None) -> LLMProvider:
        """Get a provider by name."""
        name = name or self.default_provider
        if not name or name not in self.providers:
            raise ValueError(f"No provider '{name}' available. Available: {list(self.providers.keys())}")
        return self.providers[name]

    async def chat(
        self,
        messages: list[LLMMessage],
        provider: str = None,
        tools: list[dict] = None,
        **kwargs
    ) -> LLMResponse:
        """Chat with the LLM."""
        llm = self.get_provider(provider)
        return await llm.chat(messages, tools, **kwargs)

    def add_system_prompt(self, prompt: str):
        """Add system prompt to conversation."""
        self.conversation_history.insert(0, LLMMessage(role="system", content=prompt))

    def add_user_message(self, content: str):
        """Add user message to conversation."""
        self.conversation_history.append(LLMMessage(role="user", content=content))

    def add_assistant_message(self, content: str, tool_calls: list[dict] = None):
        """Add assistant message to conversation."""
        self.conversation_history.append(LLMMessage(role="assistant", content=content, tool_calls=tool_calls))

    def add_tool_result(self, tool_call_id: str, content: str):
        """Add tool result to conversation."""
        self.conversation_history.append(LLMMessage(role="tool", content=content, tool_call_id=tool_call_id))

    def get_history(self) -> list[LLMMessage]:
        return self.conversation_history.copy()

    def clear_history(self, keep_system: bool = True):
        """Clear conversation history."""
        if keep_system:
            system_msgs = [m for m in self.conversation_history if m.role == "system"]
            self.conversation_history = system_msgs
        else:
            self.conversation_history = []


# Jarvis tools that the LLM can call
JARVIS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_emails",
            "description": "List emails from Gmail accounts",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Specific account email, or empty for all"},
                    "query": {"type": "string", "description": "Gmail search query (e.g., 'is:unread', 'from:teacher')"},
                    "max_results": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_emails",
            "description": "Analyze emails for assignments, deadlines, action items using AI",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Specific account email, or empty for all"},
                    "query": {"type": "string", "description": "Gmail search query", "default": "is:unread"},
                    "max_results": {"type": "integer", "default": 20},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_calendar_events",
            "description": "List upcoming calendar events",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Specific account email"},
                    "days_ahead": {"type": "integer", "default": 7},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "account": {"type": "string", "description": "Account email"},
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO format: 2024-01-15T10:00:00"},
                    "end_time": {"type": "string", "description": "ISO format: 2024-01-15T11:00:00"},
                    "description": {"type": "string", "default": ""},
                },
                "required": ["account", "title", "start_time", "end_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_reminder",
            "description": "Create a reminder",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "message": {"type": "string"},
                    "trigger_at": {"type": "string", "description": "ISO format datetime"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "default": "normal"},
                },
                "required": ["title", "message", "trigger_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_reminders",
            "description": "List upcoming reminders",
            "parameters": {
                "type": "object",
                "properties": {
                    "hours_ahead": {"type": "integer", "default": 24},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_github_repos",
            "description": "List GitHub repositories",
            "parameters": {
                "type": "object",
                "properties": {
                    "org": {"type": "string", "description": "Organization name (optional)"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_github_readme",
            "description": "Create a README for a repository",
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Full repo name (owner/repo)"},
                    "title": {"type": "string"},
                    "description": {"type": "string", "default": ""},
                },
                "required": ["repo", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_app_command",
            "description": "Run macOS app automation (launch, quit, type, click, notify, open_url)",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["launch", "quit", "type", "click", "notify", "open_url"]},
                    "app": {"type": "string", "description": "App name"},
                    "text": {"type": "string", "description": "Text to type (for type action)"},
                    "x": {"type": "integer", "description": "X coordinate (for click)"},
                    "y": {"type": "integer", "description": "Y coordinate (for click)"},
                    "title": {"type": "string", "description": "Notification title"},
                    "message": {"type": "string", "description": "Notification message"},
                    "url": {"type": "string", "description": "URL to open (for open_url action)"},
                    "browser": {"type": "string", "description": "Browser to use (for open_url action)", "default": "Safari"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search local files",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string", "default": "~"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a local file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a local file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def create_llm_manager() -> LLMManager:
    """Create LLM manager with configured providers."""
    manager = LLMManager()

    # Try to add providers based on env vars
    if os.getenv("OPENAI_API_KEY"):
        manager.add_provider("openai", OpenAIProvider(), default=True)

    if os.getenv("ANTHROPIC_API_KEY"):
        manager.add_provider("anthropic", AnthropicProvider(), default=not manager.default_provider)

    # Always try Ollama (local)
    try:
        manager.add_provider("ollama", OllamaProvider(), default=not manager.default_provider)
    except Exception:
        pass

    return manager