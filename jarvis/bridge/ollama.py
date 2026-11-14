"""Ollama client for local LLM inference."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class OllamaConfig:
    """Ollama configuration."""
    host: str = "http://localhost:11434"
    model: str = "llama3.1"
    temperature: float = 0.7
    top_p: float = 0.9
    num_ctx: int = 4096
    num_predict: int = 2048
    keep_alive: str = "5m"  # Keep model loaded


class OllamaClient:
    """Async client for Ollama API."""

    def __init__(self, config: Optional[OllamaConfig] = None):
        self.config = config or OllamaConfig()
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            await self._session.close()

    async def _ensure_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

    async def is_available(self) -> bool:
        """Check if Ollama is running."""
        await self._ensure_session()
        try:
            async with self._session.get(f"{self.config.host}/api/tags", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def list_models(self) -> list[str]:
        """List available models."""
        await self._ensure_session()
        try:
            async with self._session.get(f"{self.config.host}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"[ollama] Failed to list models: {e}")
        return []

    async def pull_model(self, model: str) -> bool:
        """Pull a model if not available."""
        await self._ensure_session()
        try:
            async with self._session.post(
                f"{self.config.host}/api/pull",
                json={"name": model, "stream": False},
                timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"[ollama] Failed to pull model {model}: {e}")
            return False

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        **kwargs
    ) -> dict:
        """Send chat completion request."""
        await self._ensure_session()

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "num_ctx": kwargs.get("num_ctx", self.config.num_ctx),
                "num_predict": kwargs.get("num_predict", self.config.num_predict),
                "keep_alive": kwargs.get("keep_alive", self.config.keep_alive),
            }
        }

        if tools:
            payload["tools"] = tools

        try:
            async with self._session.post(
                f"{self.config.host}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"[ollama] Chat error: {error}")
                    return {"error": error}

                if stream:
                    return await self._handle_stream(resp)
                else:
                    return await resp.json()

        except asyncio.TimeoutError:
            logger.error("[ollama] Request timed out")
            return {"error": "Request timed out"}
        except Exception as e:
            logger.error(f"[ollama] Chat error: {e}")
            return {"error": str(e)}

    async def _handle_stream(self, resp: aiohttp.ClientResponse) -> dict:
        """Handle streaming response."""
        content = ""
        async for line in resp.content:
            if line:
                try:
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        content += chunk["message"]["content"]
                    if chunk.get("done"):
                        break
                except json.JSONDecodeError:
                    continue
        return {"message": {"content": content, "role": "assistant"}}

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs
    ) -> dict:
        """Simple text generation (non-chat)."""
        await self._ensure_session()

        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.config.temperature),
                "top_p": kwargs.get("top_p", self.config.top_p),
                "num_ctx": kwargs.get("num_ctx", self.config.num_ctx),
                "num_predict": kwargs.get("num_predict", self.config.num_predict),
                "keep_alive": kwargs.get("keep_alive", self.config.keep_alive),
            }
        }

        if system:
            payload["system"] = system

        try:
            async with self._session.post(
                f"{self.config.host}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"[ollama] Generate error: {error}")
                    return {"error": error}
                return await resp.json()
        except Exception as e:
            logger.error(f"[ollama] Generate error: {e}")
            return {"error": str(e)}


async def create_ollama_client(
    model: str = "llama3.1",
    host: str = "http://localhost:11434"
) -> Optional[OllamaClient]:
    """Factory to create and verify Ollama client."""
    config = OllamaConfig(host=host, model=model)
    client = OllamaClient(config)

    if await client.is_available():
        models = await client.list_models()
        if model not in models:
            logger.info(f"[ollama] Model {model} not found, attempting to pull...")
            await client.pull_model(model)
        logger.info(f"[ollama] Connected to {host}, model: {model}")
        return client
    else:
        logger.warning(f"[ollama] Ollama not available at {host}")
        return None