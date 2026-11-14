# Jarvis Enhancement Plan: Adopting adewaskar/jarvis Strategies

## Current State (Python Jarvis)
- CLI-based with Typer + Rich
- Plugin architecture (Gmail, Calendar, GitHub, Files, Finance, Apps, Reminders)
- Encrypted secrets with age/Fernet
- LLM integration (OpenAI, Anthropic, Ollama)
- Task queue with workers
- macOS automation via pyobjc

## Target State (Enhanced Python Jarvis)
- **Bridge Architecture**: WebSocket server (brain) + Web UI (face)
- **Voice Interface**: Wake word "Hey Jarvis" + local VAD + barge-in
- **Iron Man HUD UI**: Three.js + React frontend served by Python
- **MCP Integration**: Use Claude Agent SDK to spawn `claude` CLI headless
- **Real-time Communication**: WebSocket for voice/text/UI updates
- **Capability Detection**: Auto-detect ElevenLabs, browser speech, etc.

---

## Phase 1: Bridge Server (Backend Brain)

### 1.1 Add WebSocket Server
- New module: `jarvis/bridge/server.py`
- Use `aiohttp` + `websockets` for WebSocket server
- Port 8787 (configurable via `JARVIS_BRIDGE_PORT`)
- Handle: voice commands, tool calls, UI updates

### 1.2 Integrate Claude Agent SDK
- Use `@anthropic-ai/claude-agent-sdk` via Node bridge OR
- Spawn `claude` CLI as subprocess (like adewaskar does)
- Pass MCP servers from `~/.claude.json`
- Tool permission gate: read-only by default, `JARVIS_ALLOW_WRITES=1` for writes

### 1.3 Voice Pipeline
- Local VAD (energy-based) for wake word detection
- STT: ElevenLabs Scribe (if key) → browser SpeechRecognition (fallback)
- TTS: ElevenLabs (if key) → browser speechSynthesis (fallback)
- Barge-in support: interrupt current speech

### 1.4 MCP Server Management
- Read `~/.claude.json` for configured servers
- Filter via `JARVIS_MCP_SERVERS` env var
- Account connectors opt-in via `JARVIS_ACCOUNT_CONNECTORS=1`

---

## Phase 2: Web Frontend (Face)

### 2.1 React + Vite + Three.js UI
- Serve static files from Python (or separate Node dev server)
- Iron Man HUD: reactor, orbit, panels, boot sequence
- Real-time transcript display
- Diagnostics panel (press D)
- Audio self-test (press T)

### 2.2 Voice Interface in Browser
- Wake word: "Hey Jarvis" (Porcupine or simple energy VAD)
- SpeechRecognition API for STT
- speechSynthesis for TTS
- MediaRecorder for audio capture
- WebSocket to bridge for processing

### 2.3 UI Control Tools (MCP tools exposed to agent)
- `ui_theme` - accent, background, colors
- `ui_reactor` - color, scale, intensity, style
- `ui_orbit` - put images in orbit
- `ui_chrome` - show/hide rails, transcript
- `ui_effect` - glitch, pulse, scan, shake, flash
- `ui_screen` - clear
- `ui_reset` - back to defaults

---

## Phase 3: Enhanced Python Backend

### 3.1 New Dependencies
```toml
# Bridge
"websockets>=12.0",
"aiohttp>=3.9",
"aiohttp-cors>=0.7",

# Voice
"pvporcupine>=3.0",          # Wake word (optional)
"webrtcvad>=2.0.10",         # Voice activity detection
"numpy>=1.26",               # Audio processing

# Frontend serving
"jinja2>=3.1",               # Template rendering
```

### 3.2 Configuration (`.env` additions)
```bash
# Bridge
JARVIS_BRIDGE_PORT=8787
JARVIS_BRIDGE_HOST=127.0.0.1
JARVIS_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Voice
ELEVENLABS_API_KEY=optional
JARVIS_VOICE_ID=optional
PORCUPINE_ACCESS_KEY=optional  # For wake word

# Security
JARVIS_ALLOW_WRITES=false
JARVIS_MCP_SERVERS=all  # or comma-separated list
JARVIS_ACCOUNT_CONNECTORS=false
JARVIS_WORKSPACE=~/.jarvis/workspace
JARVIS_FILE_ROOTS=optional,extra,paths
JARVIS_KEEP_TRANSCRIPTS=false
JARVIS_DEBUG=false

# Model
JARVIS_MODEL=claude-opus-5
JARVIS_EFFORT=medium
```

### 3.3 New Commands
```bash
jarvis bridge          # Start bridge server only
jarvis bridge:writes   # Start bridge with writes enabled
jarvis face            # Start frontend dev server (or serve built)
jarvis start           # Start both (bridge + face)
jarvis init            # Now also sets up bridge config
```

---

## Phase 4: Implementation Priority

### Week 1: Core Bridge
1. WebSocket server with aiohttp
2. Spawn `claude` CLI subprocess
3. Basic tool execution pipeline
4. Read `~/.claude.json` MCP servers

### Week 2: Voice Pipeline
1. Local VAD implementation
2. ElevenLabs integration (STT + TTS)
3. Browser SpeechRecognition fallback
4. Wake word detection (Porcupine or energy-based)

### Week 3: Frontend
1. React + Vite + Three.js setup
2. Iron Man HUD components
3. WebSocket connection to bridge
4. Voice recording/playback

### Week 4: Integration & Polish
1. Boot sequence animation
2. UI control tools
3. Diagnostics panel
4. Security hardening
5. Documentation

---

## Security Model (from adewaskar/jarvis)

1. **Origin validation**: Only localhost origins by default
2. **DNS rebinding protection**: Check Host header
3. **Tool gate**: Default deny for effectful tools
4. **File confinement**: Workspace + temp + JARVIS_FILE_ROOTS only
5. **No credential access**: Refuse ~/.ssh, ~/.claude, .env files
6. **SSRF guards**: /file, /img, /media endpoints validate paths
7. **Account connectors opt-in**: Disabled by default

---

## Migration Strategy

Keep existing CLI working! Add bridge as new entry point:

```
jarvis start          # Current: interactive CLI
jarvis bridge         # New: WebSocket server
jarvis face           # New: Frontend
jarvis start --bridge # New: Start both
```

The bridge reuses all existing plugins and infrastructure.