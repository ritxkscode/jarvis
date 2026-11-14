# 🤖 JARVIS - Personal AI Butler with Iron Man HUD

> "Jarvis, sometimes you gotta run before you can walk." — Tony Stark

A comprehensive personal AI assistant featuring a **bridge architecture** (WebSocket brain + Web UI face), **Iron Man HUD interface** (Three.js React), **voice interaction** (wake word + push-to-talk), and **native integrations** for Gmail, Calendar, GitHub, Files, Finance, macOS Apps, and Reminders.

---

## ✨ Features

### 🎭 Dual Interface Architecture
| Mode | Description |
|------|-------------|
| **CLI** | Terminal REPL with full plugin access |
| **Bridge + HUD** | WebSocket backend + Three.js Iron Man UI with voice |

### 🔌 Native Integrations (Plugins)
| Domain | Capabilities |
|--------|--------------|
| **📧 Gmail** | Read/send/search across 3+ accounts, labels, filters, threads |
| **📅 Calendar** | Events, reminders, free-slot finding, conflict detection, multi-cal |
| **📁 Files** | Read/write/search/watch, JSON/YAML/TOML, workspace confinement |
| **🐙 GitHub** | Repos, issues, PRs, actions, auto-README, push local changes |
| **💰 Finance** | Plaid bank sync, manual tracking, budgets, expenses, investments |
| **🖥️ macOS Apps** | Launch/quit, click, type, notifications, AppleScript automation |
| **⏰ Reminders** | One-time, recurring (cron), assignment due dates, snooze |

### 🌉 Bridge Architecture (WebSocket)
- **Brain**: Python `aiohttp` server on `ws://localhost:8787/ws`
- **Face**: React + Three.js + Vite on `http://localhost:5173`
- **Protocol**: JSON messages (voice, chat, tool_call, auth, ping/pong)
- **Security**: Origin/Host validation, read-only tool gate, file confinement, SSRF guards

### 🎨 Iron Man HUD (Three.js + React)
- **Arc Reactor**: Animated core (ring/sphere/wire styles, particle field, pulse)
- **Boot Sequence**: 4-beat startup animation (status bar → rings → suit → reactor)
- **Orbit System**: Images/videos orbiting the reactor (drag to reposition)
- **Transcript Panel**: Live conversation log with decoding animation
- **Side Panels**: Systems status, tool readout, diagnostics modal
- **Effects**: Glitch, scan, pulse, shake, flash, blade sweeps

### 🎤 Voice Pipeline
- **Wake Word**: Porcupine "Hey Jarvis" (optional) or SPACE push-to-talk
- **VAD**: WebRTC VAD (energy-based fallback)
- **STT**: Browser SpeechRecognition / ElevenLabs Scribe (configurable)
- **TTS**: Browser speechSynthesis / ElevenLabs / Kokoro.js (configurable)
- **Barge-in**: Interrupt Jarvis mid-speech with new command

### 🔐 Security Model
- **DNS Rebinding Protection**: Origin/Host validation on WebSocket upgrade
- **Tool Gate**: Read-only by default, `--writes` enables effectful tools
- **File Confinement**: Workspace + `JARVIS_FILE_ROOTS` only, blocks `.ssh`, `.claude`, `.env`
- **SSRF Guards**: `/file`, `/img`, `/media` proxies validate targets
- **Secrets**: Encrypted with `age` (or Fernet), password in `JARVIS_SECRETS_PASSWORD`

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Node.js 20+ (for frontend)
- `age` binary for secrets encryption (`brew install age`)

### Installation

```bash
# Clone
git clone https://github.com/ritxkscode/jarvis.git
cd jarvis

# Python dependencies
pip install -e ".[dev,bridge]"

# Frontend dependencies
cd frontend && npm install && cd ..

# Initialize config
jarvis init

# Edit credentials
cp .env.example .env
# Add: Google OAuth, GitHub token, Plaid keys, ElevenLabs (optional), secrets password

# Set up Google accounts
jarvis setup-oauth
```

---

## ⚡ Running JARVIS

### Option 1: CLI Mode (Original)
```bash
jarvis start                    # Interactive REPL
jarvis start --daemon           # Background daemon
```

### Option 2: Bridge + HUD (New Iron Man UI)

```bash
# Terminal 1: Start bridge (WebSocket backend)
jarvis bridge [--writes] [--port 8787] [--model claude-opus-5] [--debug]

# Terminal 2: Start frontend (Vite dev server)
jarvis face [--dev]             # http://localhost:5173

# OR: Full stack in one command
jarvis start --bridge [--writes]
```

### Environment Variables
```bash
# Core
JARVIS_ALLOW_WRITES=1           # Enable effectful tools (default: 0)
JARVIS_BRIDGE_PORT=8787         # Bridge WebSocket port
JARVIS_MODEL=claude-opus-5      # claude-opus-5, claude-sonnet-5, etc.
JARVIS_EFFORT=medium            # low, medium, high
JARVIS_MCP_SERVERS=all          # or comma-separated list

# Voice (optional - better quality)
ELEVENLABS_API_KEY=xxx          # ElevenLabs STT/TTS
PORCUPINE_ACCESS_KEY=xxx        # Picovoice wake word "Hey Jarvis"

# File access
JARVIS_FILE_ROOTS=/path/to/additional/roots
```

---

## 🎮 Using the HUD

