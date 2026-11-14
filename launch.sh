#!/bin/bash
# Jarvis One-Click Launcher
# Starts Ollama (if available) + Jarvis with a single command

set -euo pipefail

JARVIS_DIR="$HOME/jarvis"
LOG_FILE="$HOME/.jarvis/logs/launch.log"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

mkdir -p "$HOME/.jarvis/logs"

log() {
    echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"
}

success() {
    echo -e "${GREEN}✓${NC} $*" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}⚠${NC} $*" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}✗${NC} $*" | tee -a "$LOG_FILE"
}

# Check if Ollama is installed
has_ollama() {
    command -v ollama &> /dev/null
}

# Start Ollama server in background
start_ollama() {
    if ! has_ollama; then
        log "Ollama not installed. Install with: brew install ollama"
        return 1
    fi

    # Check if already running
    if pgrep -x ollama > /dev/null; then
        success "Ollama already running"
        return 0
    fi

    log "Starting Ollama server..."
    nohup ollama serve > "$HOME/.jarvis/logs/ollama.log" 2>&1 &
    OLLAMA_PID=$!

    # Wait for it to be ready
    for i in {1..10}; do
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            success "Ollama started (PID: $OLLAMA_PID)"
            echo $OLLAMA_PID > "$HOME/.jarvis/ollama.pid"
            return 0
        fi
        sleep 1
    done

    warn "Ollama may not have started fully. Check $HOME/.jarvis/logs/ollama.log"
    return 1
}

# Check for available models
check_ollama_models() {
    if has_ollama && pgrep -x ollama > /dev/null; then
        MODELS=$(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}' | head -5)
        if [ -n "$MODELS" ]; then
            success "Available models: $MODELS"
        else
            warn "No Ollama models found. Pull one with: ollama pull llama3.1"
        fi
    fi
}

# Main
clear
echo -e "${BLUE}"
echo "╔══════════════════════════════════════╗"
echo "║       🤖 JARVIS LAUNCHER             ║"
echo "║   Your Personal AI Butler            ║"
echo "╚══════════════════════════════════════╝"
echo -e "${NC}"

log "Starting Jarvis..."

# Start Ollama (optional, for LLM chat)
start_ollama
check_ollama_models

# Activate venv and start Jarvis
cd "$JARVIS_DIR"
source .venv/bin/activate

log "Launching Jarvis..."
echo ""
echo -e "${GREEN}Ready! Type 'chat' at the prompt to talk naturally.${NC}"
echo -e "${GREEN}Commands: help, email, calendar, github, files, app, remind${NC}"
echo ""

# Start Jarvis (this blocks)
python -m jarvis start

# Cleanup on exit
if [ -f "$HOME/.jarvis/ollama.pid" ]; then
    OLLAMA_PID=$(cat "$HOME/.jarvis/ollama.pid")
    log "Shutting down Ollama (PID: $OLLAMA_PID)..."
    kill $OLLAMA_PID 2>/dev/null || true
    rm "$HOME/.jarvis/ollama.pid"
fi

log "Jarvis stopped. Goodbye!"