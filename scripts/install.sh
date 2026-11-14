#!/usr/bin/env bash
# Jarvis Installation Script

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

JARVIS_DIR="${JARVIS_DIR:-$HOME/jarvis}"
PYTHON_MIN_VERSION="3.11"

echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🤖 Jarvis Installation Script    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# Check Python version
echo -e "${YELLOW}Checking Python version...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python 3 not found. Please install Python ${PYTHON_MIN_VERSION}+${NC}"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ $(echo "$PYTHON_VERSION >= $PYTHON_MIN_VERSION" | bc -l) -eq 0 ]]; then
    echo -e "${RED}Python ${PYTHON_VERSION} found, but ${PYTHON_MIN_VERSION}+ required${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python ${PYTHON_VERSION}${NC}"

# Check for uv (preferred) or pip
if command -v uv &> /dev/null; echo -e "${GREEN}✓ uv found${NC}"; INSTALLER="uv pip install"
elif command -v pip3 &> /dev/null; then
    echo -e "${YELLOW}Using pip3 (uv recommended for faster installs)${NC}"
    INSTALLER="pip3 install"
else
    echo -e "${RED}Neither uv nor pip3 found${NC}"
    exit 1
fi

# Install system dependencies (macOS)
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo -e "${YELLOW}Installing macOS dependencies...${NC}"

    # Check for Homebrew
    if ! command -v brew &> /dev/null; then
        echo -e "${RED}Homebrew not found. Please install from https://brew.sh${NC}"
        exit 1
    fi

    # Required for pyobjc, watchdog, etc.
    brew install python@3.11 2>/dev/null || true

    # For audio/voice (optional)
    # brew install portaudio ffmpeg

    # For age encryption
    brew install age 2>/dev/null || true

    # For ripgrep (file search)
    brew install ripgrep 2>/dev/null || true
fi

# Create project directory
echo -e "${YELLOW}Setting up Jarvis in ${JARVIS_DIR}...${NC}"
mkdir -p "$JARVIS_DIR"
cd "$JARVIS_DIR"

# Copy project files if not present
if [[ ! -f "pyproject.toml" ]]; then
    echo -e "${YELLOW}Project files not found. Please clone or copy the Jarvis source first.${NC}"
    exit 1
fi

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [[ ! -d ".venv" ]]; then
    python3 -m venv .venv
fi

# Activate and install
source .venv/bin/activate

echo -e "${YELLOW}Installing Jarvis with all dependencies...${NC}"
$INSTALLER -e ".[dev]"

# Install Playwright browsers (for future browser automation)
if command -v playwright &> /dev/null; then
    echo -e "${YELLOW}Installing Playwright browsers...${NC}"
    playwright install chromium 2>/dev/null || true
fi

# Create .env from example
if [[ ! -f ".env" && -f ".env.example" ]]; then
    cp .env.example .env
    echo -e "${GREEN}Created .env from example. Please edit it with your credentials.${NC}"
fi

# Create data directories
mkdir -p ~/.jarvis/{logs,plugins,finance}

# Setup shell integration
SHELL_RC=""
if [[ "$SHELL" == */zsh ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ "$SHELL" == */bash ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [[ -n "$SHELL_RC" ]]; then
    JARVIS_ALIAS="alias jarvis='cd $JARVIS_DIR && source .venv/bin/activate && python -m jarvis'"
    if ! grep -q "alias jarvis=" "$SHELL_RC" 2>/dev/null; then
        echo "" >> "$SHELL_RC"
        echo "# Jarvis" >> "$SHELL_RC"
        echo "$JARVIS_ALIAS" >> "$SHELL_RC"
        echo -e "${GREEN}Added 'jarvis' alias to $SHELL_RC${NC}"
    fi
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     ✅ Installation Complete!        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Edit .env with your credentials:"
echo -e "     ${YELLOW}nano $JARVIS_DIR/.env${NC}"
echo ""
echo "  2. Reload shell or run:"
echo -e "     ${YELLOW}source $SHELL_RC${NC}"
echo ""
echo "  3. Initialize Jarvis:"
echo -e "     ${YELLOW}jarvis init${NC}"
echo ""
echo "  4. Set up Google OAuth (Gmail + Calendar):"
echo -e "     ${YELLOW}jarvis setup-oauth${NC}"
echo ""
echo "  5. Start Jarvis:"
echo -e "     ${YELLOW}jarvis start${NC}"
echo ""
echo -e "${BLUE}Project directory:${NC} $JARVIS_DIR"
echo -e "${BLUE}Data directory:${NC} ~/.jarvis"