### Controls
| Key | Action |
|-----|--------|
| `SPACE` | Push-to-talk / barge-in |
| `~` / `` ` `` | Initialize (from offline) |
| `ESC` | Stand down / stop |
| `D` | Diagnostics modal |
| `T` | Audio test |
| `V` | Cycle TTS voice (Kokoro) |
| `G` | Toggle camera/gestures |

### Voice Commands
```
"Hey Jarvis, what's on my calendar today?"
"Jarvis, search my emails for GitHub notifications"
"Hey Jarvis, create a reminder for CS101 homework due Friday"
"Jarvis, show me my GitHub repos"
"Hey Jarvis, what's the weather?" (via web search)
"Make the reactor red"          # UI control
"Put that image in orbit"       # Orbit system
"Clear the screen"              # Clear panels/transcript
```

---

## 🏗 Architecture

```
jarvis/
├── jarvis/
│   ├── bridge/              # WebSocket bridge server
│   │   ├── server.py        # aiohttp server, WS handler, proxies
│   │   ├── config.py        # BridgeConfig from env
│   │   └── __init__.py      # Exports
│   ├── config/              # Settings & encrypted secrets
│   ├── core/                # Agent, plugins, events, task executor
│   ├── integrations/        # 7 native plugins
│   ├── __main__.py          # CLI entry (Typer): start, bridge, face, init
│   └── plugins/             # Plugin base classes
├── frontend/                # React + Three.js + Vite
│   ├── src/
│   │   ├── ui/              # Reactor, BootSequence, HUD components
│   │   ├── hooks/           # useBridge, useVoice
│   │   ├── components/      # Transcript, Panels, Controls, Diagnostics
│   │   ├── lib/             # store (Zustand), brain, voice, tts, sfx
│   │   ├── scene/           # Three.js: Core, Particles, Orbits
│   │   └── styles.css       # Iron Man HUD theme
│   └── package.json
├── tests/
├── pyproject.toml
├── .gitignore
└── README.md
```

### Bridge Message Protocol
```json
// Client → Server
{"type": "voice", "action": "start"}           // Start listening
{"type": "voice", "action": "stop"}            // Stop listening
{"type": "voice", "transcript": "text"}        // Send transcript
{"type": "chat", "text": "message"}            // Text chat
{"type": "tool_call", "tool": "name", "args": {}} // Call tool
{"type": "auth", "token": "xxx"}               // Authenticate
{"type": "ping"}                               // Heartbeat

// Server → Client
{"type": "welcome", "client_id": "uuid", "config": {...}}
{"type": "voice", "action": "response", "response": "text", "transcript": "user said"}
{"type": "chat_response", "text": "response"}
{"type": "tool_result", "tool": "name", "result": {...}, "error": null}
{"type": "pong"}
{"type": "error", "message": "..."}
```

---

## 🔧 Development

```bash
# Install all deps
pip install -e ".[dev,bridge]"
cd frontend && npm install && cd ..

# Run tests
pytest

# Lint & format
ruff check . && ruff format .

# Type check
mypy jarvis

# Frontend dev
cd frontend && npm run dev

# Frontend build
cd frontend && npm run build
```

---

## 📦 Project Structure Details

### Bridge Server (`jarvis/bridge/server.py`)
- `BridgeConfig` — Pydantic config from environment
- `ClientSession` — Per-connection state, tool gate, MCP client
- `validate_origin()` — DNS rebinding protection
- `proxy_file/img/media()` — SSRF-guarded asset proxies
- `handle_ws()` — Main WebSocket message router

### Frontend Store (`frontend/src/lib/store.ts`)
- `phase` — offline | boot | dormant | waking | listening | thinking | tooling | speaking
- `ui` — Reactor (color, scale, intensity, spin, style), orbits, chrome, effects
- `panels` / `blades` — HUD cards and full-screen articles
- `turns` — Conversation history

### Plugins (all in `jarvis/integrations/`)
Each plugin implements: `initialize()`, `start()`, `stop()`, and action methods.
Registered via `PluginManager` in `jarvis/core/plugin.py`.

---

## 🔐 Security Notes

1. **Never commit `.env`** — Contains OAuth tokens, API keys
2. **Secrets encrypted** — `~/.jarvis/secrets.age` with `JARVIS_SECRETS_PASSWORD`
3. **Read-only default** — Bridge rejects write tools without `--writes` / `JARVIS_ALLOW_WRITES=1`
4. **File sandbox** — Only `~/.jarvis/workspace`, temp, and `JARVIS_FILE_ROOTS` accessible
5. **No credential leakage** — `.ssh`, `.claude`, `.env*`, `*.pem`, `*.key` blocked

---

## 🗺 Roadmap

- [x] Bridge architecture (WebSocket + React)
- [x] Iron Man HUD (Three.js reactor, boot, orbits, transcript)
- [x] Voice pipeline (VAD, STT, TTS, barge-in)
- [x] Porcupine wake word integration (planned)
- [x] ElevenLabs STT/TTS integration (planned)
- [x] Claude Agent SDK (replace subprocess) (planned)
- [x] UI control tools exposed to agent (planned)
- [ ] Boot sound (`public/audio/boot-music.mp3`)
- [ ] Image/video proxy caching
- [ ] Browser automation (Playwright)
- [ ] Assignment solver (LLM-powered)
- [ ] Telegram/Discord gateway
- [ ] iOS Shortcuts integration

---

## 🤝 Contributing

1. Fork the repo
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

---

## 📄 License

MIT — Build your own Jarvis.

---

## 🙏 Credits

- **Architecture inspired by** [adewaskar/jarvis](https://github.com/adewaskar/jarvis) (bridge + HUD patterns)
- **Three.js / React Three Fiber** for the 3D reactor
- **Zustand** for state management
- **Claude** (Anthropic) for the brain
- **ElevenLabs** for premium voice (optional)
- **Picovoice Porcupine** for wake word (optional)

---

*Built with ❤️ for developers who want a butler.*