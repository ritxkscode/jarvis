"""Jarvis Bridge Server - WebSocket server for voice-first AI assistant."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import aiohttp
from aiohttp import web
from aiohttp_cors import setup as setup_cors, ResourceOptions
from loguru import logger

from ..config.settings import get_settings
from ..config.secrets import get_secrets_manager
from .ollama import OllamaClient, OllamaConfig, create_ollama_client


@dataclass
class BridgeConfig:
    """Bridge configuration from environment."""
    host: str = "127.0.0.1"
    port: int = 8787
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    allowed_hosts: list[str] = field(default_factory=lambda: ["localhost", "127.0.0.1"])
    model: str = "claude-opus-5"
    effort: str = "medium"
    allow_writes: bool = False
    mcp_servers: Optional[str] = None  # comma-separated, or None for all
    account_connectors: bool = False
    workspace: str = "~/.jarvis/workspace"
    file_roots: Optional[str] = None
    keep_transcripts: bool = False
    debug: bool = False
    claude_executable: str = "claude"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    # Ollama settings
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    use_ollama: bool = False

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        """Load configuration from environment variables."""
        def get_bool(key: str, default: bool = False) -> bool:
            val = os.environ.get(key, "").lower()
            return val in ("1", "true", "yes", "on") if val else default

        def get_list(key: str, default: list[str]) -> list[str]:
            val = os.environ.get(key, "")
            return [x.strip() for x in val.split(",")] if val else default

        return cls(
            host=os.environ.get("JARVIS_BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("JARVIS_BRIDGE_PORT", "8787")),
            allowed_origins=get_list("JARVIS_ALLOWED_ORIGINS", ["http://localhost:5173", "http://127.0.0.1:5173"]),
            allowed_hosts=get_list("JARVIS_ALLOWED_HOSTS", ["localhost", "127.0.0.1"]),
            model=os.environ.get("JARVIS_MODEL", "claude-opus-5"),
            effort=os.environ.get("JARVIS_EFFORT", "medium"),
            allow_writes=get_bool("JARVIS_ALLOW_WRITES"),
            mcp_servers=os.environ.get("JARVIS_MCP_SERVERS") or None,
            account_connectors=get_bool("JARVIS_ACCOUNT_CONNECTORS"),
            workspace=os.environ.get("JARVIS_WORKSPACE", "~/.jarvis/workspace"),
            file_roots=os.environ.get("JARVIS_FILE_ROOTS") or None,
            keep_transcripts=get_bool("JARVIS_KEEP_TRANSCRIPTS"),
            debug=get_bool("JARVIS_DEBUG"),
            claude_executable=os.environ.get("JARVIS_CLAUDE_EXECUTABLE", "claude"),
            elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY") or None,
            elevenlabs_voice_id=os.environ.get("JARVIS_VOICE_ID") or None,
            # Ollama settings
            ollama_host=os.environ.get("JARVIS_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("JARVIS_OLLAMA_MODEL", "llama3.1"),
            use_ollama=get_bool("JARVIS_USE_OLLAMA"),
        )


@dataclass
class ClientSession:
    """Active client WebSocket session."""
    ws: web.WebSocketResponse
    client_id: str
    connected_at: datetime
    authenticated: bool = False
    metadata: dict = field(default_factory=dict)


class BridgeServer:
    """WebSocket bridge server connecting frontend to AI (Claude or Ollama)."""

    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig.from_env()
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.sessions: dict[str, ClientSession] = {}
        self.claude_process: Optional[subprocess.Popen] = None
        self.ollama_client: Optional[OllamaClient] = None
        self._running = False
        self._setup_logging()

    def _setup_logging(self):
        """Configure logging for bridge."""
        if self.config.debug:
            logger.remove()
            logger.add(sys.stderr, level="DEBUG", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
        else:
            logger.remove()
            logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")

    async def start(self) -> None:
        """Start the bridge server."""
        logger.info(f"[jarvis] Starting bridge on {self.config.host}:{self.config.port}")

        # Initialize LLM backend
        if self.config.use_ollama:
            logger.info(f"[jarvis] LLM: Ollama ({self.config.ollama_model} @ {self.config.ollama_host})")
            self.ollama_client = OllamaClient(OllamaConfig(
                host=self.config.ollama_host,
                model=self.config.ollama_model,
            ))
            if await self.ollama_client.is_available():
                models = await self.ollama_client.list_models()
                if self.config.ollama_model not in models:
                    logger.info(f"[jarvis] Pulling model {self.config.ollama_model}...")
                    await self.ollama_client.pull_model(self.config.ollama_model)
                logger.info("[jarvis] Ollama ready")
            else:
                logger.warning("[jarvis] Ollama not available, falling back to Claude CLI")
                self.config.use_ollama = False
        else:
            logger.info(f"[jarvis] LLM: Claude ({self.config.model} · Effort: {self.config.effort})")

        logger.info(f"[jarvis] Writes: {'enabled' if self.config.allow_writes else 'disabled (read-only)'}")
        logger.info(f"[jarvis] MCP servers: {self.config.mcp_servers or 'all configured'}")
        logger.info(f"[jarvis] Account connectors: {'enabled' if self.config.account_connectors else 'disabled'}")
        logger.info(f"[jarvis] Workspace: {self.config.workspace}")

        # Expand workspace path
        workspace = Path(self.config.workspace).expanduser()
        workspace.mkdir(parents=True, exist_ok=True)

        # Create aiohttp app
        self.app = web.Application()
        self._setup_routes()
        self._setup_cors()

        # Start runner
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        self.site = web.TCPSite(self.runner, self.config.host, self.config.port)
        await self.site.start()

        self._running = True
        logger.info(f"[jarvis] Bridge listening on http://{self.config.host}:{self.config.port}")

    async def stop(self) -> None:
        """Stop the bridge server."""
        logger.info("[jarvis] Stopping bridge...")
        self._running = False

        # Close all WebSocket connections
        for session in self.sessions.values():
            await session.ws.close(code=1001, message=b"Server shutting down")
        self.sessions.clear()

        # Stop claude process if running
        if self.claude_process and self.claude_process.poll() is None:
            self.claude_process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.claude_process.wait),
                    timeout=5
                )
            except asyncio.TimeoutError:
                self.claude_process.kill()
                await asyncio.to_thread(self.claude_process.wait)

        # Close Ollama client
        if self.ollama_client and self.ollama_client._session:
            await self.ollama_client._session.close()

        # Stop web server
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()

        logger.info("[jarvis] Bridge stopped")

    def _setup_routes(self):
        """Setup HTTP and WebSocket routes."""
        # Health check
        self.app.router.add_get("/health", self._handle_health)

        # WebSocket endpoint
        self.app.router.add_get("/ws", self._handle_websocket)

        # Static file serving for frontend (production)
        # In dev, frontend runs on separate Vite server

        # File/media proxy endpoints (SSRF guarded)
        self.app.router.add_get("/file", self._handle_file_proxy)
        self.app.router.add_get("/img", self._handle_img_proxy)
        self.app.router.add_get("/media", self._handle_media_proxy)

    def _setup_cors(self):
        """Setup CORS for allowed origins."""
        cors = setup_cors(self.app, defaults={
            origin: ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            ) for origin in self.config.allowed_origins
        })
        # Add CORS to all routes
        for route in list(self.app.router.routes()):
            cors.add(route)

    async def _handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint - reports capabilities."""
        if self.config.use_ollama:
            return web.json_response({
                "ok": True,
                "tts": self.config.elevenlabs_api_key is not None,
                "stt": self.config.elevenlabs_api_key is not None,
                "model": f"ollama/{self.config.ollama_model}",
                "provider": "ollama",
                "writes": self.config.allow_writes,
            })
        return web.json_response({
            "ok": True,
            "tts": self.config.elevenlabs_api_key is not None,
            "stt": self.config.elevenlabs_api_key is not None,
            "model": self.config.model,
            "effort": self.config.effort,
            "provider": "claude",
            "writes": self.config.allow_writes,
        })

    async def _handle_websocket(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection from frontend."""
        # Origin check (DNS rebinding protection)
        origin = request.headers.get("Origin", "")
        if origin and not self._is_allowed_origin(origin):
            logger.warning(f"[jarvis] Rejected connection from unauthorized origin: {origin}")
            return web.Response(status=403, text="Forbidden: Origin not allowed")

        # Host header check
        host = request.headers.get("Host", "")
        if host and not self._is_allowed_host(host):
            logger.warning(f"[jarvis] Rejected connection from unauthorized host: {host}")
            return web.Response(status=403, text="Forbidden: Host not allowed")

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        client_id = str(uuid.uuid4())[:8]
        session = ClientSession(ws=ws, client_id=client_id, connected_at=datetime.now())
        self.sessions[client_id] = session

        logger.info(f"[jarvis] Client connected: {client_id} (origin: {origin})")

        try:
            # Send welcome message
            model_info = f"ollama/{self.config.ollama_model}" if self.config.use_ollama else self.config.model
            await ws.send_json({
                "type": "welcome",
                "client_id": client_id,
                "config": {
                    "tts": self.config.elevenlabs_api_key is not None,
                    "stt": self.config.elevenlabs_api_key is not None,
                    "model": model_info,
                    "writes": self.config.allow_writes,
                }
            })

            # Handle messages
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._handle_message(session, msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"[jarvis] WebSocket error: {ws.exception()}")
                    break

        except Exception as e:
            logger.error(f"[jarvis] Session {client_id} error: {e}")
        finally:
            self.sessions.pop(client_id, None)
            logger.info(f"[jarvis] Client disconnected: {client_id}")

        return ws

    def _is_allowed_origin(self, origin: str) -> bool:
        """Check if origin is allowed."""
        # Allow configured origins
        if origin in self.config.allowed_origins:
            return True
        # Allow localhost variants without port
        if origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"):
            return True
        return False

    def _is_allowed_host(self, host: str) -> bool:
        """Check if host header is allowed."""
        host_lower = host.lower()
        for allowed in self.config.allowed_hosts:
            if host_lower == allowed or host_lower.startswith(allowed + ":"):
                return True
        return False

    async def _handle_message(self, session: ClientSession, data: str):
        """Handle incoming WebSocket message."""
        try:
            msg = json.loads(data)
            msg_type = msg.get("type")

            if msg_type == "ping":
                await session.ws.send_json({"type": "pong"})

            elif msg_type == "voice":
                # Voice audio data from frontend
                await self._handle_voice(session, msg)

            elif msg_type == "tool_call":
                # Tool call from frontend (UI control, etc.)
                await self._handle_tool_call(session, msg)

            elif msg_type == "chat":
                # Text chat message
                await self._handle_chat(session, msg)

            elif msg_type == "auth":
                # Authentication (future)
                session.authenticated = True
                await session.ws.send_json({"type": "auth_ok"})

            else:
                logger.warning(f"[jarvis] Unknown message type: {msg_type}")
                await session.ws.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

        except json.JSONDecodeError:
            logger.warning(f"[jarvis] Invalid JSON from {session.client_id}")
        except Exception as e:
            logger.error(f"[jarvis] Error handling message: {e}")
            await session.ws.send_json({"type": "error", "message": str(e)})

    async def _handle_voice(self, session: ClientSession, msg: dict):
        """Handle voice audio from frontend."""
        # This is where we'd process audio:
        # 1. Receive audio chunks
        # 2. Run VAD (voice activity detection)
        # 3. Send to STT (ElevenLabs or browser)
        # 4. Process transcript with LLM
        # 5. Get response, send to TTS
        # 6. Stream audio back to frontend

        action = msg.get("action")

        if action == "start":
            # Start listening
            await session.ws.send_json({"type": "voice", "action": "listening"})

        elif action == "stop":
            # Stop listening, process
            audio_data = msg.get("audio")  # base64 encoded
            if audio_data:
                transcript = await self._transcribe_audio(audio_data)
                if transcript:
                    # Process with LLM
                    response = await self._process_with_llm(transcript, session)
                    # Send response back
                    await session.ws.send_json({
                        "type": "voice",
                        "action": "response",
                        "transcript": transcript,
                        "response": response
                    })

        elif action == "audio_chunk":
            # Streaming audio chunk - buffer for VAD
            pass

    async def _transcribe_audio(self, audio_base64: str) -> Optional[str]:
        """Transcribe audio using ElevenLabs or return None for browser STT."""
        if self.config.elevenlabs_api_key:
            # TODO: Call ElevenLabs Scribe API
            logger.debug("[jarvis] Would call ElevenLabs STT")
            return None  # Fallback to browser for now
        return None  # Browser handles STT

    async def _process_with_llm(self, prompt: str, session: ClientSession) -> str:
        """Process prompt with configured LLM (Ollama or Claude)."""
        if self.config.use_ollama and self.ollama_client:
            return await self._process_with_ollama(prompt)
        else:
            return await self._process_with_claude(prompt)

    async def _process_with_ollama(self, prompt: str) -> str:
        """Process prompt with Ollama."""
        logger.debug(f"[jarvis] Ollama prompt: {prompt[:100]}...")

        try:
            # Build conversation context from session
            # For now, simple single-turn
            messages = [
                {"role": "system", "content": "You are JARVIS, a helpful AI assistant. Be concise and natural."},
                {"role": "user", "content": prompt},
            ]

            result = await self.ollama_client.chat(messages)

            if "error" in result:
                return f"Error: {result['error']}"

            # Extract response
            if "message" in result and "content" in result["message"]:
                return result["message"]["content"]

            return "No response from Ollama"

        except Exception as e:
            logger.error(f"[jarvis] Ollama error: {e}")
            return f"Error: {e}"

    async def _process_with_claude(self, prompt: str, session: ClientSession) -> str:
        """Process prompt with Claude CLI."""
        # Spawn claude CLI with the prompt
        # This is a simplified version - real implementation would use
        # the Agent SDK or manage a persistent claude process

        cmd = [
            self.config.claude_executable,
            "--print",
            "--model", self.config.model,
            "--output-format", "json",
        ]

        # Add MCP servers
        if self.config.mcp_servers:
            cmd.extend(["--mcp-servers", self.config.mcp_servers])

        if self.config.allow_writes:
            cmd.append("--writes")

        if self.config.account_connectors:
            cmd.append("--account-connectors")

        cmd.extend(["-p", prompt])

        logger.debug(f"[jarvis] Running: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=Path(self.config.workspace).expanduser(),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode != 0:
                logger.error(f"[jarvis] Claude error: {stderr.decode()}")
                return f"Error: {stderr.decode()[:500]}"

            # Parse JSON output
            result = json.loads(stdout.decode())
            return result.get("content", [{}])[0].get("text", "No response")

        except asyncio.TimeoutError:
            return "Request timed out"
        except Exception as e:
            logger.error(f"[jarvis] Claude execution error: {e}")
            return f"Error: {e}"

    async def _handle_tool_call(self, session: ClientSession, msg: dict):
        """Handle tool call from frontend (UI control, etc.)."""
        tool_name = msg.get("tool")
        tool_args = msg.get("args", {})
        call_id = msg.get("id", str(uuid.uuid4()))

        # UI control tools
        if tool_name in ("ui_theme", "ui_reactor", "ui_orbit", "ui_chrome", "ui_effect", "ui_screen", "ui_reset"):
            # Echo back to all clients for UI update
            await self._broadcast({
                "type": "tool_result",
                "id": call_id,
                "tool": tool_name,
                "result": {"ok": True, "applied": tool_args}
            })
        else:
            await session.ws.send_json({
                "type": "tool_result",
                "id": call_id,
                "tool": tool_name,
                "error": f"Unknown tool: {tool_name}"
            })

    async def _handle_chat(self, session: ClientSession, msg: dict):
        """Handle text chat message."""
        text = msg.get("text", "")
        if not text:
            return

        # Process with LLM
        response = await self._process_with_llm(text, session)

        await session.ws.send_json({
            "type": "chat_response",
            "text": response
        })

    async def _broadcast(self, msg: dict, exclude: Optional[str] = None):
        """Broadcast message to all connected clients."""
        data = json.dumps(msg)
        for client_id, session in self.sessions.items():
            if client_id != exclude:
                try:
                    await session.ws.send_str(data)
                except Exception:
                    pass  # Client likely disconnected

    # SSRF-guarded proxy endpoints
    async def _handle_file_proxy(self, request: web.Request) -> web.Response:
        """Proxy file requests with SSRF protection."""
        path = request.query.get("path")
        if not path:
            return web.Response(status=400, text="Missing path parameter")

        # Validate path is within allowed roots
        allowed_roots = [
            Path(self.config.workspace).expanduser().resolve(),
            Path(tempfile.gettempdir()).resolve(),
        ]
        if self.config.file_roots:
            for root in self.config.file_roots.split(","):
                allowed_roots.append(Path(root).expanduser().resolve())

        requested = Path(path).expanduser().resolve()

        # Check if requested path is within allowed roots
        allowed = False
        for root in allowed_roots:
            try:
                requested.relative_to(root)
                allowed = True
                break
            except ValueError:
                continue

        if not allowed:
            return web.Response(status=403, text="Path not allowed")

        # Refuse credential paths
        for forbidden in [".ssh", ".claude", ".env", "secrets"]:
            if forbidden in requested.parts:
                return web.Response(status=403, text="Forbidden path")

        if not requested.exists() or not requested.is_file():
            return web.Response(status=404, text="File not found")

        # Serve file
        return web.FileResponse(requested)

    async def _handle_img_proxy(self, request: web.Request) -> web.Response:
        """Proxy image requests with SSRF protection."""
        url = request.query.get("url")
        if not url:
            return web.Response(status=400, text="Missing url parameter")

        # Validate URL scheme
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return web.Response(status=400, text="Invalid scheme")

        # Block private/loopback addresses
        if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return web.Response(status=403, text="Loopback not allowed")

        # Check for private IP ranges
        import ipaddress
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return web.Response(status=403, text="Private address not allowed")
        except ValueError:
            # Hostname, not IP - would need DNS resolution check
            pass

        # Fetch and proxy
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return web.Response(status=resp.status, text="Failed to fetch")
                content = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/jpeg")
                return web.Response(body=content, content_type=content_type)

    async def _handle_media_proxy(self, request: web.Request) -> web.Response:
        """Proxy media (video/audio) requests with SSRF protection."""
        # Similar to img_proxy but for media
        return await self._handle_img_proxy(request)


async def run_bridge(config: Optional[BridgeConfig] = None) -> BridgeServer:
    """Run the bridge server."""
    server = BridgeServer(config)
    await server.start()

    # Handle shutdown signals
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(server.stop()))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    # Keep running
    while server._running:
        await asyncio.sleep(1)

    return server


# Import at bottom to avoid circular imports
import tempfile
import urllib.parse